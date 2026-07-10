from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import ADMIN
from app.core.security import decode_token
from app.db import get_db
from app.models import AuthUser


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> AuthUser:
    if not authorization.startswith("Bearer "):
        raise AppError("UNAUTHORIZED", "未登录或凭证无效", 401)
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise AppError("UNAUTHORIZED", "凭证已过期，请重新登录", 401)
    user = db.get(AuthUser, user_id)
    if not user or not user.is_active or user.is_deleted:
        raise AppError("UNAUTHORIZED", "账号不存在或已禁用", 401)
    return user


def require_roles(*roles: str):
    """角色守卫：admin 隐式放行；自定义角色经 base_role 继承内置权限。"""

    def guard(
        user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> AuthUser:
        from app.services.rbac import actor_keys

        held = actor_keys(db, user)
        if ADMIN in held or held & set(roles):
            return user
        raise AppError("FORBIDDEN", "没有执行此操作的权限", 403)

    return guard
