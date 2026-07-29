"""MCP 写操作的预览确认、短期凭证与幂等状态。"""

from datetime import datetime, timedelta
import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.glid import new_glid
from app.models import AuthUser, McpOperationIntent
from app.services.service_forms import canonical_json


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if not 8 <= len(key) <= 128:
        raise AppError("INVALID_IDEMPOTENCY_KEY", "幂等键长度必须为 8-128 个字符")
    return key


def prepare(
    db: Session,
    user: AuthUser,
    tool_name: str,
    payload: dict,
    idempotency_key: str,
    ttl_minutes: int = 10,
) -> tuple[McpOperationIntent, str]:
    key = validate_idempotency_key(idempotency_key)
    digest = payload_digest(payload)
    row = (
        db.query(McpOperationIntent)
        .filter(
            McpOperationIntent.auth_user_id == user.id,
            McpOperationIntent.tool_name == tool_name,
            McpOperationIntent.idempotency_key == key,
            McpOperationIntent.is_deleted.is_(False),
        )
        .first()
    )
    if row and row.payload_digest != digest:
        raise AppError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同内容", 409)
    token = secrets.token_urlsafe(32)
    if row:
        if row.status == "executed":
            return row, token
        row.normalized_payload = payload
        row.token_hash = _token_hash(token)
        row.status = "prepared"
        row.expires_at = datetime.now() + timedelta(minutes=ttl_minutes)
    else:
        row = McpOperationIntent(
            intent_id=new_glid(),
            tool_name=tool_name,
            auth_user_id=user.id,
            normalized_payload=payload,
            payload_digest=digest,
            token_hash=_token_hash(token),
            idempotency_key=key,
            status="prepared",
            expires_at=datetime.now() + timedelta(minutes=ttl_minutes),
        )
        db.add(row)
    db.flush()
    return row, token


def begin_direct_action(
    db: Session,
    user: AuthUser,
    tool_name: str,
    payload: dict,
    idempotency_key: str,
) -> tuple[McpOperationIntent, bool]:
    """为无需二次预览的用户动作建立同事务幂等边界。

    P2 的确认、重开和评价本身就是用户在 Aily 中的明确动作，因此不再签发
    第二个确认令牌；幂等记录与领域变更在同一事务提交，成功后可安全重放。
    """
    key = validate_idempotency_key(idempotency_key)
    digest = payload_digest(payload)
    row = (
        db.query(McpOperationIntent)
        .filter(
            McpOperationIntent.auth_user_id == user.id,
            McpOperationIntent.tool_name == tool_name,
            McpOperationIntent.idempotency_key == key,
            McpOperationIntent.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    if row and row.payload_digest != digest:
        raise AppError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同内容", 409)
    if row:
        return row, row.status == "executed"
    row = McpOperationIntent(
        intent_id=new_glid(),
        tool_name=tool_name,
        auth_user_id=user.id,
        normalized_payload=payload,
        payload_digest=digest,
        token_hash=_token_hash(secrets.token_urlsafe(32)),
        idempotency_key=key,
        status="prepared",
        expires_at=datetime.now() + timedelta(days=3650),
    )
    db.add(row)
    db.flush()
    return row, False


def require_prepared(
    db: Session,
    user: AuthUser,
    tool_name: str,
    idempotency_key: str,
    confirmation_token: str,
) -> tuple[McpOperationIntent, bool]:
    key = validate_idempotency_key(idempotency_key)
    row = (
        db.query(McpOperationIntent)
        .filter(
            McpOperationIntent.auth_user_id == user.id,
            McpOperationIntent.tool_name == tool_name,
            McpOperationIntent.idempotency_key == key,
            McpOperationIntent.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    if not row:
        raise AppError("CONFIRMATION_NOT_FOUND", "未找到对应的预览确认", 404)
    if row.status == "executed":
        return row, True
    if row.status != "prepared":
        raise AppError("CONFIRMATION_INVALID", "确认意图状态无效")
    if row.expires_at < datetime.now():
        row.status = "expired"
        raise AppError("CONFIRMATION_EXPIRED", "确认凭证已过期，请重新预览")
    if not confirmation_token or not hmac.compare_digest(
        row.token_hash,
        _token_hash(confirmation_token),
    ):
        raise AppError("CONFIRMATION_TOKEN_INVALID", "确认凭证无效", 403)
    return row, False


def mark_executed(
    row: McpOperationIntent,
    entity_type: str,
    entity_id: str,
    result_snapshot: dict,
) -> None:
    row.status = "executed"
    row.consumed_at = datetime.now()
    row.result_entity_type = entity_type
    row.result_entity_id = entity_id
    row.result_snapshot = result_snapshot
