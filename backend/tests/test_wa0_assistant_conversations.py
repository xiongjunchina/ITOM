"""WA0 owned assistant-conversation boundary contracts."""

from datetime import datetime, timedelta, timezone
import json

from app.core.errors import AppError
from app.db import SessionLocal
from app.models import (
    AiAction,
    AiAgentProfile,
    AiAgentProfileVersion,
    AiConversation,
    AiMessage,
    AiProviderConfig,
    AuthUser,
)
from app.routers.admin_ai import ProfileDraftUpdateIn
from app.services import assistant_config, assistant_conversations, it_document_guide
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


def _published_snapshot(profile: AiAgentProfile, *, retention_days: int) -> dict:
    return {
        "schema_version": 1,
        "name": profile.name,
        "default_provider_id": profile.default_provider_id,
        "retention_days": retention_days,
        "enabled": True,
    }


def _usable_provider(db) -> AiProviderConfig:
    provider = AiProviderConfig(
        code=f"wa0-conversation-provider-{db.query(AiProviderConfig).count()}",
        name="WA0 conversation provider",
        provider_type="openai_compatible",
        api_base_url="https://provider.example.test/v1",
        model="wa0-test",
        enabled=True,
        probe_status="success",
        last_probed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        capability_probe={
            "authentication": True,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_schema": True,
        },
    )
    db.add(provider)
    db.flush()
    return provider


