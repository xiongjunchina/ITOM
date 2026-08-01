"""WA0 administrator-only provider and agent-profile governance contracts."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import asyncio
import httpx
import pytest
from pydantic import BaseModel

from app.assistant.registry import CapabilityRegistry
from app.assistant.types import AssistantChannel, CapabilityDefinition, CapabilityResult, RiskLevel
from app.assistant.providers import OpenAICompatibleProvider, ProviderProbe
from app.core.config import settings
from app.core.errors import AppError
from app.db import SessionLocal
from app.models import (
    AiAction,
    AiAgentProfile,
    AiAgentProfileVersion,
    AiConversation,
    AiProviderCall,
    AiProviderConfig,
    AuditLog,
    AuthUser,
)
from app.services.migrate import run_migrations
from app.services.secrets_store import decrypt_secret


VALID_PROVIDER = {
    "code": "wa0-primary",
    "name": "WA0 Primary",
    "provider_type": "openai_compatible",
    "api_base_url": "https://models.example.test/v1",
    "api_key": "wa0-provider-secret-value",
    "model": "test-model",
    "timeout_seconds": 30,
    "max_output_tokens": 512,
    "temperature": 0.1,
    "is_primary": True,
    "enabled": False,
}


def _run(awaitable):
    return asyncio.run(awaitable)


async def _public_dns(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


def _basic_probe_response(content: str = "ok") -> dict:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]
    }


def _tool_probe_response() -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-probe",
                            "type": "function",
                            "function": {"name": "wa0_capability_probe", "arguments": '{"status":"ok"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _schema_probe_response() -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"status":"schema-ok"}'},
                "finish_reason": "stop",
            }
        ]
    }


def _probe_stream_response() -> str:
    documents = [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "stream-ok"}, "finish_reason": "stop"}]},
    ]
    return "\n\n".join([*(f"data: {json.dumps(item)}" for item in documents), "data: [DONE]"]) + "\n\n"


class _CapabilityInput(BaseModel):
    subject: str


def _capability_handler(*_args) -> CapabilityResult:
    return CapabilityResult(status="ok", data={})


def _test_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    definitions = (
        ("knowledge.read", {"requester", "bdo", "it", "admin"}, RiskLevel.L1, None, None, False),
        ("requirement.prepare", {"bdo", "it", "admin"}, RiskLevel.L2, "requirements", "create", False),
        ("incident.prepare", {"it", "admin"}, RiskLevel.L2, "ticket_incident", "create", False),
        ("incident.submit", {"it", "admin"}, RiskLevel.L3, "ticket_incident", "create", True),
    )
    for code, audiences, risk, module, action, confirmation in definitions:
        registry.register(
            CapabilityDefinition(
                code=code,
                channels=frozenset({AssistantChannel.WEB}),
                audiences=frozenset(audiences),
                module=module,
                action=action,
                risk=risk,
                input_model=_CapabilityInput,
                handler=_capability_handler,
                requires_confirmation=confirmation,
            )
        )
    return registry


def _create_healthy_provider(client, admin_headers, monkeypatch, code: str) -> str:
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    payload = {**VALID_PROVIDER, "code": code, "name": code, "is_primary": False}
    response = client.post("/api/admin/ai/providers", headers=admin_headers, json=payload)
    assert response.status_code == 200, response.text
    provider_id = response.json()["data"]["id"]
    with SessionLocal() as db:
        row = db.get(AiProviderConfig, provider_id)
        row.probe_status = "success"
        row.last_probed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        row.capability_probe = {
            "authentication": True,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_schema": True,
        }
        row.enabled = True
        db.commit()
    return provider_id


def _create_user(client, admin_headers, username: str, roles: list[str]) -> dict[str, str]:
    person_response = client.post("/api/members", headers=admin_headers, json={"name": username})
    assert person_response.status_code == 200, person_response.text
    person_id = person_response.json()["data"]["id"]
    user_response = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": username, "password": "pass123", "roles": roles, "person_id": person_id},
    )
    assert user_response.status_code == 200, user_response.text
    login = client.post("/api/auth/login", json={"username": username, "password": "pass123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['data']['token']}"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/admin/ai/providers", None),
        ("POST", "/api/admin/ai/providers", {"code": "blocked", "name": "Blocked"}),
        ("PATCH", "/api/admin/ai/providers/missing", {"name": "Blocked"}),
        ("DELETE", "/api/admin/ai/providers/missing", None),
        ("POST", "/api/admin/ai/providers/missing/test", None),
        ("GET", "/api/admin/ai/profiles/requester/draft", None),
        ("PATCH", "/api/admin/ai/profiles/requester/draft", {"name": "Blocked"}),
        ("POST", "/api/admin/ai/profiles/requester/publish", {}),
        ("POST", "/api/admin/ai/profiles/requester/rollback", {"version": 1}),
        ("GET", "/api/admin/ai/health", None),
        ("GET", "/api/admin/ai/usage", None),
        ("GET", "/api/admin/ai/action-audits", None),
    ],
)
def test_every_ai_admin_endpoint_requires_real_server_side_admin_ai_permission(
    client, admin_headers, method, path, body
):
    """Removing any route guard must let a persisted requester reach AI governance."""
    suffix = hashlib.sha256(f"{method}:{path}".encode()).hexdigest()[:12]
    requester_headers = _create_user(client, admin_headers, f"wa0_blocked_{suffix}", ["requester"])

    response = client.request(method, path, headers=requester_headers, json=body)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_provider_secret_is_encrypted_write_only_and_blank_update_preserves_ciphertext(
    client, admin_headers, monkeypatch
):
    """Returning raw/ciphertext or replacing a secret on blank PATCH must break this contract."""
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")

    created_response = client.post("/api/admin/ai/providers", headers=admin_headers, json=VALID_PROVIDER)

    assert created_response.status_code == 200, created_response.text
    created = created_response.json()["data"]
    provider_id = created["id"]
    assert created["has_secret"] is True
    assert created["probe_status"] == "unverified"
    assert created["enabled"] is False
    assert "api_key" not in created
    assert "api_key_encrypted" not in created
    assert VALID_PROVIDER["api_key"] not in created_response.text

    with SessionLocal() as db:
        stored = db.get(AiProviderConfig, provider_id)
        original_ciphertext = stored.api_key_encrypted
        assert original_ciphertext != VALID_PROVIDER["api_key"]
        assert decrypt_secret(original_ciphertext) == VALID_PROVIDER["api_key"]

    updated_response = client.patch(
        f"/api/admin/ai/providers/{provider_id}",
        headers=admin_headers,
        json={"name": "WA0 Primary Updated", "api_key": "   "},
    )
    assert updated_response.status_code == 200, updated_response.text
    assert updated_response.json()["data"]["has_secret"] is True
    assert VALID_PROVIDER["api_key"] not in updated_response.text

    listed_response = client.get("/api/admin/ai/providers", headers=admin_headers)
    assert listed_response.status_code == 200, listed_response.text
    listed = next(row for row in listed_response.json()["data"] if row["id"] == provider_id)
    assert listed["name"] == "WA0 Primary Updated"
    assert listed["has_secret"] is True
    assert {"api_key", "api_key_encrypted"}.isdisjoint(listed)

    with SessionLocal() as db:
        assert db.get(AiProviderConfig, provider_id).api_key_encrypted == original_ciphertext
        audit_rows = db.query(AuditLog).filter(AuditLog.entity_id == provider_id).all()
        assert {row.action for row in audit_rows} >= {"create", "update"}
        serialized_audits = json.dumps([row.summary for row in audit_rows])
        assert VALID_PROVIDER["api_key"] not in serialized_audits
        assert original_ciphertext not in serialized_audits


def test_provider_preserves_nonblank_secret_bytes_including_edge_whitespace(
    client, admin_headers, monkeypatch
):
    """Trimming a nonblank credential must corrupt a legitimate provider secret."""
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    exact_secret = "  edge-whitespace-is-significant  "
    payload = {
        **VALID_PROVIDER,
        "code": "wa0-exact-secret",
        "name": "Exact Secret",
        "api_key": exact_secret,
        "is_primary": False,
    }

    response = client.post("/api/admin/ai/providers", headers=admin_headers, json=payload)

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        stored = db.get(AiProviderConfig, response.json()["data"]["id"])
        assert decrypt_secret(stored.api_key_encrypted) == exact_secret


@pytest.mark.parametrize(
    ("patch", "expected_code"),
    [
        ({"api_base_url": "http://models.example.test/v1"}, "AI_PROVIDER_CONFIG_INVALID"),
        ({"api_base_url": "https://unlisted.example.test/v1"}, "AI_PROVIDER_CONFIG_INVALID"),
        ({"enabled": True}, "AI_PROVIDER_PROBE_REQUIRED"),
    ],
)
def test_provider_update_reuses_transport_safety_and_cannot_enable_unverified_provider(
    client, admin_headers, monkeypatch, patch, expected_code
):
    """Bypassing Task 3 validation or the probe gate must make unsafe providers usable."""
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    suffix = hashlib.sha256(json.dumps(patch, sort_keys=True).encode()).hexdigest()[:8]
    payload = {**VALID_PROVIDER, "code": f"wa0-update-{suffix}", "name": f"Update {suffix}", "is_primary": False}
    created = client.post("/api/admin/ai/providers", headers=admin_headers, json=payload)
    assert created.status_code == 200, created.text
    provider = created.json()["data"]

    response = client.patch(f"/api/admin/ai/providers/{provider['id']}", headers=admin_headers, json=patch)

    assert response.status_code in {400, 409}, response.text
    assert response.json()["error"]["code"] == expected_code
    with SessionLocal() as db:
        stored = db.get(AiProviderConfig, provider["id"])
        assert stored.api_base_url == VALID_PROVIDER["api_base_url"]
        assert stored.enabled is False


def test_provider_fallback_requires_existing_acyclic_chain(client, admin_headers, monkeypatch):
    """Create and update must reject dangling fallback references and fallback cycles."""
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    dangling = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={
            **VALID_PROVIDER,
            "code": "wa0-dangling-fallback",
            "name": "Dangling Fallback",
            "is_primary": False,
            "fallback_provider_id": "missing-provider",
        },
    )
    assert dangling.status_code == 404, dangling.text
    assert dangling.json()["error"]["code"] == "AI_PROVIDER_NOT_FOUND"

    first = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={**VALID_PROVIDER, "code": "wa0-fallback-a", "name": "Fallback A", "is_primary": False},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["id"]
    second = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={
            **VALID_PROVIDER,
            "code": "wa0-fallback-b",
            "name": "Fallback B",
            "is_primary": False,
            "fallback_provider_id": first_id,
        },
    )
    assert second.status_code == 200, second.text
    second_id = second.json()["data"]["id"]

    cycle = client.patch(
        f"/api/admin/ai/providers/{first_id}",
        headers=admin_headers,
        json={"fallback_provider_id": second_id},
    )
    assert cycle.status_code == 400, cycle.text
    assert cycle.json()["error"]["code"] == "AI_PROVIDER_FALLBACK_INVALID"

    assert client.patch(
        f"/api/admin/ai/providers/{first_id}", headers=admin_headers, json={"is_primary": True}
    ).status_code == 200
    promoted = client.patch(
        f"/api/admin/ai/providers/{second_id}", headers=admin_headers, json={"is_primary": True}
    )
    assert promoted.status_code == 200, promoted.text
    with SessionLocal() as db:
        primary_ids = [
            row.id
            for row in db.query(AiProviderConfig).filter_by(is_primary=True, is_deleted=False).all()
        ]
        assert primary_ids == [second_id]


class _ProviderLockQueryCapture:
    def __init__(self, events: list[str]):
        self.events = events

    def order_by(self, *_columns):
        self.events.append("order_by_id")
        return self

    def with_for_update(self):
        self.events.append("for_update")
        return self

    def populate_existing(self):
        self.events.append("populate_existing")
        return self

    def all(self):
        self.events.append("read_rows")
        return []


class _ProviderLockSessionCapture:
    def __init__(self):
        self.events: list[str] = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(self, statement, parameters):
        assert parameters == {"lock_key": 0x49544F4D41495052}
        self.events.append(str(statement))

    def query(self, model):
        assert model is AiProviderConfig
        self.events.append("provider_query")
        return _ProviderLockQueryCapture(self.events)


def test_provider_governance_lock_precedes_deterministic_postgres_row_locks():
    """Dropping/reordering the cross-pod advisory and provider row locks must break serialization."""
    from app.services import assistant_config

    session = _ProviderLockSessionCapture()

    assistant_config._lock_provider_governance(session)

    assert session.events == [
        "SELECT pg_advisory_xact_lock(:lock_key)",
        "provider_query",
        "order_by_id",
        "for_update",
        "populate_existing",
        "read_rows",
    ]


def test_every_provider_or_active_reference_mutation_enters_shared_lock_before_read_or_write(
    client, admin_headers, monkeypatch
):
    """Any create/update/delete/probe path skipping the shared lock can race another pod."""
    from app.services import assistant_config

    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    existing_id = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={**VALID_PROVIDER, "code": "wa0-lock-existing", "name": "Lock Existing", "is_primary": False},
    ).json()["data"]["id"]
    profile_draft = client.get(
        "/api/admin/ai/profiles/requester/draft", headers=admin_headers
    ).json()["data"]

    def stop_at_lock(_db):
        raise AppError("AI_PROVIDER_LOCK_SENTINEL", "lock boundary reached", 409)

    monkeypatch.setattr(assistant_config, "_lock_provider_governance", stop_at_lock, raising=False)
    requests = (
        ("POST", "/api/admin/ai/providers", {**VALID_PROVIDER, "code": "wa0-lock-create", "is_primary": False}),
        ("PATCH", f"/api/admin/ai/providers/{existing_id}", {"name": "must not update"}),
        ("DELETE", f"/api/admin/ai/providers/{existing_id}", None),
        ("POST", f"/api/admin/ai/providers/{existing_id}/test", None),
        (
            "POST",
            "/api/admin/ai/profiles/requester/publish",
            {"expected_draft_updated_at": profile_draft["draft_updated_at"]},
        ),
        (
            "POST",
            "/api/admin/ai/profiles/requester/rollback",
            {"version": 1, "expected_latest_version": 1},
        ),
    )

    for method, path, body in requests:
        response = client.request(method, path, headers=admin_headers, json=body)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "AI_PROVIDER_LOCK_SENTINEL"

    with SessionLocal() as db:
        row = db.get(AiProviderConfig, existing_id)
        assert row.name == "Lock Existing"
        assert row.is_deleted is False
        assert db.query(AiProviderConfig).filter_by(code="wa0-lock-create").count() == 0


def test_stale_enable_cannot_win_after_another_transaction_invalidates_provider_probe(
    client, admin_headers, monkeypatch
):
    """A cached healthy row must be refreshed under lock before enabling a changed provider."""
    from app.services import assistant_config

    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-stale-enable")
    stale_db = SessionLocal()
    writer_db = SessionLocal()
    try:
        stale_actor = stale_db.query(AuthUser).filter_by(username="admin").one()
        stale_row = stale_db.get(AiProviderConfig, provider_id)
        assert stale_row.enabled is True
        assert stale_row.probe_status == "success"

        changed = writer_db.get(AiProviderConfig, provider_id)
        changed.model = "changed-after-stale-read"
        changed.enabled = False
        changed.probe_status = "unverified"
        changed.capability_probe = {}
        changed.last_probed_at = None
        writer_db.commit()

        with pytest.raises(AppError) as exc_info:
            assistant_config.update_provider(stale_db, provider_id, {"enabled": True}, stale_actor)
        assert exc_info.value.code == "AI_PROVIDER_PROBE_REQUIRED"
        stale_db.rollback()
    finally:
        stale_db.close()
        writer_db.close()

    with SessionLocal() as db:
        current = db.get(AiProviderConfig, provider_id)
        assert current.model == "changed-after-stale-read"
        assert current.probe_status == "unverified"
        assert current.enabled is False


def test_provider_probe_runs_task3_exact_sequence_and_atomically_persists_truthful_status(
    client, admin_headers, monkeypatch
):
    """Skipping/reordering an exact probe or not persisting its result must fail this admin contract."""
    from app.services import assistant_config

    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    payload = {**VALID_PROVIDER, "code": "wa0-probe-success", "name": "Probe Success", "is_primary": False}
    provider_id = client.post("/api/admin/ai/providers", headers=admin_headers, json=payload).json()["data"]["id"]
    sequence: list[str] = []
    clients: list[httpx.AsyncClient] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["Authorization"] == f"Bearer {VALID_PROVIDER['api_key']}"
        if body.get("stream") is True:
            sequence.append("stream")
            return httpx.Response(200, text=_probe_stream_response(), headers={"Content-Type": "text/event-stream"})
        if "tool_choice" in body:
            sequence.append("tool")
            return httpx.Response(200, json=_tool_probe_response())
        if "response_format" in body:
            sequence.append("json_schema")
            return httpx.Response(200, json=_schema_probe_response())
        sequence.append("authentication")
        return httpx.Response(200, json=_basic_probe_response())

    def provider_factory(row):
        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(mock_client)
        return OpenAICompatibleProvider(
            row,
            allowed_hosts=settings.ai_provider_allowed_hosts,
            client=mock_client,
            resolver=_public_dns,
        )

    monkeypatch.setattr(assistant_config, "_provider_for_probe", provider_factory, raising=False)
    try:
        response = client.post(f"/api/admin/ai/providers/{provider_id}/test", headers=admin_headers)
    finally:
        for mock_client in clients:
            _run(mock_client.aclose())

    assert response.status_code == 200, response.text
    assert sequence == ["authentication", "stream", "tool", "json_schema"]
    data = response.json()["data"]
    assert data["probe_status"] == "success"
    assert data["capability_probe"] == {
        "authentication": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_json_schema": True,
    }
    assert data["last_probed_at"] is not None
    assert VALID_PROVIDER["api_key"] not in response.text

    enabled = client.patch(
        f"/api/admin/ai/providers/{provider_id}", headers=admin_headers, json={"enabled": True}
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["enabled"] is True


def test_provider_probe_releases_database_transaction_before_awaiting_network(
    client, admin_headers, monkeypatch
):
    """Moving the network await back inside Phase A/C must expose an open DB transaction."""
    from app.services import assistant_config

    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    provider_id = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={**VALID_PROVIDER, "code": "wa0-probe-no-db-lock", "is_primary": False},
    ).json()["data"]["id"]
    probe_db = SessionLocal()
    started = asyncio.Event()
    release = asyncio.Event()

    class AwaitingProbe:
        async def probe(self):
            started.set()
            await release.wait()
            return ProviderProbe(
                success=True,
                supports_streaming=True,
                supports_tools=True,
                supports_json_schema=True,
                checked_at=datetime.now(timezone.utc),
                model="test-model",
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(assistant_config, "_provider_for_probe", lambda _row: AwaitingProbe())

    async def exercise():
        actor = probe_db.query(AuthUser).filter_by(username="admin").one()
        probe_db.commit()
        task = asyncio.create_task(assistant_config.probe_provider(probe_db, provider_id, actor))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            assert probe_db.in_transaction() is False
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=1)

    try:
        _run(exercise())
    finally:
        probe_db.close()


def test_provider_mutation_can_finish_during_probe_and_stale_result_is_discarded(
    client, admin_headers, monkeypatch
):
    """A probe result for an older revision must not overwrite a newer unverified config."""
    from app.services import assistant_config

    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    fallback_id = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={**VALID_PROVIDER, "code": "wa0-probe-new-fallback", "is_primary": False},
    ).json()["data"]["id"]
    provider_id = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={**VALID_PROVIDER, "code": "wa0-probe-stale-result", "is_primary": False},
    ).json()["data"]["id"]
    probe_db = SessionLocal()
    writer_db = SessionLocal()
    started = asyncio.Event()
    release = asyncio.Event()

    class AwaitingProbe:
        async def probe(self):
            started.set()
            await release.wait()
            return ProviderProbe(
                success=True,
                supports_streaming=True,
                supports_tools=True,
                supports_json_schema=True,
                checked_at=datetime.now(timezone.utc),
                model="test-model",
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(assistant_config, "_provider_for_probe", lambda _row: AwaitingProbe())

    async def exercise():
        probe_actor = probe_db.query(AuthUser).filter_by(username="admin").one()
        writer_actor = writer_db.query(AuthUser).filter_by(username="admin").one()
        probe_db.commit()
        writer_db.commit()
        task = asyncio.create_task(assistant_config.probe_provider(probe_db, provider_id, probe_actor))
        await asyncio.wait_for(started.wait(), timeout=1)

        before_revision = writer_db.get(AiProviderConfig, provider_id).config_revision
        updated = assistant_config.update_provider(
            writer_db,
            provider_id,
            {"fallback_provider_id": fallback_id},
            writer_actor,
        )
        assert updated["fallback_provider_id"] == fallback_id
        writer_db.expire_all()
        assert writer_db.get(AiProviderConfig, provider_id).config_revision == before_revision + 1

        release.set()
        with pytest.raises(AppError) as exc_info:
            await asyncio.wait_for(task, timeout=1)
        assert exc_info.value.code == "AI_PROVIDER_PROBE_STALE"

    try:
        _run(exercise())
    finally:
        release.set()
        probe_db.close()
        writer_db.close()

    with SessionLocal() as db:
        current = db.get(AiProviderConfig, provider_id)
        assert current.fallback_provider_id == fallback_id
        assert current.probe_status == "unverified"
        assert current.capability_probe == {}
        assert current.last_probed_at is None
        assert current.enabled is False


def test_failed_provider_probe_cannot_leave_provider_healthy_or_leak_error_content(
    client, admin_headers, monkeypatch
):
    """A failed re-probe must revoke health/enablement and persist only a stable redacted failure."""
    from app.services import assistant_config

    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    payload = {**VALID_PROVIDER, "code": "wa0-probe-failure", "name": "Probe Failure", "is_primary": False}
    provider_id = client.post("/api/admin/ai/providers", headers=admin_headers, json=payload).json()["data"]["id"]
    clients: list[httpx.AsyncClient] = []

    def provider_factory(row):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text=f"upstream echoed {VALID_PROVIDER['api_key']}")

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(mock_client)
        return OpenAICompatibleProvider(
            row,
            allowed_hosts=settings.ai_provider_allowed_hosts,
            client=mock_client,
            resolver=_public_dns,
        )

    monkeypatch.setattr(assistant_config, "_provider_for_probe", provider_factory, raising=False)
    try:
        response = client.post(f"/api/admin/ai/providers/{provider_id}/test", headers=admin_headers)
    finally:
        for mock_client in clients:
            _run(mock_client.aclose())

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "AI_PROVIDER_PROBE_FAILED"
    assert VALID_PROVIDER["api_key"] not in response.text
    with SessionLocal() as db:
        stored = db.get(AiProviderConfig, provider_id)
        assert stored.probe_status == "failed"
        assert stored.enabled is False
        assert stored.last_probed_at is not None
        assert stored.capability_probe == {
            "authentication": False,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_json_schema": False,
            "error_code": "PROVIDER_AUTH_FAILED",
            "error_message": "provider authentication failed",
        }


def test_profile_bootstrap_is_fixed_and_draft_updates_reject_stale_or_unsafe_content(
    client, admin_headers, monkeypatch
):
    """Adding arbitrary profiles/handlers or accepting a stale unsafe draft must break governance."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-profile-provider")

    drafts = {}
    for code in ("requester", "bdo", "it_staff", "admin"):
        response = client.get(f"/api/admin/ai/profiles/{code}/draft", headers=admin_headers)
        assert response.status_code == 200, response.text
        drafts[code] = response.json()["data"]
    assert {row["code"] for row in drafts.values()} == {"requester", "bdo", "it_staff", "admin"}
    assert {code: row["audience"] for code, row in drafts.items()} == {
        "requester": "requester",
        "bdo": "bdo",
        "it_staff": "it",
        "admin": "admin",
    }
    unknown = client.get("/api/admin/ai/profiles/arbitrary/draft", headers=admin_headers)
    assert unknown.status_code == 404

    requester = drafts["requester"]
    update = {
        "expected_updated_at": requester["draft_updated_at"],
        "name": "Requester Assistant",
        "default_provider_id": provider_id,
        "system_prompt_zh": "你是 ITOM 业务用户助手。",
        "system_prompt_en": "You are the ITOM requester assistant.",
        "enabled_capabilities": ["knowledge.read"],
        "knowledge_scope": ["public", "service_catalog", "own_records"],
        "max_risk_level": "L1",
        "retention_days": 30,
        "enabled": True,
    }
    updated_response = client.patch(
        "/api/admin/ai/profiles/requester/draft", headers=admin_headers, json=update
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()["data"]
    assert updated["enabled_capabilities"] == ["knowledge.read"]
    assert updated["draft_updated_at"] != requester["draft_updated_at"]

    stale = client.patch(
        "/api/admin/ai/profiles/requester/draft",
        headers=admin_headers,
        json={**update, "name": "Stale overwrite"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "AI_PROFILE_DRAFT_STALE"

    for unsafe_patch, expected_code in (
        ({"enabled_capabilities": ["unknown.dynamic.handler"]}, "AI_PROFILE_CAPABILITY_INVALID"),
        ({"enabled_capabilities": ["incident.prepare"], "max_risk_level": "L2"}, "AI_PROFILE_AUDIENCE_INVALID"),
        ({"max_risk_level": "L4"}, "AI_PROFILE_RISK_INVALID"),
        ({"knowledge_scope": ["internal_knowledge"]}, "AI_PROFILE_KNOWLEDGE_INVALID"),
    ):
        current = client.get("/api/admin/ai/profiles/requester/draft", headers=admin_headers).json()["data"]
        response = client.patch(
            "/api/admin/ai/profiles/requester/draft",
            headers=admin_headers,
            json={"expected_updated_at": current["draft_updated_at"], **unsafe_patch},
        )
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == expected_code


def test_publish_and_rollback_create_immutable_increasing_versions_and_reject_stale_state(
    client, admin_headers, monkeypatch
):
    """Updating history or reusing stale revisions must break deterministic publication semantics."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-version-provider")
    initial = client.get("/api/admin/ai/profiles/it_staff/draft", headers=admin_headers).json()["data"]

    def save_draft(expected_updated_at: str, prompt_suffix: str) -> dict:
        response = client.patch(
            "/api/admin/ai/profiles/it_staff/draft",
            headers=admin_headers,
            json={
                "expected_updated_at": expected_updated_at,
                "name": "IT Staff Assistant",
                "default_provider_id": provider_id,
                "system_prompt_zh": f"IT 员工助手 {prompt_suffix}",
                "system_prompt_en": f"IT staff assistant {prompt_suffix}",
                "enabled_capabilities": ["knowledge.read", "incident.prepare", "incident.submit"],
                "knowledge_scope": ["public", "internal_knowledge", "authorized_records"],
                "max_risk_level": "L3",
                "enabled": True,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    draft_v1 = save_draft(initial["draft_updated_at"], "v1")
    published_v1_response = client.post(
        "/api/admin/ai/profiles/it_staff/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v1["draft_updated_at"]},
    )
    assert published_v1_response.status_code == 200, published_v1_response.text
    published_v1 = published_v1_response.json()["data"]
    assert published_v1["version"] == 1

    stale_publish = client.post(
        "/api/admin/ai/profiles/it_staff/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v1["draft_updated_at"]},
    )
    assert stale_publish.status_code == 409
    assert stale_publish.json()["error"]["code"] == "AI_PROFILE_DRAFT_STALE"

    current = client.get("/api/admin/ai/profiles/it_staff/draft", headers=admin_headers).json()["data"]
    draft_v2 = save_draft(current["draft_updated_at"], "v2")
    published_v2_response = client.post(
        "/api/admin/ai/profiles/it_staff/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v2["draft_updated_at"]},
    )
    assert published_v2_response.status_code == 200, published_v2_response.text
    assert published_v2_response.json()["data"]["version"] == 2

    rollback_response = client.post(
        "/api/admin/ai/profiles/it_staff/rollback",
        headers=admin_headers,
        json={"version": 1, "expected_latest_version": 2},
    )
    assert rollback_response.status_code == 200, rollback_response.text
    rolled_back = rollback_response.json()["data"]
    assert rolled_back["version"] == 3
    assert rolled_back["system_prompt_en"] == "IT staff assistant v1"

    stale_rollback = client.post(
        "/api/admin/ai/profiles/it_staff/rollback",
        headers=admin_headers,
        json={"version": 1, "expected_latest_version": 2},
    )
    assert stale_rollback.status_code == 409
    assert stale_rollback.json()["error"]["code"] == "AI_PROFILE_VERSION_STALE"

    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="it_staff").one()
        versions = (
            db.query(AiAgentProfileVersion)
            .filter_by(profile_id=profile.id, status="published")
            .order_by(AiAgentProfileVersion.version)
            .all()
        )
        assert [row.version for row in versions] == [1, 2, 3]
        assert [row.system_prompt_en for row in versions] == [
            "IT staff assistant v1",
            "IT staff assistant v2",
            "IT staff assistant v1",
        ]


def test_failed_publish_is_atomic_when_provider_is_unhealthy(client, admin_headers, monkeypatch):
    """Publishing an unhealthy provider must not alter profile status or create a partial version."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    provider_payload = {**VALID_PROVIDER, "code": "wa0-unhealthy-provider", "name": "Unhealthy", "is_primary": False}
    provider_id = client.post("/api/admin/ai/providers", headers=admin_headers, json=provider_payload).json()["data"]["id"]
    initial = client.get("/api/admin/ai/profiles/bdo/draft", headers=admin_headers).json()["data"]
    saved_response = client.patch(
        "/api/admin/ai/profiles/bdo/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": initial["draft_updated_at"],
            "default_provider_id": provider_id,
            "system_prompt_zh": "BDO 助手",
            "system_prompt_en": "BDO assistant",
            "enabled_capabilities": ["knowledge.read", "requirement.prepare"],
            "knowledge_scope": ["public", "service_catalog", "own_records", "own_requirements"],
            "max_risk_level": "L2",
            "enabled": True,
        },
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()["data"]

    response = client.post(
        "/api/admin/ai/profiles/bdo/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": saved["draft_updated_at"]},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "AI_PROFILE_PROVIDER_UNHEALTHY"
    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="bdo").one()
        assert profile.status == "draft"
        assert profile.enabled is False
        assert profile.default_provider_id is None
        assert db.query(AiAgentProfileVersion).filter_by(profile_id=profile.id, status="published").count() == 0


def test_published_profile_isolated_from_draft_and_publish_rollback_apply_snapshots_atomically(
    client, admin_headers, monkeypatch
):
    """Drafts must not contaminate active settings; publish/rollback apply immutable snapshots."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    provider_v1 = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-profile-active-v1")
    provider_v2_response = client.post(
        "/api/admin/ai/providers",
        headers=admin_headers,
        json={
            **VALID_PROVIDER,
            "code": "wa0-profile-active-v2",
            "name": "Profile Active V2",
            "is_primary": False,
        },
    )
    assert provider_v2_response.status_code == 200, provider_v2_response.text
    provider_v2 = provider_v2_response.json()["data"]["id"]

    initial = client.get("/api/admin/ai/profiles/requester/draft", headers=admin_headers).json()["data"]
    draft_v1_response = client.patch(
        "/api/admin/ai/profiles/requester/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": initial["draft_updated_at"],
            "name": "Requester Active V1",
            "default_provider_id": provider_v1,
            "retention_days": 10,
            "enabled": True,
            "system_prompt_zh": "请求者活动版本一",
            "system_prompt_en": "Requester active version one",
            "enabled_capabilities": ["knowledge.read"],
            "knowledge_scope": ["public", "own_records"],
            "max_risk_level": "L1",
        },
    )
    assert draft_v1_response.status_code == 200, draft_v1_response.text
    draft_v1 = draft_v1_response.json()["data"]
    published_v1_response = client.post(
        "/api/admin/ai/profiles/requester/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v1["draft_updated_at"]},
    )
    assert published_v1_response.status_code == 200, published_v1_response.text
    assert published_v1_response.json()["data"]["version"] == 1

    active_v1 = {
        "name": "Requester Active V1",
        "default_provider_id": provider_v1,
        "retention_days": 10,
        "enabled": True,
        "max_risk_level": "L1",
        "status": "published",
    }
    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        assert {key: getattr(profile, key) for key in active_v1} == active_v1
        active_v1_updated_at = profile.updated_at
        version_v1 = db.query(AiAgentProfileVersion).filter_by(profile_id=profile.id, version=1).one()
        immutable_v1 = {
            "id": version_v1.id,
            "version": version_v1.version,
            "status": version_v1.status,
            "config_snapshot": dict(version_v1.config_snapshot),
            "system_prompt_zh": version_v1.system_prompt_zh,
            "system_prompt_en": version_v1.system_prompt_en,
            "enabled_capabilities": list(version_v1.enabled_capabilities),
            "knowledge_scope": list(version_v1.knowledge_scope),
            "max_risk_level": version_v1.max_risk_level,
            "published_by": version_v1.published_by,
            "published_at": version_v1.published_at,
            "created_at": version_v1.created_at,
            "updated_at": version_v1.updated_at,
            "is_deleted": version_v1.is_deleted,
            "is_example": version_v1.is_example,
        }

    current = client.get("/api/admin/ai/profiles/requester/draft", headers=admin_headers).json()["data"]
    draft_v2_response = client.patch(
        "/api/admin/ai/profiles/requester/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": current["draft_updated_at"],
            "name": "Requester Staged V2",
            "default_provider_id": provider_v2,
            "retention_days": 20,
            "enabled": False,
            "system_prompt_zh": "请求者待发布版本二",
            "system_prompt_en": "Requester staged version two",
        },
    )
    assert draft_v2_response.status_code == 200, draft_v2_response.text
    draft_v2 = draft_v2_response.json()["data"]
    assert {
        "name": draft_v2["name"],
        "default_provider_id": draft_v2["default_provider_id"],
        "retention_days": draft_v2["retention_days"],
        "enabled": draft_v2["enabled"],
    } == {
        "name": "Requester Staged V2",
        "default_provider_id": provider_v2,
        "retention_days": 20,
        "enabled": False,
    }

    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        assert {key: getattr(profile, key) for key in active_v1} == active_v1
        assert profile.updated_at == active_v1_updated_at
        version_v1 = db.query(AiAgentProfileVersion).filter_by(profile_id=profile.id, version=1).one()
        assert {
            "id": version_v1.id,
            "version": version_v1.version,
            "status": version_v1.status,
            "config_snapshot": dict(version_v1.config_snapshot),
            "system_prompt_zh": version_v1.system_prompt_zh,
            "system_prompt_en": version_v1.system_prompt_en,
            "enabled_capabilities": list(version_v1.enabled_capabilities),
            "knowledge_scope": list(version_v1.knowledge_scope),
            "max_risk_level": version_v1.max_risk_level,
            "published_by": version_v1.published_by,
            "published_at": version_v1.published_at,
            "created_at": version_v1.created_at,
            "updated_at": version_v1.updated_at,
            "is_deleted": version_v1.is_deleted,
            "is_example": version_v1.is_example,
        } == immutable_v1

    rejected = client.post(
        "/api/admin/ai/profiles/requester/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v2["draft_updated_at"]},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "AI_PROFILE_PROVIDER_UNHEALTHY"
    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        assert {key: getattr(profile, key) for key in active_v1} == active_v1
        assert profile.updated_at == active_v1_updated_at
        version_v1 = db.query(AiAgentProfileVersion).filter_by(profile_id=profile.id, version=1).one()
        assert {
            "id": version_v1.id,
            "version": version_v1.version,
            "status": version_v1.status,
            "config_snapshot": dict(version_v1.config_snapshot),
            "system_prompt_zh": version_v1.system_prompt_zh,
            "system_prompt_en": version_v1.system_prompt_en,
            "enabled_capabilities": list(version_v1.enabled_capabilities),
            "knowledge_scope": list(version_v1.knowledge_scope),
            "max_risk_level": version_v1.max_risk_level,
            "published_by": version_v1.published_by,
            "published_at": version_v1.published_at,
            "created_at": version_v1.created_at,
            "updated_at": version_v1.updated_at,
            "is_deleted": version_v1.is_deleted,
            "is_example": version_v1.is_example,
        } == immutable_v1

        healthy_v2 = db.get(AiProviderConfig, provider_v2)
        healthy_v2.probe_status = "success"
        healthy_v2.last_probed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        healthy_v2.capability_probe = {
            "authentication": True,
            "supports_streaming": True,
            "supports_tools": True,
            "supports_json_schema": True,
        }
        healthy_v2.enabled = True
        db.commit()

    published_v2_response = client.post(
        "/api/admin/ai/profiles/requester/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": draft_v2["draft_updated_at"]},
    )
    assert published_v2_response.status_code == 200, published_v2_response.text
    assert published_v2_response.json()["data"]["version"] == 2
    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        assert profile.name == "Requester Staged V2"
        assert profile.default_provider_id == provider_v2
        assert profile.retention_days == 20
        assert profile.enabled is False

    rollback_response = client.post(
        "/api/admin/ai/profiles/requester/rollback",
        headers=admin_headers,
        json={"version": 1, "expected_latest_version": 2},
    )
    assert rollback_response.status_code == 200, rollback_response.text
    assert rollback_response.json()["data"]["version"] == 3
    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        assert {key: getattr(profile, key) for key in active_v1} == active_v1
        versions = (
            db.query(AiAgentProfileVersion)
            .filter_by(profile_id=profile.id, status="published")
            .order_by(AiAgentProfileVersion.version)
            .all()
        )
        assert [row.version for row in versions] == [1, 2, 3]
        assert versions[2].config_snapshot == versions[0].config_snapshot
        assert versions[2].system_prompt_en == versions[0].system_prompt_en


def test_legacy_profile_snapshot_rollback_fails_closed_and_complete_snapshot_rolls_back(
    client, admin_headers, monkeypatch
):
    """Filling a legacy snapshot from current active state must corrupt historical rollback."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-legacy-snapshot-provider")
    client.get("/api/admin/ai/profiles/bdo/draft", headers=admin_headers)

    with SessionLocal() as db:
        actor = db.query(AuthUser).filter_by(username="admin").one()
        profile = db.query(AiAgentProfile).filter_by(code="bdo").one()
        assert db.query(AiAgentProfileVersion).filter_by(
            profile_id=profile.id, status="published"
        ).count() == 0
        profile.name = "Legacy BDO Active"
        profile.default_provider_id = provider_id
        profile.retention_days = 7
        profile.enabled = True
        profile.max_risk_level = "L1"
        profile.status = "published"
        legacy = AiAgentProfileVersion(
            profile_id=profile.id,
            version=1,
            status="published",
            system_prompt_zh="旧版 BDO 助手",
            system_prompt_en="Legacy BDO assistant",
            enabled_capabilities=["knowledge.read"],
            knowledge_scope=["public"],
            config_snapshot={},
            max_risk_level="L1",
            published_by=actor.id,
            published_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

        run_migrations(db)
        db.expire_all()
        assert db.get(AiAgentProfileVersion, legacy_id).config_snapshot == {}

    draft = client.get("/api/admin/ai/profiles/bdo/draft", headers=admin_headers).json()["data"]
    staged_v2_response = client.patch(
        "/api/admin/ai/profiles/bdo/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": draft["draft_updated_at"],
            "name": "BDO Complete V2",
            "default_provider_id": provider_id,
            "retention_days": 22,
            "enabled": True,
            "system_prompt_zh": "完整快照版本二",
            "system_prompt_en": "Complete snapshot version two",
            "enabled_capabilities": ["knowledge.read"],
            "knowledge_scope": ["public", "own_requirements"],
            "max_risk_level": "L1",
        },
    )
    assert staged_v2_response.status_code == 200, staged_v2_response.text
    staged_v2 = staged_v2_response.json()["data"]
    published_v2 = client.post(
        "/api/admin/ai/profiles/bdo/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": staged_v2["draft_updated_at"]},
    )
    assert published_v2.status_code == 200, published_v2.text
    assert published_v2.json()["data"]["version"] == 2

    def persisted_state():
        with SessionLocal() as db:
            profile = db.query(AiAgentProfile).filter_by(code="bdo").one()
            profile_state = {column.key: getattr(profile, column.key) for column in profile.__table__.columns}
            versions = (
                db.query(AiAgentProfileVersion)
                .filter_by(profile_id=profile.id, status="published")
                .order_by(AiAgentProfileVersion.version)
                .all()
            )
            version_state = [
                {column.key: getattr(row, column.key) for column in row.__table__.columns}
                for row in versions
            ]
            return profile_state, version_state

    before_rejected_rollback = persisted_state()
    rejected = client.post(
        "/api/admin/ai/profiles/bdo/rollback",
        headers=admin_headers,
        json={"version": 1, "expected_latest_version": 2},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "AI_PROFILE_LEGACY_SNAPSHOT_UNAVAILABLE"
    assert persisted_state() == before_rejected_rollback

    current = client.get("/api/admin/ai/profiles/bdo/draft", headers=admin_headers).json()["data"]
    staged_v3_response = client.patch(
        "/api/admin/ai/profiles/bdo/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": current["draft_updated_at"],
            "name": "BDO Complete V3",
            "default_provider_id": provider_id,
            "retention_days": 33,
            "enabled": False,
            "system_prompt_zh": "完整快照版本三",
            "system_prompt_en": "Complete snapshot version three",
        },
    )
    assert staged_v3_response.status_code == 200, staged_v3_response.text
    staged_v3 = staged_v3_response.json()["data"]
    published_v3 = client.post(
        "/api/admin/ai/profiles/bdo/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": staged_v3["draft_updated_at"]},
    )
    assert published_v3.status_code == 200, published_v3.text
    assert published_v3.json()["data"]["version"] == 3

    rolled_back = client.post(
        "/api/admin/ai/profiles/bdo/rollback",
        headers=admin_headers,
        json={"version": 2, "expected_latest_version": 3},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["data"]["version"] == 4

    with SessionLocal() as db:
        profile = db.query(AiAgentProfile).filter_by(code="bdo").one()
        assert profile.name == "BDO Complete V2"
        assert profile.default_provider_id == provider_id
        assert profile.retention_days == 22
        assert profile.enabled is True
        versions = (
            db.query(AiAgentProfileVersion)
            .filter_by(profile_id=profile.id, status="published")
            .order_by(AiAgentProfileVersion.version)
            .all()
        )
        assert [row.version for row in versions] == [1, 2, 3, 4]
        assert versions[0].config_snapshot == {}
        assert versions[1].config_snapshot == {
            "schema_version": 1,
            "name": "BDO Complete V2",
            "default_provider_id": provider_id,
            "retention_days": 22,
            "enabled": True,
        }
        assert versions[2].config_snapshot["schema_version"] == 1
        assert versions[3].config_snapshot == versions[1].config_snapshot


def test_health_usage_and_action_audits_are_aggregate_redacted_allowlists(
    client, admin_headers, monkeypatch
):
    """Returning stored payload/error/message/secret fields must break the admin read boundary."""
    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-metrics-provider")
    client.get("/api/admin/ai/profiles/requester/draft", headers=admin_headers)
    sensitive_values = {
        "prompt": "raw-prompt-must-not-leak",
        "secret": "raw-secret-must-not-leak",
        "token": "raw-token-hash-must-not-leak",
        "payload": "raw-normalized-payload-must-not-leak",
    }
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter_by(username="admin").one()
        profile = db.query(AiAgentProfile).filter_by(code="requester").one()
        conversation = AiConversation(auth_user_id=admin.id, profile_id=profile.id, page_context={})
        db.add(conversation)
        db.flush()
        db.add(
            AiProviderCall(
                provider_id=provider_id,
                conversation_id=conversation.id,
                model="aggregate-model",
                purpose="chat",
                input_tokens=12,
                output_tokens=7,
                duration_ms=40,
                result_code="PROVIDER_TIMEOUT",
                status="failed",
                error_redacted={"prompt": sensitive_values["prompt"], "secret": sensitive_values["secret"]},
            )
        )
        action = AiAction(
            conversation_id=conversation.id,
            auth_user_id=admin.id,
            capability_code="knowledge.read",
            risk_level="L1",
            normalized_payload={"value": sensitive_values["payload"]},
            payload_digest="d" * 64,
            token_hash=sensitive_values["token"],
            idempotency_key="wa0-audit-action",
            status="failed",
            result_code="DOMAIN_REJECTED",
            result_summary={"secret": sensitive_values["secret"]},
            result_entity_type="ticket",
            result_entity_id="TK-PUBLIC-001",
        )
        db.add(action)
        db.commit()
        action_id = action.id

    health_response = client.get("/api/admin/ai/health", headers=admin_headers)
    assert health_response.status_code == 200, health_response.text
    health = health_response.json()["data"]
    assert set(health) == {"providers", "profiles"}
    assert set(health["providers"]) == {"total", "enabled", "healthy", "failed", "unverified"}
    assert set(health["profiles"]) == {"fixed_total", "published", "enabled"}

    usage_response = client.get("/api/admin/ai/usage", headers=admin_headers)
    assert usage_response.status_code == 200, usage_response.text
    usage = usage_response.json()["data"]
    assert set(usage) == {
        "window_days",
        "window_started_at",
        "total_calls",
        "completed_calls",
        "failed_calls",
        "input_tokens",
        "output_tokens",
        "average_duration_ms",
        "by_provider",
        "by_result_code",
    }
    assert usage["total_calls"] >= 1
    assert all(set(row) == {"provider_code", "calls", "input_tokens", "output_tokens"} for row in usage["by_provider"])
    assert all(set(row) == {"result_code", "count"} for row in usage["by_result_code"])

    audits_response = client.get(
        "/api/admin/ai/action-audits?page=1&page_size=20&status=failed",
        headers=admin_headers,
    )
    assert audits_response.status_code == 200, audits_response.text
    assert audits_response.json()["total"] >= 1
    action_row = next(row for row in audits_response.json()["data"] if row["id"] == action_id)
    assert set(action_row) == {
        "id",
        "capability_code",
        "risk_level",
        "status",
        "result_code",
        "result_entity_type",
        "result_entity_id",
        "created_at",
        "consumed_at",
    }

    combined = health_response.text + usage_response.text + audits_response.text
    for sensitive in sensitive_values.values():
        assert sensitive not in combined
    for forbidden_key in (
        "normalized_payload",
        "payload_digest",
        "token_hash",
        "result_summary",
        "error_redacted",
        "conversation_id",
        "message_id",
        "api_key_encrypted",
    ):
        assert forbidden_key not in combined


def test_usage_uses_bounded_sql_aggregates_and_excludes_rows_outside_window(
    client, admin_headers, monkeypatch
):
    """Removing the SQL/window boundary must count old calls or select sensitive call rows."""
    from sqlalchemy import event

    from app.db import engine

    provider_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-window-provider")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        db.query(AiProviderCall).delete(synchronize_session=False)
        db.add_all(
            [
                AiProviderCall(
                    provider_id=provider_id,
                    model="window-model",
                    purpose="chat",
                    input_tokens=5,
                    output_tokens=3,
                    duration_ms=20,
                    result_code="OK",
                    status="completed",
                    created_at=now - timedelta(days=2),
                ),
                AiProviderCall(
                    provider_id=provider_id,
                    model="window-model",
                    purpose="chat",
                    input_tokens=7,
                    output_tokens=4,
                    duration_ms=40,
                    result_code="PROVIDER_TIMEOUT",
                    status="failed",
                    error_redacted={"must_not_be_selected": "sensitive"},
                    created_at=now - timedelta(days=3),
                ),
                AiProviderCall(
                    provider_id=provider_id,
                    model="window-model-old",
                    purpose="chat",
                    input_tokens=1000,
                    output_tokens=1000,
                    duration_ms=9999,
                    result_code="OLD_FAILURE",
                    status="failed",
                    error_redacted={"old_sensitive": "must-not-load"},
                    created_at=now - timedelta(days=31),
                ),
            ]
        )
        db.commit()

    captured_sql: list[str] = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "ai_provider_call" in statement.lower():
            captured_sql.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        response = client.get("/api/admin/ai/usage?days=30", headers=admin_headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    usage = response.json()["data"]
    assert usage["window_days"] == 30
    assert usage["window_started_at"] is not None
    assert usage["total_calls"] == 2
    assert usage["completed_calls"] == 1
    assert usage["failed_calls"] == 1
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 7
    assert usage["average_duration_ms"] == 30
    assert usage["by_result_code"] == [
        {"result_code": "OK", "count": 1},
        {"result_code": "PROVIDER_TIMEOUT", "count": 1},
    ]
    assert usage["by_provider"] == [
        {"provider_code": "wa0-window-provider", "calls": 2, "input_tokens": 12, "output_tokens": 7}
    ]
    assert captured_sql
    for statement in captured_sql:
        assert "error_redacted" not in statement
        assert "conversation_id" not in statement
        assert "message_id" not in statement
        assert "profile_version_id" not in statement
        assert "ai_provider_call.model" not in statement

    for invalid_days in (0, 91):
        invalid = client.get(f"/api/admin/ai/usage?days={invalid_days}", headers=admin_headers)
        assert invalid.status_code == 422, invalid.text


def test_provider_delete_is_soft_audited_and_rejects_live_profile_reference(
    client, admin_headers, monkeypatch
):
    """Deleting an in-use provider or omitting its redacted audit must break configuration integrity."""
    from app.services import assistant_config

    monkeypatch.setattr(assistant_config, "capability_registry", _test_registry(), raising=False)
    monkeypatch.setattr(settings, "ai_provider_allowed_hosts", "models.example.test")
    deletable_payload = {**VALID_PROVIDER, "code": "wa0-delete-provider", "name": "Delete", "is_primary": False}
    deletable_id = client.post("/api/admin/ai/providers", headers=admin_headers, json=deletable_payload).json()["data"]["id"]
    deleted_response = client.delete(f"/api/admin/ai/providers/{deletable_id}", headers=admin_headers)
    assert deleted_response.status_code == 200, deleted_response.text
    assert all(
        row["id"] != deletable_id
        for row in client.get("/api/admin/ai/providers", headers=admin_headers).json()["data"]
    )

    referenced_id = _create_healthy_provider(client, admin_headers, monkeypatch, "wa0-referenced-provider")
    draft = client.get("/api/admin/ai/profiles/admin/draft", headers=admin_headers).json()["data"]
    saved = client.patch(
        "/api/admin/ai/profiles/admin/draft",
        headers=admin_headers,
        json={
            "expected_updated_at": draft["draft_updated_at"],
            "default_provider_id": referenced_id,
            "system_prompt_zh": "管理员活动档案",
            "system_prompt_en": "Administrator active profile",
            "enabled_capabilities": ["knowledge.read"],
            "knowledge_scope": ["public"],
            "max_risk_level": "L1",
            "enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        "/api/admin/ai/profiles/admin/publish",
        headers=admin_headers,
        json={"expected_draft_updated_at": saved.json()["data"]["draft_updated_at"]},
    )
    assert published.status_code == 200, published.text
    blocked = client.delete(f"/api/admin/ai/providers/{referenced_id}", headers=admin_headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "AI_PROVIDER_IN_USE"

    with SessionLocal() as db:
        deleted = db.get(AiProviderConfig, deletable_id)
        assert deleted.is_deleted is True
        delete_audit = db.query(AuditLog).filter_by(
            entity_type="ai_provider_config", entity_id=deletable_id, action="delete"
        ).one()
        serialized = json.dumps(delete_audit.summary)
        assert VALID_PROVIDER["api_key"] not in serialized
        assert deleted.api_key_encrypted not in serialized
