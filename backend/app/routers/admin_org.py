"""组织结构管理（admin）：部门 / 业务域 / 开通规则（docs/06）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm, require_roles
from app.models import BusinessDomain, BusinessDomainDepartment, BusinessDomainMember, Department, OrgMember, ProvisionRule, Requirement
from app.schemas.common import ok
from app.services.audit import audit
from app.services.feishu import is_enabled as feishu_enabled
from app.services.rbac import valid_role_codes

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEPT_TYPES = ("it", "business", "audit")


class DeptIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None
    dept_type: str = "business"
    sort: int = 0


class DeptUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    dept_type: str | None = None
    sort: int | None = None
    active: bool | None = None


class DomainIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    owner_id: str | None = None
    backup_owner_id: str | None = None
    department_ids: list[str] = Field(default_factory=list)
    include_children: bool = True
    sort: int = 0


class DomainUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    owner_id: str | None = None
    backup_owner_id: str | None = None
    department_ids: list[str] | None = None
    include_children: bool | None = None
    sort: int | None = None
    active: bool | None = None


class RuleIn(BaseModel):
    match_type: str
    match_value: str
    default_roles: list[str]
    sort: int = 0
    active: bool = True


# ---------- 部门 ----------

@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(Department).filter(Department.is_deleted.is_(False)).order_by(Department.sort, Department.created_at).all()
    member_counts: dict[str, int] = {}
    for (dept_id,) in db.query(OrgMember.department_id).filter(OrgMember.is_deleted.is_(False), OrgMember.department_id.isnot(None)):
        member_counts[dept_id] = member_counts.get(dept_id, 0) + 1
    return ok(
        [
            {
                "id": d.id, "code": d.code, "name": d.name, "parent_id": d.parent_id,
                "dept_type": d.dept_type, "sort": d.sort, "active": d.active,
                "external_source": d.external_source,
                "member_count": member_counts.get(d.id, 0),
            }
            for d in rows
        ],
        total=len(rows),
    )


@router.post("/departments")
def create_department(body: DeptIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_departments", "create"))):
    if body.dept_type not in DEPT_TYPES:
        raise AppError("INVALID_TYPE", "部门类型必须为 it/business/audit")
    if db.query(Department).filter(Department.code == body.code, Department.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "部门编码已存在")
    dept = Department(**body.model_dump())
    db.add(dept)
    db.flush()
    audit(db, "department", dept.id, "create", actor, {"code": body.code, "name": body.name})
    db.commit()
    return ok({"id": dept.id})


@router.patch("/departments/{dept_id}")
def update_department(dept_id: str, body: DeptUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_departments", "edit"))):
    dept = db.get(Department, dept_id)
    if not dept or dept.is_deleted:
        raise AppError("NOT_FOUND", "部门不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if dept.external_source:
        from app.services.org_sync import DEPT_LOCAL_FIELDS

        locked = set(data) - DEPT_LOCAL_FIELDS
        if locked:
            raise AppError(
                "SYNCED_READONLY",
                f"该部门由 {dept.external_source} 同步，结构以外部源为准；本地仅可编辑：部门类型",
            )
    if data.get("dept_type") and data["dept_type"] not in DEPT_TYPES:
        raise AppError("INVALID_TYPE", "部门类型必须为 it/business/audit")
    if data.get("parent_id") == dept.id:
        raise AppError("INVALID_PARENT", "上级部门不能是自己")
    for k, v in data.items():
        setattr(dept, k, v)
    audit(db, "department", dept.id, "update", actor, data)
    db.commit()
    return ok({"id": dept.id})


@router.delete("/departments/{dept_id}")
def delete_department(dept_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_departments", "delete"))):
    dept = db.get(Department, dept_id)
    if not dept or dept.is_deleted:
        raise AppError("NOT_FOUND", "部门不存在", 404)
    if db.query(OrgMember).filter(OrgMember.department_id == dept.id, OrgMember.is_deleted.is_(False)).first():
        raise AppError("DEPT_IN_USE", "无法删除：仍有人员归属该部门")
    if db.query(Department).filter(Department.parent_id == dept.id, Department.is_deleted.is_(False)).first():
        raise AppError("DEPT_IN_USE", "无法删除：存在下级部门")
    if dept.external_source:
        raise AppError("SYNCED_READONLY", "同步部门不可本地删除（外部源移除后自动停用）")
    dept.is_deleted = True
    audit(db, "department", dept.id, "delete", actor, {"code": dept.code})
    db.commit()
    return ok({"id": dept.id})


# ---------- 业务域 / 服务线 ----------

class DomainMembersIn(BaseModel):
    person_ids: list[str]


class DomainDepartmentsIn(BaseModel):
    department_ids: list[str]
    include_children: bool = True


class OrgSettingsUpdate(BaseModel):
    digital_team_department_ids: list[str] | None = None
    digital_team_include_children: bool | None = None
    feishu_auto_sync_enabled: bool | None = None
    feishu_auto_sync_interval_minutes: int | None = Field(default=None, ge=15, le=10080)


def _org_settings_payload(settings) -> dict:
    return {
        "digital_team_department_ids": settings.digital_team_department_ids or [],
        "digital_team_include_children": settings.digital_team_include_children,
        "feishu_auto_sync_enabled": settings.feishu_auto_sync_enabled,
        "feishu_auto_sync_interval_minutes": settings.feishu_auto_sync_interval_minutes,
        "feishu_auto_sync_last_attempt_at": settings.feishu_auto_sync_last_attempt_at,
    }


@router.get("/org-settings")
def get_org_settings_api(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    from app.services.org_settings import get_org_settings
    settings = get_org_settings(db)
    db.commit()
    return ok(_org_settings_payload(settings))


@router.patch("/org-settings")
def update_org_settings(body: OrgSettingsUpdate, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
    from app.services.org_settings import get_org_settings
    settings = get_org_settings(db)
    data = body.model_dump(exclude_unset=True)
    roots = data.get("digital_team_department_ids")
    if roots is not None:
        roots = list(dict.fromkeys(roots))
        valid = {row.id for row in db.query(Department).filter(
            Department.id.in_(roots or ["-"]), Department.is_deleted.is_(False), Department.active.is_(True)
        )}
        if set(roots) - valid:
            raise AppError("INVALID_DEPARTMENT", "数字化团队范围包含不存在或已停用的部门")
        data["digital_team_department_ids"] = roots
    for key, value in data.items():
        setattr(settings, key, value)
    audit(db, "org_settings", settings.id, "update", actor, {"fields": list(data)})
    db.commit()
    return ok(_org_settings_payload(settings))


def _validate_it_people(db: Session, person_ids: list[str | None]):
    from app.services.team_scope import it_member_ids

    selected = {person_id for person_id in person_ids if person_id}
    if selected - it_member_ids(db):
        raise AppError("NOT_IT_TEAM_MEMBER", "负责人和服务团队成员只能从数字化团队中选择")


def _replace_domain_departments(db: Session, domain_id: str, department_ids: list[str], include_children: bool):
    unique_ids = list(dict.fromkeys(department_ids))
    rows = db.query(Department).filter(Department.id.in_(unique_ids or ["-"]), Department.is_deleted.is_(False)).all()
    by_id = {d.id: d for d in rows}
    if set(unique_ids) - set(by_id):
        raise AppError("INVALID_DEPARTMENT", "包含不存在的部门")
    if any(not d.active or d.dept_type != "business" for d in rows):
        raise AppError("INVALID_DEPARTMENT", "只能选择启用的业务部门")
    db.query(BusinessDomainDepartment).filter(BusinessDomainDepartment.domain_id == domain_id).delete()
    for department_id in unique_ids:
        db.add(BusinessDomainDepartment(
            domain_id=domain_id, department_id=department_id, include_children=include_children,
        ))
    return len(unique_ids)


@router.get("/business-domains")
def list_domains(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False)).order_by(BusinessDomain.sort).all()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False)).all()}
    members_by_domain: dict[str, list] = {}
    for dm in db.query(BusinessDomainMember).filter(BusinessDomainMember.is_deleted.is_(False)).all():
        members_by_domain.setdefault(dm.domain_id, []).append({"id": dm.person_id, "name": names.get(dm.person_id)})
    departments = {
        d.id: d for d in db.query(Department).filter(Department.is_deleted.is_(False)).all()
    }
    departments_by_domain: dict[str, list] = {}
    for link in db.query(BusinessDomainDepartment).filter(BusinessDomainDepartment.is_deleted.is_(False)).all():
        dept = departments.get(link.department_id)
        if dept:
            departments_by_domain.setdefault(link.domain_id, []).append({
                "id": dept.id, "name": dept.name, "parent_id": dept.parent_id,
                "active": dept.active, "include_children": link.include_children,
            })
    return ok(
        [
            {
                "id": d.id, "code": d.code, "name": d.name, "description": d.description,
                "owner_id": d.owner_id, "owner_name": names.get(d.owner_id),
                "backup_owner_id": d.backup_owner_id, "backup_owner_name": names.get(d.backup_owner_id),
                "members": members_by_domain.get(d.id, []),
                "departments": departments_by_domain.get(d.id, []),
                "sort": d.sort, "active": d.active,
            }
            for d in rows
        ],
        total=len(rows),
    )


@router.put("/business-domains/{domain_id}/members")
def set_domain_members(domain_id: str, body: DomainMembersIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "edit"))):
    """服务团队成员：BM 带领的 BP/开发等（矩阵组织横向服务线）。"""
    domain = db.get(BusinessDomain, domain_id)
    if not domain or domain.is_deleted:
        raise AppError("NOT_FOUND", "业务域不存在", 404)
    _validate_it_people(db, body.person_ids)
    valid = {m.id for m in db.query(OrgMember).filter(OrgMember.id.in_(body.person_ids or ["-"])).all()}
    bad = set(body.person_ids) - valid
    if bad:
        raise AppError("INVALID_MEMBER", "包含不存在的人员")
    db.query(BusinessDomainMember).filter(BusinessDomainMember.domain_id == domain.id).delete()
    for pid in body.person_ids:
        db.add(BusinessDomainMember(domain_id=domain.id, person_id=pid))
    audit(db, "business_domain", domain.id, "set_members", actor, {"count": len(body.person_ids)})
    db.commit()
    return ok({"id": domain.id, "count": len(body.person_ids)})


@router.put("/business-domains/{domain_id}/departments")
def set_domain_departments(domain_id: str, body: DomainDepartmentsIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "edit"))):
    """从组织架构选择业务域服务的启用业务部门。"""
    domain = db.get(BusinessDomain, domain_id)
    if not domain or domain.is_deleted:
        raise AppError("NOT_FOUND", "业务域不存在", 404)
    count = _replace_domain_departments(db, domain.id, body.department_ids, body.include_children)
    audit(db, "business_domain", domain.id, "set_departments", actor, {
        "count": count, "include_children": body.include_children,
    })
    db.commit()
    return ok({"id": domain.id, "count": count, "include_children": body.include_children})


@router.post("/business-domains")
def create_domain(body: DomainIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "create"))):
    if db.query(BusinessDomain).filter(BusinessDomain.code == body.code, BusinessDomain.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "业务域编码已存在")
    _validate_it_people(db, [body.owner_id, body.backup_owner_id])
    data = body.model_dump(exclude={"department_ids", "include_children"})
    domain = BusinessDomain(**data)
    db.add(domain)
    db.flush()
    count = _replace_domain_departments(db, domain.id, body.department_ids, body.include_children)
    audit(db, "business_domain", domain.id, "create", actor, {"code": body.code, "department_count": count})
    db.commit()
    return ok({"id": domain.id})


@router.patch("/business-domains/{domain_id}")
def update_domain(domain_id: str, body: DomainUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "edit"))):
    domain = db.get(BusinessDomain, domain_id)
    if not domain or domain.is_deleted:
        raise AppError("NOT_FOUND", "业务域不存在", 404)
    data = body.model_dump(exclude_unset=True)
    _validate_it_people(db, [data.get("owner_id"), data.get("backup_owner_id")])
    department_ids = data.pop("department_ids", None)
    include_children = data.pop("include_children", None)
    for k, v in data.items():
        setattr(domain, k, v)
    if department_ids is not None:
        _replace_domain_departments(db, domain.id, department_ids, include_children if include_children is not None else True)
    audit(db, "business_domain", domain.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": domain.id})


@router.delete("/business-domains/{domain_id}")
def delete_domain(domain_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "delete"))):
    domain = db.get(BusinessDomain, domain_id)
    if not domain or domain.is_deleted:
        raise AppError("NOT_FOUND", "业务域不存在", 404)
    if db.query(Requirement).filter(
        Requirement.business_domain_id == domain.id, Requirement.is_deleted.is_(False)
    ).first():
        raise AppError("DOMAIN_IN_USE", "无法删除：该业务域仍被需求引用，请先迁移相关需求", 409)
    domain.is_deleted = True
    for row in db.query(BusinessDomainMember).filter(BusinessDomainMember.domain_id == domain.id):
        row.is_deleted = True
    for row in db.query(BusinessDomainDepartment).filter(BusinessDomainDepartment.domain_id == domain.id):
        row.is_deleted = True
    audit(db, "business_domain", domain.id, "delete", actor, {"code": domain.code})
    db.commit()
    return ok({"id": domain.id})


# ---------- 开通规则 ----------

@router.get("/provision-rules")
def list_rules(db: Session = Depends(get_db), _=Depends(require_perm("admin_provision", "view"))):
    rows = db.query(ProvisionRule).filter(ProvisionRule.is_deleted.is_(False)).order_by(ProvisionRule.sort).all()
    dept_names = {d.id: d.name for d in db.query(Department).filter(Department.is_deleted.is_(False)).all()}
    return ok(
        [
            {
                "id": r.id, "match_type": r.match_type, "match_value": r.match_value,
                "match_label": dept_names.get(r.match_value, r.match_value),
                "default_roles": r.default_roles or [], "sort": r.sort, "active": r.active,
            }
            for r in rows
        ],
        total=len(rows),
    )


@router.put("/provision-rules")
def replace_rules(body: list[RuleIn], db: Session = Depends(get_db), actor=Depends(require_perm("admin_provision", "edit"))):
    valid_roles = valid_role_codes(db)
    for r in body:
        if r.match_type not in ("dept_type", "department"):
            raise AppError("INVALID_RULE", "match_type 必须为 dept_type 或 department")
        if r.match_type == "dept_type" and r.match_value not in DEPT_TYPES:
            raise AppError("INVALID_RULE", "dept_type 取值必须为 it/business/audit")
        bad = set(r.default_roles) - valid_roles
        if bad:
            raise AppError("INVALID_RULE", f"未知角色: {','.join(bad)}")
        if "admin" in r.default_roles:
            raise AppError("INVALID_RULE", "admin 不允许作为开通默认角色，请在用户管理单独分配")
    db.query(ProvisionRule).delete()
    for r in body:
        db.add(ProvisionRule(**r.model_dump()))
    audit(db, "provision_rule", "batch", "replace", actor, {"count": len(body)})
    db.commit()
    return ok({"count": len(body)})


# ---------- 组织架构树（公司→部门→人员）与同步 ----------

@router.get("/org-tree")
def org_tree(db: Session = Depends(get_db), _=Depends(require_perm("admin_departments", "view"))):
    from app.models import MasterData
    from app.services.org_sync import SYNC_PROVIDERS

    company = (
        db.query(MasterData)
        .filter(MasterData.category == "sys_config", MasterData.code == "company_name")
        .first()
    )
    depts = db.query(Department).filter(Department.is_deleted.is_(False)).order_by(Department.sort).all()
    members = db.query(OrgMember).filter(OrgMember.is_deleted.is_(False)).order_by(OrgMember.name).all()
    member_names = {m.id: m.name for m in members}

    def member_row(m: OrgMember) -> dict:
        return {
            "id": m.id, "name": m.name, "name_en": m.name_en, "employee_no": m.employee_no,
            "gender": m.gender, "birth_date": m.birth_date, "employment_type": m.employment_type,
            "supervisor_id": m.supervisor_id, "supervisor_name": member_names.get(m.supervisor_id),
            "work_location": m.work_location, "department_id": m.department_id,
            "position_id": m.position_id, "position_name": m.position.name if m.position else None,
            "status": m.status, "hire_date": m.hire_date, "email": m.email, "mobile": m.mobile,
            "skills": m.skills or [], "remarks": m.remarks,
            "external_source": m.external_source,
        }

    members_by_dept: dict = {}
    unassigned = []
    for m in members:
        if m.department_id:
            members_by_dept.setdefault(m.department_id, []).append(member_row(m))
        else:
            unassigned.append(member_row(m))

    return ok(
        {
            "company": {
                "name": company.name if company else "我的公司",
                "master_data_id": company.id if company else None,
            },
            "departments": [
                {
                    "id": d.id, "code": d.code, "name": d.name, "parent_id": d.parent_id,
                    "dept_type": d.dept_type, "sort": d.sort, "active": d.active,
                    "external_source": d.external_source,
                    "members": members_by_dept.get(d.id, []),
                }
                for d in depts
            ],
            "unassigned_members": unassigned,
            "sync_sources": sorted(set(SYNC_PROVIDERS) | ({"feishu"} if feishu_enabled(db) else set())),  # 空=未配置外部同步
        }
    )


@router.post("/org-sync")
def trigger_org_sync(body: dict, db: Session = Depends(get_db), actor=Depends(require_perm("admin_departments", "edit"))):
    """触发组织同步（M35 异步化：全公司同步耗时较长，后台执行+完成通知，避免请求超时）。

    sync=false（默认）：启动后台线程立即返回 started；前端轮询 feishu-config.last_sync_stats.status。
    sync=true：同步等待返回统计（测试/脚本用）。
    """
    import threading

    from app.services.feishu import get_config
    from app.services.org_sync import run_sync

    source = (body or {}).get("source", "feishu")
    if (body or {}).get("sync"):  # 同步模式（测试/脚本）
        stats = run_sync(db, source)
        return ok({**stats, "status": "done"})

    cfg = get_config(db)
    if (cfg.last_sync_stats or {}).get("status") == "running":
        raise AppError("SYNC_RUNNING", "组织同步正在进行中，请稍候（完成后将收到站内通知）", 409)
    cfg.last_sync_stats = {**(cfg.last_sync_stats or {}), "status": "running"}
    audit(db, "org_sync", "manual", "trigger", actor, {"source": source})
    db.commit()

    recipient = actor.person_id or actor.id

    def _run_in_background():
        from app.db import SessionLocal
        from app.events import notifier

        db2 = SessionLocal()
        try:
            stats = run_sync(db2, source)  # 内部写 last_sync_at/stats
            cfg2 = get_config(db2)
            cfg2.last_sync_stats = {**stats, "status": "done"}
            notifier.notify(
                db2, "org_sync.done", "org_sync", "manual", [recipient],
                f"组织同步完成：新增 {stats.get('member_created', 0)} 人 / 更新 {stats.get('member_updated', 0)} 人"
                f" / 离职 {stats.get('member_left', 0)} 人，部门 +{stats.get('dept_created', 0)}",
                link="/admin/org?tab=architecture",
            )
            db2.commit()
        except Exception as e:  # noqa: BLE001 后台线程兜底：失败落状态+通知，不静默
            db2.rollback()
            try:
                cfg2 = get_config(db2)
                cfg2.last_sync_stats = {"status": "failed", "error": str(e)[:300]}
                notifier.notify(db2, "org_sync.failed", "org_sync", "manual", [recipient],
                                "组织同步失败", str(e)[:200], link="/admin/integrations?tab=feishu")
                db2.commit()
            except Exception:
                db2.rollback()
        finally:
            db2.close()

    threading.Thread(target=_run_in_background, daemon=True).start()
    return ok({"started": True})


# ==================== 飞书集成配置（M11，仅 admin） ====================

from pydantic import BaseModel as _BM  # noqa: E402


class FeishuConfigIn(_BM):
    api_base: str | None = None
    app_id: str | None = None
    app_secret: str | None = None  # 留空=不修改
    sync_scope: str | None = None
    enabled: bool | None = None


def _mask(secret: str | None) -> str | None:
    if not secret:
        return None
    return secret[:4] + "*" * 8 if len(secret) > 4 else "****"


def _feishu_cfg_payload(cfg) -> dict:
    return {
        "api_base": cfg.api_base, "app_id": cfg.app_id,
        "app_secret_masked": _mask(cfg.app_secret), "has_secret": bool(cfg.app_secret),
        "sync_scope": cfg.sync_scope, "enabled": cfg.enabled,
        "last_sync_at": cfg.last_sync_at, "last_sync_stats": cfg.last_sync_stats,
    }


@router.get("/feishu-config")
def get_feishu_config(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    from app.services.feishu import get_config

    cfg = get_config(db)
    db.commit()
    return ok(_feishu_cfg_payload(cfg))


@router.put("/feishu-config")
def update_feishu_config(body: FeishuConfigIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
    from app.services.feishu import get_config

    cfg = get_config(db)
    data = body.model_dump(exclude_unset=True)
    if data.get("enabled"):
        app_id = data.get("app_id") or cfg.app_id
        secret = data.get("app_secret") or cfg.app_secret
        if not (app_id and secret):
            raise AppError("FEISHU_CONFIG_INCOMPLETE", "启用前需先配置 App ID 与 App Secret")
    for k, v in data.items():
        if k == "app_secret":
            if v:  # 留空不改
                cfg.app_secret = v
            continue
        setattr(cfg, k, v)
    audit(db, "feishu_config", cfg.id, "update", actor,
          {"fields": [k for k in data if k != "app_secret"], "secret_changed": bool(data.get("app_secret"))})
    db.commit()
    return ok(_feishu_cfg_payload(cfg))


@router.post("/feishu-config/test")
def test_feishu_config(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    """测试连接：换 tenant_token；配置了 IT 部门则顺带取部门名。"""
    from app.services.feishu import build_client, get_config

    from app.services.feishu import parse_scope

    cfg = get_config(db)
    client = build_client(cfg)
    token = client.tenant_access_token()
    scope = parse_scope(cfg.sync_scope)
    scope_names = []
    for dep in scope[:5]:
        if dep == "0":
            scope_names.append("全公司")
        else:
            scope_names.append((client.get_department(token, dep) or {}).get("name") or dep)
    db.commit()
    return ok({"connected": True, "scope_names": scope_names})
