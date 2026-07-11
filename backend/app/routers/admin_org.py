"""组织结构管理（admin）：部门 / 业务域 / 开通规则（docs/06）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm, require_roles
from app.models import BusinessDomain, BusinessDomainMember, Department, OrgMember, ProvisionRule
from app.schemas.common import ok
from app.services.audit import audit
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
    sort: int = 0


class DomainUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    owner_id: str | None = None
    backup_owner_id: str | None = None
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


@router.get("/business-domains")
def list_domains(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False)).order_by(BusinessDomain.sort).all()
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False)).all()}
    members_by_domain: dict[str, list] = {}
    for dm in db.query(BusinessDomainMember).filter(BusinessDomainMember.is_deleted.is_(False)).all():
        members_by_domain.setdefault(dm.domain_id, []).append({"id": dm.person_id, "name": names.get(dm.person_id)})
    return ok(
        [
            {
                "id": d.id, "code": d.code, "name": d.name, "description": d.description,
                "owner_id": d.owner_id, "owner_name": names.get(d.owner_id),
                "backup_owner_id": d.backup_owner_id, "backup_owner_name": names.get(d.backup_owner_id),
                "members": members_by_domain.get(d.id, []),
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


@router.post("/business-domains")
def create_domain(body: DomainIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "create"))):
    if db.query(BusinessDomain).filter(BusinessDomain.code == body.code, BusinessDomain.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "业务域编码已存在")
    domain = BusinessDomain(**body.model_dump())
    db.add(domain)
    db.flush()
    audit(db, "business_domain", domain.id, "create", actor, {"code": body.code})
    db.commit()
    return ok({"id": domain.id})


@router.patch("/business-domains/{domain_id}")
def update_domain(domain_id: str, body: DomainUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_business_domains", "edit"))):
    domain = db.get(BusinessDomain, domain_id)
    if not domain or domain.is_deleted:
        raise AppError("NOT_FOUND", "业务域不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(domain, k, v)
    audit(db, "business_domain", domain.id, "update", actor, {"fields": list(data.keys())})
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
            "sync_sources": sorted(SYNC_PROVIDERS.keys()),  # 空=尚未配置外部同步
        }
    )


@router.post("/org-sync")
def trigger_org_sync(body: dict, db: Session = Depends(get_db), actor=Depends(require_perm("admin_departments", "edit"))):
    """手动触发组织同步（飞书凭据上线前返回 501）。"""
    from app.services.org_sync import run_sync

    source = (body or {}).get("source", "feishu")
    stats = run_sync(db, source)
    audit(db, "org_sync", source, "run", actor, stats)
    db.commit()
    return ok(stats)