def _publish_requester_profile(*, retention_days: int = 30) -> tuple[str, str]:
    with SessionLocal() as db:
        provider = _usable_provider(db)
        profile = AiAgentProfile(
            code=f"wa0-conversation-{db.query(AiAgentProfile).count()}",
            name="WA0 conversations",
            audience="requester",
            enabled=True,
            status="published",
            max_risk_level="L1",
            retention_days=retention_days,
            default_provider_id=provider.id,
        )
        db.add(profile)
        db.flush()
        version = AiAgentProfileVersion(
            profile_id=profile.id,
            version=1,
            status="published",
            system_prompt_zh="你是 ITOM 助手。",
            system_prompt_en="You are an ITOM assistant.",
            enabled_capabilities=[],
            knowledge_scope=["public"],
            config_snapshot=_published_snapshot(profile, retention_days=retention_days),
            max_risk_level="L1",
            published_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(version)
        db.commit()
        return profile.id, version.id


def _publish_next_version(db, profile: AiAgentProfile, *, retention_days: int) -> AiAgentProfileVersion:
    profile.retention_days = retention_days
    profile.enabled = True
    profile.status = "published"
    version = AiAgentProfileVersion(
        profile_id=profile.id,
        version=2,
        status="published",
        system_prompt_zh="你是 ITOM 助手。",
        system_prompt_en="You are an ITOM assistant.",
        enabled_capabilities=[],
        knowledge_scope=["public"],
        config_snapshot=_published_snapshot(profile, retention_days=retention_days),
        max_risk_level="L1",
        published_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(version)
    db.commit()
    return version


def _disable_other_requester_profiles(db, active_profile_id: str | None = None) -> None:
    for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
        if profile.id != active_profile_id:
            profile.enabled = False
    db.commit()


def _publish_requester_through_task4(db, actor: AuthUser, *, retention_days: int = 30) -> str:
    """Publish the requester profile through the real Task 4 draft/publish services."""
    provider = _usable_provider(db)
    draft = assistant_config.get_profile_draft(db, "requester", actor)
    updated = assistant_config.update_profile_draft(
        db,
        "requester",
        {
            "name": "Task 4 requester",
            "default_provider_id": provider.id,
            "retention_days": retention_days,
            "enabled": True,
            "system_prompt_zh": "你是 ITOM 助手。",
            "system_prompt_en": "You are an ITOM assistant.",
            "enabled_capabilities": [],
            "knowledge_scope": ["public"],
            "max_risk_level": "L1",
        },
        draft["draft_updated_at"],
        actor,
    )
    assistant_config.publish_profile(db, "requester", updated["draft_updated_at"], actor)
    return db.query(AiAgentProfile).filter(AiAgentProfile.code == "requester").one().id


def _withdraw_requester_through_task4(db, actor: AuthUser) -> None:
    profile = db.query(AiAgentProfile).filter(AiAgentProfile.code == "requester").one()
    draft = db.query(AiAgentProfileVersion).filter(
        AiAgentProfileVersion.profile_id == profile.id,
        AiAgentProfileVersion.version == 0,
        AiAgentProfileVersion.status == "draft",
    ).one()
    updated = assistant_config.update_profile_draft(
        db, "requester", {"enabled": False}, draft.updated_at, actor,
    )
    assistant_config.publish_profile(db, "requester", updated["draft_updated_at"], actor)


def _republish_requester_through_task4(db, actor: AuthUser, *, retention_days: int) -> None:
    draft = assistant_config.get_profile_draft(db, "requester", actor)
    updated = assistant_config.update_profile_draft(
        db, "requester", {"retention_days": retention_days}, draft["draft_updated_at"], actor,
    )
    assistant_config.publish_profile(db, "requester", updated["draft_updated_at"], actor)


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


@pytest.mark.parametrize(
    "malformation",
    [
        "missing_snapshot",
        "missing_bilingual_prompt",
        "unknown_capability",
        "missing_capabilities",
        "unhealthy_provider",
        "active_config_mismatch",
    ],
)
def test_bootstrap_and_create_fail_closed_for_malformed_published_runtime_profiles(
    client, admin_headers, malformation
):
    """A published row without its complete runtime proof must never enable the assistant or create a conversation."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, version_id = _publish_requester_profile(retention_days=30)
    with SessionLocal() as db:
        profile = db.get(AiAgentProfile, profile_id)
        version = db.get(AiAgentProfileVersion, version_id)
        if malformation == "missing_snapshot":
            version.config_snapshot = {}
        elif malformation == "missing_bilingual_prompt":
            version.system_prompt_en = " "
        elif malformation == "unknown_capability":
            version.enabled_capabilities = ["unknown.capability"]
        elif malformation == "missing_capabilities":
            version.enabled_capabilities = None
        elif malformation == "unhealthy_provider":
            db.get(AiProviderConfig, profile.default_provider_id).enabled = False
        else:
            profile.retention_days = 31
        db.commit()
    headers = _create_user(client, admin_headers, f"wa0_malformed_{malformation}")

    bootstrap = client.get("/api/assistant/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    assert bootstrap.json()["data"]["enabled"] is False
    create = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert create.status_code == 403, create.text
    assert create.json()["error"]["code"] == "AI_ASSISTANT_UNAVAILABLE"


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("enabled_capabilities", None),
        ("knowledge_scope", None),
        ("enabled_capabilities", {"knowledge.search": True}),
        ("knowledge_scope", {"public": True}),
    ],
)
def test_runtime_published_profile_rejects_raw_missing_or_malformed_collections(client, field, malformed_value):
    """The shared runtime validator must see raw persisted shapes, not coerced empty lists."""
    profile_id, version_id = _publish_requester_profile(retention_days=30)
    with SessionLocal() as db:
        profile = db.get(AiAgentProfile, profile_id)
        version = db.get(AiAgentProfileVersion, version_id)
        setattr(version, field, malformed_value)
        db.commit()
        assert assistant_config.runtime_published_profile(db, profile, audience="requester") is None


@pytest.mark.parametrize("field", ["enabled_capabilities", "knowledge_scope"])
def test_bootstrap_and_create_fail_closed_when_a_required_runtime_collection_is_missing(
    client, admin_headers, field
):
    """Each required published collection is independently fail-closed for browser entry points."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, version_id = _publish_requester_profile(retention_days=30)
    with SessionLocal() as db:
        setattr(db.get(AiAgentProfileVersion, version_id), field, None)
        db.commit()
    headers = _create_user(client, admin_headers, f"wa0_missing_{field}")

    bootstrap = client.get("/api/assistant/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    assert bootstrap.json()["data"]["enabled"] is False
    create = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert create.status_code == 403, create.text
    assert create.json()["error"]["code"] == "AI_ASSISTANT_UNAVAILABLE"


def test_bootstrap_fallback_uses_the_authenticated_permission_aware_document_guide(client, admin_headers, monkeypatch):
    """A literal fallback flag would falsely advertise a deterministic guide when its safe authenticated payload is unavailable."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    _publish_requester_profile(retention_days=30)
    headers = _create_user(client, admin_headers, "wa0_guide_fallback")

    guide = client.get("/api/it-document-guide", headers=headers)
    assert guide.status_code == 200, guide.text
    documents = guide.json()["data"]["documents"]
    assert {document["type"] for document in documents} == {
        "service_request", "incident", "problem", "change", "requirement", "project"
    }
    assert all(isinstance(document["can_create"], bool) for document in documents)
    assert all(
        document["target_path"] is not None if document["can_create"] else document["target_path"] is None
        for document in documents
    )
    assert client.get("/api/assistant/bootstrap", headers=headers).json()["data"]["fallback_available"] is True

    monkeypatch.setattr(it_document_guide, "guide_payload", lambda *_args: {"documents": "unsafe"})
    unavailable = client.get("/api/assistant/bootstrap", headers=headers)
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json()["data"]["fallback_available"] is False


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


def test_zero_retention_remains_nonpersistent_after_a_real_task4_positive_republish(
    client, admin_headers
):
    """The Task 4 publish path cannot turn a captured zero-retention conversation into a transcript."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        _publish_requester_through_task4(db, admin, retention_days=0)
    headers = _create_user(client, admin_headers, "wa0_retention_zero_republish")
    created = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        _republish_requester_through_task4(db, admin, retention_days=30)
        assert assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="user",
            content={"text": "must never become a retained transcript"},
            redacted_text="must never become a retained transcript",
        ) is None
        db.commit()
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation.id).count() == 0


def test_create_takes_the_task4_governance_lock_before_loading_runtime_state(client, admin_headers, monkeypatch):
    """Loading before the shared lock would allow Task 4 publication to overtake a stale create."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    _publish_requester_profile(retention_days=30)
    _create_user(client, admin_headers, "wa0_create_lock_order")
    events: list[str] = []
    original_runtime = assistant_config.runtime_published_profile
    original_lock = getattr(assistant_config, "lock_profile_runtime_governance", None)

    def observed_lock(db):
        events.append("governance_lock")
        if original_lock is not None:
            return original_lock(db)
        return None

    def observed_runtime(db, profile, *, audience=None):
        events.append("runtime_reload")
        return original_runtime(db, profile, audience=audience)

    monkeypatch.setattr(assistant_config, "lock_profile_runtime_governance", observed_lock, raising=False)
    monkeypatch.setattr(assistant_config, "runtime_published_profile", observed_runtime)
    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == "wa0_create_lock_order").one()
        created = assistant_conversations.create_conversation(
            db, actor, language="zh-CN", page_context=PAGE_CONTEXT,
        )

    assert created["id"]
    assert events[:2] == ["governance_lock", "runtime_reload"]


def test_create_captures_real_task4_republish_that_wins_before_its_governance_lock(
    client, admin_headers, monkeypatch
):
    """The creation barrier must reload the version published immediately before it takes the shared lock."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        _publish_requester_through_task4(db, admin, retention_days=0)
    _create_user(client, admin_headers, "wa0_create_republish")
    original_lock = getattr(assistant_config, "lock_profile_runtime_governance", None)
    events: list[str] = []

    def republish_barrier_then_lock(creation_db):
        events.append("create_waiting_for_governance_lock")
        if len(events) == 1:
            with SessionLocal() as publication_db:
                admin = publication_db.query(AuthUser).filter(AuthUser.username == "admin").one()
                _republish_requester_through_task4(publication_db, admin, retention_days=30)
            events.append("task4_republish_committed")
        if original_lock is not None:
            return original_lock(creation_db)
        return None

    monkeypatch.setattr(
        assistant_config,
        "lock_profile_runtime_governance",
        republish_barrier_then_lock,
        raising=False,
    )
    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == "wa0_create_republish").one()
        created = assistant_conversations.create_conversation(
            db, actor, language="zh-CN", page_context=PAGE_CONTEXT,
        )
        conversation = db.get(AiConversation, created["id"])
        captured = db.get(AiAgentProfileVersion, conversation.profile_version_id)

    assert captured.config_snapshot["retention_days"] == 30
    assert created["expires_at"] is not None
    assert events == ["create_waiting_for_governance_lock", "task4_republish_committed"]


