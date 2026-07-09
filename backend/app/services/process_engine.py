"""流程引擎最小版（PRD §8）：单据触发实例，任务按步骤推进，默认角色指派。"""
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
)


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
    """指派解析：优先单据受理人，否则按步骤默认角色找一个在岗成员（负载均衡留后续）。"""
    if preferred:
        return preferred
    if not step.default_role:
        return None
    candidates = (
        db.query(AuthUser)
        .join(OrgMember, AuthUser.person_id == OrgMember.id)
        .filter(AuthUser.is_active.is_(True), OrgMember.status == "在岗")
        .all()
    )
    user = next((u for u in candidates if step.default_role in (u.roles or [])), None)
    return user.person_id if user else None


def _spawn_task(db: Session, instance: ProcessInstance, step: ProcessStep, preferred: str | None):
    now = datetime.now()
    db.add(
        ProcessTask(
            instance_id=instance.id,
            step_id=step.id,
            assignee=_resolve_assignee(db, step, preferred),
            status="待处理",
            started_at=now,
            due_at=now + timedelta(hours=step.sla_hours) if step.sla_hours else None,
        )
    )


def start_instance(db: Session, entity_type: str, entity_id: str, entity_attrs: dict, preferred_assignee: str | None = None) -> ProcessInstance | None:
    definition = _match_definition(db, entity_type, entity_attrs)
    if not definition or not definition.steps:
        return None
    instance = ProcessInstance(
        definition_id=definition.id,
        entity_type=entity_type,
        entity_id=entity_id,
        current_step_seq=definition.steps[0].seq,
        started_at=datetime.now(),
    )
    db.add(instance)
    db.flush()
    _spawn_task(db, instance, definition.steps[0], preferred_assignee)
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
    steps = instance.definition.steps
    current_idx = next(i for i, s in enumerate(steps) if s.id == task.step_id)
    if current_idx + 1 < len(steps):
        next_step = steps[current_idx + 1]
        instance.current_step_seq = next_step.seq
        _spawn_task(db, instance, next_step, None)
    else:
        instance.status = "已完成"
        instance.completed_at = datetime.now()
    return instance


def reassign_task(db: Session, task_id: str, assignee: str) -> ProcessTask:
    task = db.get(ProcessTask, task_id)
    if not task or task.is_deleted:
        raise AppError("NOT_FOUND", "流程任务不存在", 404)
    task.assignee = assignee
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
    tasks_by_step = {t.step_id: t for t in instance.tasks}
    return {
        "id": instance.id,
        "definition_name": instance.definition.name,
        "status": instance.status,
        "current_step_seq": instance.current_step_seq,
        "steps": [
            {
                "seq": s.seq,
                "name": s.name,
                "default_role": s.default_role,
                "autonomy_level": s.autonomy_level,
                "task_id": tasks_by_step[s.id].id if s.id in tasks_by_step else None,
                "task_status": tasks_by_step[s.id].status if s.id in tasks_by_step else "未开始",
                "assignee": tasks_by_step[s.id].assignee if s.id in tasks_by_step else None,
                "assignee_name": member_names.get(tasks_by_step[s.id].assignee) if s.id in tasks_by_step and tasks_by_step[s.id].assignee else None,
                "due_at": tasks_by_step[s.id].due_at if s.id in tasks_by_step else None,
                "completed_at": tasks_by_step[s.id].completed_at if s.id in tasks_by_step else None,
            }
            for s in instance.definition.steps
        ],
    }
