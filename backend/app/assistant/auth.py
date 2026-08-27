"""Scalar, bounded authentication for long-lived assistant message streams."""

from collections.abc import Callable
import time

from fastapi import Header
from sqlalchemy.orm import Session

from app.assistant.execution import (
    BoundedExecutionTimeout,
    BoundedToolExecutor,
    DEFAULT_ASSISTANT_DB_EXECUTOR,
    ToolExecutorSaturated,
    await_bounded_call,
)
from app.core.errors import AppError
from app.core.security import decode_token
from app.db import SessionLocal
from app.models import AuthUser


DEFAULT_STREAM_AUTH_TIMEOUT_SECONDS = 5.0


async def resolve_assistant_stream_actor_id(
    authorization: str,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    db_executor: BoundedToolExecutor = DEFAULT_ASSISTANT_DB_EXECUTOR,
    timeout_seconds: float = DEFAULT_STREAM_AUTH_TIMEOUT_SECONDS,
) -> str:
    """Return only an active actor id; the worker owns and closes its Session."""

    def authenticate() -> str:
        if not authorization.startswith("Bearer "):
            raise AppError("UNAUTHORIZED", "未登录或凭证无效", 401)
        user_id = decode_token(authorization[7:])
        if not user_id:
            raise AppError("UNAUTHORIZED", "凭证已过期，请重新登录", 401)
        db = session_factory()
        try:
            user = db.get(AuthUser, user_id)
            if user is None or not user.is_active or user.is_deleted:
                raise AppError("UNAUTHORIZED", "账号不存在或已禁用", 401)
            return str(user.id)
        finally:
            try:
                db.rollback()
            finally:
                db.close()

    try:
        return str(await await_bounded_call(
            db_executor,
            authenticate,
            deadline_monotonic=time.monotonic() + max(0.001, float(timeout_seconds)),
        ))
    except ToolExecutorSaturated:
        raise AppError("AI_ASSISTANT_AUTH_BUSY", "智能体认证资源繁忙，请稍后重试", 503) from None
    except BoundedExecutionTimeout:
        raise AppError("AI_ASSISTANT_AUTH_TIMEOUT", "智能体认证超时，请稍后重试", 503) from None


async def get_assistant_stream_actor_id(authorization: str = Header(default="")) -> str:
    return await resolve_assistant_stream_actor_id(authorization)
