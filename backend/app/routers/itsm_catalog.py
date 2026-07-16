"""服务目录 + 服务项 + SLA 策略/看板（PRD §5.3/5.5）。"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
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
def list_catalogs(db: Session = Depends(get_db), _=Depends(require_perm("catalog", "view"))):
    rows = db.query(ServiceCatalog).filter(ServiceCatalog.is_deleted.is_(False)).order_by(ServiceCatalog.is_example.desc(), ServiceCatalog.sort).all()
    item_counts = dict(
        db.query(ServiceItem.catalog_id, func.count(ServiceItem.id))
        .filter(ServiceItem.is_deleted.is_(False))
        .group_by(ServiceItem.catalog_id)
        .all()
    )
    return ok(
        [
            {
                "id": c.id, "code": c.code, "name": c.name, "tier": c.tier, "is_example": c.is_example,
                "description": c.description, "sort": c.sort, "status": c.status,
                "item_count": item_counts.get(c.id, 0),
            }
            for c in rows
        ],
        total=len(rows),
    )


@router.post("/api/catalogs")
def create_catalog(body: CatalogCreate, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "create"))):
    catalog = ServiceCatalog(**body.model_dump(), code=gen_code(db, ServiceCatalog, "code", "SC"))
    db.add(catalog)
    db.flush()
    audit(db, "service_catalog", catalog.id, "create", actor, {"name": body.name})
    db.commit()
    return ok({"id": catalog.id})


@router.patch("/api/catalogs/{catalog_id}")
def update_catalog(catalog_id: str, body: CatalogUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "edit"))):
    catalog = db.get(ServiceCatalog, catalog_id)
    if not catalog or catalog.is_deleted:
        raise AppError("NOT_FOUND", "目录不存在", 404)
    ensure_not_example(catalog)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(catalog, k, v)
    audit(db, "service_catalog", catalog.id, "update", actor, data)
    db.commit()
    return ok({"id": catalog.id})


@router.delete("/api/catalogs/{catalog_id}")
def delete_catalog(catalog_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "delete"))):
    """删除服务目录（M21，软删）：目录下仍有服务项时拒绝。"""
    catalog = db.get(ServiceCatalog, catalog_id)
    if not catalog or catalog.is_deleted:
        raise AppError("NOT_FOUND", "目录不存在", 404)
    ensure_not_example(catalog)
    live = db.query(ServiceItem).filter(ServiceItem.catalog_id == catalog.id, ServiceItem.is_deleted.is_(False)).count()
    if live > 0:
        raise AppError("CATALOG_IN_USE", f"该目录下还有 {live} 个服务项，请先删除或迁移服务项")
    catalog.is_deleted = True
    audit(db, "service_catalog", catalog.id, "delete", actor, {"code": catalog.code, "name": catalog.name})
    db.commit()
    return ok({"id": catalog.id})


# ---- 服务项 ----

def _item_row(i: ServiceItem, db: Session) -> dict:
    owner = db.get(OrgMember, i.owner) if i.owner else None
    return {
        "id": i.id, "item_code": i.item_code, "name": i.name, "is_example": i.is_example,
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
    rows = query.order_by(ServiceItem.is_example.desc(), ServiceItem.created_at).all()
    return ok([_item_row(i, db) for i in rows], total=len(rows))


@router.post("/api/service-items")
def create_item(body: ServiceItemCreate, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "create"))):
    if not db.get(ServiceCatalog, body.catalog_id):
        raise AppError("NOT_FOUND", "目录不存在", 404)
    item = ServiceItem(**body.model_dump(), item_code=gen_code(db, ServiceItem, "item_code", "SI"))
    db.add(item)
    db.flush()
    audit(db, "service_item", item.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_item_row(item, db))


@router.patch("/api/service-items/{item_id}")
def update_item(item_id: str, body: ServiceItemUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "edit"))):
    item = db.get(ServiceItem, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    ensure_not_example(item)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    audit(db, "service_item", item.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_item_row(item, db))


@router.delete("/api/service-items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "delete"))):
    """删除服务项（M21，软删）：已有工单引用时拒绝（历史可溯），建议改为下架。"""
    item = db.get(ServiceItem, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    ensure_not_example(item)
    from app.models import Ticket

    used = db.query(Ticket).filter(Ticket.service_item_id == item.id, Ticket.is_deleted.is_(False)).count()
    if used > 0:
        raise AppError("ITEM_IN_USE", f"该服务项已被 {used} 张工单引用，不可删除；如不再提供请改为「下架」")
    item.is_deleted = True
    audit(db, "service_item", item.id, "delete", actor, {"code": item.item_code, "name": item.name})
    db.commit()
    return ok({"id": item.id})


# ---- SLA 策略（admin）与看板 ----

@router.get("/api/admin/sla-policies")
def list_sla_policies(db: Session = Depends(get_db), _=Depends(require_perm("sla", "view"))):
    rows = db.query(SlaPolicy).filter(SlaPolicy.is_deleted.is_(False)).order_by(SlaPolicy.priority).all()
    return ok(
        [
            {"id": p.id, "priority": p.priority, "response_minutes": p.response_minutes,
             "resolution_hours": p.resolution_hours, "active": p.active}
            for p in rows
        ]
    )


@router.put("/api/admin/sla-policies")
def upsert_sla_policies(body: list[SlaPolicyIn], db: Session = Depends(get_db), actor=Depends(require_perm("sla", "edit"))):
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


class PriorityDefinitionIn(BaseModel):
    flow_type: str
    priority: str
    definition: str = Field(min_length=1, max_length=2000)
    examples: str | None = Field(default=None, max_length=2000)


@router.get("/api/sla/priority-definitions")
def list_priority_definitions(db: Session = Depends(get_db), _=Depends(require_perm("sla", "view"))):
    """P1-P4 优先级定义（M29）：四流程 × 四级，seed ITIL/ServiceNow 初稿，管理员可编辑。"""
    from app.models import SlaPriorityDefinition

    rows = db.query(SlaPriorityDefinition).filter(SlaPriorityDefinition.is_deleted.is_(False)).all()
    return ok([
        {"flow_type": r.flow_type, "priority": r.priority, "definition": r.definition, "examples": r.examples}
        for r in rows
    ])


@router.put("/api/sla/priority-definitions")
def upsert_priority_definitions(body: list[PriorityDefinitionIn], db: Session = Depends(get_db), actor=Depends(require_perm("sla", "edit"))):
    from app.models import SlaPriorityDefinition

    valid_flows = {"service_request", "incident", "change", "problem"}
    valid_priorities = {"P1", "P2", "P3", "P4"}
    for entry in body:
        if entry.flow_type not in valid_flows or entry.priority not in valid_priorities:
            raise AppError("INVALID_DEFINITION", f"非法的流程类型或优先级：{entry.flow_type}/{entry.priority}")
        row = (
            db.query(SlaPriorityDefinition)
            .filter(SlaPriorityDefinition.flow_type == entry.flow_type, SlaPriorityDefinition.priority == entry.priority)
            .first()
        )
        if row:
            row.definition = entry.definition
            row.examples = entry.examples
            row.is_deleted = False
        else:
            db.add(SlaPriorityDefinition(**entry.model_dump()))
    audit(db, "sla_priority_definition", "batch", "upsert", actor, {"count": len(body)})
    db.commit()
    return ok({"count": len(body)})


@router.get("/api/sla/dashboard")
def sla_dashboard(db: Session = Depends(get_db), _=Depends(require_perm("sla", "view"))):
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
