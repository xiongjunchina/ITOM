"""Server-owned WA0 L3 preview, confirmation, and idempotency boundary."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from contextlib import contextmanager

from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.policy import capabilities_for_user
from app.assistant.redaction import redact_for_message
from app.assistant.registry import registry
from app.assistant.types import (
    ActionActorContext,
    ActionUnitOfWork,
    AssistantChannel,
    CapabilityDefinition,
    CapabilityResult,
    ReadOnlyActionData,
    RiskLevel,
)
from app.core.errors import AppError
from app.core.config import settings
from app.db import SessionLocal
from app.models import AiAction, AiConversation, AuthUser
from app.services import assistant_conversations
from app.services.audit import audit
from app.services.service_forms import canonical_json


_TOKEN_TTL_MINUTES = 10
_IDEMPOTENCY_CONSTRAINT = "uq_ai_action_user_capability_idempotency"


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
    lock: bool = False,
) -> AiConversation:
    return assistant_conversations._owned_conversation_row(
        db,
        actor,
        conversation_id,
        require_active=require_active,
        lock=lock,
    )


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
        if not isinstance(normalized, dict) or not isinstance(redacted, dict) or redacted != normalized:
            raise ValueError("sensitive action payload")
        return normalized, parsed
    except (ValidationError, ValueError):
        raise AppError("AI_ACTION_PAYLOAD_INVALID", "动作参数无效")


def _set_preview_transaction_read_only(db: Session) -> None:
    """Apply PostgreSQL's transaction-level read-only boundary before preview access."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(
            text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
            {"timeout_ms": str(max(1, int(settings.ai_assistant_tool_statement_timeout_ms)))},
        )


@contextmanager
def _preview_transaction_boundary(db: Session):
    """Keep preview rollback-only even if a handler mutates attached ORM state."""
    try:
        yield
        if db.new or db.dirty or db.deleted:
            raise AppError(
                "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION",
                "动作预览不得修改数据或控制事务",
                409,
            )
    finally:
        pass


def _uniform_preview_unavailable() -> AppError:
    return AppError(
        "AI_ACTION_PREVIEW_UNAVAILABLE",
        "当前记录不可用于该动作预览",
        404,
    )


def _preview_result(
    handler: object,
    preview_db: ReadOnlyActionData,
    actor: ActionActorContext,
    data: BaseModel,
) -> CapabilityResult:
    authorize_preview = getattr(handler, "authorize_preview", None)
    preview = getattr(handler, "preview", None)
    authorize_record = getattr(handler, "authorize_record", None)
    if not all(callable(item) for item in (authorize_preview, preview, authorize_record)):
        raise _uniform_preview_unavailable()
    try:
        authorize_preview(preview_db, actor, data)
        result = preview(preview_db, actor, data)
    except AppError as exc:
        if exc.code == "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION":
            raise
        raise _uniform_preview_unavailable() from None
    except Exception:
        raise _uniform_preview_unavailable() from None
    if not isinstance(result, CapabilityResult) or result.status != "prepared":
        raise AppError("AI_ACTION_PREVIEW_INVALID", "服务端预览结果无效", 409)
    return result


def _run_rollback_only_preview(handler: object, actor: AuthUser, data: BaseModel) -> CapabilityResult:
    preview_db = SessionLocal()
    try:
        _set_preview_transaction_read_only(preview_db)
        preview_actor = preview_db.get(AuthUser, actor.id)
        if preview_actor is None or preview_actor.is_deleted or not preview_actor.is_active:
            raise _uniform_preview_unavailable()
        with _preview_transaction_boundary(preview_db):
            return _preview_result(
                handler,
                ReadOnlyActionData(preview_db),
                ActionActorContext.from_auth_user(preview_actor),
                data,
            )
    finally:
        try:
            preview_db.rollback()
        finally:
            preview_db.close()


def _is_named_idempotency_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _IDEMPOTENCY_CONSTRAINT


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


def _action_candidate(
    db: Session,
    actor: AuthUser,
    capability_code: str,
    idempotency_key: str,
) -> AiAction | None:
    return (
        db.query(AiAction)
        .filter(
            AiAction.auth_user_id == actor.id,
            AiAction.capability_code == capability_code,
            AiAction.idempotency_key == idempotency_key,
            AiAction.is_deleted.is_(False),
        )
        .first()
    )


