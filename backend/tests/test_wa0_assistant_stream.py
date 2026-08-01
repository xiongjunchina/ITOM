"""WA0 guarded assistant orchestration and POST-SSE contracts."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.assistant.gateway import GatewayError
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.providers import ModelStreamEvent
from app.assistant.registry import register_capability, registry
from app.assistant.types import (
    AssistantChannel,
    CapabilityDefinition,
    CapabilityResult,
    RiskLevel,
)
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
from app.routers import assistant as assistant_router


READ_CODE = "wa0.stream.read"
ACTION_CODE = "wa0.stream.prepare"
PAGE_CONTEXT = {"route": "/itsm/tickets", "page_type": "ticket_list"}


class _ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


class _ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


class _ReadHandler:
    def __init__(self):
        self.calls = 0

    def __call__(self, _db, _actor, data):
        self.calls += 1
        return CapabilityResult(status="succeeded", data={"items": [{"title": data.query}]})


class _ActionHandler:
    def __init__(self):
        self.executions = 0

    def authorize_preview(self, _db, _actor, _data):
        return None

    def preview(self, _db, _actor, data):
        return CapabilityResult(status="prepared", data={"title": data.title, "status": "preview"})

    def authorize_record(self, _db, _actor, _data):
        return None

    def __call__(self, _db, _actor, _data):
        self.executions += 1
        return CapabilityResult(status="succeeded", data={"entity_id": "must-not-run"})


READ_HANDLER = _ReadHandler()
ACTION_HANDLER = _ActionHandler()


class FakeProvider:
    """Deterministic gateway double; assertions target orchestrator behavior, not the fake."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.requests = []
        self.cancelled = False

    async def stream(self, request):
        self.requests.append(request)
        if not self.rounds:
            raise AssertionError("unexpected provider round")
        response = self.rounds.pop(0)
        if isinstance(response, BaseException):
            raise response
        try:
            for event in response:
                if isinstance(event, tuple) and event[0] == "sleep":
                    await asyncio.sleep(event[1])
                    continue
                await asyncio.sleep(0)
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            self.cancelled = True
            raise


def _events(*items):
    return list(items)


def _create_user(client, admin_headers, username: str) -> tuple[dict, str]:
    person = client.post("/api/members", json={"name": username}, headers=admin_headers).json()["data"]
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass1234", "roles": ["requester"], "person_id": person["id"]},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    assert login.status_code == 200, login.text
    with SessionLocal() as db:
        user_id = db.query(AuthUser).filter(AuthUser.username == username).one().id
    return {"Authorization": f"Bearer {login.json()['data']['token']}"}, user_id


