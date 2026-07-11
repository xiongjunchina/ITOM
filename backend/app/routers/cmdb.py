"""CMDB 配置管理（PRD §5.4）：单表 CI + 关系 + 影响分析。"""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, Ci, CiRelationship, OrgMember, Ticket, Vendor
from app.schemas.common import ok, paginate
from app.services.audit import audit
from app.services.codes import gen_code

router = APIRouter(tags=["itsm"])

RELATION_TYPES = ("运行于", "依赖", "连接")


class CiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: str
    status: str = "运行中"
    owner: str
    environment: str | None = None
    business_owner: str | None = None
    vendor_id: str | None = None
    description: str | None = None
    launch_date: date | None = None
    attrs: dict = {}
    remarks: str | None = None


class CiUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    status: str | None = None
    owner: str | None = None
    environment: str | None = None
    business_owner: str | None = None
    vendor_id: str | None = None
    description: str | None = None
    launch_date: date | None = None
    attrs: dict | None = None
    remarks: str | None = None


class RelationIn(BaseModel):
    source_ci_id: str
    target_ci_id: str
    relation_type: str


def _row(c: Ci, db: Session) -> dict:
    owner = db.get(OrgMember, c.owner) if c.owner else None
    vendor = db.get(Vendor, c.vendor_id) if c.vendor_id else None
    return {
        "id": c.id, "ci_code": c.ci_code, "name": c.name, "category": c.category,
        "status": c.status, "owner": c.owner, "owner_name": owner.name if owner else None,
        "environment": c.environment, "business_owner": c.business_owner,
        "vendor_id": c.vendor_id, "vendor_name": vendor.name if vendor else None,
        "description": c.description, "launch_date": c.launch_date,
        "attrs": c.attrs or {}, "remarks": c.remarks,
    }


@router.get("/api/cis")
def list_cis(
    page: int = 1, page_size: int = 20, q: str = "", category: str = "", status: str = "", environment: str = "",
    db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user),
):
    query = db.query(Ci).filter(Ci.is_deleted.is_(False))
    if q:
        query = query.filter(or_(Ci.name.ilike(f"%{q}%"), Ci.ci_code.ilike(f"%{q}%")))
    if category:
        query = query.filter(Ci.category == category)
    if status:
        query = query.filter(Ci.status == status)
    if environment:
        query = query.filter(Ci.environment == environment)
    items, total = paginate(query.order_by(Ci.created_at.desc()), page, page_size)
    return ok([_row(c, db) for c in items], total=total, page=page)


@router.post("/api/cis")
def create_ci(body: CiCreate, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "create"))):
    ci = Ci(**body.model_dump(), ci_code=gen_code(db, Ci, "ci_code", "CI"))
    db.add(ci)
    db.flush()
    audit(db, "ci", ci.id, "create", actor, {"name": body.name, "category": body.category})
    db.commit()
    return ok(_row(ci, db))


@router.patch("/api/cis/{ci_id}")
def update_ci(ci_id: str, body: CiUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "edit"))):
    ci = db.get(Ci, ci_id)
    if not ci or ci.is_deleted:
        raise AppError("NOT_FOUND", "配置项不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(ci, k, v)
    audit(db, "ci", ci.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_row(ci, db))


@router.get("/api/cis/{ci_id}/impact")
def impact_analysis(ci_id: str, db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    """影响分析：上游（我依赖的）/下游（依赖我的）+ 关联工单历史。"""
    ci = db.get(Ci, ci_id)
    if not ci or ci.is_deleted:
        raise AppError("NOT_FOUND", "配置项不存在", 404)
    rels = (
        db.query(CiRelationship)
        .filter(
            or_(CiRelationship.source_ci_id == ci_id, CiRelationship.target_ci_id == ci_id),
            CiRelationship.is_deleted.is_(False),
        )
        .all()
    )
    ci_ids = {r.source_ci_id for r in rels} | {r.target_ci_id for r in rels}
    ci_map = {c.id: c for c in db.query(Ci).filter(Ci.id.in_(ci_ids or ["-"]))}

    def brief(cid: str) -> dict:
        c = ci_map.get(cid)
        return {"id": cid, "name": c.name if c else "?", "category": c.category if c else None, "status": c.status if c else None}

    upstream = [
        {"relation_type": r.relation_type, "ci": brief(r.target_ci_id), "relation_id": r.id}
        for r in rels if r.source_ci_id == ci_id
    ]
    downstream = [
        {"relation_type": r.relation_type, "ci": brief(r.source_ci_id), "relation_id": r.id}
        for r in rels if r.target_ci_id == ci_id
    ]
    tickets = (
        db.query(Ticket)
        .filter(Ticket.ci_id == ci_id, Ticket.is_deleted.is_(False))
        .order_by(Ticket.submitted_at.desc())
        .limit(20)
        .all()
    )
    return ok(
        {
            "ci": _row(ci, db),
            "upstream": upstream,
            "downstream": downstream,
            "tickets": [
                {"id": t.id, "ticket_code": t.ticket_code, "title": t.title, "status": t.status,
                 "priority": t.priority, "submitted_at": t.submitted_at}
                for t in tickets
            ],
        }
    )


@router.post("/api/ci-relationships")
def create_relation(body: RelationIn, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "edit"))):
    if body.relation_type not in RELATION_TYPES:
        raise AppError("INVALID_RELATION", f"关系类型须为：{'/'.join(RELATION_TYPES)}")
    if body.source_ci_id == body.target_ci_id:
        raise AppError("INVALID_RELATION", "不能与自身建立关系")
    for cid in (body.source_ci_id, body.target_ci_id):
        if not db.get(Ci, cid):
            raise AppError("NOT_FOUND", "配置项不存在", 404)
    dup = (
        db.query(CiRelationship)
        .filter_by(source_ci_id=body.source_ci_id, target_ci_id=body.target_ci_id, relation_type=body.relation_type)
        .filter(CiRelationship.is_deleted.is_(False))
        .first()
    )
    if dup:
        raise AppError("DUPLICATE", "关系已存在")
    rel = CiRelationship(**body.model_dump())
    db.add(rel)
    db.flush()
    audit(db, "ci_relationship", rel.id, "create", actor, body.model_dump())
    db.commit()
    return ok({"id": rel.id})


@router.delete("/api/ci-relationships/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "edit"))):
    rel = db.get(CiRelationship, relation_id)
    if not rel or rel.is_deleted:
        raise AppError("NOT_FOUND", "关系不存在", 404)
    rel.is_deleted = True
    audit(db, "ci_relationship", rel.id, "delete", actor)
    db.commit()
    return ok({"id": rel.id})
