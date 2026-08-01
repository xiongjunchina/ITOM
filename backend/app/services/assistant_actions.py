"""Server-owned WA0 L3 preview, confirmation, and idempotency boundary."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from contextlib import contextmanager

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.assistant.policy import capabilities_for_user
from app.assistant.redaction import redact_for_message
from app.assistant.registry import registry
from app.assistant.types import AssistantChannel, CapabilityDefinition, CapabilityResult, RiskLevel
from app.core.errors import AppError
from app.models import AiAction, AiConversation, AuthUser
from app.services.audit import audit
from app.services.service_forms import canonical_json


_TOKEN_TTL_MINUTES = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(payload)).encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if not 8 <= len(key) <= 128:
        raise AppError("AI_ACTION_IDEMPOTENCY_KEY_INVALID", "幂等键长度必须为 8-128 个字符")
    return key


def _owned_conversation(
    db: Session,
    actor: AuthUser,
    conversation_id: str,
    *,
    require_active: bool = True,
) -> AiConversation:
    row = (
        db.query(AiConversation)
        .filter(
            AiConversation.id == conversation_id,
            AiConversation.auth_user_id == actor.id,
            AiConversation.is_deleted.is_(False),
        )
        .first()
    )
    if row is None or (require_active and row.status != "active"):
        raise AppError("AI_CONVERSATION_NOT_FOUND", "智能体会话不存在", 404)
    return row


def _current_l3_definition(
    db: Session,
    actor: AuthUser,
    capability_code: str,
    *,
    unavailable_code: str,
) -> CapabilityDefinition:
    visible = capabilities_for_user(
        db,
        actor,
        channel=AssistantChannel.WEB,
        max_risk=RiskLevel.L3,
        registry=registry,
    )
    definition = next((item for item in visible if item.code == capability_code), None)
    if (
        definition is None
        or definition.risk is not RiskLevel.L3
        or not definition.requires_confirmation
        or not callable(definition.handler)
    ):
        raise AppError(unavailable_code, "当前账号不能执行该智能体动作", 403)
    return definition


def _normalized_payload(definition: CapabilityDefinition, payload: object) -> tuple[dict, BaseModel]:
    try:
        parsed = definition.input_model.model_validate(payload)
        normalized = parsed.model_dump(mode="json")
        redacted = redact_for_message(normalized)
        if not isinstance(redacted, dict):
            raise ValueError("redacted action payload is not an object")
        # Confirmation executes only the persisted, redacted canonical payload.
        # This prevents credentials embedded in free text from becoming durable
        # action state while retaining the exact registered Pydantic contract.
        return redacted, definition.input_model.model_validate(redacted)
    except (ValidationError, ValueError):
        raise AppError("AI_ACTION_PAYLOAD_INVALID", "动作参数无效")


def _preview_result(handler: object, db: Session, actor: AuthUser, data: BaseModel) -> CapabilityResult:
    preview = getattr(handler, "preview", None)
    if not callable(preview):
        raise AppError("AI_ACTION_PREVIEW_UNAVAILABLE", "该动作没有可验证的服务端预览", 409)
    result = preview(db, actor, data)
    if not isinstance(result, CapabilityResult):
        raise AppError("AI_ACTION_PREVIEW_INVALID", "服务端预览结果无效", 409)
    return result


def _safe_result(result: CapabilityResult) -> tuple[dict, str | None]:
    data = redact_for_message(dict(result.data or {}))
    message = redact_for_message(result.message) if result.message is not None else None
    if not isinstance(data, dict) or (message is not None and not isinstance(message, str)):
        raise AppError("AI_ACTION_RESULT_INVALID", "动作结果无效", 409)
    return data, message


def _action_payload(row: AiAction, *, include_token: str | None = None) -> dict:
    summary = row.result_summary if isinstance(row.result_summary, dict) else {}
    body = {
        "action_id": row.id,
        "capability_code": row.capability_code,
        "risk": row.risk_level,
        "status": row.status,
        "confirmation_expires_at": row.expires_at,
    }
    if row.status == "prepared":
        body["preview"] = summary.get("preview", {})
    else:
        body["result"] = summary.get("result", {})
    if include_token is not None:
        body["confirmation_token"] = include_token
    return body


def prepare_action(
    db: Session,
    actor: AuthUser,
    conversation_id: str,
    capability_code: str,
    payload: object,
    idempotency_key: str,
) -> dict:
    """Create one authoritative L3 preview and return its raw token once."""
    try:
        conversation = _owned_conversation(db, actor, conversation_id)
        definition = _current_l3_definition(
            db,
            actor,
            capability_code,
            unavailable_code="AI_ACTION_CAPABILITY_UNAVAILABLE",
        )
        key = _idempotency_key(idempotency_key)
        normalized, parsed = _normalized_payload(definition, payload)
        payload_digest = _digest(normalized)
        existing = (
            db.query(AiAction)
            .filter(
                AiAction.auth_user_id == actor.id,
                AiAction.capability_code == definition.code,
                AiAction.idempotency_key == key,
                AiAction.is_deleted.is_(False),
            )
            .with_for_update()
            .first()
        )
        if existing is not None:
            if existing.payload_digest != payload_digest:
                raise AppError(
                    "AI_ACTION_IDEMPOTENCY_CONFLICT",
                    "同一幂等键不能用于不同动作内容",
                    409,
                )
            db.rollback()
            return _action_payload(existing)

        preview_result = _preview_result(definition.handler, db, actor, parsed)
        preview, preview_message = _safe_result(preview_result)
        raw_token = secrets.token_urlsafe(32)
        row = AiAction(
            conversation_id=conversation.id,
            auth_user_id=actor.id,
            capability_code=definition.code,
            risk_level=definition.risk.value,
            normalized_payload=normalized,
            payload_digest=payload_digest,
            token_hash=_token_hash(raw_token),
            idempotency_key=key,
            status="prepared",
            expires_at=_utcnow() + timedelta(minutes=_TOKEN_TTL_MINUTES),
            result_code=preview_result.status,
            result_summary={"preview": preview, "message": preview_message},
        )
        db.add(row)
        db.flush()
        audit(
            db,
            "ai_action",
            row.id,
            "prepared",
            actor,
            {
                "capability_code": definition.code,
                "risk_level": definition.risk.value,
                "payload_digest": payload_digest,
            },
        )
        db.commit()
        db.refresh(row)
        return _action_payload(row, include_token=raw_token)
    except Exception:
        db.rollback()
        raise


def _locked_owned_action(db: Session, actor: AuthUser, action_id: str) -> AiAction:
    row = (
        db.query(AiAction)
        .filter(
            AiAction.id == action_id,
            AiAction.auth_user_id == actor.id,
            AiAction.is_deleted.is_(False),
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        raise AppError("AI_ACTION_NOT_FOUND", "智能体动作不存在", 404)
    return row


def _persist_failed_action(
    db: Session,
    actor_id: str,
    action_id: str,
    *,
    code: str,
) -> None:
    """Commit only a bounded failure fact after the business transaction rolled back."""
    try:
        row = (
            db.query(AiAction)
            .filter(
                AiAction.id == action_id,
                AiAction.auth_user_id == actor_id,
                AiAction.is_deleted.is_(False),
            )
            .with_for_update()
            .first()
        )
        if row is not None and row.status == "prepared":
            row.status = "failed"
            row.consumed_at = _utcnow()
            row.result_code = code
            row.result_summary = {
                "result": {},
                "error": {"code": code, "message": "操作未执行"},
            }
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()


@contextmanager
def _handler_transaction_boundary(db: Session):
    """Keep a fixed handler inside the action service's atomic transaction."""
    original_commit = db.commit
    original_rollback = db.rollback

    def reject_transaction_control() -> None:
        raise AppError(
            "AI_ACTION_TRANSACTION_VIOLATION",
            "动作处理器不能自行提交或回滚事务",
            409,
        )

    db.commit = reject_transaction_control  # type: ignore[method-assign]
    db.rollback = reject_transaction_control  # type: ignore[method-assign]
    try:
        yield
    finally:
        db.commit = original_commit  # type: ignore[method-assign]
        db.rollback = original_rollback  # type: ignore[method-assign]


