"""角色 / 用户组自配置维护（admin）。

- 内置角色只读（承载 API 权限）；自定义角色须继承一个内置角色获得系统权限
- 用户组用于流程步骤指派与状态机授权（键格式 "group:组码"）
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm, require_roles
from app.models import (
    AuthUser,
    OrgMember,
    ProcessStep,
    Role,
    UserGroup,
    UserGroupMember,
    WorkflowTransition,
)
from app.schemas.common import ok
from app.services.audit import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=64)
    base_role: str
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    base_role: str | None = None
    description: str | None = None


class GroupCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    roles: list[str] = []
    owner_id: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    roles: list[str] | None = None
    owner_id: str | None = None


class GroupMembersIn(BaseModel):
    person_ids: list[str]


# ---------- 角色 ----------

@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    """全员可读（状态机/流程配置下拉需要）。"""
    rows = db.query(Role).filter(Role.is_deleted.is_(False)).order_by(Role.is_builtin.desc(), Role.created_at).all()
    user_counts: dict[str, int] = {}
    for u in db.query(AuthUser).filter(AuthUser.is_deleted.is_(False)).all():
        for c in u.roles or []:
            user_counts[c] = user_counts.get(c, 0) + 1
    return ok(
        [
            {
                "id": r.id, "code": r.code, "name": r.name, "description": r.description,
                "base_role": r.base_role, "is_builtin": r.is_builtin,
                "user_count": user_counts.get(r.code, 0),
            }
            for r in rows
        ],
        total=len(rows),
    )


def _validate_base(db: Session, base_role: str):
    base = db.query(Role).filter(Role.code == base_role, Role.is_builtin.is_(True), Role.is_deleted.is_(False)).first()
    if not base:
        raise AppError("INVALID_BASE_ROLE", "继承角色必须是内置角色")
    if base.code == "admin":
        raise AppError("INVALID_BASE_ROLE", "不允许继承 admin，请直接为用户分配 admin 角色")


@router.post("/roles")
def create_role(body: RoleCreate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_roles", "create"))):
    if db.query(Role).filter(Role.code == body.code, Role.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "角色代码已存在")
    _validate_base(db, body.base_role)
    role = Role(**body.model_dump(), is_builtin=False)
    db.add(role)
    db.flush()
    # 复制模板角色（base_role）的权限矩阵为初始值，之后独立编辑
    from app.models import RolePermission

    template_rows = (
        db.query(RolePermission)
        .filter(RolePermission.role_code == body.base_role, RolePermission.is_deleted.is_(False))
        .all()
    )
    for row in template_rows:
        db.add(RolePermission(role_code=role.code, module=row.module, actions=list(row.actions or [])))
    audit(db, "role", role.id, "create", actor, {"code": body.code, "base_role": body.base_role, "perms_copied": len(template_rows)})
    db.commit()
    return ok({"id": role.id})


@router.patch("/roles/{role_id}")
def update_role(role_id: str, body: RoleUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_roles", "edit"))):
    role = db.get(Role, role_id)
    if not role or role.is_deleted:
        raise AppError("NOT_FOUND", "角色不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if role.is_builtin and "base_role" in data:
        raise AppError("BUILTIN_ROLE", "内置角色的代码与继承关系不可修改（名称/描述可以）")
    if data.get("base_role"):
        _validate_base(db, data["base_role"])
    for k, v in data.items():
        setattr(role, k, v)
    audit(db, "role", role.id, "update", actor, data)
    db.commit()
    return ok({"id": role.id})


def _role_in_use(db: Session, code: str) -> str | None:
    for u in db.query(AuthUser).filter(AuthUser.is_deleted.is_(False)).all():
        if code in (u.roles or []):
            return f"用户 {u.username} 持有该角色"
    step = db.query(ProcessStep).filter(ProcessStep.default_role == code, ProcessStep.is_deleted.is_(False)).first()
    if step:
        return "流程步骤引用了该角色"
    for t in db.query(WorkflowTransition).filter(WorkflowTransition.is_deleted.is_(False)).all():
        if code in (t.allowed_roles or []):
            return "状态机流转规则引用了该角色"
    return None


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_roles", "delete"))):
    role = db.get(Role, role_id)
    if not role or role.is_deleted:
        raise AppError("NOT_FOUND", "角色不存在", 404)
    if role.is_builtin:
        raise AppError("BUILTIN_ROLE", "内置角色不可删除")
    reason = _role_in_use(db, role.code)
    if reason:
        raise AppError("ROLE_IN_USE", f"无法删除：{reason}")
    role.is_deleted = True
    audit(db, "role", role.id, "delete", actor, {"code": role.code})
    db.commit()
    return ok({"id": role.id})


# ---------- 用户组 ----------

def _group_row(g: UserGroup, db: Session) -> dict:
    members = (
        db.query(OrgMember)
        .join(UserGroupMember, UserGroupMember.person_id == OrgMember.id)
        .filter(UserGroupMember.group_id == g.id, UserGroupMember.is_deleted.is_(False))
        .all()
    )
    owner = db.get(OrgMember, g.owner_id) if g.owner_id else None
    return {
        "id": g.id, "code": g.code, "name": g.name, "description": g.description,
        "roles": g.roles or [],
        "owner_id": g.owner_id, "owner_name": owner.name if owner else None,
        "members": [{"id": m.id, "name": m.name} for m in members],
    }


@router.get("/groups")
def list_groups(db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    rows = db.query(UserGroup).filter(UserGroup.is_deleted.is_(False)).order_by(UserGroup.created_at).all()
    return ok([_group_row(g, db) for g in rows], total=len(rows))


def _check_group_roles(db: Session, roles: list[str]):
    from app.services.rbac import valid_role_codes

    bad = set(roles) - valid_role_codes(db)
    if bad:
        raise AppError("INVALID_ROLE", f"未知角色: {','.join(bad)}")
    if "admin" in roles:
        raise AppError("INVALID_ROLE", "admin 不允许通过用户组授予，请在用户管理单独分配")


@router.post("/groups")
def create_group(body: GroupCreate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_groups", "create"))):
    if db.query(UserGroup).filter(UserGroup.code == body.code, UserGroup.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", "用户组代码已存在")
    _check_group_roles(db, body.roles)
    group = UserGroup(**body.model_dump())
    db.add(group)
    db.flush()
    audit(db, "user_group", group.id, "create", actor, {"code": body.code})
    db.commit()
    return ok(_group_row(group, db))


@router.patch("/groups/{group_id}")
def update_group(group_id: str, body: GroupUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_groups", "edit"))):
    group = db.get(UserGroup, group_id)
    if not group or group.is_deleted:
        raise AppError("NOT_FOUND", "用户组不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if data.get("roles") is not None:
        _check_group_roles(db, data["roles"])
    for k, v in data.items():
        setattr(group, k, v)
    audit(db, "user_group", group.id, "update", actor, data)
    db.commit()
    return ok(_group_row(group, db))


@router.put("/groups/{group_id}/members")
def set_group_members(group_id: str, body: GroupMembersIn, db: Session = Depends(get_db), actor=Depends(require_perm("admin_groups", "edit"))):
    group = db.get(UserGroup, group_id)
    if not group or group.is_deleted:
        raise AppError("NOT_FOUND", "用户组不存在", 404)
    valid = {m.id for m in db.query(OrgMember).filter(OrgMember.id.in_(body.person_ids or ["-"])).all()}
    bad = set(body.person_ids) - valid
    if bad:
        raise AppError("INVALID_MEMBER", "包含不存在的人员")
    db.query(UserGroupMember).filter(UserGroupMember.group_id == group.id).delete()
    for pid in body.person_ids:
        db.add(UserGroupMember(group_id=group.id, person_id=pid))
    audit(db, "user_group", group.id, "set_members", actor, {"count": len(body.person_ids)})
    db.commit()
    return ok(_group_row(group, db))


@router.get("/members/{person_id}/groups")
def get_person_groups(person_id: str, db: Session = Depends(get_db), _=Depends(require_roles())):
    rows = (
        db.query(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .filter(
            UserGroupMember.person_id == person_id,
            UserGroupMember.is_deleted.is_(False),
            UserGroup.is_deleted.is_(False),
        )
        .all()
    )
    return ok([{"id": g.id, "code": g.code, "name": g.name} for g in rows])


class PersonGroupsIn(BaseModel):
    group_ids: list[str]


@router.put("/members/{person_id}/groups")
def set_person_groups(person_id: str, body: PersonGroupsIn, db: Session = Depends(get_db), actor=Depends(require_roles())):
    """按人设置所属用户组（与按组设置成员等价，双向入口）。"""
    if not db.get(OrgMember, person_id):
        raise AppError("NOT_FOUND", "人员不存在", 404)
    valid = {
        g.id for g in db.query(UserGroup).filter(UserGroup.id.in_(body.group_ids or ["-"]), UserGroup.is_deleted.is_(False))
    }
    bad = set(body.group_ids) - valid
    if bad:
        raise AppError("INVALID_GROUP", "包含不存在的用户组")
    db.query(UserGroupMember).filter(UserGroupMember.person_id == person_id).delete()
    for gid in body.group_ids:
        db.add(UserGroupMember(group_id=gid, person_id=person_id))
    audit(db, "org_member", person_id, "set_groups", actor, {"count": len(body.group_ids)})
    db.commit()
    return ok({"person_id": person_id, "group_ids": body.group_ids})


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_groups", "delete"))):
    group = db.get(UserGroup, group_id)
    if not group or group.is_deleted:
        raise AppError("NOT_FOUND", "用户组不存在", 404)
    key = f"group:{group.code}"
    step = db.query(ProcessStep).filter(ProcessStep.default_role == key, ProcessStep.is_deleted.is_(False)).first()
    if step:
        raise AppError("GROUP_IN_USE", "无法删除：流程步骤引用了该用户组")
    for t in db.query(WorkflowTransition).filter(WorkflowTransition.is_deleted.is_(False)).all():
        if key in (t.allowed_roles or []):
            raise AppError("GROUP_IN_USE", "无法删除：状态机流转规则引用了该用户组")
    group.is_deleted = True
    db.query(UserGroupMember).filter(UserGroupMember.group_id == group.id).delete()
    audit(db, "user_group", group.id, "delete", actor, {"code": group.code})
    db.commit()
    return ok({"id": group.id})


# ---------- 权限矩阵 ----------

class PermEntry(BaseModel):
    module: str
    actions: list[str]


class PermPut(BaseModel):
    role_code: str
    entries: list[PermEntry]


@router.get("/permission-modules")
def permission_modules(_=Depends(get_current_user)):
    """模块注册表（矩阵网格用）。"""
    from app.services.permissions import ACTIONS, MODULE_PAGES, MODULES, PAGE_NAMES

    return ok({
        "actions": list(ACTIONS),
        "modules": [
            {"code": c, "name": n, "group": g,
             "page": MODULE_PAGES.get(c), "page_name": PAGE_NAMES.get(MODULE_PAGES.get(c))}
            for c, n, g in MODULES
        ],
    })


@router.get("/permissions")
def get_role_permissions(role: str = "", db: Session = Depends(get_db), _=Depends(require_perm("admin_permissions", "view"))):
    from app.models import RolePermission

    query = db.query(RolePermission).filter(RolePermission.is_deleted.is_(False))
    if role:
        query = query.filter(RolePermission.role_code == role)
    return ok([
        {"role_code": r.role_code, "module": r.module, "actions": r.actions or []}
        for r in query.all()
    ])


@router.put("/permissions")
def put_role_permissions(body: PermPut, db: Session = Depends(get_db), actor=Depends(require_perm("admin_permissions", "edit"))):
    """整体替换某角色的权限矩阵。admin 不可配置（隐式全权）。"""
    from app.services.permissions import ACTIONS, MODULE_CODES
    from app.models import RolePermission

    if body.role_code == "admin":
        raise AppError("ADMIN_LOCKED", "admin 隐式全权，不可配置")
    role = db.query(Role).filter(Role.code == body.role_code, Role.is_deleted.is_(False)).first()
    if not role:
        raise AppError("NOT_FOUND", "角色不存在", 404)
    for e in body.entries:
        if e.module not in MODULE_CODES:
            raise AppError("INVALID_MODULE", f"未知模块: {e.module}")
        bad = set(e.actions) - set(ACTIONS)
        if bad:
            raise AppError("INVALID_ACTION", f"未知动作: {','.join(bad)}")
    db.query(RolePermission).filter(RolePermission.role_code == body.role_code).delete()
    for e in body.entries:
        if e.actions:
            db.add(RolePermission(role_code=body.role_code, module=e.module, actions=e.actions))
    audit(db, "role_permission", body.role_code, "replace", actor, {"modules": len(body.entries)})
    db.commit()
    return ok({"role_code": body.role_code})
