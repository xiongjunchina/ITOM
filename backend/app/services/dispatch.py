"""服务请求派单：服务项 → 目录 → 全局兜底，结果可审计。"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AuthUser,
    OrgMember,
    ServiceDispatchRule,
    ServiceItem,
    UserGroup,
    UserGroupMember,
)


@dataclass(frozen=True)
class DispatchDecision:
    assignee_id: str | None
    rule: ServiceDispatchRule | None
    source: str
    support_label: str
    manual_queue: bool = False


def _eligible_member(db: Session, person_id: str) -> OrgMember | None:
    member = db.get(OrgMember, person_id)
    if not member or member.is_deleted or member.status != "在岗":
        return None
    user = (
        db.query(AuthUser)
        .filter(
            AuthUser.person_id == member.id,
            AuthUser.is_active.is_(True),
            AuthUser.is_deleted.is_(False),
        )
        .first()
    )
    return member if user else None


def _group_candidates(db: Session, group_id: str) -> list[OrgMember]:
    return (
        db.query(OrgMember)
        .join(UserGroupMember, UserGroupMember.person_id == OrgMember.id)
        .join(AuthUser, AuthUser.person_id == OrgMember.id)
        .filter(
            UserGroupMember.group_id == group_id,
            UserGroupMember.is_deleted.is_(False),
            OrgMember.is_deleted.is_(False),
            OrgMember.status == "在岗",
            AuthUser.is_deleted.is_(False),
            AuthUser.is_active.is_(True),
        )
        .order_by(OrgMember.id)
        .all()
    )


def _pick(db: Session, rule: ServiceDispatchRule) -> str | None:
    if rule.target_type == "member":
        member = _eligible_member(db, rule.target_id)
        return member.id if member else None
    if rule.target_type != "group":
        return None
    group = db.get(UserGroup, rule.target_id)
    if not group or group.is_deleted:
        return None
    candidates = _group_candidates(db, group.id)
    if not candidates or rule.strategy == "manual_queue":
        return None
    if rule.strategy == "fixed":
        return candidates[0].id
    ids = [member.id for member in candidates]
    try:
        index = (ids.index(rule.last_assigned_member_id) + 1) % len(ids)
    except (ValueError, TypeError):
        index = 0
    return ids[index]


def resolve_rule(
    db: Session,
    item: ServiceItem,
    dispatch_stage: str = "acceptance",
) -> ServiceDispatchRule | None:
    """按服务项 → 目录 → 全局解析指定阶段派单规则。

    历史规则由迁移默认标记为 acceptance；implementation 只在受理转交时使用，
    因而不会改变存量工单或原有首节点派单。
    """
    scopes = (
        ("service_item", item.id),
        ("catalog", item.catalog_id),
        ("global", None),
    )
    for scope_type, scope_id in scopes:
        query = db.query(ServiceDispatchRule).filter(
            ServiceDispatchRule.scope_type == scope_type,
            ServiceDispatchRule.dispatch_stage == dispatch_stage,
            ServiceDispatchRule.active.is_(True),
            ServiceDispatchRule.is_deleted.is_(False),
        )
        query = query.filter(
            ServiceDispatchRule.scope_id == scope_id
            if scope_id is not None
            else ServiceDispatchRule.scope_id.is_(None)
        )
        row = query.order_by(ServiceDispatchRule.priority, ServiceDispatchRule.created_at).first()
        if row:
            return row
    return None


def preview(
    db: Session,
    item: ServiceItem,
    dispatch_stage: str = "acceptance",
) -> DispatchDecision:
    rule = resolve_rule(db, item, dispatch_stage)
    if not rule:
        return DispatchDecision(None, None, "unassigned", "IT 服务兜底队列")
    source = rule.scope_type
    assignee_id = _pick(db, rule)
    return DispatchDecision(
        assignee_id,
        rule,
        source,
        rule.name,
        manual_queue=rule.strategy == "manual_queue",
    )


def assign(
    db: Session,
    item: ServiceItem,
    dispatch_stage: str = "acceptance",
) -> DispatchDecision:
    decision = preview(db, item, dispatch_stage)
    if decision.rule and decision.assignee_id:
        decision.rule.last_assigned_member_id = decision.assignee_id
        decision.rule.last_assigned_at = datetime.now()
    return decision


def validate_rule_target(
    db: Session,
    target_type: str,
    target_id: str,
    strategy: str,
) -> None:
    if target_type == "member":
        if strategy not in {"fixed", "round_robin"}:
            raise AppError("INVALID_DISPATCH_RULE", "人员目标只支持 fixed 或 round_robin")
        if not _eligible_member(db, target_id):
            raise AppError("INVALID_DISPATCH_TARGET", "派单人员不存在、未启用或无活动账号")
        return
    group = db.get(UserGroup, target_id)
    if not group or group.is_deleted:
        raise AppError("INVALID_DISPATCH_TARGET", "派单用户组不存在")
    if strategy != "manual_queue" and not _group_candidates(db, target_id):
        raise AppError("INVALID_DISPATCH_TARGET", "派单用户组没有可用的在岗账号")
