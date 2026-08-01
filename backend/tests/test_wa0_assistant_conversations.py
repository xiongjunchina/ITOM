"""WA0 owned assistant-conversation boundary contracts."""

from datetime import datetime, timedelta, timezone
import json

from app.db import SessionLocal
from app.models import AiAction, AiAgentProfile, AiAgentProfileVersion, AiConversation, AiMessage
from app.routers.admin_ai import ProfileDraftUpdateIn
from app.services import assistant_conversations
import pytest
from pydantic import ValidationError


PAGE_CONTEXT = {"route": "/itsm/tickets", "page_type": "ticket_list"}
SAFE_GLID = "01J9E9Q4R2M3N4P5Q6R7S8T9VW"


def _create_user(client, admin_headers, username: str) -> dict:
    person = client.post("/api/members", json={"name": username}, headers=admin_headers).json()["data"]
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": ["requester"], "person_id": person["id"]},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    logged_in = client.post("/api/auth/login", json={"username": username, "password": "pass123"})
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['data']['token']}"}


def _publish_requester_profile(*, retention_days: int = 30) -> None:
    with SessionLocal() as db:
        profile = AiAgentProfile(
            code=f"wa0-conversation-{db.query(AiAgentProfile).count()}",
            name="WA0 conversations",
            audience="requester",
            enabled=True,
            status="published",
            max_risk_level="L1",
            retention_days=retention_days,
        )
        db.add(profile)
        db.flush()
        db.add(AiAgentProfileVersion(
            profile_id=profile.id,
            version=1,
            status="published",
            enabled_capabilities=[],
            knowledge_scope=[],
            max_risk_level="L1",
        ))
        db.commit()


def test_create_rejects_client_authority_fields_before_any_conversation_is_created(client, admin_headers):
    """Accepting client roles would let a browser supply authority facts the server must own."""
    response = client.post(
        "/api/assistant/conversations",
        headers=admin_headers,
        json={
            "language": "zh-CN",
            "page_context": {
                "route": "/itsm/tickets",
                "roles": ["admin"],
            },
        },
    )

    assert response.status_code == 422, response.text