def _install_runtime(*, retention_days: int = 30) -> tuple[str, str]:
    with SessionLocal() as db:
        for profile in db.query(AiAgentProfile).filter(AiAgentProfile.audience == "requester"):
            profile.enabled = False
        provider = AiProviderConfig(
            code=f"wa0-stream-provider-{db.query(AiProviderConfig).count()}",
            name="WA0 stream provider",
            provider_type="openai_compatible",
            api_base_url="https://provider.example.test/v1",
            model="wa0-stream",
            enabled=True,
            is_primary=True,
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
        profile = AiAgentProfile(
            code=f"wa0-stream-requester-{db.query(AiAgentProfile).count()}",
            name="WA0 stream requester",
            audience="requester",
            default_provider_id=provider.id,
            max_risk_level="L3",
            status="published",
            enabled=True,
            retention_days=retention_days,
        )
        db.add(profile)
        db.flush()
        version = AiAgentProfileVersion(
            profile_id=profile.id,
            version=1,
            status="published",
            system_prompt_zh="你是已发布的 ITOM 助手。",
            system_prompt_en="You are the published ITOM assistant.",
            enabled_capabilities=[READ_CODE, ACTION_CODE],
            knowledge_scope=["public"],
            config_snapshot={
                "schema_version": 1,
                "name": profile.name,
                "default_provider_id": provider.id,
                "retention_days": retention_days,
                "enabled": True,
            },
            max_risk_level="L3",
            published_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(version)
        db.commit()
        return profile.id, version.id


@pytest.fixture(scope="module", autouse=True)
def _registered_capabilities(client):
    if registry.get(READ_CODE) is None:
        register_capability(CapabilityDefinition(
            code=READ_CODE,
            channels=frozenset({AssistantChannel.WEB}),
            audiences=frozenset({"requester"}),
            module=None,
            action=None,
            risk=RiskLevel.L1,
            input_model=_ReadInput,
            handler=READ_HANDLER,
            description="Read a safe test record",
        ))
    if registry.get(ACTION_CODE) is None:
        register_capability(CapabilityDefinition(
            code=ACTION_CODE,
            channels=frozenset({AssistantChannel.WEB}),
            audiences=frozenset({"requester"}),
            module=None,
            action=None,
            risk=RiskLevel.L3,
            input_model=_ActionInput,
            handler=ACTION_HANDLER,
            requires_confirmation=True,
            description="Prepare a guarded test action",
        ))


def _conversation(user_id: str, profile_id: str, version_id: str) -> str:
    with SessionLocal() as db:
        row = AiConversation(
            auth_user_id=user_id,
            profile_id=profile_id,
            profile_version_id=version_id,
            language="zh-CN",
            page_context=PAGE_CONTEXT,
        )
        db.add(row)
        db.commit()
        return row.id


def _decode_sse(body: str) -> list[dict]:
    decoded = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        assert len(lines) == 2, block
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        decoded.append({"type": lines[0][7:], "data": json.loads(lines[1][6:])})
    return decoded


def _post_stream(client, monkeypatch, headers, conversation_id: str, fake: FakeProvider, *, client_id="msg-0001", content="请查询"):
    real = AssistantOrchestrator
    monkeypatch.setattr(
        assistant_router,
        "AssistantOrchestrator",
        lambda db, actor, **kwargs: real(db, actor, gateway=fake, **kwargs),
    )
    response = client.post(
        f"/api/assistant/conversations/{conversation_id}/messages",
        headers=headers,
        json={
            "content": content,
            "client_message_id": client_id,
            "page_context": PAGE_CONTEXT,
        },
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    return _decode_sse(response.text)


def test_post_sse_normal_delta_has_fixed_order_and_one_done(client, admin_headers, monkeypatch):
    """Removing meta/delta/message/done ordering must break the browser stream contract."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_normal")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(
        ModelStreamEvent(kind="text_delta", text="您好\n\nevent: injected"),
        ModelStreamEvent(kind="done", finish_reason="stop"),
    )])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert [event["type"] for event in events] == ["meta", "delta", "message", "done"]
    assert events[1]["data"]["text"] == "您好\n\nevent: injected"
    assert sum(event["type"] == "done" for event in events) == 1
    assert events[-1]["data"] == {"finish_reason": "stop"}


def test_fixed_tool_code_is_reauthorized_and_result_is_untrusted(client, admin_headers, monkeypatch):
    """Skipping request-time registry authorization would let model-selected tools bypass ITOM policy."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_tool")
    conversation_id = _conversation(user_id, profile_id, version_id)
    before = READ_HANDLER.calls
    fake = FakeProvider([
        _events(
            ModelStreamEvent(kind="tool_call", tool_call_id="call-1", tool_name=READ_CODE, arguments={"query": "TK-1"}),
            ModelStreamEvent(kind="done", finish_reason="tool_calls"),
        ),
        _events(ModelStreamEvent(kind="text_delta", text="找到了可见记录"), ModelStreamEvent(kind="done", finish_reason="stop")),
    ])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert READ_HANDLER.calls == before + 1
    assert [event["type"] for event in events] == ["meta", "delta", "message", "done"]
    second_messages = fake.requests[1].messages
    tool_message = next(message for message in second_messages if message.get("role") == "tool")
    assert "UNTRUSTED_TOOL_RESULT" in tool_message["content"]


def test_l3_stream_only_prepares_server_action_and_never_executes(client, admin_headers, monkeypatch):
    """Calling an L3 handler during streaming would bypass Task 6 explicit confirmation."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_action")
    conversation_id = _conversation(user_id, profile_id, version_id)
    before = ACTION_HANDLER.executions
    fake = FakeProvider([
        _events(
            ModelStreamEvent(kind="tool_call", tool_call_id="action-1", tool_name=ACTION_CODE, arguments={"title": "需要确认"}),
            ModelStreamEvent(kind="done", finish_reason="tool_calls"),
        ),
        _events(ModelStreamEvent(kind="text_delta", text="请确认预览"), ModelStreamEvent(kind="done", finish_reason="stop")),
    ])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert ACTION_HANDLER.executions == before
    assert [event["type"] for event in events] == ["meta", "action", "delta", "message", "done"]
    action = events[1]["data"]
    assert action["risk"] == "L3"
    assert action["preview"] == {"title": "需要确认", "status": "preview"}
    assert action["confirmation_token"]
    with SessionLocal() as db:
        row = db.get(AiAction, action["action_id"])
        assert row is not None and row.status == "prepared"
        assert row.token_hash and row.token_hash != action["confirmation_token"]


@pytest.mark.parametrize(
    "tool_name,arguments,expected_code",
    [
        ("unknown.tool", {"query": "x"}, "AI_ASSISTANT_TOOL_UNAVAILABLE"),
        (READ_CODE, {"query": "x", "role": "admin"}, "AI_ASSISTANT_TOOL_ARGUMENTS_INVALID"),
        (READ_CODE, {"query": "x", "handler": "unsafe"}, "AI_ASSISTANT_TOOL_ARGUMENTS_INVALID"),
        (READ_CODE, {"query": "x", "risk": "L0"}, "AI_ASSISTANT_TOOL_ARGUMENTS_INVALID"),
        (READ_CODE, {"query": "x", "result": {"status": "succeeded"}}, "AI_ASSISTANT_TOOL_ARGUMENTS_INVALID"),
    ],
)
def test_illegal_tool_code_or_arguments_fail_closed(client, admin_headers, monkeypatch, tool_name, arguments, expected_code):
    """Trusting model names or authority arguments would expose an unregistered execution path."""
    profile_id, version_id = _install_runtime()
    suffix = hashlib.sha256(json.dumps([tool_name, arguments], sort_keys=True).encode()).hexdigest()[:8]
    headers, user_id = _create_user(client, admin_headers, f"wa0_stream_illegal_{suffix}")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(
        ModelStreamEvent(kind="tool_call", tool_call_id="bad-1", tool_name=tool_name, arguments=arguments),
        ModelStreamEvent(kind="done", finish_reason="tool_calls"),
    )])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert [event["type"] for event in events] == ["meta", "error", "done"]
    assert events[1]["data"]["code"] == expected_code
    assert events[-1]["data"]["finish_reason"] == "error"


def test_repeated_identical_tool_call_stops_before_second_execution(client, admin_headers, monkeypatch):
    """Missing call fingerprints would let a model loop execute the same capability repeatedly."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_repeat")
    conversation_id = _conversation(user_id, profile_id, version_id)
    before = READ_HANDLER.calls
    repeated = _events(
        ModelStreamEvent(kind="tool_call", tool_call_id="repeat", tool_name=READ_CODE, arguments={"query": "same"}),
        ModelStreamEvent(kind="done", finish_reason="tool_calls"),
    )
    fake = FakeProvider([repeated, repeated])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert READ_HANDLER.calls == before + 1
    assert events[-2]["type"] == "error"
    assert events[-2]["data"]["code"] == "AI_ASSISTANT_TOOL_LOOP_REPEATED"


def test_more_than_four_tool_rounds_stops_safely(client, admin_headers, monkeypatch):
    """Removing the four-round bound would allow unbounded provider and capability work."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_limit")
    conversation_id = _conversation(user_id, profile_id, version_id)
    rounds = [
        _events(
            ModelStreamEvent(kind="tool_call", tool_call_id=f"call-{index}", tool_name=READ_CODE, arguments={"query": f"q-{index}"}),
            ModelStreamEvent(kind="done", finish_reason="tool_calls"),
        )
        for index in range(5)
    ]
    fake = FakeProvider(rounds)

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert len(fake.requests) == 4
    assert events[-2]["data"]["code"] == "AI_ASSISTANT_TOOL_LOOP_LIMIT"


def test_false_business_success_without_committed_server_result_is_blocked(client, admin_headers, monkeypatch):
    """Streaming model prose as success would make model text impersonate ITOM business state."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_false_success")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(
        ModelStreamEvent(kind="text_delta", text="工单已创建成功，编号 TK-FAKE"),
        ModelStreamEvent(kind="done", finish_reason="stop"),
    )])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert [event["type"] for event in events] == ["meta", "error", "done"]
    assert "TK-FAKE" not in json.dumps(events, ensure_ascii=False)
    with SessionLocal() as db:
        completed = db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id, AiMessage.role == "assistant", AiMessage.status == "completed").all()
        assert completed == []