def confirm_action(
    db: Session,
    actor: AuthUser,
    action_id: str,
    confirmation_token: str,
) -> dict:
    """Lock, reauthorize, execute, audit, and commit one prepared action."""
    row = _locked_owned_action(db, actor, action_id)
    if row.status != "prepared":
        db.rollback()
        raise AppError("AI_ACTION_NOT_PREPARED", "智能体动作已失效或已处理", 409)
    if row.expires_at is None or row.expires_at <= _utcnow():
        row.status = "expired"
        row.consumed_at = _utcnow()
        row.result_code = "AI_ACTION_EXPIRED"
        row.result_summary = {
            "result": {},
            "error": {"code": "AI_ACTION_EXPIRED", "message": "操作未执行"},
        }
        db.commit()
        raise AppError("AI_ACTION_EXPIRED", "确认凭证已过期，请重新预览", 409)
    if not confirmation_token or not row.token_hash or not hmac.compare_digest(
        row.token_hash,
        _token_hash(str(confirmation_token)),
    ):
        db.rollback()
        raise AppError("AI_ACTION_TOKEN_INVALID", "确认凭证无效", 403)

    try:
        conversation = _owned_conversation(db, actor, row.conversation_id)
        if conversation.auth_user_id != row.auth_user_id:
            raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作归属校验失败", 403)
        active_actor = (
            db.query(AuthUser)
            .filter(
                AuthUser.id == actor.id,
                AuthUser.is_active.is_(True),
                AuthUser.is_deleted.is_(False),
            )
            .populate_existing()
            .first()
        )
        if active_actor is None:
            raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "当前账号已失效", 403)
        definition = _current_l3_definition(
            db,
            active_actor,
            row.capability_code,
            unavailable_code="AI_ACTION_REAUTHORIZATION_FAILED",
        )
        if row.risk_level != definition.risk.value:
            raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作安全级别已变化", 403)
        if not isinstance(row.normalized_payload, dict) or _digest(row.normalized_payload) != row.payload_digest:
            raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作参数摘要校验失败", 403)
        parsed = definition.input_model.model_validate(row.normalized_payload)
        authorize_record = getattr(definition.handler, "authorize_record", None)
        if not callable(authorize_record):
            raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作缺少记录级授权校验", 403)
        with _handler_transaction_boundary(db):
            authorize_record(db, active_actor, parsed)
            result = definition.handler(db, active_actor, parsed)
        if not isinstance(result, CapabilityResult) or result.status != "succeeded":
            raise AppError("AI_ACTION_RESULT_INVALID", "动作处理器未返回已提交结果", 409)
        result_data, result_message = _safe_result(result)
        entity_type = result_data.get("entity_type")
        entity_id = result_data.get("entity_id")
        if entity_type is not None and not isinstance(entity_type, str):
            raise AppError("AI_ACTION_RESULT_INVALID", "动作结果实体类型无效", 409)
        if entity_id is not None and not isinstance(entity_id, str):
            raise AppError("AI_ACTION_RESULT_INVALID", "动作结果实体标识无效", 409)

        row.status = "succeeded"
        row.consumed_at = _utcnow()
        row.result_code = result.status
        row.result_summary = {"result": result_data, "message": result_message}
        row.result_entity_type = entity_type
        row.result_entity_id = entity_id
        audit(
            db,
            "ai_action",
            row.id,
            "succeeded",
            active_actor,
            {
                "capability_code": row.capability_code,
                "risk_level": row.risk_level,
                "payload_digest": row.payload_digest,
                "result_code": result.status,
                "result_entity_type": entity_type,
                "result_entity_id": entity_id,
            },
        )
        db.commit()
        db.refresh(row)
        return _action_payload(row)
    except Exception as exc:
        db.rollback()
        if isinstance(exc, AppError):
            public_error = AppError(
                exc.code,
                "操作未执行，请检查当前权限和记录状态后重试",
                exc.status_code,
            )
            failure_code = exc.code
        else:
            public_error = AppError(
                "AI_ACTION_EXECUTION_FAILED",
                "操作未执行，请检查当前权限和记录状态后重试",
                409,
            )
            failure_code = public_error.code
        _persist_failed_action(db, actor.id, action_id, code=failure_code)
        raise public_error from None


