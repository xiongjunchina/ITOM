from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_token, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.common import ok
from app.schemas.support import LoginIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_payload(db: Session, user: AuthUser) -> dict:
    from app.services.permissions import user_permissions
    from app.services.rbac import effective_roles

    return {
        "id": user.id,
        "username": user.username,
        "name": user.person.name if user.person else user.username,
        "roles": sorted(effective_roles(db, user)),  # 有效角色=直接∪组授予∪继承
        "direct_roles": user.roles or [],
        "permissions": user_permissions(db, user),  # {module:[actions]}，admin 为 {"*":[...]}；前端菜单/按钮以此渲染
        "auth_source": user.auth_source,
        "person_id": user.person_id,
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(AuthUser).filter(AuthUser.username == body.username, AuthUser.is_deleted.is_(False)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise AppError("LOGIN_FAILED", "用户名或密码错误", 401)
    if not user.is_active:
        raise AppError("LOGIN_FAILED", "账号已禁用", 401)
    user.last_login_at = datetime.now()
    db.commit()
    return ok({"token": create_token(user.id), "user": _user_payload(db, user)})


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok({**_user_payload(db, user), "preferences": user.preferences or {}})


class PreferencesIn(BaseModel):
    dashboard_widgets: list[str] | None = None
    team_overview_widgets: list[str] | None = None


@router.patch("/me/preferences")
def update_preferences(body: PreferencesIn, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """个人偏好（总览 widget 配置等）：只更新提交的键。"""
    prefs = dict(user.preferences or {})
    for k, v in body.model_dump(exclude_unset=True).items():
        prefs[k] = v
    user.preferences = prefs
    db.commit()
    return ok({"preferences": prefs})