def test_system_prompt_extraction_is_blocked_and_not_persisted(client, admin_headers, monkeypatch):
    """Returning a published instruction verbatim would disclose server authority."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_prompt_extract")
    conversation_id = _conversation(user_id, profile_id, version_id)
    extracted = "你是已发布的 ITOM 助手。"
    fake = FakeProvider([_events(
        ModelStreamEvent(kind="text_delta", text=extracted),
        ModelStreamEvent(kind="done", finish_reason="stop"),
    )])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake)

    assert [event["type"] for event in events] == ["meta", "error", "done"]
    assert events[1]["data"]["code"] == "AI_ASSISTANT_PROMPT_EXTRACTION_BLOCKED"
    assert extracted not in json.dumps(events, ensure_ascii=False)
    with SessionLocal() as db:
        assert db.query(AiMessage).filter(
            AiMessage.conversation_id == conversation_id,
            AiMessage.role == "assistant",
            AiMessage.status == "completed",
        ).count() == 0


@pytest.mark.parametrize(
    "provider_round",
    [
        GatewayError("GATEWAY_ALL_PROVIDERS_FAILED", "Bearer top-secret provider failure"),
        _events(ModelStreamEvent(kind="unknown", text="malformed"), ModelStreamEvent(kind="done", finish_reason="stop")),
        _events(ModelStreamEvent(kind="text_delta", text="partial without terminal")),
    ],
)
def test_provider_failures_return_generic_fallback_without_leakage(client, admin_headers, monkeypatch, provider_round):
    """Returning provider errors or partial output would leak internals and persist an incomplete answer."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, f"wa0_stream_failure_{abs(hash(str(provider_round))) % 100000}")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([provider_round])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake, content="Authorization: Bearer user-secret")

    assert [event["type"] for event in events] == ["meta", "error", "done"]
    serialized = json.dumps(events, ensure_ascii=False)
    assert "top-secret" not in serialized and "user-secret" not in serialized and "partial" not in serialized
    assert events[1]["data"]["fallback_path"].startswith("/")
    with SessionLocal() as db:
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id, AiMessage.role == "assistant", AiMessage.status == "completed").count() == 0


