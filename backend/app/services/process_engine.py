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
