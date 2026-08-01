"""WA0 web-agent persistence models.

These tables deliberately remain separate from Aily/MCP configuration and
audits.  They store only encrypted/redacted assistant metadata; domain writes
continue to use the existing ITOM services.
"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase, JsonCol


class AiProviderConfig(GlidBase):
    __tablename__ = "ai_provider_config"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    provider_type: Mapped[str] = mapped_column(String(32), index=True)
    api_base_url: Mapped[str | None] = mapped_column(String(300))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    temperature: Mapped[float | None] = mapped_column()
    capability_probe: Mapped[dict] = mapped_column(JsonCol, default=dict)
    probe_status: Mapped[str] = mapped_column(String(16), default="unverified", index=True)
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fallback_provider_id: Mapped[str | None] = mapped_column(ForeignKey("ai_provider_config.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class AiAgentProfile(GlidBase):
    __tablename__ = "ai_agent_profile"
    __table_args__ = (
        CheckConstraint("retention_days BETWEEN 0 AND 90", name="ck_ai_agent_profile_retention_days"),
    )

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(128))
    audience: Mapped[str] = mapped_column(String(32), index=True)
    default_provider_id: Mapped[str | None] = mapped_column(ForeignKey("ai_provider_config.id"), index=True)
    max_risk_level: Mapped[str] = mapped_column(String(2), default="L1")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")


class AiAgentProfileVersion(GlidBase):
    __tablename__ = "ai_agent_profile_version"
    __table_args__ = (UniqueConstraint("profile_id", "version"),)

    profile_id: Mapped[str] = mapped_column(ForeignKey("ai_agent_profile.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    system_prompt_zh: Mapped[str | None] = mapped_column(Text)
    system_prompt_en: Mapped[str | None] = mapped_column(Text)
    enabled_capabilities: Mapped[list] = mapped_column(JsonCol, default=list)
    knowledge_scope: Mapped[list] = mapped_column(JsonCol, default=list)
    config_snapshot: Mapped[dict] = mapped_column(JsonCol, default=dict)
    max_risk_level: Mapped[str] = mapped_column(String(2), default="L1")
    published_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiConversation(GlidBase):
    __tablename__ = "ai_conversation"

    auth_user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("ai_agent_profile.id"), index=True)
    profile_version_id: Mapped[str | None] = mapped_column(ForeignKey("ai_agent_profile_version.id"), index=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    page_context: Mapped[dict] = mapped_column(JsonCol, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiMessage(GlidBase):
    __tablename__ = "ai_message"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversation.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[dict] = mapped_column(JsonCol, default=dict)
    redacted_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="completed", index=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class AiAction(GlidBase):
    __tablename__ = "ai_action"
    __table_args__ = (UniqueConstraint("auth_user_id", "capability_code", "idempotency_key"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversation.id"), index=True)
    auth_user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("ai_message.id"), index=True)
    capability_code: Mapped[str] = mapped_column(String(96), index=True)
    risk_level: Mapped[str] = mapped_column(String(2))
    normalized_payload: Mapped[dict] = mapped_column(JsonCol, default=dict)
    payload_digest: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="prepared", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    result_code: Mapped[str | None] = mapped_column(String(64), index=True)
    result_summary: Mapped[dict | None] = mapped_column(JsonCol)
    result_entity_type: Mapped[str | None] = mapped_column(String(32))
    result_entity_id: Mapped[str | None] = mapped_column(String(26))


class AiProviderCall(GlidBase):
    __tablename__ = "ai_provider_call"

    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_provider_config.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("ai_conversation.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("ai_message.id"), index=True)
    profile_version_id: Mapped[str | None] = mapped_column(ForeignKey("ai_agent_profile_version.id"), index=True)
    model: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(32), default="chat", index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="completed", index=True)
    error_redacted: Mapped[dict | None] = mapped_column(JsonCol)
