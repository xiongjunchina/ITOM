"""流程引擎最小版（PRD §8）：单据触发实例，任务按步骤推进，默认角色指派。"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AuthUser,
    OrgMember,
    ProcessDefinition,
    ProcessInstance,
    ProcessStep,
    ProcessTask,
    Role,
    UserGroup,
    UserGroupMember,
    Ticket,
    Requirement,
    RequirementTask,
)
from app.services.requirement_scoring import ROUTE_DEV
from app.services.rbac import GROUP_PREFIX

logger = logging.getLogger("aom.process")


def _match_definition(db: Session, entity_type: str, entity: dict) -> ProcessDefinition | None:
    defs = (
        db.query(ProcessDefinition)
        .filter(
            ProcessDefinition.entity_type == entity_type,
            ProcessDefinition.active.is_(True),
            ProcessDefinition.is_deleted.is_(False),
        )
        .all()
    )
    for d in defs:
        cond = d.trigger_condition or {}
        if all(entity.get(k) == v for k, v in cond.items()):
            return d
    return None


def resolve_definition(
    db: Session,
    entity_type: str,
    entity_attrs: dict,
    definition_id: str | None = None,
) -> ProcessDefinition | None:
    """解析显式绑定流程；未绑定时兼容按实体触发条件匹配。"""
    if not definition_id:
        return _match_definition(db, entity_type, entity_attrs)
    definition = db.get(ProcessDefinition, definition_id)
    if (
        not definition
        or definition.is_deleted
        or not definition.active
        or definition.entity_type != entity_type
    ):
        raise AppError("PROCESS_DEFINITION_UNAVAILABLE", "服务项绑定流程不存在、未启用或类型不匹配")
    return definition


def _resolve_assignee(db: Session, step: ProcessStep, preferred: str | None) -> str | None:
    """指派解析：优先单据受理人；否则按步骤默认角色/用户组找一个在岗成员。

    default_role 支持三种取值：内置角色码、自定义角色码（含继承匹配）、"group:组码"。
    """
    if preferred:
        return preferred
    target = step.default_role
    if not target:
        return None
    if target.startswith(GROUP_PREFIX):
        code = target[len(GROUP_PREFIX):]
        group = db.query(UserGroup).filter(UserGroup.code == code, UserGroup.is_deleted.is_(False)).first()
        if not group:
            return None
        member = (
            db.query(OrgMember)
            .join(UserGroupMember, UserGroupMember.person_id == OrgMember.id)
            .filter(
                UserGroupMember.group_id == group.id,
                UserGroupMember.is_deleted.is_(False),
                OrgMember.status == "在岗",
            )
            .first()
        )
        return member.id if member else None

    custom_base = {
        r.code: r.base_role
        for r in db.query(Role).filter(Role.is_builtin.is_(False), Role.is_deleted.is_(False))
    }
    candidates = (
        db.query(AuthUser)
        .join(OrgMember, AuthUser.person_id == OrgMember.id)
        .filter(AuthUser.is_active.is_(True), OrgMember.status == "在岗")
        .all()
    )
    for u in candidates:
        keys = set(u.roles or [])
        keys |= {custom_base[c] for c in list(keys) if custom_base.get(c)}
        if target in keys:
            return u.person_id
    return None


ENTITY_LINKS = {
    "ticket": "/itsm/tickets/{id}",
    "ticket_change": "/itsm/tickets/{id}",
    "problem": "/itsm/problems/{id}",
    "requirement": "/requirements/{id}",
    "project": "/projects/{id}",
    "bug": "/task-management/development?tab=bug&bug_id={id}",
}


def _resolve_key_persons(db: Session, key: str) -> list[str]:
    """解析角色码或 group:组码 → 在岗人员 person_id 列表（知会解析用）。"""
    if key.startswith(GROUP_PREFIX):
        code = key[len(GROUP_PREFIX):]
        group = db.query(UserGroup).filter(UserGroup.code == code, UserGroup.is_deleted.is_(False)).first()
        if not group:
            return []
        members = (
            db.query(OrgMember)
            .join(UserGroupMember, UserGroupMember.person_id == OrgMember.id)
            .filter(
                UserGroupMember.group_id == group.id,
                UserGroupMember.is_deleted.is_(False),
                OrgMember.status == "在岗",
            )
            .all()
        )
        return [m.id for m in members]
    custom_base = {
        r.code: r.base_role
        for r in db.query(Role).filter(Role.is_builtin.is_(False), Role.is_deleted.is_(False))
    }
    result = []
    candidates = (
        db.query(AuthUser)
        .join(OrgMember, AuthUser.person_id == OrgMember.id)
        .filter(AuthUser.is_active.is_(True), OrgMember.status == "在岗")
        .all()
    )
    for u in candidates:
        keys = set(u.roles or [])
        keys |= {custom_base[c] for c in list(keys) if custom_base.get(c)}
        if key in keys:
            result.append(u.person_id)
    return result


def _notify_cc(db: Session, instance: ProcessInstance, step: ProcessStep, assignee: str | None):
    """知会人：仅通知，不产生任务、不阻塞流程（RACI 的 I）。"""
    if not step.cc_roles:
        return
    from app.events import notifier

    recipients: set[str] = set()
    for key in step.cc_roles:
        recipients.update(_resolve_key_persons(db, key))
    recipients.discard(assignee)
    if not recipients:
        return
    link = ENTITY_LINKS.get(instance.entity_type, "").format(id=instance.entity_id)
    notifier.notify(
        db, "process.step_cc", instance.entity_type, instance.entity_id,
        sorted(recipients),
        f"流程知会：{instance.definition.name}·{step.name}",
        content="该节点进入处理中，你是知会人（无需操作）",
        link=link,
    )


def _requester_person(db: Session, entity_type: str, entity_id: str) -> str | None:
    """单据提交人对应的人员 id（default_role=requester 的动态指派，M16.8）。"""
    uid = None
    if entity_type in ("ticket", "ticket_change"):
        t = db.get(Ticket, entity_id)
        uid = t.submitter if t else None
    elif entity_type == "requirement":
        from app.models import Requirement

        r = db.get(Requirement, entity_id)
        uid = r.requester if r else None
    elif entity_type == "project":
        from app.models import Project

        project = db.get(Project, entity_id)
        return project.pm if project else None
    elif entity_type == "problem":
        from app.models import Problem

        problem = db.get(Problem, entity_id)
        uid = problem.reporter if problem else None
    if not uid:
        return None
    u = db.get(AuthUser, uid)
    return u.person_id if u else None


def _notify_assignee(db: Session, instance: ProcessInstance, step: ProcessStep, assignee: str | None, reassigned: bool = False):
    """待办提醒（RACI 的 R）：任务落到谁头上就通知谁（M18，用户预期：钟俊歌收到受理提醒）。"""
    if not assignee:
        return
    from app.events import notifier

    link = ENTITY_LINKS.get(instance.entity_type, "").format(id=instance.entity_id)
    notifier.notify(
        db, "process.task_reassigned" if reassigned else "process.task_assigned",
        instance.entity_type, instance.entity_id,
        [assignee],
        f"待办任务{'（改派给你）' if reassigned else ''}：{instance.definition.name}·{step.name}",
        content="流程推进到你负责的节点，请及时处理",
        link=link,
    )


def _spawn_task(
    db: Session,
    instance: ProcessInstance,
    step: ProcessStep,
    preferred: str | None,
    *,
    force_unassigned: bool = False,
):
    now = datetime.now()
    # 项目流程中的 IT PM 节点必须跟随项目主数据指定的项目经理，不能从所有
    # it_pm 角色持有人中任取一人。这样章程导入/手工创建、后续推进与流程回退
    # 使用同一责任人；非 IT PM 节点（如 it_pmo 收尾复盘）仍按节点角色解析。
    if instance.entity_type == "project":
        from app.models import Project

        project = db.get(Project, instance.entity_id)
        preferred = project.pm if project and step.default_role == "it_pm" else None
    if force_unassigned:
        # 服务目录明确配置「人工队列」时，不得再静默按节点默认角色挑选一人。
        # 任务保留为待处理，满足节点角色的 IT 人员可按既有认领机制处理。
        assignee = None
    elif step.default_role == "requester":
        # 「用户确认」类步骤：指派该单据的提交人本人，而非任意业务用户
        assignee = _requester_person(db, instance.entity_type, instance.entity_id) or _resolve_assignee(db, step, preferred)
    else:
        assignee = _resolve_assignee(db, step, preferred)
    db.add(
        ProcessTask(
            instance_id=instance.id,
            step_id=step.id,
            definition_version=instance.definition.version,
            step_code_snapshot=step.step_code or f"step_{step.seq}",
            raci_snapshot={
                "responsible": step.default_role,
                "accountable": step.default_role,
                "consulted": [],
                "informed": step.cc_roles or [],
            },
            assignee=assignee,
            status="待处理",
            started_at=now,
            # This is intentionally explicit rather than relying only on the
            # model default: the production migration keeps historical pending
            # tasks disabled while every task spawned after this release opts in.
            upstream_correction_enabled=True,
            due_at=now + timedelta(hours=step.sla_hours) if step.sla_hours else None,
        )
    )
    # 流程任务才是“系统分派”的权威来源。工单创建时 Ticket.assignee 可能为空，
    # 但服务请求的首个节点仍会按默认角色解析出实际处理人；领域事件供站内通知
    # 和后续可靠机器人发件箱消费，不改变流程与派单事实。
    if assignee and instance.entity_type == "ticket":
        from app.events.bus import publish

        publish(
            db,
            "ticket.assigned",
            "ticket",
            instance.entity_id,
            {
                "assignee": assignee,
                "step_code": step.step_code or f"step_{step.seq}",
                "step_name": step.name,
            },
        )
    _notify_assignee(db, instance, step, assignee)
    _notify_cc(db, instance, step, assignee)


def _live_steps(definition: ProcessDefinition) -> list[ProcessStep]:
    """定义的有效步骤（编辑收缩产生的软删步骤不参与执行/展示）。"""
    return [s for s in definition.steps if not s.is_deleted]


def start_instance(
    db: Session,
    entity_type: str,
    entity_id: str,
    entity_attrs: dict,
    preferred_assignee: str | None = None,
    definition_id: str | None = None,
    force_unassigned: bool = False,
) -> ProcessInstance | None:
    definition = resolve_definition(db, entity_type, entity_attrs, definition_id)
    if not definition or not _live_steps(definition):
        return None
    instance = ProcessInstance(
        definition_id=definition.id,
        entity_type=entity_type,
        entity_id=entity_id,
        current_step_seq=_live_steps(definition)[0].seq,
        started_at=datetime.now(),
    )
    db.add(instance)
    db.flush()
    _spawn_task(
        db,
        instance,
        _live_steps(definition)[0],
        preferred_assignee,
        force_unassigned=force_unassigned,
    )
    return instance


def _require_requirement_implementation_tasks(
    db: Session,
    instance: ProcessInstance | None,
    task: ProcessTask,
):
    """需求开发实现的「实现交付」节点至少要有一条开发任务。

    该校验放在流程引擎而不是前端或单一路由，确保网页、API 和后续自动化调用
    都不能绕过它。仅约束写入 implementation_route 快照后的新记录，存量需求
    保持原有行为，避免上线时影响正在处理的历史单据。
    """
    if not instance or instance.entity_type != "requirement":
        return
    step = db.get(ProcessStep, task.step_id)
    if not step or "实现交付" not in (step.name or ""):
        return
    requirement = db.get(Requirement, instance.entity_id)
    if (
        not requirement
        or requirement.is_deleted
        or requirement.implementation_route != ROUTE_DEV
    ):
        return
    has_task = (
        db.query(RequirementTask.id)
        .filter(
            RequirementTask.requirement_id == requirement.id,
            RequirementTask.is_deleted.is_(False),
        )
        .first()
    )
    if not has_task:
        raise AppError(
            "REQUIREMENT_TASK_REQUIRED",
            "需求开发实现须先在“实现”区域创建至少一条开发任务后，才能完成实现交付",
            409,
        )


def complete_task(
    db: Session,
    task_id: str,
    actor: AuthUser,
    comment: str = "",
    *,
    next_preferred_assignee: str | None = None,
    force_next_unassigned: bool = False,
) -> ProcessInstance:
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if task.status != "待处理":
        raise AppError("TASK_DONE", "该任务已处理")
    instance = db.get(ProcessInstance, task.instance_id)
    _require_requirement_implementation_tasks(db, instance, task)
    # Any completion is necessarily an actual handling action.  Direct domain
    # service calls (for example Bug/Problem orchestration) therefore close the
    # upstream correction window even when they do not pass through HTTP /view.
    if task.viewed_at is None:
        task.viewed_at = datetime.now()
        task.viewed_by = actor.person_id
    task.status = "已完成"
    task.completed_at = datetime.now()
    task.completed_by = actor.person_id
    task.comment = comment or task.comment

    steps = _live_steps(instance.definition)
    current_idx = next(i for i, s in enumerate(steps) if s.id == task.step_id)
    if current_idx + 1 < len(steps):
        next_step = steps[current_idx + 1]
        instance.current_step_seq = next_step.seq
        _spawn_task(
            db,
            instance,
            next_step,
            next_preferred_assignee,
            force_unassigned=force_next_unassigned,
        )
    else:
        instance.status = "completed"
        instance.completed_at = datetime.now()
        # 服务请求最后一个节点是 requester 审批节点时，明确记录“用户确认”
        # 节奏点，再由工单编排继续走 resolved -> closed。这样“用户确认关闭”
        # 不会被流程完成后的自动关单吞掉，外部同步也能稳定区分该节点。
        if instance.entity_type == "ticket" and task.step.default_role == "requester":
            ticket = db.get(Ticket, instance.entity_id)
            if (
                ticket
                and ticket.ticket_type == "service_request"
            ):
                from app.events.bus import publish

                publish(
                    db,
                    "ticket.user_confirmed",
                    "ticket",
                    ticket.id,
                    {"step_code": task.step.step_code or f"step_{task.step.seq}"},
                )
    return instance


def approve_task(
    db: Session,
    task_id: str,
    actor: AuthUser,
    comment: str = "",
    *,
    next_preferred_assignee: str | None = None,
    force_next_unassigned: bool = False,
) -> ProcessInstance:
    """审批节点同意：审批节点专用入口，理由可选，复用正常完成推进。"""
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if task.step.node_type != "approval":
        raise AppError("NOT_APPROVAL_STEP", "当前节点不是审批节点")
    instance = db.get(ProcessInstance, task.instance_id)
    if instance.entity_type == "ticket_change":
        from app.models import Ticket
        from app.services.tickets import do_transition

        ticket = db.get(Ticket, instance.entity_id)
        if ticket and ticket.status == "new":
            do_transition(db, ticket, "pending_approval", {}, actor, system=True)
        elif ticket and ticket.status == "pending_approval":
            do_transition(db, ticket, "approved", {"approval_comment": comment}, actor, system=True)
    return complete_task(
        db,
        task_id,
        actor,
        comment,
        next_preferred_assignee=next_preferred_assignee,
        force_next_unassigned=force_next_unassigned,
    )


def reject_task(db: Session, task_id: str, actor: AuthUser, reason: str) -> ProcessInstance:
    """审批节点驳回：终止当前流程实例并保留驳回理由。"""
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if task.status != "待处理":
        raise AppError("TASK_DONE", "该任务已处理")
    if task.step.node_type != "approval":
        raise AppError("NOT_APPROVAL_STEP", "当前节点不是审批节点")
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "驳回理由至少 5 个字")
    instance = db.get(ProcessInstance, task.instance_id)
    now = datetime.now()
    if task.viewed_at is None:
        task.viewed_at = now
        task.viewed_by = actor.person_id
    task.status = "已驳回"
    task.completed_at = now
    task.comment = f"[驳回] {reason.strip()}"
    # 变更单已有明确的「已拒绝」终态；其他实体保留业务状态，由流程实例状态表达驳回结果。
    if instance.entity_type == "ticket_change":
        from app.services.tickets import do_transition
        from app.models import Ticket

        ticket = db.get(Ticket, instance.entity_id)
        if ticket and ticket.status not in ("closed", "rejected"):
            if ticket.status == "new":
                do_transition(db, ticket, "pending_approval", {}, actor, system=True)
            do_transition(db, ticket, "rejected", {"approval_comment": reason.strip()}, actor, system=True)
    instance.status = "rejected"
    instance.completed_at = now
    requester = _requester_person(db, instance.entity_type, instance.entity_id)
    if requester:
        from app.events import notifier

        link = ENTITY_LINKS.get(instance.entity_type, "").format(id=instance.entity_id)
        notifier.notify(
            db, "process.rejected", instance.entity_type, instance.entity_id, [requester],
            f"流程被驳回：{instance.definition.name}·{task.step.name}",
            content=f"驳回理由：{reason.strip()}", link=link,
        )
    return instance


def rewind_to_step(db: Session, entity_type: str, entity_id: str, target_seq: int,
                   preferred_assignee: str | None = None) -> ProcessInstance | None:
    """流程回退（M12，项目重启用）：回到指定步骤重新开始。

    目标步骤及其后的任务作废（软删，审计留痕），实例恢复 running 并在目标步骤生成新任务；
    目标步骤之前已完成的任务保留。找不到实例/步骤时静默返回（不阻塞项目重启）。
    """
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == entity_type,
            ProcessInstance.entity_id == entity_id,
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not instance:
        return None
    steps = _live_steps(instance.definition)
    target = next((st for st in steps if st.seq == target_seq), None)
    if not target:
        return None
    rewind_step_ids = {st.id for st in steps if st.seq >= target_seq}
    for task in instance.tasks:
        if task.step_id in rewind_step_ids and not task.is_deleted:
            task.is_deleted = True
    instance.status = "running"
    instance.completed_at = None
    instance.current_step_seq = target.seq
    db.flush()
    _spawn_task(db, instance, target, preferred_assignee)
    logger.info("process %s/%s rewound to step %s", entity_type, entity_id, target_seq)
    return instance


def current_pending_task(
    db: Session,
    entity_type: str,
    entity_id: str,
    *,
    for_update: bool = False,
) -> ProcessTask | None:
    """最新活跃流程实例的当前待处理任务；无实例或流程已完成返回 None。"""
    db.flush()  # Session autoflush=False：先落刚生成的实例/任务再查
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == entity_type,
            ProcessInstance.entity_id == entity_id,
            ProcessInstance.status.in_(["running", "进行中"]),
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not instance:
        return None
    # 不使用已经加载过的 instance.tasks 集合：完成当前节点后，_spawn_task
    # 会在同一 Session 新增下一节点任务，懒加载集合可能仍保留旧快照，导致
    # 流程服务误判为“没有当前任务”。直接查询保证同事务内看到最新任务。
    query = (
        db.query(ProcessTask)
        .filter(
            ProcessTask.instance_id == instance.id,
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
        )
        .order_by(ProcessTask.created_at.desc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


@dataclass(frozen=True)
class WorkflowEditAccess:
    """The single authorization decision for a running workflow record.

    ``mode`` is kept deliberately small so routes can audit a correction without
    disclosing field values: normal permission, current-node handler, admin, or
    a narrowly scoped upstream correction.
    """

    allowed: bool
    mode: str | None = None
    reason: str | None = None
    task: ProcessTask | None = None


def entity_creator_user_id(db: Session, entity_type: str, entity_id: str) -> str | None:
    """Return the immutable creator user for workflow correction authorization."""
    if entity_type in {"ticket", "ticket_change"}:
        ticket = db.get(Ticket, entity_id)
        return ticket.submitter if ticket else None
    if entity_type == "requirement":
        from app.models import Requirement

        requirement = db.get(Requirement, entity_id)
        return requirement.requester if requirement else None
    if entity_type == "problem":
        from app.models import Problem

        problem = db.get(Problem, entity_id)
        return problem.reporter if problem else None
    if entity_type == "project":
        from app.models import Project

        project = db.get(Project, entity_id)
        return project.created_by if project else None
    if entity_type == "bug":
        from app.models import Bug

        bug = db.get(Bug, entity_id)
        return bug.reporter_id if bug else None
    return None


def _is_admin(db: Session, user: AuthUser) -> bool:
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    return ADMIN in actor_keys(db, user)


def upstream_correction_access(
    db: Session,
    user: AuthUser,
    entity_type: str,
    entity_id: str,
    *,
    for_update: bool = False,
) -> WorkflowEditAccess:
    """Check the short upstream correction window without changing task state.

    First node: the record creator can correct or delete before the next handler
    has viewed the generated task.  Later nodes: only the actual completer of the
    immediately previous node can correct before the next handler has viewed it.
    Historical pending tasks have ``upstream_correction_enabled=false`` by the
    release migration and therefore never receive a retroactive grant.
    """
    task = current_pending_task(db, entity_type, entity_id, for_update=for_update)
    if not task:
        return WorkflowEditAccess(False, reason="流程当前没有待处理节点")
    if not task.upstream_correction_enabled:
        return WorkflowEditAccess(False, reason="该历史流程任务不适用上游更正窗口", task=task)
    if task.viewed_at is not None:
        return WorkflowEditAccess(False, reason="当前节点已被查阅或处理", task=task)
    if not task.step:
        return WorkflowEditAccess(False, reason="当前流程任务缺少节点定义", task=task)

    steps = _live_steps(db.get(ProcessInstance, task.instance_id).definition)
    first_seq = steps[0].seq if steps else 1
    if task.step.seq == first_seq:
        creator_id = entity_creator_user_id(db, entity_type, entity_id)
        if creator_id and creator_id == user.id:
            return WorkflowEditAccess(True, mode="upstream_creator", task=task)
        return WorkflowEditAccess(False, reason="仅创建人可在首节点未查阅前更正", task=task)

    previous = (
        db.query(ProcessTask)
        .join(ProcessStep, ProcessStep.id == ProcessTask.step_id)
        .filter(
            ProcessTask.instance_id == task.instance_id,
            ProcessTask.status.in_(["已完成", "已驳回"]),
            ProcessTask.completed_at.is_not(None),
            ProcessTask.is_deleted.is_(False),
            ProcessStep.seq < task.step.seq,
        )
        .order_by(ProcessStep.seq.desc(), ProcessTask.completed_at.desc())
        .first()
    )
    if previous and user.person_id and previous.completed_by == user.person_id:
        return WorkflowEditAccess(True, mode="upstream_handler", task=task)
    return WorkflowEditAccess(False, reason="仅上一节点实际处理人可在本节点未查阅前更正", task=task)


def workflow_edit_access(
    db: Session,
    user: AuthUser,
    entity_type: str,
    entity_id: str,
    module: str,
    *,
    for_update: bool = False,
) -> WorkflowEditAccess:
    """Authorise content editing without allowing a live workflow to be bypassed."""
    from app.services.permissions import has_perm

    if _is_admin(db, user):
        return WorkflowEditAccess(True, mode="admin")
    task = current_pending_task(db, entity_type, entity_id, for_update=for_update)
    if not task:
        return WorkflowEditAccess(
            has_perm(db, user, module, "edit"),
            mode="module_permission" if has_perm(db, user, module, "edit") else None,
            reason="当前角色无编辑权限",
        )
    if has_perm(db, user, module, "edit") and can_act_on_task(db, user, task):
        return WorkflowEditAccess(True, mode="current_handler", task=task)
    correction = upstream_correction_access(db, user, entity_type, entity_id, for_update=for_update)
    if correction.allowed:
        return correction
    return WorkflowEditAccess(False, reason=correction.reason or "当前流程节点不允许编辑", task=task)


def require_workflow_edit(
    db: Session,
    user: AuthUser,
    entity_type: str,
    entity_id: str,
    module: str,
) -> WorkflowEditAccess:
    """Raise a stable error for routes that modify a workflow record."""
    access = workflow_edit_access(db, user, entity_type, entity_id, module, for_update=True)
    if not access.allowed:
        raise AppError("WORKFLOW_EDIT_LOCKED", access.reason or "当前流程节点不允许编辑", 403)
    return access


def require_safe_correction_fields(access: WorkflowEditAccess, data: dict, forbidden: set[str]) -> None:
    """Upstream correction never changes the task routing or current assignee."""
    if access.mode not in {"upstream_creator", "upstream_handler"}:
        return
    unsafe = sorted(set(data) & forbidden)
    if unsafe:
        raise AppError(
            "WORKFLOW_CORRECTION_FIELD_FORBIDDEN",
            "上游更正窗口仅可修改单据内容，不能改变当前流程处理人或路由字段",
            403,
        )


def workflow_delete_access(
    db: Session,
    user: AuthUser,
    entity_type: str,
    entity_id: str,
    module: str,
    *,
    for_update: bool = False,
) -> WorkflowEditAccess:
    """Deletion is intentionally narrower: only the creator can delete at node 1."""
    from app.services.permissions import has_perm

    if _is_admin(db, user):
        return WorkflowEditAccess(True, mode="admin")
    task = current_pending_task(db, entity_type, entity_id, for_update=for_update)
    if not task:
        return WorkflowEditAccess(
            has_perm(db, user, module, "delete"),
            mode="module_permission" if has_perm(db, user, module, "delete") else None,
            reason="当前角色无删除权限",
        )
    correction = upstream_correction_access(db, user, entity_type, entity_id, for_update=for_update)
    if correction.allowed and correction.mode == "upstream_creator":
        return correction
    # Bug registration is modelled as an automatically completed first step so
    # the Product Manager immediately receives a confirmation task.  Preserve
    # the same create-before-first-review deletion experience for its reporter.
    if (
        correction.allowed
        and entity_type == "bug"
        and entity_creator_user_id(db, entity_type, entity_id) == user.id
    ):
        return WorkflowEditAccess(True, mode="upstream_creator", task=correction.task)
    return WorkflowEditAccess(False, reason=correction.reason or "仅创建人可在首节点未查阅前删除", task=task)


def require_workflow_delete(
    db: Session,
    user: AuthUser,
    entity_type: str,
    entity_id: str,
    module: str,
) -> WorkflowEditAccess:
    access = workflow_delete_access(db, user, entity_type, entity_id, module, for_update=True)
    if not access.allowed:
        raise AppError("WORKFLOW_DELETE_LOCKED", access.reason or "当前流程节点不允许删除", 403)
    return access


def mark_task_viewed(
    db: Session,
    user: AuthUser,
    task_id: str,
    *,
    handling_action: bool = False,
) -> tuple[ProcessTask, bool]:
    """Persist a first *actual handler* view with a row lock.

    An administrator may inspect any detail or dispatch a task.  That passive
    observation is not the downstream handler's read and must not consume the
    upstream correction window.  An administrator who actually completes,
    approves or rejects the task is, however, handling it and is recorded.
    """
    task = (
        db.query(ProcessTask)
        .filter(ProcessTask.id == task_id, ProcessTask.is_deleted.is_(False))
        .with_for_update()
        .first()
    )
    if not task:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if task.status != "待处理":
        raise AppError("TASK_DONE", "该任务已处理")
    if not can_act_on_task(db, user, task):
        raise AppError("FORBIDDEN", "仅该任务的当前处理人可确认查阅", 403)
    if _is_admin(db, user) and task.assignee != user.person_id and not handling_action:
        # Do not turn a system administrator's passive inspection into a
        # downstream-view fact.  The UI normally avoids this request; keeping
        # the server behaviour safe protects direct API callers as well.
        return task, False
    # A role-routed task can be unassigned when no preferred person existed at
    # spawn time.  The first eligible person who opens it becomes its concrete
    # handler, preventing a second role holder from racing the correction lock.
    if task.assignee is None and user.person_id:
        task.assignee = user.person_id
        instance = db.get(ProcessInstance, task.instance_id)
        if instance and instance.entity_type in {"ticket", "ticket_change"}:
            ticket = db.get(Ticket, instance.entity_id)
            if ticket and not ticket.is_deleted:
                ticket.assignee = user.person_id
    newly_viewed = task.viewed_at is None
    if newly_viewed:
        task.viewed_at = datetime.now()
        task.viewed_by = user.person_id
    return task, newly_viewed


def can_act_on_task(db: Session, user: AuthUser, task: ProcessTask) -> bool:
    """任务操作权（M18/M25 统一）：admin、任务处理人本人；
    未指派任务（角色解析不到在岗用户）→ 步骤默认角色持有者可认领操作，避免流程卡死。"""
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    held = actor_keys(db, user)
    if ADMIN in held:
        return True
    if task.assignee:
        return bool(user.person_id and task.assignee == user.person_id)
    role = task.step.default_role if task.step else None
    return bool(role and role in held)


def pending_steps_map(db: Session, entity_types: list[str], entity_ids: list[str], user: AuthUser) -> dict:
    """列表页待办标识（M31）：批量取各单据当前待处理节点，标记是否轮到当前用户处理。

    返回 {entity_id: {"task_id","name","seq","assignee_name","mine"}}；无活跃节点的单据不在结果中。
    """
    if not entity_ids:
        return {}
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    held = actor_keys(db, user)
    is_admin = ADMIN in held
    instances = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type.in_(entity_types),
            ProcessInstance.entity_id.in_(entity_ids),
            ProcessInstance.status.in_(["running", "进行中"]),
            ProcessInstance.is_deleted.is_(False),
        )
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    # Do not use ``inst.tasks`` here.  The relationship may have been loaded
    # before the current node was spawned in the same Session, which makes
    # list-page pending badges lag behind the actual workflow node.
    pending_tasks = (
        db.query(ProcessTask)
        .filter(
            ProcessTask.instance_id.in_([inst.id for inst in instances]),
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
        )
        .order_by(ProcessTask.created_at.desc())
        .all()
    )
    pending_by_instance: dict[str, ProcessTask] = {}
    for task in pending_tasks:
        pending_by_instance.setdefault(task.instance_id, task)

    out: dict = {}
    for inst in instances:
        task = pending_by_instance.get(inst.id)
        if not task:
            continue
        mine = is_admin or bool(user.person_id and task.assignee == user.person_id)
        if not mine and not task.assignee:  # 未指派：默认角色持有者可认领（M25）
            role = task.step.default_role if task.step else None
            mine = bool(role and role in held)
        out[inst.entity_id] = {
            "task_id": task.id,
            "name": task.step.name if task.step else "",
            "seq": task.step.seq if task.step else None,
            "assignee_name": names.get(task.assignee) if task.assignee else None,
            "mine": mine,
        }
    return out


def flow_operator_check(db: Session, user: AuthUser, entity_type: str, entity_id: str) -> tuple[bool, str | None]:
    """流程驱动单据的状态操作权（M25）：有活跃流程时，仅当前步骤处理人或 admin 可流转状态。

    返回 (是否可操作, 当前处理人姓名)。无活跃流程 → (True, None)，回退调用方的模块权限控制。
    """
    task = current_pending_task(db, entity_type, entity_id)
    if not task:
        return True, None
    assignee_name = None
    if task.assignee:
        member = db.get(OrgMember, task.assignee)
        assignee_name = member.name if member else None
    return can_act_on_task(db, user, task), assignee_name


def require_flow_operator(db: Session, user: AuthUser, entity_type: str, entity_id: str) -> None:
    """接口层强制版 flow_operator_check：非当前处理人流转状态 → 403。"""
    ok, assignee_name = flow_operator_check(db, user, entity_type, entity_id)
    if not ok:
        raise AppError(
            "FLOW_OPERATOR_ONLY",
            f"当前流程节点由「{assignee_name or '待指派'}」处理，仅节点处理人可操作单据状态",
            403,
        )


def require_flow_operator_for_transition(db: Session, user: AuthUser, entity_type: str, entity_id: str,
                                         from_code: str, to_code: str) -> None:
    """状态流转的流程处理人校验（M25）：

    - allowed_roles 为空的普通流转（如 新建→处理中）→ 谁在处理谁操作，要求流程当前处理人；
    - 显式配置了 allowed_roles 的审批类流转（如 待审批→已批准 by CIO）→ 尊重状态机授权，
      由 wf_transition 的角色校验把关，不叠加流程处理人限制。
    """
    from app.services.workflow import get_transition

    rule = get_transition(db, entity_type, from_code, to_code)
    if rule and (rule.allowed_roles or []):
        return  # 审批类：状态机显式授权优先
    require_flow_operator(db, user, entity_type, entity_id)


def filter_targets_by_flow(db: Session, user: AuthUser, entity_type: str, entity_id: str,
                           from_code: str, targets: list[str]) -> list[str]:
    """detail 下发按钮列表的流程过滤：非当前处理人只保留审批类（显式授权）目标。"""
    from app.services.workflow import get_transition

    ok, _ = flow_operator_check(db, user, entity_type, entity_id)
    if ok:
        return targets
    kept = []
    for code in targets:
        rule = get_transition(db, entity_type, from_code, code)
        if rule and (rule.allowed_roles or []):
            kept.append(code)
    return kept


def finalize_instance(db: Session, entity_type: str, entity_id: str, note: str) -> ProcessInstance | None:
    """单据到达终态时收尾流程实例（M24）：未处理任务作废式完成（留痕），实例标记完成。

    修复反向脱节：手动关闭/驳回单据后，流程任务仍挂在处理人待办、监控显示 running。
    幂等：无 running 实例时返回 None。
    """
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == entity_type,
            ProcessInstance.entity_id == entity_id,
            ProcessInstance.status.in_(["running", "进行中"]),  # 兼容历史中文值（M24 迁移归一）
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not instance:
        return None
    now = datetime.now()
    for task in instance.tasks:
        if task.status == "待处理" and not task.is_deleted:
            task.status = "已完成"
            task.completed_at = now
            task.comment = note
    instance.status = "completed"
    instance.completed_at = now
    logger.info("process %s/%s finalized: %s", entity_type, entity_id, note)
    return instance


def reassign_task(db: Session, task_id: str, assignee: str) -> ProcessTask:
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    changed = assignee != task.assignee
    task.assignee = assignee
    if changed:
        instance = db.get(ProcessInstance, task.instance_id)
        step = db.get(ProcessStep, task.step_id)
        # A ticket has two projections of its current owner: the process task
        # is authoritative for who may operate the node, while Ticket.assignee
        # is what the list/detail APIs display.  Keep both in sync regardless
        # of whether reassignment came from the process monitor or the ticket
        # detail page.
        if instance and instance.entity_type in {"ticket", "ticket_change"}:
            from app.models import Ticket

            linked_ticket = db.get(Ticket, instance.entity_id)
            if linked_ticket and not linked_ticket.is_deleted:
                linked_ticket.assignee = assignee
        if instance and instance.entity_type == "ticket":
            from app.events.bus import publish

            publish(
                db,
                "ticket.assigned",
                "ticket",
                instance.entity_id,
                {
                    "assignee": assignee,
                    "step_code": step.step_code or f"step_{step.seq}",
                    "step_name": step.name,
                    "reassigned": True,
                },
            )
        _notify_assignee(db, instance, step, assignee, reassigned=True)
    return task


def instance_view(db: Session, entity_type: str, entity_id: str) -> dict | None:
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == entity_type,
            ProcessInstance.entity_id == entity_id,
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .first()
    )
    if not instance:
        return None
    member_names = {m.id: m.name for m in db.query(OrgMember).all()}
    # A workflow instance can have more than one task row for a step after a
    # rewind or correction.  Always use a fresh query and keep the newest
    # non-deleted task for the step; the relationship collection can be stale
    # after _spawn_task() adds the next node in the same transaction.
    tasks = (
        db.query(ProcessTask)
        .filter(ProcessTask.instance_id == instance.id, ProcessTask.is_deleted.is_(False))
        .order_by(ProcessTask.created_at.asc())
        .all()
    )
    tasks_by_step: dict[str, ProcessTask] = {}
    for task in tasks:
        tasks_by_step[task.step_id] = task
    current_task = (
        db.query(ProcessTask)
        .filter(
            ProcessTask.instance_id == instance.id,
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
        )
        .order_by(ProcessTask.created_at.desc())
        .first()
    )
    # The active pending task is the runtime source of truth.  The persisted
    # sequence remains a compatibility fallback for completed/legacy instances
    # that intentionally have no pending task.
    effective_current_step_seq = (
        current_task.step.seq if current_task and current_task.step else instance.current_step_seq
    )
    step_rows = []
    for step in _live_steps(instance.definition):
        task = tasks_by_step.get(step.id)
        snapshot = task.raci_snapshot if task and isinstance(task.raci_snapshot, dict) else {}
        informed = snapshot.get("informed")
        # A process definition may later adjust its non-blocking CC rule.  A
        # task that already exists must continue to show its own RACI snapshot,
        # including an intentionally empty CC list; a not-yet-started step uses
        # the latest definition and will snapshot it when activated.
        cc_roles = list(informed) if isinstance(informed, list) else (step.cc_roles or [])
        step_rows.append({
            "seq": step.seq,
            "step_code": step.step_code or f"step_{step.seq}",
            "name": step.name,
            "description": step.description,
            "node_type": step.node_type or "processing",
            "default_role": step.default_role,
            "cc_roles": cc_roles,
            "autonomy_level": step.autonomy_level,
            "task_id": task.id if task else None,
            "task_status": task.status if task else "未开始",
            "assignee": task.assignee if task else None,
            "assignee_name": member_names.get(task.assignee) if task and task.assignee else None,
            "due_at": task.due_at if task else None,
            "viewed_at": task.viewed_at if task else None,
            "viewed_by": task.viewed_by if task else None,
            "viewed_by_name": member_names.get(task.viewed_by) if task and task.viewed_by else None,
            "completed_at": task.completed_at if task else None,
            "raci_snapshot": task.raci_snapshot if task else None,
        })
    return {
        "id": instance.id,
        "definition_name": instance.definition.name,
        "definition_version": instance.definition.version,
        "status": instance.status,
        "current_step_seq": effective_current_step_seq,
        "current_step_code": (
            current_task.step.step_code if current_task and current_task.step and current_task.step.step_code
            else (f"step_{effective_current_step_seq}" if effective_current_step_seq is not None else None)
        ),
        "current_step_name": current_task.step.name if current_task and current_task.step else None,
        "steps": step_rows,
    }
