"""CMDB 配置管理（PRD §5.4）：单表 CI + 关系 + 影响分析。"""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, Ci, CiRelationship, MasterData, OrgMember, Ticket, Vendor
from app.schemas.common import BatchDeleteIn, ok, paginate
from app.services.audit import audit
from app.services.batch_delete import execute_batch_delete
from app.services.codes import gen_code
from app.services.team_scope import require_it_member_if_configured

router = APIRouter(tags=["itsm"])

RELATION_TYPES = ("运行于", "依赖", "连接")
APPLICATION_CATEGORIES = {"应用", "app", "application"}


class CiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: str
    status: str = "运行中"
    owner: str
    product_manager_id: str | None = None
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
    product_manager_id: str | None = None
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
        "id": c.id, "ci_code": c.ci_code, "is_example": c.is_example, "name": c.name, "category": c.category,
        "status": c.status, "owner": c.owner, "owner_name": owner.name if owner else None,
        "product_manager_id": c.product_manager_id,
        "product_manager_name": db.get(OrgMember, c.product_manager_id).name if c.product_manager_id and db.get(OrgMember, c.product_manager_id) else None,
        "environment": c.environment, "business_owner": c.business_owner,
        "vendor_id": c.vendor_id, "vendor_name": vendor.name if vendor else None,
        "description": c.description, "launch_date": c.launch_date,
        "attrs": c.attrs or {}, "remarks": c.remarks,
    }


def _validate_application_product_manager(category: str, product_manager_id: str | None):
    """应用 CI 必须明确产品经理，作为 Bug 确认和验证关闭责任人。"""
    if category in APPLICATION_CATEGORIES and not product_manager_id:
        raise AppError("PRODUCT_MANAGER_REQUIRED", "应用配置项必须配置产品经理，供 Bug 确认与验证关闭使用", 422)


def _equivalent_ci_categories(db: Session, category: str) -> set[str]:
    """Return every persisted CI category spelling represented by one CMDB tab.

    Master-data tabs use a stable code (for example ``app``), while imported
    legacy CIs can retain the displayed Chinese name (``应用``).  Filtering by
    only one spelling makes the tab disagree with the unfiltered list.  Match
    both sides of the configured code/name pair and keep the documented
    ``application`` legacy spelling compatible as well.
    """
    values = {category}
    configured_categories = (
        db.query(MasterData)
        .filter(
            MasterData.category == "ci_category",
            MasterData.is_deleted.is_(False),
            or_(MasterData.code == category, MasterData.name == category),
        )
        .all()
    )
    for configured in configured_categories:
        values.update((configured.code, configured.name))
    if values & APPLICATION_CATEGORIES:
        values.update(APPLICATION_CATEGORIES)
    return values


@router.get("/api/cis")
def list_cis(
    page: int = 1, page_size: int = 20, q: str = "", category: str = "", status: str = "", environment: str = "",
    db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("cmdb", "view")),
):
    query = db.query(Ci).filter(Ci.is_deleted.is_(False))
    if q:
        query = query.filter(or_(Ci.name.ilike(f"%{q}%"), Ci.ci_code.ilike(f"%{q}%")))
    if category:
        query = query.filter(Ci.category.in_(_equivalent_ci_categories(db, category)))
    if status:
        query = query.filter(Ci.status == status)
    if environment:
        query = query.filter(Ci.environment == environment)
    items, total = paginate(query.order_by(Ci.is_example.desc(), Ci.created_at.desc()), page, page_size)
    return ok([_row(c, db) for c in items], total=total, page=page)