def test_retention_zero_keeps_only_bodyless_idempotency_metadata(client, admin_headers, monkeypatch):
    """Persisting text when captured retention is zero would violate the immutable privacy policy."""
    profile_id, version_id = _install_runtime(retention_days=0)
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_retention_zero")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(ModelStreamEvent(kind="text_delta", text="不应入库"), ModelStreamEvent(kind="done", finish_reason="stop"))])

    events = _post_stream(client, monkeypatch, headers, conversation_id, fake, content="用户正文不应入库")

    assert events[-1]["type"] == "done"
    with SessionLocal() as db:
        rows = db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).all()
        assert rows
        assert all(row.redacted_text is None for row in rows)
        assert "用户正文" not in json.dumps([row.content for row in rows], ensure_ascii=False)
        assert "不应入库" not in json.dumps([row.content for row in rows], ensure_ascii=False)


def test_cross_user_conversation_is_not_streamed(client, admin_headers, monkeypatch):
    """Dropping conversation ownership would expose another user's prompt and provider context."""
    profile_id, version_id = _install_runtime()
    alice_headers, alice_id = _create_user(client, admin_headers, "wa0_stream_alice")
    bob_headers, _bob_id = _create_user(client, admin_headers, "wa0_stream_bob")
    conversation_id = _conversation(alice_id, profile_id, version_id)
    fake = FakeProvider([_events(ModelStreamEvent(kind="text_delta", text="must not run"), ModelStreamEvent(kind="done", finish_reason="stop"))])

    events = _post_stream(client, monkeypatch, bob_headers, conversation_id, fake)

    assert [event["type"] for event in events] == ["error", "done"]
    assert events[0]["data"]["code"] == "AI_CONVERSATION_NOT_FOUND"
    assert fake.requests == []


