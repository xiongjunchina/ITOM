"""平台产品运营 P0 领域服务。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.core.rbac import ADMIN, CIO, IT_BM, IT_PDM, IT_PDM_LEADER
from app.models import (
    AuthUser,
    BusinessDomain,
    BusinessDomainMember,
    OrgMember,
    PlatformCapacityCommitment,
    PlatformCapacityPlan,
    PlatformDemandProfile,
    PlatformServiceProfile,
    Requirement,
    ServiceItem,
)
from app.services.audit import audit
from app.services.rbac import effective_roles


def request_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decimal_string(value: Decimal | int | float | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _active(db: Session, model, row_id: str, message: str):
    row = db.query(model).filter(model.id == row_id, model.is_deleted.is_(False)).first()
    if not row:
        raise AppError("NOT_FOUND", message, 404)
    return row


def _optional_member(db: Session, member_id: str | None):
    if not member_id:
        return None
    return _active(db, OrgMember, member_id, "人员不存在")


def service_item(db: Session, service_item_id: str) -> ServiceItem:
    return _active(db, ServiceItem, service_item_id, "服务项不存在")


def platform_service(db: Session, service_item_id: str) -> PlatformServiceProfile:
    row = db.query(PlatformServiceProfile).filter(
        PlatformServiceProfile.service_item_id == service_item_id,
        PlatformServiceProfile.is_deleted.is_(False),
    ).first()
    if not row:
        raise AppError("PLATFORM_SERVICE_NOT_FOUND", "该服务项尚未启用平台服务档案", 404)
    return row


def requirement(db: Session, requirement_id: str) -> Requirement:
    return _active(db, Requirement, requirement_id, "需求不存在")


def business_domain(db: Session, domain_id: str) -> BusinessDomain:
    row = _active(db, BusinessDomain, domain_id, "业务域不存在")
    if not row.active:
        raise AppError("BUSINESS_DOMAIN_INACTIVE", "业务域已停用", 409)
    return row


def fdse_domain_ids(db: Session, actor: AuthUser) -> set[str] | None:
    """仅 FDSE 角色按明确业务域收敛；拥有治理角色时返回 None 表示全域。"""
    roles = effective_roles(db, actor)
    if not roles or roles.intersection({ADMIN, CIO, IT_BM, IT_PDM, IT_PDM_LEADER}):
        return None
    if "it_bp" not in roles:
        return None
    if not actor.person_id:
        return set()
    member_ids = {
        row.domain_id
        for row in db.query(BusinessDomainMember).filter(
            BusinessDomainMember.person_id == actor.person_id,
            BusinessDomainMember.is_deleted.is_(False),
        ).all()
    }
    owned = {
        row.id
        for row in db.query(BusinessDomain).filter(
            BusinessDomain.owner_id == actor.person_id,
            BusinessDomain.is_deleted.is_(False),
            BusinessDomain.active.is_(True),
        ).all()
    }
    return member_ids | owned


def require_demand_domain(db: Session, actor: AuthUser, domain_id: str):
    allowed = fdse_domain_ids(db, actor)
    if allowed is not None and domain_id not in allowed:
        raise AppError("PLATFORM_DOMAIN_FORBIDDEN", "只能维护本人获授权业务域的平台需求", 403)


def _net_capacity(values: dict[str, Any]) -> Decimal:
    gross = Decimal(str(values["gross_days"]))
    unavailable = Decimal(str(values.get("planned_unavailable_days", 0)))
    bau = Decimal(str(values.get("bau_reserve_days", 0)))
    risk = Decimal(str(values.get("risk_buffer_days", 0)))
    net = gross - unavailable - bau - risk
    if net < 0:
        raise AppError("CAPACITY_INVALID", "不可用、BAU 预留和风险缓冲之和不能超过总容量", 422)
    return net


def committed_days(db: Session, plan_id: str) -> Decimal:
    value = db.query(func.coalesce(func.sum(PlatformCapacityCommitment.capacity_days), 0)).filter(
        PlatformCapacityCommitment.plan_id == plan_id,
        PlatformCapacityCommitment.status != "cancelled",
        PlatformCapacityCommitment.is_deleted.is_(False),
    ).scalar()
    return Decimal(str(value or 0))


def service_payload(db: Session, profile: PlatformServiceProfile) -> dict:
    item = db.get(ServiceItem, profile.service_item_id)
    owner = db.get(OrgMember, profile.owner_id) if profile.owner_id else None
    return {
        "id": profile.id,
        "service_item_id": profile.service_item_id,
        "item_code": item.item_code if item else None,
        "name": item.name if item else None,
        "service_type": item.service_type if item else None,
        "status": item.status if item else None,
        "owner_id": profile.owner_id,
        "owner_name": owner.name if owner else None,
        "lifecycle": profile.lifecycle,
        "value_proposition": profile.value_proposition,
        "management_scope": profile.management_scope or {},
        "enabled_at": profile.enabled_at,
        "updated_at": profile.updated_at,
    }


def demand_payload(db: Session, profile: PlatformDemandProfile) -> dict:
    req = db.get(Requirement, profile.requirement_id)
    item = db.get(ServiceItem, profile.service_item_id)
    domain = db.get(BusinessDomain, profile.business_domain_id)
    return {
        "id": profile.id,
        "requirement_id": profile.requirement_id,
        "requirement_code": req.requirement_code if req else None,
        "title": req.title if req else None,
        "requirement_status": req.status if req else None,
        "service_item_id": profile.service_item_id,
        "service_name": item.name if item else None,
        "business_domain_id": profile.business_domain_id,
        "business_domain_name": domain.name if domain else None,
        "demand_class": profile.demand_class,
        "expected_outcome": profile.expected_outcome,
        "target_quarter": profile.target_quarter,
        "capacity_class": profile.capacity_class,
        "updated_at": profile.updated_at,
    }


def plan_payload(db: Session, plan: PlatformCapacityPlan, include_commitments: bool = False) -> dict:
    item = db.get(ServiceItem, plan.service_item_id)
    total = committed_days(db, plan.id)
    net = Decimal(str(plan.net_days))
    utilization = None if net == 0 else (total / net * Decimal("100")).quantize(Decimal("0.1"))
    data = {
        "id": plan.id,
        "service_item_id": plan.service_item_id,
        "service_name": item.name if item else None,
        "period": plan.period,
        "version": plan.version,
        "status": plan.status,
        "gross_days": decimal_string(plan.gross_days),
        "planned_unavailable_days": decimal_string(plan.planned_unavailable_days),
        "bau_reserve_days": decimal_string(plan.bau_reserve_days),
        "risk_buffer_days": decimal_string(plan.risk_buffer_days),
        "net_days": decimal_string(plan.net_days),
        "committed_days": decimal_string(total),
        "remaining_days": decimal_string(net - total),
        "utilization_percent": decimal_string(utilization),
        "notes": plan.notes,
        "approved_by": plan.approved_by,
        "approval_reason": plan.approval_reason,
        "approved_at": plan.approved_at,
        "previous_version_id": plan.previous_version_id,
        "updated_at": plan.updated_at,
    }
    if include_commitments:
        rows = db.query(PlatformCapacityCommitment).filter(
            PlatformCapacityCommitment.plan_id == plan.id,
            PlatformCapacityCommitment.is_deleted.is_(False),
        ).order_by(PlatformCapacityCommitment.created_at).all()
        data["commitments"] = [commitment_payload(db, row) for row in rows]
    return data


def commitment_payload(db: Session, row: PlatformCapacityCommitment) -> dict:
    owner = db.get(OrgMember, row.owner_id) if row.owner_id else None
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "title": row.title,
        "commitment_type": row.commitment_type,
        "capacity_days": decimal_string(row.capacity_days),
        "lifecycle_stage": row.lifecycle_stage,
        "investment_intent": row.investment_intent,
        "owner_id": row.owner_id,
        "owner_name": owner.name if owner else None,
        "status": row.status,
        "over_capacity_reason": row.over_capacity_reason,
        "over_capacity_approved_by": row.over_capacity_approved_by,
        "over_capacity_approved_at": row.over_capacity_approved_at,
    }


def create_service_profile(db: Session, actor: AuthUser, values: dict) -> PlatformServiceProfile:
    item = service_item(db, values["service_item_id"])
    ensure_not_example(item)
    if db.query(PlatformServiceProfile).filter(
        PlatformServiceProfile.service_item_id == item.id,
        PlatformServiceProfile.is_deleted.is_(False),
    ).first():
        raise AppError("PLATFORM_SERVICE_EXISTS", "该服务项已启用平台服务档案", 409)
    _optional_member(db, values.get("owner_id"))
    row = PlatformServiceProfile(**values, created_by=actor.id, updated_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, "platform_service_profile", row.id, "create", actor, {
        "service_item_id": row.service_item_id, "lifecycle": row.lifecycle,
    })
    db.commit()
    return row


def update_service_profile(db: Session, actor: AuthUser, service_item_id: str, values: dict) -> PlatformServiceProfile:
    row = platform_service(db, service_item_id)
    ensure_not_example(row)
    reason = values.pop("lifecycle_change_reason", None)
    next_lifecycle = values.get("lifecycle")
    if next_lifecycle and next_lifecycle != row.lifecycle:
        normal_next = {
            "candidate": "pilot", "pilot": "active", "active": "retiring", "retiring": "retired",
        }.get(row.lifecycle)
        if next_lifecycle != normal_next and (not reason or len(reason.strip()) < 5):
            raise AppError("PLATFORM_LIFECYCLE_REASON_REQUIRED", "跨阶段或恢复平台服务必须填写清晰理由", 422)
    if "owner_id" in values:
        _optional_member(db, values["owner_id"])
    before = {key: getattr(row, key) for key in values}
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = actor.id
    audit(db, "platform_service_profile", row.id, "update", actor, {
        "before": before, "after": values, "lifecycle_change_reason": reason,
    })
    db.commit()
    return row


def create_demand_profile(db: Session, actor: AuthUser, values: dict) -> PlatformDemandProfile:
    req = requirement(db, values["requirement_id"])
    ensure_not_example(req)
    platform_service(db, values["service_item_id"])
    business_domain(db, values["business_domain_id"])
    if req.business_domain_id != values["business_domain_id"]:
        raise AppError("DEMAND_DOMAIN_MISMATCH", "平台需求业务域必须与需求主记录一致", 422)
    require_demand_domain(db, actor, values["business_domain_id"])
    if db.query(PlatformDemandProfile).filter(
        PlatformDemandProfile.requirement_id == req.id,
        PlatformDemandProfile.is_deleted.is_(False),
    ).first():
        raise AppError("PLATFORM_DEMAND_EXISTS", "该需求已进入平台需求池", 409)
    row = PlatformDemandProfile(**values, created_by=actor.id, updated_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, "platform_demand_profile", row.id, "create", actor, {
        "requirement_id": row.requirement_id, "service_item_id": row.service_item_id,
        "business_domain_id": row.business_domain_id,
    })
    db.commit()
    return row


def update_demand_profile(db: Session, actor: AuthUser, requirement_id: str, values: dict) -> PlatformDemandProfile:
    row = db.query(PlatformDemandProfile).filter(
        PlatformDemandProfile.requirement_id == requirement_id,
        PlatformDemandProfile.is_deleted.is_(False),
    ).first()
    if not row:
        raise AppError("PLATFORM_DEMAND_NOT_FOUND", "该需求尚未进入平台需求池", 404)
    ensure_not_example(row)
    require_demand_domain(db, actor, row.business_domain_id)
    target_domain = values.get("business_domain_id", row.business_domain_id)
    req = requirement(db, requirement_id)
    if target_domain != req.business_domain_id:
        raise AppError("DEMAND_DOMAIN_MISMATCH", "平台需求业务域必须与需求主记录一致", 422)
    require_demand_domain(db, actor, target_domain)
    if "service_item_id" in values:
        platform_service(db, values["service_item_id"])
    if "business_domain_id" in values:
        business_domain(db, target_domain)
    before = {key: getattr(row, key) for key in values}
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = actor.id
    audit(db, "platform_demand_profile", row.id, "update", actor, {"before": before, "after": values})
    db.commit()
    return row


def find_idempotent(db: Session, model, actor_id: str, key: str, digest: str):
    row = db.query(model).filter(
        model.created_by == actor_id,
        model.idempotency_key == key,
        model.is_deleted.is_(False),
    ).first()
    if row and row.request_digest != digest:
        raise AppError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求", 409)
    return row


def create_capacity_plan(db: Session, actor: AuthUser, values: dict, key: str) -> PlatformCapacityPlan:
    platform_service(db, values["service_item_id"])
    digest = request_digest(values)
    replay = find_idempotent(db, PlatformCapacityPlan, actor.id, key, digest)
    if replay:
        return replay
    if db.query(PlatformCapacityPlan).filter(
        PlatformCapacityPlan.service_item_id == values["service_item_id"],
        PlatformCapacityPlan.period == values["period"],
        PlatformCapacityPlan.version == 1,
        PlatformCapacityPlan.is_deleted.is_(False),
    ).first():
        raise AppError("CAPACITY_PLAN_EXISTS", "该服务和季度已存在容量计划", 409)
    row = PlatformCapacityPlan(
        **values, version=1, status="draft", net_days=_net_capacity(values),
        created_by=actor.id, updated_by=actor.id, idempotency_key=key, request_digest=digest,
    )
    db.add(row)
    db.flush()
    audit(db, "platform_capacity_plan", row.id, "create", actor, {
        "service_item_id": row.service_item_id, "period": row.period, "version": row.version,
    })
    db.commit()
    return row


def update_capacity_plan(db: Session, actor: AuthUser, plan_id: str, values: dict) -> PlatformCapacityPlan:
    row = _active(db, PlatformCapacityPlan, plan_id, "容量计划不存在")
    ensure_not_example(row)
    if row.status != "draft":
        raise AppError("CAPACITY_PLAN_LOCKED", "只有草稿容量计划可以修改；已批准计划请创建修订版本", 409)
    merged = {
        "gross_days": values.get("gross_days", row.gross_days),
        "planned_unavailable_days": values.get("planned_unavailable_days", row.planned_unavailable_days),
        "bau_reserve_days": values.get("bau_reserve_days", row.bau_reserve_days),
        "risk_buffer_days": values.get("risk_buffer_days", row.risk_buffer_days),
    }
    net = _net_capacity(merged)
    if committed_days(db, row.id) > net:
        raise AppError("CAPACITY_BELOW_COMMITMENTS", "净容量不能低于当前有效承诺容量", 409)
    before = {key: decimal_string(getattr(row, key)) if key.endswith("days") else getattr(row, key) for key in values}
    for key, value in values.items():
        setattr(row, key, value)
    row.net_days = net
    row.updated_by = actor.id
    audit(db, "platform_capacity_plan", row.id, "update", actor, {"before": before, "after": values})
    db.commit()
    return row


def transition_capacity_plan(db: Session, actor: AuthUser, plan_id: str, action: str, reason: str | None = None) -> PlatformCapacityPlan:
    row = _active(db, PlatformCapacityPlan, plan_id, "容量计划不存在")
    ensure_not_example(row)
    if action == "submit":
        if row.status != "draft":
            raise AppError("CAPACITY_TRANSITION_INVALID", "只有草稿容量计划可以提交审核", 409)
        row.status = "review"
    elif action == "approve":
        if row.status != "review":
            raise AppError("CAPACITY_TRANSITION_INVALID", "只有待审核容量计划可以批准", 409)
        roles = effective_roles(db, actor)
        if not roles.intersection({CIO, IT_PDM_LEADER}):
            raise AppError("CAPACITY_APPROVAL_FORBIDDEN", "仅平台负责人或 CIO 可以批准容量计划", 403)
        row.status = "approved"
        row.approved_by = actor.id
        row.approval_reason = reason
        row.approved_at = datetime.now()
    else:
        raise AppError("CAPACITY_TRANSITION_INVALID", "不支持的容量计划状态操作", 422)
    row.updated_by = actor.id
    audit(db, "platform_capacity_plan", row.id, action, actor, {"status": row.status, "reason": reason})
    db.commit()
    return row


def create_commitment(db: Session, actor: AuthUser, plan_id: str, values: dict, key: str) -> PlatformCapacityCommitment:
    plan = _active(db, PlatformCapacityPlan, plan_id, "容量计划不存在")
    ensure_not_example(plan)
    if plan.status != "draft":
        raise AppError("CAPACITY_PLAN_LOCKED", "只有草稿容量计划可以调整承诺", 409)
    digest_values = {**values, "plan_id": plan_id}
    digest = request_digest(digest_values)
    replay = find_idempotent(db, PlatformCapacityCommitment, actor.id, key, digest)
    if replay:
        return replay
    allow_overcommit = bool(values.pop("allow_overcommit", False))
    reason = values.pop("over_capacity_reason", None)
    if values["subject_type"] == "requirement":
        if not values.get("subject_id"):
            raise AppError("COMMITMENT_SUBJECT_REQUIRED", "需求承诺必须选择需求", 422)
        demand = db.query(PlatformDemandProfile).filter(
            PlatformDemandProfile.requirement_id == values["subject_id"],
            PlatformDemandProfile.is_deleted.is_(False),
        ).first()
        if not demand or demand.service_item_id != plan.service_item_id:
            raise AppError("COMMITMENT_SUBJECT_INVALID", "需求必须已进入当前平台服务的需求池", 422)
    _optional_member(db, values.get("owner_id"))
    proposed = committed_days(db, plan.id) + Decimal(str(values["capacity_days"]))
    over = proposed > Decimal(str(plan.net_days))
    approved_by = approved_at = None
    if over:
        roles = effective_roles(db, actor)
        if not allow_overcommit:
            raise AppError("CAPACITY_EXCEEDED", "承诺容量超过净容量，请调整计划或由 CIO 批准例外", 409)
        if CIO not in roles:
            raise AppError("CAPACITY_OVERRIDE_FORBIDDEN", "仅 CIO 可以批准超容量例外", 403)
        if not reason or len(reason.strip()) < 5:
            raise AppError("CAPACITY_OVERRIDE_REASON_REQUIRED", "超容量例外必须填写清晰理由", 422)
        approved_by = actor.id
        approved_at = datetime.now()
    row = PlatformCapacityCommitment(
        **values, plan_id=plan.id, created_by=actor.id, updated_by=actor.id,
        idempotency_key=key, request_digest=digest,
        over_capacity_reason=reason if over else None,
        over_capacity_approved_by=approved_by,
        over_capacity_approved_at=approved_at,
    )
    db.add(row)
    db.flush()
    audit(db, "platform_capacity_commitment", row.id, "create", actor, {
        "plan_id": plan.id, "capacity_days": decimal_string(row.capacity_days),
        "over_capacity": over, "over_capacity_reason": reason if over else None,
    })
    db.commit()
    return row


def create_revision(db: Session, actor: AuthUser, plan_id: str, values: dict, key: str) -> PlatformCapacityPlan:
    previous = _active(db, PlatformCapacityPlan, plan_id, "容量计划不存在")
    ensure_not_example(previous)
    if previous.status not in {"approved", "superseded"}:
        raise AppError("CAPACITY_REVISION_INVALID", "只有已批准或已替代的计划可以创建修订版本", 409)
    if values["service_item_id"] != previous.service_item_id or values["period"] != previous.period:
        raise AppError("CAPACITY_REVISION_SCOPE_INVALID", "修订版本不能改变平台服务或季度", 422)
    digest_values = {**values, "previous_version_id": previous.id}
    digest = request_digest(digest_values)
    replay = find_idempotent(db, PlatformCapacityPlan, actor.id, key, digest)
    if replay:
        return replay
    revision_reason = values.pop("revision_reason")
    if not values.get("notes"):
        values["notes"] = revision_reason
    latest_version = db.query(func.max(PlatformCapacityPlan.version)).filter(
        PlatformCapacityPlan.service_item_id == previous.service_item_id,
        PlatformCapacityPlan.period == previous.period,
        PlatformCapacityPlan.is_deleted.is_(False),
    ).scalar() or 0
    row = PlatformCapacityPlan(
        **values, version=latest_version + 1, status="draft", net_days=_net_capacity(values),
        created_by=actor.id, updated_by=actor.id, idempotency_key=key, request_digest=digest,
        previous_version_id=previous.id,
    )
    db.add(row)
    db.flush()
    old_commitments = db.query(PlatformCapacityCommitment).filter(
        PlatformCapacityCommitment.plan_id == previous.id,
        PlatformCapacityCommitment.is_deleted.is_(False),
        PlatformCapacityCommitment.status != "cancelled",
    ).all()
    total = sum((Decimal(str(item.capacity_days)) for item in old_commitments), Decimal("0"))
    if total > Decimal(str(row.net_days)):
        raise AppError("CAPACITY_REVISION_TOO_SMALL", "修订净容量不能低于需要继承的有效承诺容量", 409)
    for item in old_commitments:
        copy = PlatformCapacityCommitment(
            plan_id=row.id, subject_type=item.subject_type, subject_id=item.subject_id,
            title=item.title, commitment_type=item.commitment_type, capacity_days=item.capacity_days,
            lifecycle_stage=item.lifecycle_stage, investment_intent=item.investment_intent,
            owner_id=item.owner_id, status=item.status, created_by=actor.id, updated_by=actor.id,
            idempotency_key=f"{key}:{item.id}",
            request_digest=request_digest({"revision": row.id, "commitment": item.id}),
        )
        db.add(copy)
    previous.status = "superseded"
    previous.updated_by = actor.id
    audit(db, "platform_capacity_plan", row.id, "create_revision", actor, {
        "previous_version_id": previous.id, "revision_reason": revision_reason, "version": row.version,
    })
    db.commit()
    return row


def apply_fdse_demand_scope(query, db: Session, actor: AuthUser):
    allowed = fdse_domain_ids(db, actor)
    if allowed is None:
        return query
    if not allowed:
        return query.filter(PlatformDemandProfile.id == "")
    return query.filter(PlatformDemandProfile.business_domain_id.in_(allowed))
