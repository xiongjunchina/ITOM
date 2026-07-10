"""统一状态机（docs/05 §6.1）：所有单据的状态流转唯一入口。

transition() = 合法性校验 + 角色校验 + 阶段必填字段校验 + 赋值 + 审计。
打点与领域事件由调用方（各域 service）在 transition 前后处理。
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import ADMIN
from app.models import AuthUser, WorkflowStatus, WorkflowTransition
from app.services.audit import audit
from app.services.rbac import actor_keys

# 各转换要求的阶段必填字段：{entity_type: {(from, to) 或 ("*", to): [字段]}}
STAGE_FIELDS: dict[str, dict[tuple, list[str]]] = {
    "ticket": {
        ("*", "resolved"): ["solution"],
        ("*", "closed"): ["closure_code"],
    },
    "ticket_change": {
        ("*", "resolved"): ["solution"],
        ("resolved", "closed"): ["closure_code"],
    },
    "problem": {
        ("*", "known_error"): ["root_cause"],
        ("*", "resolved"): ["root_cause"],
    },
}


def get_transition(db: Session, entity_type: str, from_code: str, to_code: str) -> WorkflowTransition | None:
    return (
        db.query(WorkflowTransition)
        .filter(
            WorkflowTransition.entity_type == entity_type,
            WorkflowTransition.from_code == from_code,
            WorkflowTransition.to_code == to_code,
            WorkflowTransition.is_deleted.is_(False),
        )
        .first()
    )


def transition(
    db: Session,
    entity,
    entity_type: str,
    to_code: str,
    fields: dict,
    actor: AuthUser,
    status_attr: str = "status",
):
    """执行状态流转；返回 (from_code, to_code)。调用方负责 commit 与事件。"""
    from_code = getattr(entity, status_attr)
    rule = get_transition(db, entity_type, from_code, to_code)
    if not rule:
        raise AppError("INVALID_TRANSITION", f"不允许从「{from_code}」流转到「{to_code}」")

    allowed = rule.allowed_roles or []
    if allowed:
        held = actor_keys(db, actor)
        if ADMIN not in held and not (held & set(allowed)):
            raise AppError("FORBIDDEN", "当前角色无权执行此流转", 403)

    required = STAGE_FIELDS.get(entity_type, {})
    need = required.get((from_code, to_code)) or required.get(("*", to_code)) or []
    for f in need:
        if not fields.get(f) and not getattr(entity, f, None):
            raise AppError("STAGE_FIELD_REQUIRED", f"此步骤必须填写：{f}")

    for k, v in fields.items():
        if hasattr(entity, k):
            setattr(entity, k, v)
    setattr(entity, status_attr, to_code)

    audit(db, entity_type, entity.id, "transition", actor, {"from": from_code, "to": to_code})
    return from_code, to_code


def status_names(db: Session, entity_type: str) -> dict[str, str]:
    rows = db.query(WorkflowStatus).filter(
        WorkflowStatus.entity_type == entity_type, WorkflowStatus.is_deleted.is_(False)
    )
    return {s.code: s.name for s in rows}


def allowed_targets(db: Session, entity_type: str, from_code: str, actor: AuthUser) -> list[str]:
    """给前端：当前状态+角色可流转到哪些状态。"""
    rows = (
        db.query(WorkflowTransition)
        .filter(
            WorkflowTransition.entity_type == entity_type,
            WorkflowTransition.from_code == from_code,
            WorkflowTransition.is_deleted.is_(False),
        )
        .all()
    )
    held = actor_keys(db, actor)
    result = []
    for t in rows:
        allowed = t.allowed_roles or []
        if not allowed or ADMIN in held or held & set(allowed):
            result.append(t.to_code)
    return result
