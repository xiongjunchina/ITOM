"""流程引擎最小版（PRD §8）：单据触发实例，任务按步骤推进，默认角色指派。"""
import logging
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
)
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


def _spawn_task(db: Session, instance: ProcessInstance, step: ProcessStep, preferred: str | None):
    now = datetime.now()
    # 项目流程中的 IT PM 节点必须跟随项目主数据指定的项目经理，不能从所有
    # it_pm 角色持有人中任取一人。这样章程导入/手工创建、后续推进与流程回退
    # 使用同一责任人；非 IT PM 节点（如 it_pmo 收尾复盘）仍按节点角色解析。
    if instance.entity_type == "project":
        from app.models import Project

        project = db.get(Project, instance.entity_id)
        preferred = project.pm if project and step.default_role == "it_pm" else None
    if step.default_role == "requester":
        # 「用户确认」类步骤：指派该单据的提交人本人，而非任意业务用户
        assignee = _requester_person(db, instance.entity_type, instance.entity_id) or _resolve_assignee(db, step, preferred)
    else:
        assignee = _resolve_assignee(db, step, preferred)
    db.add(
        ProcessTask(
            instance_id=instance.id,
            step_id=step.id,
            assignee=assignee,
            status="待处理",
            started_at=now,
            due_at=now + timedelta(hours=step.sla_hours) if step.sla_hours else None,
        )
    )
    _notify_assignee(db, instance, step, assignee)
    _notify_cc(db, instance, step, assignee)


def _live_steps(definition: ProcessDefinition) -> list[ProcessStep]:
    """定义的有效步骤（编辑收缩产生的软删步骤不参与执行/展示）。"""
    return [s for s in definition.steps if not s.is_deleted]


def start_instance(db: Session, entity_type: str, entity_id: str, entity_attrs: dict, preferred_assignee: str | None = None) -> ProcessInstance | None:
    definition = _match_definition(db, entity_type, entity_attrs)
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
    _spawn_task(db, instance, _live_steps(definition)[0], preferred_assignee)
    return instance


def complete_task(db: Session, task_id: str, actor: AuthUser, comment: str = "") -> ProcessInstance:
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    if task.status != "待处理":
        raise AppError("TASK_DONE", "该任务已处理")
    task.status = "已完成"
    task.completed_at = datetime.now()
    task.comment = comment or task.comment

    instance = db.get(ProcessInstance, task.instance_id)
    steps = _live_steps(instance.definition)
    current_idx = next(i for i, s in enumerate(steps) if s.id == task.step_id)
    if current_idx + 1 < len(steps):
        next_step = steps[current_idx + 1]
        instance.current_step_seq = next_step.seq
        _spawn_task(db, instance, next_step, None)
    else:
        instance.status = "completed"
        instance.completed_at = datetime.now()
    return instance


def approve_task(db: Session, task_id: str, actor: AuthUser, comment: str = "") -> ProcessInstance:
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
    return complete_task(db, task_id, actor, comment)


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


def current_pending_task(db: Session, entity_type: str, entity_id: str) -> ProcessTask | None:
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
    return next((t for t in instance.tasks if t.status == "待处理" and not t.is_deleted), None)


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
    out: dict = {}
    for inst in instances:
        task = next((t for t in inst.tasks if t.status == "待处理" and not t.is_deleted), None)
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
    tasks_by_step = {t.step_id: t for t in instance.tasks if not t.is_deleted}  # 回退作废的任务不算现状
    return {
        "id": instance.id,
        "definition_name": instance.definition.name,
        "status": instance.status,
        "current_step_seq": instance.current_step_seq,
        "steps": [
            {
                "seq": s.seq,
                "name": s.name,
                "description": s.description,
                "node_type": s.node_type or "processing",
                "default_role": s.default_role,
                "cc_roles": s.cc_roles or [],
                "autonomy_level": s.autonomy_level,
                "task_id": tasks_by_step[s.id].id if s.id in tasks_by_step else None,
                "task_status": tasks_by_step[s.id].status if s.id in tasks_by_step else "未开始",
                "assignee": tasks_by_step[s.id].assignee if s.id in tasks_by_step else None,
                "assignee_name": member_names.get(tasks_by_step[s.id].assignee) if s.id in tasks_by_step and tasks_by_step[s.id].assignee else None,
                "due_at": tasks_by_step[s.id].due_at if s.id in tasks_by_step else None,
                "completed_at": tasks_by_step[s.id].completed_at if s.id in tasks_by_step else None,
            }
            for s in _live_steps(instance.definition)
        ],
    }