@router.post("/api/cis")
def create_ci(body: CiCreate, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "create"))):
    _validate_application_product_manager(body.category, body.product_manager_id)
    require_it_member_if_configured(db, body.owner, "配置项负责人")
    require_it_member_if_configured(db, body.business_owner, "配置项业务负责人")
    require_it_member_if_configured(db, body.product_manager_id, "配置项产品经理")
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
    ensure_not_example(ci)
    data = body.model_dump(exclude_unset=True)
    final_category = data.get("category", ci.category)
    final_product_manager_id = data.get("product_manager_id", ci.product_manager_id)
    _validate_application_product_manager(final_category, final_product_manager_id)
    if "owner" in data:
        require_it_member_if_configured(db, data["owner"], "配置项负责人")
    if "product_manager_id" in data:
        require_it_member_if_configured(db, data["product_manager_id"], "配置项产品经理")
    if "business_owner" in data:
        require_it_member_if_configured(db, data["business_owner"], "配置项业务负责人")
    for k, v in data.items():
        setattr(ci, k, v)
    audit(db, "ci", ci.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_row(ci, db))


@router.get("/api/cis/{ci_id}/impact")
def impact_analysis(ci_id: str, db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("cmdb", "view"))):
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
        ci_obj = db.get(Ci, cid)
        if not ci_obj:
            raise AppError("NOT_FOUND", "配置项不存在", 404)
        ensure_not_example(ci_obj)
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


def _delete_ci(db: Session, ci: Ci, actor: AuthUser) -> dict:
    """软删配置项及关联关系，并解除工单引用；由调用方提交事务。"""
    ensure_example_delete_allowed(ci, db, actor)
    ci.is_deleted = True
    relations = 0
    for rel in db.query(CiRelationship).filter(
        or_(CiRelationship.source_ci_id == ci.id, CiRelationship.target_ci_id == ci.id),
        CiRelationship.is_deleted.is_(False),
    ):
        rel.is_deleted = True
        relations += 1
    unlinked = 0
    for t in db.query(Ticket).filter(Ticket.ci_id == ci.id, Ticket.is_deleted.is_(False)):
        t.ci_id = None
        unlinked += 1
    audit(db, "ci", ci.id, "delete", actor, {"code": ci.ci_code, "relations": relations, "tickets_unlinked": unlinked})
    return {"id": ci.id, "relations": relations, "tickets_unlinked": unlinked}


def _delete_relation(db: Session, rel: CiRelationship, actor: AuthUser) -> dict:
    rel.is_deleted = True
    audit(db, "ci_relationship", rel.id, "delete", actor)
    return {"id": rel.id}


@router.delete("/api/cis/batch-delete")
def batch_delete_cis(body: BatchDeleteIn, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "delete"))):
    def delete_one(ci_id: str) -> None:
        ci = db.get(Ci, ci_id)
        if not ci or ci.is_deleted:
            raise AppError("NOT_FOUND", "配置项不存在", 404)
        _delete_ci(db, ci, actor)

    return ok(execute_batch_delete(db, body.ids, delete_one))


@router.delete("/api/ci-relationships/batch-delete")
def batch_delete_relations(body: BatchDeleteIn, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "edit"))):
    def delete_one(relation_id: str) -> None:
        rel = db.get(CiRelationship, relation_id)
        if not rel or rel.is_deleted:
            raise AppError("NOT_FOUND", "关系不存在", 404)
        _delete_relation(db, rel, actor)

    return ok(execute_batch_delete(db, body.ids, delete_one))


@router.delete("/api/cis/{ci_id}")
def delete_ci(ci_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "delete"))):
    """删除配置项（M21，软删）：级联软删其上下游关系；关联工单解除 CI 挂接。"""
    ci = db.get(Ci, ci_id)
    if not ci or ci.is_deleted:
        raise AppError("NOT_FOUND", "配置项不存在", 404)
    result = _delete_ci(db, ci, actor)
    db.commit()
    return ok(result)


@router.delete("/api/ci-relationships/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "edit"))):
    rel = db.get(CiRelationship, relation_id)
    if not rel or rel.is_deleted:
        raise AppError("NOT_FOUND", "关系不存在", 404)
    result = _delete_relation(db, rel, actor)
    db.commit()
    return ok(result)