def test_conversation_routes_keep_every_read_and_archive_scoped_to_the_owner(client, admin_headers):
    """Dropping the auth_user_id predicate would expose another user's transcript or archive state."""
    _publish_requester_profile()
    alice_headers = _create_user(client, admin_headers, "wa0_conv_alice")
    bob_headers = _create_user(client, admin_headers, "wa0_conv_bob")
    alice = client.post(
        "/api/assistant/conversations",
        headers=alice_headers,
        json={"language": "zh-CN", "page_context": PAGE_CONTEXT},
    )
    bob = client.post(
        "/api/assistant/conversations",
        headers=bob_headers,
        json={"language": "en", "page_context": PAGE_CONTEXT},
    )
    assert alice.status_code == 200, alice.text
    assert bob.status_code == 200, bob.text
    alice_id = alice.json()["data"]["id"]
    bob_id = bob.json()["data"]["id"]

    own_list = client.get("/api/assistant/conversations", headers=alice_headers)
    assert own_list.status_code == 200, own_list.text
    assert own_list.json()["total"] == 1
    assert [row["id"] for row in own_list.json()["data"]] == [alice_id]

    for response in (
        client.get(f"/api/assistant/conversations/{bob_id}", headers=alice_headers),
        client.post(f"/api/assistant/conversations/{bob_id}/archive", headers=alice_headers),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "AI_CONVERSATION_NOT_FOUND"

    archive = client.post(f"/api/assistant/conversations/{alice_id}/archive", headers=alice_headers)
    assert archive.status_code == 200, archive.text
    assert client.get("/api/assistant/conversations", headers=alice_headers).json()["data"] == []
    archived = client.get("/api/assistant/conversations?include_archived=true", headers=alice_headers)
    assert [row["id"] for row in archived.json()["data"]] == [alice_id]


@pytest.mark.parametrize("unsafe_field", ["roles", "permissions", "dom", "html", "prompt", "cookies", "headers"])
def test_page_context_rejects_browser_authority_and_document_payloads(client, admin_headers, unsafe_field):
    """Relaxing the PageContext allowlist would admit untrusted authority or whole-document content."""
    response = client.post(
        "/api/assistant/conversations",
        headers=admin_headers,
        json={
            "page_context": {"route": "/itsm/tickets", unsafe_field: "untrusted"},
        },
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("unsafe_route", [
    "https://outside.example.test/records",
    "//outside.example.test/records",
    "/itsm/../admin/users",
    "/itsm//tickets",
    "/%2e%2e/admin/users",
    "/%2f%2fevil.example.test/records",
])
def test_page_context_rejects_external_and_traversal_like_routes(client, admin_headers, unsafe_route):
    """Treating a URL-looking or traversal-like path as a local route enables context redirection."""
    response = client.post(
        "/api/assistant/conversations",
        headers=admin_headers,
        json={"page_context": {"route": unsafe_route}},
    )

    assert response.status_code == 422, response.text


def test_bootstrap_is_a_safe_allowlist_and_disabled_profile_fails_closed(client, admin_headers):
    """Adding policy details or treating an unpublished profile as enabled would leak authority or bypass governance."""
    with SessionLocal() as db:
        for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
            profile.enabled = False
        db.commit()
    headers = _create_user(client, admin_headers, "wa0_bootstrap")
    unavailable = client.get("/api/assistant/bootstrap", headers=headers)
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json()["data"] == {
        "enabled": False,
        "profile": None,
        "max_risk": None,
        "suggested_prompts": [],
        "retention_days": None,
        "fallback_available": True,
    }

    with SessionLocal() as db:
        draft = AiAgentProfile(
            code=f"wa0-unpublished-{db.query(AiAgentProfile).count()}",
            audience="requester",
            enabled=True,
            status="draft",
        )
        db.add(draft)
        db.flush()
        db.add(AiAgentProfileVersion(profile_id=draft.id, version=1, status="draft"))
        db.commit()
    unpublished = client.get("/api/assistant/bootstrap", headers=headers)
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["data"]["enabled"] is False

    _publish_requester_profile(retention_days=30)
    enabled = client.get("/api/assistant/bootstrap", headers=headers)
    assert enabled.status_code == 200, enabled.text
    data = enabled.json()["data"]
    assert set(data) == {"enabled", "profile", "max_risk", "suggested_prompts", "retention_days", "fallback_available"}
    assert data["enabled"] is True
    assert data["profile"]["version"] == 1
    assert data["max_risk"] == "L1"
    assert data["retention_days"] == 30
    assert data["fallback_available"] is True


def test_inactive_account_cannot_bootstrap_or_create_a_conversation(client, admin_headers):
    """Trusting an earlier login after account deactivation would bypass the database-loaded identity gate."""
    headers = _create_user(client, admin_headers, "wa0_inactive_conversation")
    with SessionLocal() as db:
        from app.models import AuthUser

        db.query(AuthUser).filter(AuthUser.username == "wa0_inactive_conversation").one().is_active = False
        db.commit()
    for response in (
        client.get("/api/assistant/bootstrap", headers=headers),
        client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT}),
    ):
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("selected_ids", [
    ["not-a-glid"],
    [SAFE_GLID] * 21,
])
def test_page_context_rejects_invalid_or_over_limit_selected_ids(client, admin_headers, selected_ids):
    """Accepting invalid IDs or more than twenty selections makes page context an unbounded data channel."""
    response = client.post(
        "/api/assistant/conversations",
        headers=admin_headers,
        json={"page_context": {"route": "/itsm/tickets", "selected_ids": selected_ids}},
    )

    assert response.status_code == 422, response.text


def test_retention_zero_never_persists_ordinary_message_bodies_on_success_or_failure(client, admin_headers):
    """Persisting either a completed or failed ordinary message at retention zero violates the no-transcript policy."""
    with SessionLocal() as db:
        for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
            profile.enabled = False
        db.commit()
    _publish_requester_profile(retention_days=0)
    headers = _create_user(client, admin_headers, "wa0_retention_zero")
    created = client.post(
        "/api/assistant/conversations",
        headers=headers,
        json={"page_context": PAGE_CONTEXT},
    )
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        persist = getattr(assistant_conversations, "persist_ordinary_message", None)
        assert callable(persist), "conversation service must own ordinary-message retention enforcement"
        assert persist(
            db,
            conversation,
            role="user",
            content={"text": "completed secret", "access_token": "completed-token-raw"},
            redacted_text="completed secret",
        ) is None
        assert persist(
            db,
            conversation,
            role="assistant",
            content={"text": "failed secret", "authorization": "failed-token-raw"},
            redacted_text="failed secret",
            status="failed",
        ) is None
        db.commit()
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation.id).count() == 0


