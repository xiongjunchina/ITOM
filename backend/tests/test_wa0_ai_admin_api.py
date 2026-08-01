"""WA0 administrator-only provider and agent-profile governance contracts."""

import hashlib
import json
from datetime import datetime, timezone

import asyncio
import httpx
import pytest
from pydantic import BaseModel

from app.assistant.registry import CapabilityRegistry
from app.assistant.types import AssistantChannel, CapabilityDefinition, CapabilityResult, RiskLevel
from app.assistant.providers import OpenAICompatibleProvider
from app.core.config import settings
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
        assert profile.enabled is True
        assert db.query(AiAgentProfileVersion).filter_by(profile_id=profile.id, status="published").count() == 0


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


def test_provider_delete_is_soft_audited_and_rejects_live_profile_reference(
    client, admin_headers, monkeypatch
):
    """Deleting an in-use provider or omitting its redacted audit must break configuration integrity."""
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
        json={"expected_updated_at": draft["draft_updated_at"], "default_provider_id": referenced_id},
    )
    assert saved.status_code == 200, saved.text
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
