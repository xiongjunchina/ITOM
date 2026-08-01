"""WA0 assistant persistence foundation remains additive and disabled by default."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import AuthUser, Ticket
from app.services.migrate import run_migrations
from app.services.permissions import MODULES, has_perm, user_permissions


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
        assert profile.enabled is False

        version = AiAgentProfileVersion(profile_id=profile.id, version=1)
        conversation = AiConversation(
            auth_user_id=admin.id,
            profile_id=profile.id,
        )
        db.add_all([version, conversation])
        db.flush()
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

        run_migrations(db)
        preserved = db.get(Ticket, ticket_id)
        assert preserved.ticket_code == "TK-WA0-PRESERVE"
        assert preserved.status == "new"
        assert preserved.request_data == {"source": "wa0-test"}


def test_only_admin_has_default_admin_ai_access(client):
    """Granting admin_ai to a default non-admin role must fail this authorization boundary."""
    assert ("admin_ai", "AI 智能体", "系统管理") in MODULES
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        requester = AuthUser(
            username="wa0-requester",
            password_hash="not-used-by-this-test",
            roles=["requester"],
        )
        db.add(requester)
        db.commit()

        assert has_perm(db, admin, "admin_ai", "view") is True
        assert "admin_ai" not in user_permissions(db, requester)