def test_replayed_client_message_id_reuses_completed_result_without_second_provider_call(client, admin_headers, monkeypatch):
    """Ignoring client_message_id would duplicate model/tool work after browser retries."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_replay")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(ModelStreamEvent(kind="text_delta", text="稳定回复"), ModelStreamEvent(kind="done", finish_reason="stop"))])

    first = _post_stream(client, monkeypatch, headers, conversation_id, fake, client_id="same-client-message")
    second = _post_stream(client, monkeypatch, headers, conversation_id, fake, client_id="same-client-message")

    assert len(fake.requests) == 1
    assert [event["type"] for event in second] == ["meta", "message", "done"]
    assert first[-2]["data"]["message"]["content"]["text"] == second[-2]["data"]["message"]["content"]["text"]


def test_replayed_client_message_id_with_different_payload_fails_closed(client, admin_headers, monkeypatch):
    """Reusing an idempotency key for different content must not replay or call the provider."""
    profile_id, version_id = _install_runtime()
    headers, user_id = _create_user(client, admin_headers, "wa0_stream_replay_conflict")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(
        ModelStreamEvent(kind="text_delta", text="first"),
        ModelStreamEvent(kind="done", finish_reason="stop"),
    )])

    _post_stream(
        client,
        monkeypatch,
        headers,
        conversation_id,
        fake,
        client_id="same-conflict-message",
        content="first request",
    )
    conflict = _post_stream(
        client,
        monkeypatch,
        headers,
        conversation_id,
        fake,
        client_id="same-conflict-message",
        content="different request",
    )

    assert len(fake.requests) == 1
    assert [event["type"] for event in conflict] == ["error", "done"]
    assert conflict[0]["data"]["code"] == "AI_ASSISTANT_MESSAGE_IDEMPOTENCY_CONFLICT"


def test_disconnect_cancels_provider_and_does_not_complete_assistant_message(client, admin_headers):
    """Continuing work after disconnect could prepare tools or persist partial model output."""
    profile_id, version_id = _install_runtime()
    _headers, user_id = _create_user(client, admin_headers, "wa0_stream_disconnect")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(ModelStreamEvent(kind="text_delta", text="partial"), ("sleep", 1), ModelStreamEvent(kind="done", finish_reason="stop"))])
    checks = 0

    async def disconnected():
        nonlocal checks
        checks += 1
        return checks >= 3

    async def consume():
        with SessionLocal() as db:
            actor = db.get(AuthUser, user_id)
            stream = AssistantOrchestrator(db, actor, gateway=fake, disconnect_check=disconnected).stream_turn(
                conversation_id=conversation_id,
                content="start",
                client_message_id="disconnect-msg",
                page_context=PAGE_CONTEXT,
            )
            with pytest.raises(asyncio.CancelledError):
                async for _event in stream:
                    pass

    asyncio.run(consume())
    assert fake.cancelled is True
    with SessionLocal() as db:
        assert db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id, AiMessage.role == "assistant", AiMessage.status == "completed").count() == 0


def test_turn_timeout_is_bounded_and_safe(client, admin_headers):
    """Removing the turn deadline would let a provider occupy a worker indefinitely."""
    profile_id, version_id = _install_runtime()
    _headers, user_id = _create_user(client, admin_headers, "wa0_stream_timeout")
    conversation_id = _conversation(user_id, profile_id, version_id)
    fake = FakeProvider([_events(("sleep", 0.2), ModelStreamEvent(kind="done", finish_reason="stop"))])

    async def consume():
        with SessionLocal() as db:
            actor = db.get(AuthUser, user_id)
            return [event async for event in AssistantOrchestrator(db, actor, gateway=fake, turn_timeout_seconds=0.01).stream_turn(
                conversation_id=conversation_id,
                content="timeout",
                client_message_id="timeout-msg",
                page_context=PAGE_CONTEXT,
            )]

    events = asyncio.run(consume())
    assert [event["type"] for event in events] == ["meta", "error", "done"]
    assert events[1]["data"]["code"] == "AI_ASSISTANT_TIMEOUT"
