from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_token, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.common import ok
from app.schemas.support import LoginIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_payload(user: AuthUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "name": user.person.name if user.person else user.username,
        "roles": user.roles or [],
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
    return ok({"token": create_token(user.id), "user": _user_payload(user)})


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user)):
    return ok(_user_payload(user))
