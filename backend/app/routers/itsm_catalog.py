"""服务目录 + 服务项 + SLA 策略/看板（PRD §5.3/5.5）。"""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import MANAGER
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import OrgMember, ServiceCatalog, ServiceItem, SlaPolicy, Ticket
from app.schemas.common import ok
from app.schemas.itsm import (
    CatalogCreate,
    CatalogUpdate,
    ServiceItemCreate,
    ServiceItemUpdate,
    SlaPolicyIn,
)
from app.services.audit import audit
from app.services.codes import gen_code

router = APIRouter(tags=["itsm"])


# ---- 服务目录 ----

@router.get("/api/catalogs")
def list_catalogs(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(ServiceCatalog).filter(ServiceCatalog.is_deleted.is_(False)).order_by(ServiceCatalog.sort).all()
    item_counts = dict(
        db.query(ServiceItem.catalog_id, func.count(ServiceItem.id))
        .filter(ServiceItem.is_deleted.is_(False))
        .group_by(ServiceItem.catalog_id)
        .all()
    )
    return ok(
        [
            {
                "id": c.id, "code": c.code, "name": c.name, "tier": c.tier,
                "description": c.description, "sort": c.sort, "status": c.status,
                "item_count": item_counts.get(c.id, 0),
            }
            for c in rows
        ],
        total=len(rows),
    )


@router.post("/api/catalogs")
def create_catalog(body: CatalogCreate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    catalog = ServiceCatalog(**body.model_dump(), code=gen_code(db, ServiceCatalog, "code", "SC"))
    db.add(catalog)
    db.flush()
    audit(db, "service_catalog", catalog.id, "create", actor, {"name": body.name})
    db.commit()
    return ok({"id": catalog.id})


@router.patch("/api/catalogs/{catalog_id}")
def update_catalog(catalog_id: str, body: CatalogUpdate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    catalog = db.get(ServiceCatalog, catalog_id)
    if not catalog or catalog.is_deleted:
        raise AppError("NOT_FOUND", "目录不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(catalog, k, v)
    audit(db, "service_catalog", catalog.id, "update", actor, data)
    db.commit()
    return ok({"id": catalog.id})


# ---- 服务项 ----

def _item_row(i: ServiceItem, db: Session) -> dict:
    owner = db.get(OrgMember, i.owner) if i.owner else None
    return {
        "id": i.id, "item_code": i.item_code, "name": i.name,
        "catalog_id": i.catalog_id, "catalog_name": i.catalog.name if i.catalog else None,
        "service_type": i.service_type, "owner": i.owner, "owner_name": owner.name if owner else None,
        "description": i.description,
        "sla_response_hours": i.sla_response_hours, "sla_resolution_hours": i.sla_resolution_hours,
        "target_audience": i.target_audience, "status": i.status,
    }


@router.get("/api/service-items")
def list_items(catalog_id: str = "", q: str = "", db: Session = Depends(get_db), _=Depends(get_current_user)):
    query = db.query(ServiceItem).filter(ServiceItem.is_deleted.is_(False))
    if catalog_id:
        query = query.filter(ServiceItem.catalog_id == catalog_id)
    if q:
        query = query.filter(ServiceItem.name.ilike(f"%{q}%"))
    rows = query.order_by(ServiceItem.created_at).all()
    return ok([_item_row(i, db) for i in rows], total=len(rows))


@router.post("/api/service-items")
def create_item(body: ServiceItemCreate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    if not db.get(ServiceCatalog, body.catalog_id):
        raise AppError("NOT_FOUND", "目录不存在", 404)
    item = ServiceItem(**body.model_dump(), item_code=gen_code(db, ServiceItem, "item_code", "SI"))
    db.add(item)
    db.flush()
    audit(db, "service_item", item.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_item_row(item, db))


@router.patch("/api/service-items/{item_id}")
def update_item(item_id: str, body: ServiceItemUpdate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    item = db.get(ServiceItem, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    audit(db, "service_item", item.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_item_row(item, db))


# ---- SLA 策略（admin）与看板 ----

@router.get("/api/admin/sla-policies")
def list_sla_policies(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(SlaPolicy).filter(SlaPolicy.is_deleted.is_(False)).order_by(SlaPolicy.priority).all()
    return ok(
        [
            {"id": p.id, "priority": p.priority, "response_minutes": p.response_minutes,
             "resolution_hours": p.resolution_hours, "active": p.active}
            for p in rows
        ]
    )


@router.put("/api/admin/sla-policies")
def upsert_sla_policies(body: list[SlaPolicyIn], db: Session = Depends(get_db), actor=Depends(require_roles())):
    for entry in body:
        row = db.query(SlaPolicy).filter(SlaPolicy.priority == entry.priority).first()
        if row:
            row.response_minutes = entry.response_minutes
            row.resolution_hours = entry.resolution_hours
            row.active = entry.active
        else:
            db.add(SlaPolicy(**entry.model_dump()))
    audit(db, "sla_policy", "batch", "upsert", actor, {"count": len(body)})
    db.commit()
    return ok({"count": len(body)})


@router.get("/api/sla/dashboard")
def sla_dashboard(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """实时达成率看板：本月按优先级 + 超时/临期清单。"""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resolved = (
        db.query(Ticket)
        .filter(Ticket.resolved_at >= month_start, Ticket.is_deleted.is_(False))
        .all()
    )
    by_priority = {}
    for p in ("P1", "P2", "P3", "P4"):
        subset = [t for t in resolved if t.priority == p and t.sla_resolution_met is not None]
        met = sum(1 for t in subset if t.sla_resolution_met)
        by_priority[p] = {
            "resolved": len(subset),
            "met": met,
            "rate": round(met / len(subset) * 100, 1) if subset else None,
        }
    open_overdue = (
        db.query(Ticket)
        .filter(
            Ticket.status.notin_(["resolved", "closed", "rejected"]),
            Ticket.sla_warned.is_(True),
            Ticket.is_deleted.is_(False),
        )
        .order_by(Ticket.submitted_at)
        .all()
    )
    return ok(
        {
            "month": now.strftime("%Y-%m"),
            "by_priority": by_priority,
            "warning_tickets": [
                {"id": t.id, "ticket_code": t.ticket_code, "title": t.title, "priority": t.priority,
                 "status": t.status, "submitted_at": t.submitted_at, "sla_resolution_hours": t.sla_resolution_hours}
                for t in open_overdue
            ],
        }
    )