def test_create_fails_closed_when_real_task4_withdrawal_wins_before_its_governance_lock(
    client, admin_headers, monkeypatch
):
    """A deterministic withdrawal barrier proves the create reload observes the post-withdrawal state."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        _publish_requester_through_task4(db, admin)
    _create_user(client, admin_headers, "wa0_create_withdrawal")
    original_lock = getattr(assistant_config, "lock_profile_runtime_governance", None)
    events: list[str] = []

    def withdrawal_barrier_then_lock(creation_db):
        events.append("create_waiting_for_governance_lock")
        if len(events) == 1:
            with SessionLocal() as publication_db:
                admin = publication_db.query(AuthUser).filter(AuthUser.username == "admin").one()
                _withdraw_requester_through_task4(publication_db, admin)
            events.append("task4_withdrawal_committed")
        if original_lock is not None:
            return original_lock(creation_db)
        return None

    monkeypatch.setattr(
        assistant_config,
        "lock_profile_runtime_governance",
        withdrawal_barrier_then_lock,
        raising=False,
    )
    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == "wa0_create_withdrawal").one()
        with pytest.raises(AppError) as raised:
            assistant_conversations.create_conversation(
                db, actor, language="zh-CN", page_context=PAGE_CONTEXT,
            )
        assert getattr(raised.value, "code", None) == "AI_ASSISTANT_UNAVAILABLE"
        assert db.query(AiConversation).filter(AiConversation.auth_user_id == actor.id).count() == 0

    assert events == ["create_waiting_for_governance_lock", "task4_withdrawal_committed"]


def test_positive_retention_remains_persistent_when_current_profile_is_republished_to_zero(client, admin_headers):
    """A later zero-retention policy must not retroactively erase the immutable version decision for an existing conversation."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, _version_id = _publish_requester_profile(retention_days=30)
    headers = _create_user(client, admin_headers, "wa0_retention_positive_republish")
    created = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        _publish_next_version(db, db.get(AiAgentProfile, profile_id), retention_days=0)
        stored = assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="assistant",
            content={"text": "retained by the original version"},
            redacted_text="retained by the original version",
        )
        assert stored is not None
        db.commit()
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation.id).count() == 1


