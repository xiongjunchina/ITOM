"""服务目录 + 服务项 + SLA 策略/看板（PRD §5.3/5.5）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    AuthUser,
    Department,
    OrgMember,
    ProcessDefinition,
    ServiceCatalog,
    ServiceDispatchRule,
    ServiceItem,
    ServiceItemFormVersion,
    SlaPolicy,
    Ticket,
)
from app.schemas.common import ok
from app.schemas.itsm import (
    CatalogCreate,
    CatalogUpdate,
    ServiceItemCreate,
    ServiceDispatchRuleIn,
    ServiceItemFormVersionIn,
    ServiceItemUpdate,
    SlaPolicyIn,
)
from app.services.audit import audit
from app.services.codes import gen_code
from app.services import dispatch, service_forms
from app.services.service_audience import service_item_visible_to_user
from app.services.team_scope import require_it_member_if_configured

router = APIRouter(tags=["itsm"])


def _global_implementation_manager(db: Session, actor: AuthUser) -> AuthUser:
    """全局实施兜底会影响全目录，限定系统管理员/CIO。"""
    from app.core.rbac import ADMIN, CIO
    from app.services.rbac import actor_keys

    if not ({ADMIN, CIO} & actor_keys(db, actor)):
        raise AppError("FORBIDDEN", "仅系统管理员或 CIO 可以维护全局实施兜底规则", 403)
    return actor


def _dispatch_rule_row(rule: ServiceDispatchRule, *, inherited: bool = False) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "scope_type": rule.scope_type,
        "scope_id": rule.scope_id,
        "dispatch_stage": rule.dispatch_stage,
        "target_type": rule.target_type,
        "target_id": rule.target_id,
        "strategy": rule.strategy,
        "priority": rule.priority,
        "active": rule.active,
        "fallback": rule.fallback,
        "inherited": inherited,
    }


def _exact_dispatch_rule(
    db: Session,
    *,
    scope_type: str,
    scope_id: str | None,
    dispatch_stage: str,
) -> ServiceDispatchRule | None:
    query = db.query(ServiceDispatchRule).filter(
        ServiceDispatchRule.scope_type == scope_type,
        ServiceDispatchRule.dispatch_stage == dispatch_stage,
        ServiceDispatchRule.is_deleted.is_(False),
    )
    query = query.filter(
        ServiceDispatchRule.scope_id == scope_id
        if scope_id is not None
        else ServiceDispatchRule.scope_id.is_(None)
    )
    return query.order_by(ServiceDispatchRule.priority, ServiceDispatchRule.created_at).first()


def _replace_dispatch_rule(
    db: Session,
    body: ServiceDispatchRuleIn,
    *,
    scope_type: str,
    scope_id: str | None,
    dispatch_stage: str,
    actor: AuthUser,
    audit_context: dict,
) -> ServiceDispatchRule:
    dispatch.validate_rule_target(db, body.target_type, body.target_id, body.strategy)
    query = db.query(ServiceDispatchRule).filter(
        ServiceDispatchRule.scope_type == scope_type,
        ServiceDispatchRule.dispatch_stage == dispatch_stage,
        ServiceDispatchRule.is_deleted.is_(False),
    )
    query = query.filter(
        ServiceDispatchRule.scope_id == scope_id
        if scope_id is not None
        else ServiceDispatchRule.scope_id.is_(None)
    )
    for current in query:
        current.is_deleted = True
    rule = ServiceDispatchRule(
        **body.model_dump(),
        scope_type=scope_type,
        scope_id=scope_id,
        dispatch_stage=dispatch_stage,
    )
    db.add(rule)
    db.flush()
    audit(
        db,
        "service_dispatch_rule",
        rule.id,
        "upsert",
        actor,
        {**audit_context, "name": rule.name, "dispatch_stage": dispatch_stage},
    )
    return rule


def _delete_dispatch_rule(
    db: Session,
    *,
    scope_type: str,
    scope_id: str | None,
    dispatch_stage: str,
    actor: AuthUser,
    audit_context: dict,
) -> None:
    rule = _exact_dispatch_rule(
        db,
        scope_type=scope_type,
        scope_id=scope_id,
        dispatch_stage=dispatch_stage,
    )
    if not rule:
        raise AppError("NOT_FOUND", "该范围未配置实施派单规则", 404)
    rule.is_deleted = True
    audit(
        db,
        "service_dispatch_rule",
        rule.id,
        "delete",
        actor,
        {**audit_context, "name": rule.name, "dispatch_stage": dispatch_stage},
    )


def _resolve_target_audience(db: Session, mode: str, refs: list[dict] | None) -> tuple[str, list[dict]]:
    """校验服务对象引用并生成兼容旧字段的可读摘要。"""
    if mode == "all":
        return "全体员工", []
    if mode != "custom":
        raise AppError("INVALID_AUDIENCE", "服务对象范围必须为全体员工或自定义范围")

    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs or []:
        kind = ref.get("type")
        ref_id = str(ref.get("id") or "")
        key = (kind, ref_id)
        if kind not in {"department", "member"} or not ref_id or key in seen:
            continue
        seen.add(key)
        normalized.append({"type": kind, "id": ref_id})
    if not normalized:
        raise AppError("AUDIENCE_REQUIRED", "请选择至少一个部门或员工")

    department_ids = [r["id"] for r in normalized if r["type"] == "department"]
    member_ids = [r["id"] for r in normalized if r["type"] == "member"]
    departments = {
        d.id: d
        for d in db.query(Department).filter(
            Department.id.in_(department_ids or ["-"]),
            Department.is_deleted.is_(False),
            Department.active.is_(True),
        )
    }
    members = {
        m.id: m
        for m in db.query(OrgMember).filter(
            OrgMember.id.in_(member_ids or ["-"]),
            OrgMember.is_deleted.is_(False),
            OrgMember.status == "在岗",
        )
    }
    missing = [
        f"部门:{ref['id']}" if ref["type"] == "department" else f"员工:{ref['id']}"
        for ref in normalized
        if (ref["id"] not in departments if ref["type"] == "department" else ref["id"] not in members)
    ]
    if missing:
        raise AppError("AUDIENCE_NOT_FOUND", f"服务对象已不存在或不可用：{'、'.join(missing)}")

    parts = []
    if department_ids:
        parts.append("部门：" + "、".join(departments[ref_id].name for ref_id in department_ids))
    if member_ids:
        parts.append("员工：" + "、".join(members[ref_id].name for ref_id in member_ids))
    return "；".join(parts), normalized


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
    item_status_counts = {
        (catalog_id, status): count
        for catalog_id, status, count in db.query(
            ServiceItem.catalog_id,
            ServiceItem.status,
            func.count(ServiceItem.id),
        )
        .filter(ServiceItem.is_deleted.is_(False))
        .group_by(ServiceItem.catalog_id, ServiceItem.status)
        .all()
    }
    return ok(
        [
            {
                "id": c.id, "code": c.code, "name": c.name, "tier": c.tier, "is_example": c.is_example,
                "description": c.description, "sort": c.sort, "status": c.status,
                "item_count": item_counts.get(c.id, 0),
                "published_item_count": item_status_counts.get((c.id, "上架"), 0),
                "unpublished_item_count": item_status_counts.get((c.id, "下架"), 0),
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
def delete_catalog(
    catalog_id: str,
    cascade: bool = Query(False, description="同时软删除该目录下的服务项"),
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "delete")),
):
    """删除服务目录（软删），可在管理员明确确认后级联软删下属服务项。

    级联只删除目录和服务项本身，不删除历史工单、项目或配置项；这些历史记录仍保留
    对原服务项的引用，避免为了清理目录而破坏审计链路。
    """
    catalog = db.get(ServiceCatalog, catalog_id)
    if not catalog or catalog.is_deleted:
        raise AppError("NOT_FOUND", "目录不存在", 404)
    ensure_example_delete_allowed(catalog, db, actor)
    live_items = db.query(ServiceItem).filter(ServiceItem.catalog_id == catalog.id, ServiceItem.is_deleted.is_(False)).all()
    if live_items and not cascade:
        raise AppError("CATALOG_IN_USE", f"该目录下还有 {len(live_items)} 个服务项，请先删除或迁移服务项，或确认级联删除")
    for item in live_items:
        item.is_deleted = True
        audit(
            db,
            "service_item",
            item.id,
            "delete",
            actor,
            {
                "code": item.item_code,
                "name": item.name,
                "cascade_from_catalog": catalog.id,
            },
        )
    catalog.is_deleted = True
    audit(
        db,
        "service_catalog",
        catalog.id,
        "delete",
        actor,
        {"code": catalog.code, "name": catalog.name, "items_deleted": len(live_items), "cascade": cascade},
    )
    db.commit()
    return ok({"id": catalog.id, "items_deleted": len(live_items), "cascade": cascade})


# ---- 服务项 ----

def _item_row(i: ServiceItem, db: Session) -> dict:
    owner = db.get(OrgMember, i.owner) if i.owner else None
    process = db.get(ProcessDefinition, i.process_definition_id) if i.process_definition_id else None
    return {
        "id": i.id, "item_code": i.item_code, "name": i.name, "is_example": i.is_example,
        "catalog_id": i.catalog_id, "catalog_name": i.catalog.name if i.catalog else None,
        "service_type": i.service_type, "owner": i.owner, "owner_name": owner.name if owner else None,
        "description": i.description,
        "sla_response_hours": i.sla_response_hours, "sla_resolution_hours": i.sla_resolution_hours,
        "target_audience": i.target_audience, "target_audience_mode": i.target_audience_mode or "all",
        "target_audience_refs": i.target_audience_refs or [], "status": i.status,
        "search_keywords": i.search_keywords or [], "search_synonyms": i.search_synonyms or [],
        "typical_scenarios": i.typical_scenarios or [], "exclusion_scenarios": i.exclusion_scenarios or [],
        "active_form_version_id": i.active_form_version_id,
        "process_definition_id": i.process_definition_id,
        "process_definition_name": process.name if process else None,
        "default_priority": i.default_priority,
    }


def _validate_service_process(db: Session, definition_id: str | None) -> None:
    if not definition_id:
        return
    definition = db.get(ProcessDefinition, definition_id)
    if not definition or definition.is_deleted or not definition.active or definition.entity_type != "ticket":
        raise AppError("INVALID_PROCESS_DEFINITION", "服务项必须绑定活动的工单流程定义")
    trigger_type = (definition.trigger_condition or {}).get("ticket_type")
    if trigger_type not in (None, "service_request"):
        raise AppError("INVALID_PROCESS_DEFINITION", "服务项不能绑定事件或变更专用流程")


@router.get("/api/service-items")
def list_items(
    catalog_id: str = "",
    q: str = "",
    status: str = "",
    sort_by: str = "",
    sort_dir: str = "ascend",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """服务项列表。

    搜索、状态筛选和排序都在查询层完成，避免前端只对当前分页数据做筛选，
    也保证服务目录页与工单/项目等引用服务项的页面使用同一套数据口径。
    """
    query = db.query(ServiceItem).filter(ServiceItem.is_deleted.is_(False))
    if catalog_id:
        query = query.filter(ServiceItem.catalog_id == catalog_id)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.outerjoin(OrgMember, ServiceItem.owner == OrgMember.id).filter(
            or_(
                ServiceItem.item_code.ilike(keyword),
                ServiceItem.name.ilike(keyword),
                ServiceItem.service_type.ilike(keyword),
                ServiceItem.target_audience.ilike(keyword),
                OrgMember.name.ilike(keyword),
            )
        )
    if status in {"上架", "下架"}:
        query = query.filter(ServiceItem.status == status)
    sort_columns = {
        "item_code": ServiceItem.item_code,
        "name": ServiceItem.name,
        "service_type": ServiceItem.service_type,
        "status": ServiceItem.status,
        "created_at": ServiceItem.created_at,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is not None:
        ordering = desc(sort_column) if sort_dir == "descend" else asc(sort_column)
        rows = query.order_by(ServiceItem.is_example.desc(), ordering, ServiceItem.created_at).all()
    else:
        rows = query.order_by(ServiceItem.is_example.desc(), ServiceItem.created_at).all()
    rows = [item for item in rows if service_item_visible_to_user(db, item, user)]
    return ok([_item_row(i, db) for i in rows], total=len(rows))


@router.post("/api/service-items")
def create_item(body: ServiceItemCreate, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "create"))):
    if not db.get(ServiceCatalog, body.catalog_id):
        raise AppError("NOT_FOUND", "目录不存在", 404)
    require_it_member_if_configured(db, body.owner, "服务项负责人")
    data = body.model_dump(exclude_unset=True)
    if not data.get("process_definition_id"):
        default_process = db.query(ProcessDefinition).filter(
            ProcessDefinition.code == "sr_flow",
            ProcessDefinition.entity_type == "ticket",
            ProcessDefinition.active.is_(True),
            ProcessDefinition.is_deleted.is_(False),
        ).first()
        if default_process:
            data["process_definition_id"] = default_process.id
    _validate_service_process(db, data.get("process_definition_id"))
    mode = data.get("target_audience_mode") or "all"
    summary, refs = _resolve_target_audience(db, mode, data.get("target_audience_refs"))
    data["target_audience"] = summary
    data["target_audience_mode"] = mode
    data["target_audience_refs"] = refs
    item = ServiceItem(**data, item_code=gen_code(db, ServiceItem, "item_code", "SI"))
    db.add(item)
    db.flush()
    service_forms.ensure_default_form(db, item, actor.id)
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
    if "target_audience_mode" in data or "target_audience_refs" in data:
        mode = data.get("target_audience_mode") or item.target_audience_mode or "all"
        refs = data.get("target_audience_refs") if "target_audience_refs" in data else (item.target_audience_refs or [])
        summary, normalized_refs = _resolve_target_audience(db, mode, refs)
        data.update({"target_audience": summary, "target_audience_mode": mode, "target_audience_refs": normalized_refs})
    if "owner" in data:
        require_it_member_if_configured(db, data["owner"], "服务项负责人")
    if "process_definition_id" in data:
        _validate_service_process(db, data["process_definition_id"])
    for k, v in data.items():
        setattr(item, k, v)
    audit(db, "service_item", item.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_item_row(item, db))


def _get_service_item(db: Session, item_id: str) -> ServiceItem:
    item = db.get(ServiceItem, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    return item


@router.get("/api/service-items/{item_id}/form")
def get_current_item_form(
    item_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = _get_service_item(db, item_id)
    if item.status != "上架" or not service_item_visible_to_user(db, item, user):
        raise AppError("NOT_FOUND", "服务项不存在或当前账号不可申请", 404)
    return ok(service_forms.form_row(service_forms.active_form(db, item)))


@router.get("/api/service-items/{item_id}/form-versions")
def list_item_form_versions(
    item_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("catalog", "view")),
):
    item = _get_service_item(db, item_id)
    rows = (
        db.query(ServiceItemFormVersion)
        .filter(
            ServiceItemFormVersion.service_item_id == item.id,
            ServiceItemFormVersion.is_deleted.is_(False),
        )
        .order_by(ServiceItemFormVersion.version.desc())
        .all()
    )
    return ok([service_forms.form_row(row) for row in rows], total=len(rows))


@router.post("/api/service-items/{item_id}/form-versions")
def create_item_form_version(
    item_id: str,
    body: ServiceItemFormVersionIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    item = _get_service_item(db, item_id)
    ensure_not_example(item)
    row = service_forms.create_draft(db, item, body.form_schema)
    audit(db, "service_item_form", row.id, "create_draft", actor, {"item_code": item.item_code, "version": row.version})
    db.commit()
    return ok(service_forms.form_row(row))


@router.post("/api/service-items/{item_id}/form-versions/{version}/publish")
def publish_item_form_version(
    item_id: str,
    version: int,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    item = _get_service_item(db, item_id)
    ensure_not_example(item)
    row = service_forms.publish_version(db, item, version, actor.id)
    audit(db, "service_item_form", row.id, "publish", actor, {"item_code": item.item_code, "version": row.version})
    db.commit()
    return ok(service_forms.form_row(row))


@router.get("/api/service-items/{item_id}/dispatch-rule")
def get_item_dispatch_rule(
    item_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("catalog", "view")),
):
    item = _get_service_item(db, item_id)
    rule = dispatch.resolve_rule(db, item, dispatch_stage="acceptance")
    if not rule:
        return ok(None)
    return ok(_dispatch_rule_row(rule, inherited=rule.scope_type != "service_item"))


@router.put("/api/service-items/{item_id}/dispatch-rule")
def put_item_dispatch_rule(
    item_id: str,
    body: ServiceDispatchRuleIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    item = _get_service_item(db, item_id)
    ensure_not_example(item)
    rule = _replace_dispatch_rule(
        db,
        body,
        scope_type="service_item",
        scope_id=item.id,
        dispatch_stage="acceptance",
        actor=actor,
        audit_context={"item_code": item.item_code},
    )
    db.commit()
    return ok(_dispatch_rule_row(rule))


@router.get("/api/service-items/{item_id}/implementation-dispatch-rule")
def get_item_implementation_dispatch_rule(
    item_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("catalog", "view")),
):
    """返回实施交付规则；服务项未配置时明确标识目录/全局继承来源。"""
    item = _get_service_item(db, item_id)
    rule = dispatch.resolve_rule(db, item, dispatch_stage="implementation")
    return ok(_dispatch_rule_row(rule, inherited=rule.scope_type != "service_item") if rule else None)


@router.put("/api/service-items/{item_id}/implementation-dispatch-rule")
def put_item_implementation_dispatch_rule(
    item_id: str,
    body: ServiceDispatchRuleIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    item = _get_service_item(db, item_id)
    ensure_not_example(item)
    rule = _replace_dispatch_rule(
        db,
        body,
        scope_type="service_item",
        scope_id=item.id,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"item_code": item.item_code},
    )
    db.commit()
    return ok(_dispatch_rule_row(rule))


@router.delete("/api/service-items/{item_id}/implementation-dispatch-rule")
def delete_item_implementation_dispatch_rule(
    item_id: str,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    item = _get_service_item(db, item_id)
    ensure_not_example(item)
    _delete_dispatch_rule(
        db,
        scope_type="service_item",
        scope_id=item.id,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"item_code": item.item_code},
    )
    db.commit()
    return ok({"scope_type": "service_item", "scope_id": item.id, "dispatch_stage": "implementation"})


def _get_catalog(db: Session, catalog_id: str) -> ServiceCatalog:
    catalog = db.get(ServiceCatalog, catalog_id)
    if not catalog or catalog.is_deleted:
        raise AppError("NOT_FOUND", "目录不存在", 404)
    return catalog


@router.get("/api/catalogs/{catalog_id}/implementation-dispatch-rule")
def get_catalog_implementation_dispatch_rule(
    catalog_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("catalog", "view")),
):
    catalog = _get_catalog(db, catalog_id)
    rule = _exact_dispatch_rule(
        db,
        scope_type="catalog",
        scope_id=catalog.id,
        dispatch_stage="implementation",
    )
    return ok(_dispatch_rule_row(rule) if rule else None)


@router.put("/api/catalogs/{catalog_id}/implementation-dispatch-rule")
def put_catalog_implementation_dispatch_rule(
    catalog_id: str,
    body: ServiceDispatchRuleIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    catalog = _get_catalog(db, catalog_id)
    ensure_not_example(catalog)
    rule = _replace_dispatch_rule(
        db,
        body,
        scope_type="catalog",
        scope_id=catalog.id,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"catalog_code": catalog.code},
    )
    db.commit()
    return ok(_dispatch_rule_row(rule))


@router.delete("/api/catalogs/{catalog_id}/implementation-dispatch-rule")
def delete_catalog_implementation_dispatch_rule(
    catalog_id: str,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("catalog", "edit")),
):
    catalog = _get_catalog(db, catalog_id)
    ensure_not_example(catalog)
    _delete_dispatch_rule(
        db,
        scope_type="catalog",
        scope_id=catalog.id,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"catalog_code": catalog.code},
    )
    db.commit()
    return ok({"scope_type": "catalog", "scope_id": catalog.id, "dispatch_stage": "implementation"})


@router.get("/api/service-dispatch/implementation-fallback")
def get_global_implementation_dispatch_rule(
    db: Session = Depends(get_db),
    actor=Depends(get_current_user),
):
    _global_implementation_manager(db, actor)
    rule = _exact_dispatch_rule(
        db,
        scope_type="global",
        scope_id=None,
        dispatch_stage="implementation",
    )
    return ok(_dispatch_rule_row(rule) if rule else None)


@router.put("/api/service-dispatch/implementation-fallback")
def put_global_implementation_dispatch_rule(
    body: ServiceDispatchRuleIn,
    db: Session = Depends(get_db),
    actor=Depends(get_current_user),
):
    _global_implementation_manager(db, actor)
    rule = _replace_dispatch_rule(
        db,
        body,
        scope_type="global",
        scope_id=None,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"scope": "global"},
    )
    db.commit()
    return ok(_dispatch_rule_row(rule))


@router.delete("/api/service-dispatch/implementation-fallback")
def delete_global_implementation_dispatch_rule(
    db: Session = Depends(get_db),
    actor=Depends(get_current_user),
):
    _global_implementation_manager(db, actor)
    _delete_dispatch_rule(
        db,
        scope_type="global",
        scope_id=None,
        dispatch_stage="implementation",
        actor=actor,
        audit_context={"scope": "global"},
    )
    db.commit()
    return ok({"scope_type": "global", "scope_id": None, "dispatch_stage": "implementation"})


@router.delete("/api/service-items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "delete"))):
    """删除服务项（M21，软删）：已有工单引用时拒绝（历史可溯），建议改为下架。"""
    item = db.get(ServiceItem, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "服务项不存在", 404)
    ensure_example_delete_allowed(item, db, actor)
    from app.models import ProcessInstance, ProcessTask, Ticket

    live_tickets = db.query(Ticket).filter(Ticket.service_item_id == item.id, Ticket.is_deleted.is_(False)).all()
    if live_tickets:
        # 示例服务项可以由管理员连同其示例工单清理；真实工单引用仍禁止删除。
        if item.is_example and all(ticket.is_example for ticket in live_tickets):
            ticket_ids = {ticket.id for ticket in live_tickets}
            for ticket in live_tickets:
                ticket.is_deleted = True
            instances = db.query(ProcessInstance).filter(
                ProcessInstance.entity_type == "ticket",
                ProcessInstance.entity_id.in_(ticket_ids),
                ProcessInstance.is_deleted.is_(False),
            ).all()
            for instance in instances:
                instance.is_deleted = True
                for task in db.query(ProcessTask).filter(ProcessTask.instance_id == instance.id, ProcessTask.is_deleted.is_(False)):
                    task.is_deleted = True
        else:
            raise AppError("ITEM_IN_USE", f"该服务项已被 {len(live_tickets)} 张工单引用，不可删除；如不再提供请改为「下架」")
    item.is_deleted = True
    audit(db, "service_item", item.id, "delete", actor, {"code": item.item_code, "name": item.name, "tickets_deleted": len(live_tickets) if item.is_example else 0})
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
