from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password
from app.db import get_db
from app.deps import require_perm
from app.models import AuthUser
from app.schemas.common import ok, paginate
from app.schemas.support import UserCreate, UserUpdate
from app.services.audit import audit

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


def _row(u: AuthUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.person.name if u.person else u.username,
        "roles": u.roles or [],
        "person_id": u.person_id,
        "auth_source": u.auth_source,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at,
        "initial_password_available": bool(u.initial_password_ciphertext),
        "initial_password_sent_at": u.initial_password_sent_at,
    }


def _check_roles(db: Session, roles: list[str]):
    from app.services.rbac import valid_role_codes

    bad = set(roles) - valid_role_codes(db)
    if bad:
        raise AppError("INVALID_ROLE", f"未知角色: {','.join(bad)}")


@router.get("")
def list_users(page: int = 1, page_size: int = 20, q: str = "", db: Session = Depends(get_db), _=Depends(require_perm("admin_users", "view"))):
    query = db.query(AuthUser).filter(AuthUser.is_deleted.is_(False))
    if q:
        query = query.filter(AuthUser.username.ilike(f"%{q}%"))
    items, total = paginate(query.order_by(AuthUser.created_at.desc()), page, page_size)
    return ok([_row(u) for u in items], total=total, page=page)


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_users", "create"))):
    _check_roles(db, body.roles)
    if db.query(AuthUser).filter(AuthUser.username == body.username).first():
        raise AppError("USERNAME_TAKEN", "用户名已存在")
    roles = body.roles
    if not roles:  # 未指定角色时按开通规则取默认（仅创建时，之后自由增减）
        from app.models import OrgMember
        from app.services.provisioning import default_roles_for

        person = db.get(OrgMember, body.person_id) if body.person_id else None
        roles = default_roles_for(db, person.department_id if person else None)
    from datetime import datetime

    user = AuthUser(
        username=body.username,
        password_hash=hash_password(body.password),
        roles=roles,
        person_id=body.person_id,
        is_active=body.is_active,
        password_set_at=datetime.now(),  # 初始口令由管理员告知本人，本人改密时需验当前密码
    )
    db.add(user)
    db.flush()
    audit(db, "auth_user", user.id, "create", actor, {"username": body.username, "roles": roles})
    db.commit()
    return ok(_row(user))


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_users", "edit"))):
    user = db.get(AuthUser, user_id)
    if not user or user.is_deleted:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    changes: dict = {}
    if body.roles is not None:
        _check_roles(db, body.roles)
        changes["roles"] = {"from": user.roles, "to": body.roles}
        user.roles = body.roles
    if body.password:
        from datetime import datetime

        user.password_hash = hash_password(body.password)
        user.password_set_at = datetime.now()
        user.initial_password_ciphertext = None
        user.initial_password_sent_at = None
        changes["password"] = "reset"
    if body.person_id is not None:
        user.person_id = body.person_id or None
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
    audit(db, "auth_user", user.id, "update", actor, changes)
    db.commit()
    return ok(_row(user))


@router.get("/{user_id}/initial-password")
def reveal_initial_password(user_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_users", "edit"))):
    user = db.get(AuthUser, user_id)
    if not user or user.is_deleted:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    if not user.initial_password_ciphertext:
        raise AppError("NO_INITIAL_PASSWORD", "该用户没有可查看的初始密码")
    from app.services.secrets_store import decrypt_secret
    audit(db, "auth_user", user.id, "reveal_initial_password", actor, {})
    db.commit()
    return ok({"password": decrypt_secret(user.initial_password_ciphertext)})


@router.post("/{user_id}/initial-password/email")
def email_initial_password(user_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_users", "edit"))):
    user = db.get(AuthUser, user_id)
    if not user or user.is_deleted:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    if not user.initial_password_ciphertext:
        raise AppError("NO_INITIAL_PASSWORD", "该用户没有可发送的初始密码")
    recipient = user.person.email if user.person else None
    if not recipient:
        raise AppError("EMAIL_REQUIRED", "关联人员未配置邮箱，无法发送初始密码")
    from datetime import datetime
    from app.services.email import send_initial_password_email
    from app.services.secrets_store import decrypt_secret
    send_initial_password_email(db, recipient, user.person.name, user.username,
                                decrypt_secret(user.initial_password_ciphertext))
    user.initial_password_sent_at = datetime.now()
    audit(db, "auth_user", user.id, "email_initial_password", actor, {"recipient": recipient})
    db.commit()
    return ok({"sent_to": recipient, "sent_at": user.initial_password_sent_at})


@router.delete("/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_users", "delete"))):
    """删除用户账号（M36）：软删并释放用户名、解绑关联人员——人员主数据与部门不受影响。

    admin 内置账号与当前登录账号不可删（防锁死/防自杀）。同一员工后续可重新开通同名账号。
    """
    u = db.get(AuthUser, user_id)
    if not u or u.is_deleted:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    if u.username == "admin":
        raise AppError("ADMIN_LOCKED", "内置管理员账号不可删除")
    if u.id == actor.id:
        raise AppError("SELF_DELETE", "不能删除当前登录账号")
    unbound_person = u.person_id
    u.is_deleted = True
    u.is_active = False
    u.person_id = None  # 解绑人员（人员主数据保留）
    u.username = f"{u.username}#del-{u.id[-6:]}"  # 释放用户名，便于同名重新开通
    audit(db, "auth_user", u.id, "delete", actor,
          {"username": u.username, "person_unbound": bool(unbound_person)})
    db.commit()
    return ok({"id": u.id})
