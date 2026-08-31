"""平台产品运营 P0 API。"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_perm
from app.models import (
    AuthUser,
    PlatformCapacityPlan,
    PlatformDemandProfile,
    PlatformServiceProfile,
    Requirement,
    ServiceItem,
)
from app.schemas.common import ok, paginate
from app.schemas.platform import (
    CapacityApprovalIn,
    CapacityCommitmentIn,
    CapacityPlanIn,
    CapacityPlanUpdate,
    CapacityRevisionIn,
    PlatformDemandIn,
    PlatformDemandUpdate,
    PlatformServiceIn,
    PlatformServiceUpdate,
)
from app.services.platform_operations import (
    apply_fdse_demand_scope,
    create_capacity_plan,
    create_commitment,
    create_demand_profile,
    create_revision,
    create_service_profile,
    demand_payload,
    plan_payload,
    platform_service,
    service_payload,
    transition_capacity_plan,
    update_capacity_plan,
    update_demand_profile,
    update_service_profile,
)


router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/services")
def list_platform_services(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    lifecycle: str = "",
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("platform_portfolio", "view")),
):
    query = db.query(PlatformServiceProfile).join(
        ServiceItem, ServiceItem.id == PlatformServiceProfile.service_item_id
    ).filter(
        PlatformServiceProfile.is_deleted.is_(False),
        ServiceItem.is_deleted.is_(False),
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(ServiceItem.item_code.ilike(like), ServiceItem.name.ilike(like)))
    if lifecycle:
        query = query.filter(PlatformServiceProfile.lifecycle == lifecycle)
    query = query.order_by(PlatformServiceProfile.is_example.desc(), ServiceItem.item_code)
    rows, total = paginate(query, page, page_size)
    return ok([service_payload(db, row) for row in rows], total=total, page=page)


@router.post("/services")
def enable_platform_service(
    body: PlatformServiceIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "edit")),
):
    row = create_service_profile(db, actor, body.model_dump())
    return ok(service_payload(db, row))


@router.get("/services/{service_item_id}")
def get_platform_service(
    service_item_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("platform_portfolio", "view")),
):
    return ok(service_payload(db, platform_service(db, service_item_id)))


@router.patch("/services/{service_item_id}")
def patch_platform_service(
    service_item_id: str,
    body: PlatformServiceUpdate,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "edit")),
):
    row = update_service_profile(db, actor, service_item_id, body.model_dump(exclude_unset=True))
    return ok(service_payload(db, row))


@router.get("/demands")
def list_platform_demands(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    service_item_id: str = "",
    business_domain_id: str = "",
    target_quarter: str = "",
    demand_class: str = "",
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "view")),
):
    query = db.query(PlatformDemandProfile).join(
        Requirement, Requirement.id == PlatformDemandProfile.requirement_id
    ).filter(
        PlatformDemandProfile.is_deleted.is_(False),
        Requirement.is_deleted.is_(False),
    )
    query = apply_fdse_demand_scope(query, db, actor)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Requirement.requirement_code.ilike(like), Requirement.title.ilike(like)))
    if service_item_id:
        query = query.filter(PlatformDemandProfile.service_item_id == service_item_id)
    if business_domain_id:
        query = query.filter(PlatformDemandProfile.business_domain_id == business_domain_id)
    if target_quarter:
        query = query.filter(PlatformDemandProfile.target_quarter == target_quarter)
    if demand_class:
        query = query.filter(PlatformDemandProfile.demand_class == demand_class)
    query = query.order_by(PlatformDemandProfile.target_quarter, Requirement.requirement_code)
    rows, total = paginate(query, page, page_size)
    return ok([demand_payload(db, row) for row in rows], total=total, page=page)


@router.post("/demands")
def add_platform_demand(
    body: PlatformDemandIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "create")),
):
    row = create_demand_profile(db, actor, body.model_dump())
    return ok(demand_payload(db, row))


@router.get("/demands/{requirement_id}")
def get_platform_demand(
    requirement_id: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "view")),
):
    query = db.query(PlatformDemandProfile).filter(
        PlatformDemandProfile.requirement_id == requirement_id,
        PlatformDemandProfile.is_deleted.is_(False),
    )
    row = apply_fdse_demand_scope(query, db, actor).first()
    if not row:
        from app.core.errors import AppError
        raise AppError("PLATFORM_DEMAND_NOT_FOUND", "该需求尚未进入平台需求池或无权查看", 404)
    return ok(demand_payload(db, row))


@router.patch("/demands/{requirement_id}")
def patch_platform_demand(
    requirement_id: str,
    body: PlatformDemandUpdate,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_portfolio", "create")),
):
    row = update_demand_profile(db, actor, requirement_id, body.model_dump(exclude_unset=True))
    return ok(demand_payload(db, row))


@router.get("/capacity-plans")
def list_capacity_plans(
    page: int = 1,
    page_size: int = 50,
    service_item_id: str = "",
    period: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("platform_capacity", "view")),
):
    query = db.query(PlatformCapacityPlan).filter(PlatformCapacityPlan.is_deleted.is_(False))
    if service_item_id:
        query = query.filter(PlatformCapacityPlan.service_item_id == service_item_id)
    if period:
        query = query.filter(PlatformCapacityPlan.period == period)
    if status:
        query = query.filter(PlatformCapacityPlan.status == status)
    query = query.order_by(PlatformCapacityPlan.period.desc(), PlatformCapacityPlan.version.desc())
    rows, total = paginate(query, page, page_size)
    return ok([plan_payload(db, row) for row in rows], total=total, page=page)


@router.post("/capacity-plans")
def add_capacity_plan(
    body: CapacityPlanIn,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "create")),
):
    row = create_capacity_plan(db, actor, body.model_dump(), idempotency_key)
    return ok(plan_payload(db, row, include_commitments=True))


@router.get("/capacity-plans/{plan_id}")
def get_capacity_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("platform_capacity", "view")),
):
    from app.core.errors import AppError
    row = db.query(PlatformCapacityPlan).filter(
        PlatformCapacityPlan.id == plan_id,
        PlatformCapacityPlan.is_deleted.is_(False),
    ).first()
    if not row:
        raise AppError("NOT_FOUND", "容量计划不存在", 404)
    return ok(plan_payload(db, row, include_commitments=True))


@router.patch("/capacity-plans/{plan_id}")
def patch_capacity_plan(
    plan_id: str,
    body: CapacityPlanUpdate,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "edit")),
):
    row = update_capacity_plan(db, actor, plan_id, body.model_dump(exclude_unset=True))
    return ok(plan_payload(db, row, include_commitments=True))


@router.post("/capacity-plans/{plan_id}/submit")
def submit_capacity_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "edit")),
):
    return ok(plan_payload(db, transition_capacity_plan(db, actor, plan_id, "submit"), True))


@router.post("/capacity-plans/{plan_id}/approve")
def approve_capacity_plan(
    plan_id: str,
    body: CapacityApprovalIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "edit")),
):
    return ok(plan_payload(db, transition_capacity_plan(db, actor, plan_id, "approve", body.reason), True))


@router.post("/capacity-plans/{plan_id}/revisions")
def revise_capacity_plan(
    plan_id: str,
    body: CapacityRevisionIn,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "edit")),
):
    row = create_revision(db, actor, plan_id, body.model_dump(), idempotency_key)
    return ok(plan_payload(db, row, include_commitments=True))


@router.post("/capacity-plans/{plan_id}/commitments")
def add_capacity_commitment(
    plan_id: str,
    body: CapacityCommitmentIn,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("platform_capacity", "create")),
):
    row = create_commitment(db, actor, plan_id, body.model_dump(), idempotency_key)
    from app.services.platform_operations import commitment_payload
    return ok(commitment_payload(db, row))
