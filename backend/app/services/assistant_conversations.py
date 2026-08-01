"""Owner-scoped persistence for the web assistant's conversation lifecycle."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.assistant.policy import capability_context_for_user
from app.assistant.redaction import redact_for_message
from app.assistant.types import AssistantChannel, RiskLevel
from app.core.errors import AppError
from app.models import AiAgentProfile, AiAgentProfileVersion, AiConversation, AiMessage, AuthUser
from app.services import assistant_config, it_document_guide


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _active_profile(
    db: Session,
    actor: AuthUser,
    *,
    lock_runtime_profile: bool = False,
) -> tuple[AiAgentProfile, AiAgentProfileVersion, dict]:
    """Resolve one current, published web profile from database-backed identity."""
    if lock_runtime_profile:
        # Match Task 4 publication/withdrawal lock order: the shared provider
        # governance lock is acquired before the exact profile row.  All
        # runtime reads below therefore occur after publication cannot overtake
        # this transaction on PostgreSQL.
        assistant_config.lock_profile_runtime_governance(db)
    context = capability_context_for_user(db, actor.id, AssistantChannel.WEB, RiskLevel.L3)
    if context is None:
        raise AppError("AI_ASSISTANT_UNAVAILABLE", "当前账号没有可用的智能体档案", 403)
    profiles_query = (
        db.query(AiAgentProfile)
        .filter(
            AiAgentProfile.audience == context.audience,
            AiAgentProfile.enabled.is_(True),
            AiAgentProfile.status == "published",
            AiAgentProfile.is_deleted.is_(False),
        )
    )
    if lock_runtime_profile:
        profiles_query = profiles_query.with_for_update().populate_existing()
    profiles = profiles_query.all()
    if len(profiles) != 1:
        raise AppError("AI_ASSISTANT_UNAVAILABLE", "当前账号没有可用的智能体档案", 403)
    profile = profiles[0]
    runtime = assistant_config.runtime_published_profile(db, profile, audience=context.audience)
    if runtime is None:
        raise AppError("AI_ASSISTANT_UNAVAILABLE", "当前账号没有可用的智能体档案", 403)
    version, config = runtime
    return profile, version, config


def bootstrap_payload(db: Session, actor: AuthUser) -> dict:
    """Return the intentionally small browser bootstrap contract.

    An unavailable profile is reported as disabled so the client can use the
    deterministic fallback without learning why governance withheld access.
    """
    fallback_available = it_document_guide.authenticated_guide_available(db, actor)
    try:
        profile, version, config = _active_profile(db, actor)
    except AppError:
        return {
            "enabled": False,
            "profile": None,
            "max_risk": None,
            "suggested_prompts": [],
            "retention_days": None,
            "fallback_available": fallback_available,
        }
    return {
        "enabled": True,
        "profile": {"code": profile.code, "version": version.version},
        "max_risk": version.max_risk_level,
        "suggested_prompts": [],
        "retention_days": config["retention_days"],
        "fallback_available": fallback_available,
    }


def _conversation_or_404(db: Session, actor: AuthUser, conversation_id: str) -> AiConversation:
    row = (
        db.query(AiConversation)
        .filter(
            AiConversation.id == conversation_id,
            AiConversation.auth_user_id == actor.id,
            AiConversation.is_deleted.is_(False),
        )
        .first()
    )
    if row is None:
        raise AppError("AI_CONVERSATION_NOT_FOUND", "智能体会话不存在", 404)
    return row


def conversation_payload(row: AiConversation) -> dict:
    return {
        "id": row.id,
        "language": row.language,
        "page_context": row.page_context,
        "status": row.status,
        "expires_at": row.expires_at,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
    }


def create_conversation(
    db: Session,
    actor: AuthUser,
    *,
    language: str,
    page_context: dict,
) -> dict:
    try:
        profile, version, config = _active_profile(db, actor, lock_runtime_profile=True)
        now = _utcnow()
        row = AiConversation(
            auth_user_id=actor.id,
            profile_id=profile.id,
            profile_version_id=version.id,
            language=language,
            page_context=page_context,
            expires_at=now + timedelta(days=config["retention_days"]) if config["retention_days"] else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return conversation_payload(row)
    except Exception:
        db.rollback()
        raise


def persist_ordinary_message(
    db: Session,
    conversation: AiConversation,
    *,
    role: str,
    content: dict,
    redacted_text: str | None,
    status: str = "completed",
) -> AiMessage | None:
    """Stage an already-redacted ordinary message only when policy permits it.

    The caller owns the transaction.  This allows normal and exception paths
    to use the same retention guard before they commit any ordinary body.
    """
    if role not in {"user", "assistant"}:
        raise ValueError("ordinary assistant messages must be user or assistant roles")
    version = db.get(AiAgentProfileVersion, conversation.profile_version_id)
    if version is None or version.profile_id != conversation.profile_id:
        return None
    retention_days = assistant_config.immutable_retention_days(version)
    if retention_days is None or retention_days == 0:
        return None

    # Publishing acquires the same profile-row lock, so a valid active runtime
    # profile cannot be republished/withdrawn between this check and the
    # caller's eventual commit of the message body.
    profile = (
        db.query(AiAgentProfile)
        .filter(AiAgentProfile.id == conversation.profile_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    context = capability_context_for_user(
        db, conversation.auth_user_id, AssistantChannel.WEB, RiskLevel.L3
    )
    if (
        profile is None
        or context is None
        or assistant_config.runtime_published_profile(db, profile, audience=context.audience) is None
    ):
        return None
    row = AiMessage(
        conversation_id=conversation.id,
        role=role,
        content=redact_for_message(content),
        redacted_text=redact_for_message(redacted_text) if redacted_text is not None else None,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def list_own_conversations(
    db: Session,
    actor: AuthUser,
    *,
    include_archived: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    query = db.query(AiConversation).filter(
        AiConversation.auth_user_id == actor.id,
        AiConversation.is_deleted.is_(False),
    )
    if not include_archived:
        query = query.filter(AiConversation.status == "active")
    total = query.count()
    rows = (
        query.order_by(AiConversation.created_at.desc(), AiConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [conversation_payload(row) for row in rows], total


def get_own_conversation(db: Session, actor: AuthUser, conversation_id: str) -> dict:
    return conversation_payload(_conversation_or_404(db, actor, conversation_id))


def archive_own_conversation(db: Session, actor: AuthUser, conversation_id: str) -> dict:
    row = _conversation_or_404(db, actor, conversation_id)
    if row.status != "archived":
        row.status = "archived"
        row.archived_at = _utcnow()
        db.commit()
        db.refresh(row)
    return conversation_payload(row)