def cancel_action(db: Session, actor: AuthUser, action_id: str) -> dict:
    """Cancel an owned prepared action without executing its domain handler."""
    try:
        row = _locked_owned_action(db, actor, action_id)
        if row.status != "prepared":
            raise AppError("AI_ACTION_NOT_PREPARED", "智能体动作已失效或已处理", 409)
        if row.expires_at is None or row.expires_at <= _utcnow():
            row.status = "expired"
            row.consumed_at = _utcnow()
            row.result_code = "AI_ACTION_EXPIRED"
            row.result_summary = {
                "result": {},
                "error": {"code": "AI_ACTION_EXPIRED", "message": "操作未执行"},
            }
            db.commit()
            raise AppError("AI_ACTION_EXPIRED", "确认凭证已过期，请重新预览", 409)
        row.status = "cancelled"
        row.consumed_at = _utcnow()
        row.result_code = "cancelled"
        row.result_summary = {"result": {}, "message": "操作已取消，未执行任何更改"}
        audit(
            db,
            "ai_action",
            row.id,
            "cancelled",
            actor,
            {
                "capability_code": row.capability_code,
                "risk_level": row.risk_level,
                "payload_digest": row.payload_digest,
            },
        )
        db.commit()
        db.refresh(row)
        return _action_payload(row)
    except AppError:
        if db.in_transaction():
            db.rollback()
        raise
    except Exception:
        db.rollback()
        raise AppError("AI_ACTION_CANCEL_FAILED", "操作未取消，请稍后重试", 409) from None
