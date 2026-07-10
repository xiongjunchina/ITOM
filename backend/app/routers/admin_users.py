from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password
from app.db import get_db
from app.deps import require_roles
from app.models import AuthUser
from app.schemas.common import ok, paginate
from app.schemas.support import UserCreate, UserUpdate
from app.services.audit import audit

router = APIRouter(prefix="/api/admin/users", tags=["admin"], dependencies=[Depends(require_roles())])


def _row(u: AuthUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.person.name if u.person else u.username,
        "roles": u.roles or [],
        "person_id": u.person_id,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at,
    }


def _check_roles(db: Session, roles: list[str]):
    from app.services.rbac import valid_role_codes

    bad = set(roles) - valid_role_codes(db)
    if bad:
        raise AppError("INVALID_ROLE", f"未知角色: {','.join(bad)}")


@router.get("")
def list_users(page: int = 1, page_size: int = 20, q: str = "", db: Session = Depends(get_db)):
    query = db.query(AuthUser).filter(AuthUser.is_deleted.is_(False))
    if q:
        query = query.filter(AuthUser.username.ilike(f"%{q}%"))
    items, total = paginate(query.order_by(AuthUser.created_at.desc()), page, page_size)
    return ok([_row(u) for u in items], total=total, page=page)


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), actor=Depends(require_roles())):
    _check_roles(db, body.roles)
    if db.query(AuthUser).filter(AuthUser.username == body.username).first():
        raise AppError("USERNAME_TAKEN", "用户名已存在")
    user = AuthUser(
        username=body.username,
        password_hash=hash_password(body.password),
        roles=body.roles,
        person_id=body.person_id,
        is_active=body.is_active,
    )
    db.add(user)
    db.flush()
    audit(db, "auth_user", user.id, "create", actor, {"username": body.username, "roles": body.roles})
    db.commit()
    return ok(_row(user))


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, db: Session = Depends(get_db), actor=Depends(require_roles())):
    user = db.get(AuthUser, user_id)
    if not user or user.is_deleted:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    changes: dict = {}
    if body.roles is not None:
        _check_roles(db, body.roles)
        changes["roles"] = {"from": user.roles, "to": body.roles}
        user.roles = body.roles
    if body.password:
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    if body.person_id is not None:
        user.person_id = body.person_id or None
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
    audit(db, "auth_user", user.id, "update", actor, changes)
    db.commit()
    return ok(_row(user))
