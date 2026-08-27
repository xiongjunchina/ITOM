"""WA0 assistant persistence foundation remains additive and disabled by default."""

from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import AuthUser, Ticket
from app.services import migrate as migrate_service
from app.services.migrate import ensure_assistant_schema, run_migrations
from app.services.permissions import DEFAULT_MATRIX, MODULES, has_perm, user_permissions


def test_wa0_models_are_additive_disabled_by_default_and_idempotent(client):
    """Removing a model table/default/unique key must break this persistence contract."""
    from app.models import (
        AiAction,
        AiAgentProfile,
        AiAgentProfileVersion,
        AiConversation,
        AiMessage,
        AiProviderCall,
        AiProviderConfig,
    )

    assert {
        "ai_provider_config",
        "ai_agent_profile",
        "ai_agent_profile_version",
        "ai_conversation",
        "ai_message",
        "ai_action",
        "ai_provider_call",
    }.issubset(inspect(engine).get_table_names())

    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        provider = AiProviderConfig(
            code="wa0-primary",
            name="WA0 Primary",
            provider_type="openai_compatible",
        )
        profile = AiAgentProfile(code="wa0-requester", audience="requester")
        db.add_all([provider, profile])
        db.commit()
        assert provider.enabled is False
        assert provider.config_revision == 1
        assert profile.enabled is False
        assert profile.retention_days == 30

        version = AiAgentProfileVersion(profile_id=profile.id, version=1)
        conversation = AiConversation(
            auth_user_id=admin.id,
            profile_id=profile.id,
        )
        db.add_all([version, conversation])
        db.flush()
        assert version.config_snapshot == {}
        message = AiMessage(conversation_id=conversation.id, role="user", content={"text": "help"})
        db.add(message)
        db.flush()
        db.add(AiProviderCall(
            provider_id=provider.id,
            conversation_id=conversation.id,
            message_id=message.id,
            model="wa0-model",
            result_code="OK",
        ))
        db.add(AiAction(
            conversation_id=conversation.id,
            auth_user_id=admin.id,
            capability_code="ticket.read",
            risk_level="L1",
            payload_digest="a" * 64,
            idempotency_key="wa0-action-key",
        ))
        db.commit()

        db.add(AiAction(
            conversation_id=conversation.id,
            auth_user_id=admin.id,
            capability_code="ticket.read",
            risk_level="L1",
            payload_digest="b" * 64,
            idempotency_key="wa0-action-key",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_profile_retention_is_persisted_and_limited_to_zero_through_ninety_days(client):
    """Removing the 0–90 retention guard must allow an invalid profile policy to persist."""
    from app.models import AiAgentProfile

    with SessionLocal() as db:
        db.add_all([
            AiAgentProfile(code="wa0-retention-zero", audience="requester", retention_days=0),
            AiAgentProfile(code="wa0-retention-ninety", audience="requester", retention_days=90),
        ])
        db.commit()
        assert db.query(AiAgentProfile).filter_by(code="wa0-retention-zero").one().retention_days == 0
        assert db.query(AiAgentProfile).filter_by(code="wa0-retention-ninety").one().retention_days == 90

        for code, days in (("wa0-retention-negative", -1), ("wa0-retention-over", 91)):
            db.add(AiAgentProfile(code=code, audience="requester", retention_days=days))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()


def test_wa0_provider_profile_and_profile_version_unique_keys_reject_duplicates(client):
    """Removing any provider/profile/version unique key must permit a duplicate governance record."""
    from app.models import AiAgentProfile, AiAgentProfileVersion, AiProviderConfig

    with SessionLocal() as db:
        provider = AiProviderConfig(
            code="wa0-unique-provider", name="WA0 Unique Provider", provider_type="openai_compatible"
        )
        db.add(provider)
        db.commit()
        db.add(AiProviderConfig(
            code="wa0-unique-provider", name="Duplicate Provider", provider_type="openai_compatible"
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        profile = AiAgentProfile(code="wa0-unique-profile", audience="requester")
        db.add(profile)
        db.commit()
        db.add(AiAgentProfile(code="wa0-unique-profile", audience="requester"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(AiAgentProfileVersion(profile_id=profile.id, version=1))
        db.commit()
        db.add(AiAgentProfileVersion(profile_id=profile.id, version=1))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_wa0_migration_preserves_existing_ticket_on_sqlite(client):
    """A migration that rewrites an existing ticket's identity, status, or request data is a bug."""
    with SessionLocal() as db:
        service_item_id = db.execute(
            text("SELECT id FROM service_item WHERE is_deleted = false LIMIT 1")
        ).scalar_one()
        ticket = Ticket(
            ticket_code="TK-WA0-PRESERVE",
            title="WA0 migration preservation",
            ticket_type="service_request",
            priority="P3",
            description="The assistant schema must not alter this ticket.",
            service_item_id=service_item_id,
            request_data={"source": "wa0-test"},
            status="new",
        )
        db.add(ticket)
        db.commit()
        ticket_id = ticket.id

    with SessionLocal() as db:
        run_migrations(db)
        db.expire_all()
        preserved = db.get(Ticket, ticket_id)
        assert preserved.ticket_code == "TK-WA0-PRESERVE"
        assert preserved.status == "new"
        assert preserved.request_data == {"source": "wa0-test"}


class _CapturingPostgresSession:
    """Minimal PostgreSQL session boundary for testing generated additive DDL."""

    def __init__(self):
        self.statements: list[str] = []
        self.commits = 0
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self):
        return self._bind

    def execute(self, statement):
        self.statements.append(str(statement))

    def commit(self):
        self.commits += 1


def test_postgres_assistant_schema_repairs_partial_tables_using_additive_ddl(monkeypatch):
    """Removing a repair column/index or adding DML/DROP must violate additive schema repair."""
    session = _CapturingPostgresSession()
    monkeypatch.setattr(migrate_service, "_columns", lambda _db, _table: {"id"})

    ensure_assistant_schema(session)

    ddl = "\n".join(session.statements)
    assert "CREATE TABLE IF NOT EXISTS ai_provider_config" in ddl
    assert "ALTER TABLE ai_provider_config ADD COLUMN config_revision INTEGER NOT NULL DEFAULT 1" in ddl
    assert "ALTER TABLE ai_provider_config ADD COLUMN fallback_provider_id VARCHAR(26)" in ddl
    assert "ALTER TABLE ai_agent_profile ADD COLUMN default_provider_id VARCHAR(26)" in ddl
    assert "ALTER TABLE ai_agent_profile ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 30" in ddl
    assert (
        "ALTER TABLE ai_agent_profile_version ADD COLUMN config_snapshot "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    ) in ddl
    assert "ALTER TABLE ai_conversation ADD COLUMN profile_version_id VARCHAR(26)" in ddl
    assert "ALTER TABLE ai_conversation ADD COLUMN expires_at TIMESTAMP" in ddl
    assert "ALTER TABLE ai_action ADD COLUMN message_id VARCHAR(26)" in ddl
    assert "ALTER TABLE ai_action ADD COLUMN token_hash VARCHAR(64)" in ddl
    assert "ALTER TABLE ai_action ADD COLUMN idempotency_key VARCHAR(128)" in ddl
    assert "CREATE INDEX IF NOT EXISTS ix_ai_action_token_hash ON ai_action (token_hash)" in ddl
    assert "CREATE INDEX IF NOT EXISTS ix_ai_provider_call_profile_version_id" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_provider_config_code" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_agent_profile_code" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_agent_profile_version_profile_version" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_action_user_capability_idempotency" in ddl
    assert session.commits == 1
    assert not any(keyword in ddl.upper() for keyword in (" DROP ", " UPDATE ", " DELETE ", " INSERT "))


def test_only_admin_has_default_admin_ai_access(client):
    """Granting admin_ai to a default non-admin role must fail this authorization boundary."""
    assert ("admin_ai", "AI 智能体", "系统管理") in MODULES
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        assert has_perm(db, admin, "admin_ai", "view") is True
        expected_non_admin_roles = {"requester", "bdo", "auditor", "it_dev", "it_ops"}
        assert expected_non_admin_roles.issubset(DEFAULT_MATRIX)
        for role_code in DEFAULT_MATRIX:
            role_user = AuthUser(
                username=f"wa0-{role_code}",
                password_hash="not-used-by-this-test",
                roles=[role_code],
            )
            assert "admin_ai" not in user_permissions(db, role_user)
