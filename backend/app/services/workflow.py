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
    system: bool = False,
):
    """执行状态流转；返回 (from_code, to_code)。调用方负责 commit 与事件。

    system=True：系统编排动作（如流程完成自动闭环）跳过角色校验——审批语义已在流程步骤中履行。
    """
    from_code = getattr(entity, status_attr)
    rule = get_transition(db, entity_type, from_code, to_code)
    if not rule:
        raise AppError("INVALID_TRANSITION", f"不允许从「{from_code}」流转到「{to_code}」")

    allowed = rule.allowed_roles or []
    if allowed and not system:
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


#: 终态目标（M28）：普通授权的终态流转 = 强制关闭
TERMINAL_TARGETS = ("closed", "cancelled")


def require_terminal_transition_admin(db: Session, user: AuthUser, entity_type: str, from_code: str, to_code: str) -> None:
    """M28：普通授权（allowed_roles 空）的终态流转 = 强制关闭，仅系统管理员；
    显式授权的审批终态（如变更审批拒绝 by CIO）不受影响。单据正常闭环走流程完成自动关闭。"""
    if to_code not in TERMINAL_TARGETS:
        return
    rule = get_transition(db, entity_type, from_code, to_code)
    if rule is None:
        return  # 不存在的转换交由 wf_transition 报 INVALID_TRANSITION（语义更准确）
    if rule.allowed_roles or []:
        return
    if ADMIN not in actor_keys(db, user):
        raise AppError("FORCE_CLOSE_FORBIDDEN", "单据须走完流程自动闭环；仅系统管理员可强制关闭", 403)


def restrict_terminal_targets(db: Session, entity_type: str, from_code: str,
                              targets: list[str], allow_terminal: bool) -> list[str]:
    """detail 按钮列表的终态过滤（M28）：allow_terminal=False 时移除普通授权的终态目标。"""
    if allow_terminal:
        return targets
    kept = []
    for code in targets:
        if code in TERMINAL_TARGETS:
            rule = get_transition(db, entity_type, from_code, code)
            if not (rule and (rule.allowed_roles or [])):
                continue
        kept.append(code)
    return kept


def closure_path(db: Session, entity_type: str, src: str, actor: AuthUser,
                 dst: str = "closed", ignore_roles: bool = False) -> list[str] | None:
    """BFS 最短状态机路径 src→dst（尊重用户配置的转换与角色限制），不可达返回 None。

    ignore_roles=True：系统编排（流程完成自动闭环）不受操作者角色限制。
    """
    from collections import deque

    held = actor_keys(db, actor)
    adj: dict[str, list[str]] = {}
    rows = (
        db.query(WorkflowTransition)
        .filter(WorkflowTransition.entity_type == entity_type, WorkflowTransition.is_deleted.is_(False))
        .all()
    )
    for tr in rows:
        allowed = tr.allowed_roles or []
        if ignore_roles or not allowed or ADMIN in held or held & set(allowed):
            adj.setdefault(tr.from_code, []).append(tr.to_code)
    prev: dict[str, str | None] = {src: None}
    queue = deque([src])
    while queue:
        cur = queue.popleft()
        if cur == dst:
            break
        for nxt in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    if dst not in prev:
        return None
    path: list[str] = []
    node: str | None = dst
    while node is not None and node != src:
        path.append(node)
        node = prev[node]
    return list(reversed(path))


def status_names(db: Session, entity_type: str) -> dict[str, str]:
    from app.core.i18n import localize_status_map

    rows = db.query(WorkflowStatus).filter(
        WorkflowStatus.entity_type == entity_type, WorkflowStatus.is_deleted.is_(False)
    )
    return localize_status_map(entity_type, {s.code: s.name for s in rows})


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