@pytest.mark.parametrize("retention_days", [1, 30, 90])
def test_positive_retention_persists_only_redacted_content_with_stable_expiry_and_keeps_action_audit(
    client, admin_headers, retention_days
):
    """Dropping expiry, redaction, or action preservation breaks the conversation privacy and audit contract."""
    with SessionLocal() as db:
        for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
            profile.enabled = False
        db.commit()
    _publish_requester_profile(retention_days=retention_days)
    headers = _create_user(client, admin_headers, f"wa0_retention_{retention_days}")
    created = client.post(
        "/api/assistant/conversations",
        headers=headers,
        json={"page_context": PAGE_CONTEXT},
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["data"]["id"]

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        assert conversation.expires_at is not None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert timedelta(days=retention_days) - timedelta(seconds=3) <= conversation.expires_at - now <= timedelta(days=retention_days) + timedelta(seconds=3)
        stored = assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="user",
            content={"text": "need help", "access_token": "persisted-token-raw"},
            redacted_text="Bearer persisted-bearer-raw",
        )
        assert stored is not None
        db.add(AiAction(
            conversation_id=conversation.id,
            auth_user_id=conversation.auth_user_id,
            capability_code="knowledge.search",
            risk_level="L1",
            payload_digest="a" * 64,
            idempotency_key=f"wa0-action-{retention_days}",
        ))
        db.commit()
        refreshed = db.get(AiConversation, conversation_id)
        message = db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).one()
        rendered = json.dumps({"content": message.content, "text": message.redacted_text})
        assert "persisted-token-raw" not in rendered
        assert "persisted-bearer-raw" not in rendered
        assert message.content["access_token"] == "[REDACTED]"
        expiry = refreshed.expires_at

    archived = client.post(f"/api/assistant/conversations/{conversation_id}/archive", headers=headers)
    assert archived.status_code == 200, archived.text
    with SessionLocal() as db:
        assert db.get(AiConversation, conversation_id).expires_at == expiry
        assert db.query(AiAction).filter(AiAction.conversation_id == conversation_id).count() == 1


def test_retention_configuration_accepts_zero_one_thirty_ninety_and_rejects_outside_bounds():
    """Relaxing the admin profile boundary would allow a conversation policy outside the authoritative 0–90 range."""
    expected_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for days in (0, 1, 30, 90):
        assert ProfileDraftUpdateIn.model_validate({
            "expected_updated_at": expected_updated_at,
            "retention_days": days,
        }).retention_days == days
    for days in (-1, 91):
        with pytest.raises(ValidationError):
            ProfileDraftUpdateIn.model_validate({
                "expected_updated_at": expected_updated_at,
                "retention_days": days,
            })


def test_owner_pagination_has_stable_order_and_never_counts_other_users(client, admin_headers):
    """Removing owner filtering or tie-breaking order leaks counts or causes list pages to shift unpredictably."""
    with SessionLocal() as db:
        for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
            profile.enabled = False
        db.commit()
    _publish_requester_profile(retention_days=30)
    alice_headers = _create_user(client, admin_headers, "wa0_page_alice")
    bob_headers = _create_user(client, admin_headers, "wa0_page_bob")
    alice_ids = [
        client.post("/api/assistant/conversations", headers=alice_headers, json={"page_context": PAGE_CONTEXT}).json()["data"]["id"]
        for _ in range(3)
    ]
    for _ in range(2):
        response = client.post("/api/assistant/conversations", headers=bob_headers, json={"page_context": PAGE_CONTEXT})
        assert response.status_code == 200, response.text

    first = client.get("/api/assistant/conversations?page=1&page_size=2", headers=alice_headers)
    repeat = client.get("/api/assistant/conversations?page=1&page_size=2", headers=alice_headers)
    second = client.get("/api/assistant/conversations?page=2&page_size=2", headers=alice_headers)
    assert first.status_code == repeat.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 3
    first_ids = [row["id"] for row in first.json()["data"]]
    assert first_ids == [row["id"] for row in repeat.json()["data"]]
    second_ids = [row["id"] for row in second.json()["data"]]
    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert not set(first_ids).intersection(second_ids)
    assert set(first_ids + second_ids) == set(alice_ids)