def _revalidate_existing_action_conversation(
    row: AiAction,
    conversation: AiConversation,
    expected_binding: tuple[str | None, str | None, str | None],
) -> None:
    if row.conversation_id != conversation.id:
        raise AppError(
            "AI_ACTION_IDEMPOTENCY_CONFLICT",
            "同一幂等键不能用于不同动作内容",
            409,
        )
    if (
        conversation.archived_at is not None
        or (
            conversation.auth_user_id,
            conversation.profile_id,
            conversation.profile_version_id,
        ) != expected_binding
    ):
        raise AppError("AI_CONVERSATION_NOT_FOUND", "智能体会话不存在", 404)


def _lock_existing_action_first(
    db: Session,
    actor: AuthUser,
    *,
    conversation_id: str,
    capability_code: str,
    idempotency_key: str,
    payload_digest: str,
    expected_binding: tuple[str | None, str | None, str | None],
) -> AiAction:
    row = (
        db.query(AiAction)
        .filter(
            AiAction.auth_user_id == actor.id,
            AiAction.capability_code == capability_code,
            AiAction.idempotency_key == idempotency_key,
            AiAction.is_deleted.is_(False),
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        raise AppError(
            "AI_ACTION_IDEMPOTENCY_RECOVERY_FAILED",
            "动作准备状态已变化，请安全重试",
            409,
        )
    conversation = _owned_conversation(
        db,
        actor,
        conversation_id,
        require_active=True,
        lock=True,
    )
    _revalidate_existing_action_conversation(row, conversation, expected_binding)
    if row.payload_digest != payload_digest:
        raise AppError(
            "AI_ACTION_IDEMPOTENCY_CONFLICT",
            "同一幂等键不能用于不同动作内容",
            409,
        )
    return row


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
        expected_conversation_binding = (
            conversation.auth_user_id,
            conversation.profile_id,
            conversation.profile_version_id,
        )
        definition = _current_l3_definition(
            db,
            actor,
            capability_code,
            unavailable_code="AI_ACTION_CAPABILITY_UNAVAILABLE",
        )
        key = _idempotency_key(idempotency_key)
        normalized, parsed = _normalized_payload(definition, payload)
        payload_digest = _digest(normalized)
        preview_result = _run_rollback_only_preview(definition.handler, actor, parsed)
        preview, preview_message = _safe_result(preview_result)
        if _action_candidate(db, actor, definition.code, key) is not None:
            existing = _lock_existing_action_first(
                db,
                actor,
                conversation_id=conversation_id,
                capability_code=definition.code,
                idempotency_key=key,
                payload_digest=payload_digest,
                expected_binding=expected_conversation_binding,
            )
            payload_body = _action_payload(existing)
            db.rollback()
            return payload_body
        locked_conversation = _owned_conversation(
            db,
            actor,
            conversation_id,
            require_active=True,
            lock=True,
        )
        if (
            locked_conversation.archived_at is not None
            or (
                locked_conversation.auth_user_id,
                locked_conversation.profile_id,
                locked_conversation.profile_version_id,
            )
            != expected_conversation_binding
        ):
            raise AppError("AI_CONVERSATION_NOT_FOUND", "智能体会话不存在", 404)
        if _action_candidate(db, actor, definition.code, key) is not None:
            db.rollback()
            existing = _lock_existing_action_first(
                db,
                actor,
                conversation_id=conversation_id,
                capability_code=definition.code,
                idempotency_key=key,
                payload_digest=payload_digest,
                expected_binding=expected_conversation_binding,
            )
            payload_body = _action_payload(existing)
            db.rollback()
            return payload_body
        raw_token = secrets.token_urlsafe(32)
        row = AiAction(
            conversation_id=locked_conversation.id,
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
        try:
            db.flush()
        except IntegrityError as exc:
            if not _is_named_idempotency_conflict(exc):
                raise
            db.rollback()
            winner = _lock_existing_action_first(
                db,
                actor,
                conversation_id=conversation_id,
                capability_code=definition.code,
                idempotency_key=key,
                payload_digest=payload_digest,
                expected_binding=expected_conversation_binding,
            )
            payload_body = _action_payload(winner)
            db.rollback()
            return payload_body
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


@contextmanager
def _handler_transaction_boundary(db: Session):
    """Keep a fixed handler inside the action service's atomic transaction."""
    original_commit = db.commit
    original_rollback = db.rollback
    original_flush = db.flush

    def reject_transaction_control(*_args, **_kwargs) -> None:
        raise AppError(
            "AI_ACTION_TRANSACTION_VIOLATION",
            "动作处理器不能自行提交或回滚事务",
            409,
        )

    db.commit = reject_transaction_control  # type: ignore[method-assign]
    db.rollback = reject_transaction_control  # type: ignore[method-assign]
    db.flush = reject_transaction_control  # type: ignore[method-assign]
    try:
        yield
    finally:
        db.commit = original_commit  # type: ignore[method-assign]
        db.rollback = original_rollback  # type: ignore[method-assign]
        db.flush = original_flush  # type: ignore[method-assign]


def _reauthorized_runtime(
    db: Session,
    actor: AuthUser,
    row: AiAction,
    conversation: AiConversation,
) -> tuple[AuthUser, ActionActorContext, CapabilityDefinition, BaseModel]:
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
    try:
        profile, version, _config = assistant_conversations._active_profile(
            db,
            active_actor,
            lock_runtime_profile=True,
        )
    except AppError:
        raise AppError(
            "AI_ACTION_REAUTHORIZATION_FAILED",
            "当前智能体运行档案已失效",
            403,
        ) from None
    if (
        conversation.auth_user_id != row.auth_user_id
        or conversation.profile_id != profile.id
        or conversation.profile_version_id != version.id
    ):
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作运行档案绑定已变化", 403)
    definition = _current_l3_definition(
        db,
        active_actor,
        row.capability_code,
        unavailable_code="AI_ACTION_REAUTHORIZATION_FAILED",
    )
    if row.capability_code not in set(version.enabled_capabilities or []):
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作能力已从运行档案撤回", 403)
    if row.risk_level != definition.risk.value:
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作安全级别已变化", 403)
    if not isinstance(row.normalized_payload, dict) or _digest(row.normalized_payload) != row.payload_digest:
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作参数摘要校验失败", 403)
    try:
        parsed = definition.input_model.model_validate(row.normalized_payload)
    except ValidationError:
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作参数已失效", 403) from None
    if not callable(getattr(definition.handler, "authorize_record", None)):
        raise AppError("AI_ACTION_REAUTHORIZATION_FAILED", "动作缺少记录级授权校验", 403)
    return active_actor, ActionActorContext.from_auth_user(active_actor), definition, parsed


def _public_execution_error(exc: Exception) -> tuple[AppError, str]:
    if isinstance(exc, AppError):
        return (
            AppError(
                exc.code,
                "操作未执行，请检查当前权限和记录状态后重试",
                exc.status_code,
            ),
            exc.code,
        )
    return (
        AppError(
            "AI_ACTION_EXECUTION_FAILED",
            "操作未执行，请检查当前权限和记录状态后重试",
            409,
        ),
        "AI_ACTION_EXECUTION_FAILED",
    )


def _commit_locked_failure(db: Session, row: AiAction, code: str) -> None:
    """Persist failure on the already locked row without releasing the outer lock."""
    row.status = "failed"
    row.consumed_at = _utcnow()
    row.result_code = code
    row.result_summary = {
        "result": {},
        "error": {"code": code, "message": "操作未执行"},
    }
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        finally:
            raise AppError(
                "AI_ACTION_FAILURE_PERSISTENCE_FAILED",
                "操作未执行，失败状态未能持久化，请稍后重试",
                503,
            ) from None


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
        conversation = _owned_conversation(
            db,
            actor,
            row.conversation_id,
            require_active=True,
            lock=True,
        )
        active_actor_row, active_actor, definition, parsed = _reauthorized_runtime(
            db,
            actor,
            row,
            conversation,
        )
        uow = ActionUnitOfWork(db)
        with db.begin_nested():
            with _handler_transaction_boundary(db):
                definition.handler.authorize_record(uow, active_actor, parsed)
                result = definition.handler(uow, active_actor, parsed)
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
                active_actor_row,
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
        if isinstance(exc, AppError) and exc.code == "AI_ACTION_FAILURE_PERSISTENCE_FAILED":
            raise
        public_error, failure_code = _public_execution_error(exc)
        _commit_locked_failure(db, row, failure_code)
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