@pytest.mark.parametrize("state", ["disabled", "deleted"])
def test_ordinary_messages_stop_when_the_current_profile_is_disabled_or_deleted(client, admin_headers, state):
    """A stale active conversation must not continue recording messages after its current profile is withdrawn."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, _version_id = _publish_requester_profile(retention_days=30)
    headers = _create_user(client, admin_headers, f"wa0_profile_{state}")
    created = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        profile = db.get(AiAgentProfile, profile_id)
        if state == "disabled":
            profile.enabled = False
        else:
            profile.is_deleted = True
        db.commit()
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        assert assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="user",
            content={"text": "withdrawn profile"},
            redacted_text="withdrawn profile",
        ) is None
        db.commit()
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation.id).count() == 0


def test_ordinary_messages_fail_closed_when_the_captured_version_has_no_complete_snapshot(client, admin_headers):
    """Falling back to live retention when an old version lacks proof would persist an ungoverned transcript."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, _version_id = _publish_requester_profile(retention_days=30)
    headers = _create_user(client, admin_headers, "wa0_legacy_conversation")
    created = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        legacy = AiAgentProfileVersion(
            profile_id=profile_id,
            version=0,
            status="published",
            system_prompt_zh="旧版",
            system_prompt_en="Legacy",
            enabled_capabilities=[],
            knowledge_scope=["public"],
            config_snapshot={},
            max_risk_level="L1",
        )
        db.add(legacy)
        db.flush()
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        conversation.profile_version_id = legacy.id
        db.commit()
        assert assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="user",
            content={"text": "legacy retention cannot be inferred"},
            redacted_text="legacy retention cannot be inferred",
        ) is None
        db.commit()
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation.id).count() == 0


def test_ordinary_messages_fail_closed_when_the_captured_version_lacks_publication_proof(client, admin_headers):
    """A timestamp-less captured version is not proof that its retention policy was ever published."""
    with SessionLocal() as db:
        _disable_other_requester_profiles(db)
    profile_id, version_id = _publish_requester_profile(retention_days=30)
    headers = _create_user(client, admin_headers, "wa0_unpublished_capture")
    created = client.post("/api/assistant/conversations", headers=headers, json={"page_context": PAGE_CONTEXT})
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        profile = db.get(AiAgentProfile, profile_id)
        _publish_next_version(db, profile, retention_days=30)
        db.get(AiAgentProfileVersion, version_id).published_at = None
        conversation = db.get(AiConversation, created.json()["data"]["id"])
        db.commit()
        assert assistant_conversations.persist_ordinary_message(
            db,
            conversation,
            role="assistant",
            content={"text": "unproved published version"},
            redacted_text="unproved published version",
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


@pytest.mark.parametrize("page", [0, 10_001])
def test_conversation_page_rejects_values_outside_the_bounded_offset_window(client, admin_headers, page):
    """Allowing an unbounded page would turn an otherwise bounded API into an overflowing database offset."""
    response = client.get(f"/api/assistant/conversations?page={page}", headers=admin_headers)

    assert response.status_code == 422, response.text
