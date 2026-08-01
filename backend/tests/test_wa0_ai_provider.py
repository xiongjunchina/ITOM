"""WA0 secure OpenAI-compatible provider and gateway contracts."""

import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import json
import secrets
from types import SimpleNamespace

import httpx
import pytest

import app.assistant.providers as provider_api
from app.assistant.providers import OpenAICompatibleProvider, ProviderConfigurationError
from app.db import SessionLocal
from app.models import AiProviderCall, AiProviderConfig
from app.services.secrets_store import encrypt_secret


def _config(
    *,
    base_url: str = "https://models.example.test/v1",
    enabled: bool = True,
    api_key_encrypted: str | None = None,
):
    return SimpleNamespace(
        id="provider-test-id",
        code="test-provider",
        name="Test provider",
        provider_type="openai_compatible",
        api_base_url=base_url,
        api_key_encrypted=api_key_encrypted,
        model="test-model",
        timeout_seconds=30,
        max_output_tokens=512,
        temperature=0.1,
        capability_probe={},
        probe_status="success",
        last_probed_at=None,
        is_primary=True,
        fallback_provider_id=None,
        enabled=enabled,
        is_deleted=False,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://models.example.test/v1",
        "https://user:password@models.example.test/v1",
        "https://models.example.test/v1?token=unsafe",
        "https://models.example.test/v1#fragment",
        "https://models.example.test/v1/../admin",
        "https://models.example.test/v1%2f..%2fadmin",
    ],
)
def test_provider_rejects_unsafe_base_urls_before_any_request(base_url):
    """Weakening scheme, credential, query, fragment, or path checks must fail this boundary."""
    with pytest.raises(ProviderConfigurationError):
        OpenAICompatibleProvider(_config(base_url=base_url), allowed_hosts="models.example.test")


def test_provider_requires_explicit_exact_or_controlled_suffix_allowlist():
    """Removing fail-closed host matching would permit an unapproved model endpoint."""
    with pytest.raises(ProviderConfigurationError):
        OpenAICompatibleProvider(_config(), allowed_hosts="")
    with pytest.raises(ProviderConfigurationError):
        OpenAICompatibleProvider(_config(), allowed_hosts="other.example.test")

    exact = OpenAICompatibleProvider(_config(), allowed_hosts="models.example.test")
    suffix = OpenAICompatibleProvider(
        _config(base_url="https://region.models.example.test/openai/v1/"),
        allowed_hosts="*.models.example.test",
    )

    assert str(exact.endpoint_url) == "https://models.example.test/v1/chat/completions"
    assert str(suffix.endpoint_url) == "https://region.models.example.test/openai/v1/chat/completions"


async def _public_dns(_host: str, _port: int):
    return ["93.184.216.34"]


def _run(awaitable):
    return asyncio.run(awaitable)


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _probe_response():
    return {
        "id": "probe-response",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"status":"ok"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
    }


def test_probe_uses_approved_endpoint_header_and_structured_capability_payload():
    """Changing the request path/header/probe shape must break the provider boundary contract."""
    assert getattr(provider_api, "ProviderProbe", None) is not None
    secret = f"unit-{secrets.token_urlsafe(18)}"

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert request.url == httpx.URL("https://models.example.test/v1/chat/completions")
        assert request.url.query == b""
        assert request.headers["Authorization"] == f"Bearer {secret}"
        assert body["stream"] is False
        assert body["tools"][0]["function"]["name"] == "wa0_probe"
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json=_probe_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    provider = OpenAICompatibleProvider(
        _config(api_key_encrypted=encrypt_secret(secret)),
        allowed_hosts="models.example.test",
        client=client,
        resolver=_public_dns,
    )
    try:
        probe = _run(provider.probe())
    finally:
        _run(client.aclose())

    assert probe.success is True
    assert probe.supports_tools is True
    assert probe.supports_json_schema is True


@pytest.mark.parametrize(
    "unsafe_address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "100.100.100.200",
        "224.0.0.1",
        "0.0.0.0",
        "240.0.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_probe_rejects_non_public_and_metadata_dns_answers_before_transport(unsafe_address):
    """Removing address-class validation must allow SSRF to local or metadata networks."""
    requests = []

    async def resolver(_host: str, _port: int):
        return [unsafe_address]

    async def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json=_probe_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=resolver
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_ADDRESS_FORBIDDEN"
    assert requests == []


def test_dns_is_revalidated_immediately_before_every_request_to_block_rebinding():
    """Caching a prior public answer must let a later private DNS answer reach transport."""
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    request_count = 0

    async def resolver(_host: str, _port: int):
        return next(answers)

    async def handler(_request: httpx.Request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=_probe_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=resolver
    )
    try:
        assert _run(provider.probe()).success is True
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_ADDRESS_FORBIDDEN"
    assert request_count == 1


def test_probe_never_follows_redirects_even_when_injected_client_would():
    """Allowing redirects must permit the approved host to redirect into an unvalidated target."""
    seen = []

    async def handler(request: httpx.Request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example.test/chat/completions"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_REDIRECT_FORBIDDEN"
    assert seen == ["https://models.example.test/v1/chat/completions"]


@pytest.mark.parametrize(
    ("status_code", "result_code"),
    [(401, "PROVIDER_AUTH_FAILED"), (403, "PROVIDER_AUTH_FAILED"), (429, "PROVIDER_RATE_LIMITED"), (503, "PROVIDER_HTTP_5XX")],
)
def test_probe_http_errors_are_classified_without_echoing_secret(status_code, result_code):
    """Including provider response bodies or request headers in errors must leak a credential."""
    secret = f"unit-{secrets.token_urlsafe(18)}"

    async def handler(_request: httpx.Request):
        return httpx.Response(status_code, text=f"upstream echoed authorization={secret}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(api_key_encrypted=encrypt_secret(secret)),
        allowed_hosts="models.example.test",
        client=client,
        resolver=_public_dns,
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == result_code
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_probe_timeout_is_classified_without_request_or_secret_details():
    """Leaking a timeout's request representation must expose provider connection metadata."""
    secret = f"unit-{secrets.token_urlsafe(18)}"

    async def handler(request: httpx.Request):
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(api_key_encrypted=encrypt_secret(secret)),
        allowed_hosts="models.example.test",
        client=client,
        resolver=_public_dns,
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_TIMEOUT"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_probe_connect_failure_is_classified_without_raw_exception_details():
    """Propagating a connect exception must leak transport context instead of a stable safe code."""
    secret = f"connect-{secrets.token_urlsafe(18)}"

    async def handler(request: httpx.Request):
        raise httpx.ConnectError(f"unsafe transport detail {secret}", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider.probe())
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_CONNECT_FAILED"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


async def _collect_stream(provider, request):
    return [event async for event in provider.stream_chat(request)]


def _sse(*documents: object) -> str:
    lines = []
    for document in documents:
        lines.append(f"data: {json.dumps(document, separators=(',', ':'))}" if document != "[DONE]" else "data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def _chat_request(**overrides):
    values = {
        "messages": ({"role": "user", "content": "Check ticket status"},),
        "tools": (
            {
                "type": "function",
                "function": {
                    "name": "ticket_lookup",
                    "description": "Look up one visible ticket",
                    "parameters": {
                        "type": "object",
                        "properties": {"ticket_code": {"type": "string"}},
                        "required": ["ticket_code"],
                        "additionalProperties": False,
                    },
                },
            },
        ),
        "response_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        "risk_level": "L2",
    }
    values.update(overrides)
    return provider_api.ChatRequest(**values)


def test_stream_chat_redacts_input_and_assembles_text_tool_usage_and_terminal_events():
    """Dropping input redaction or chunk assembly must expose secrets or malformed tool arguments."""
    user_secret = f"user-{secrets.token_urlsafe(18)}"
    request = _chat_request(
        messages=(
            {
                "role": "user",
                "content": f"Check ticket; Authorization: Bearer {user_secret}",
                "api_key": user_secret,
            },
        )
    )
    stream = _sse(
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "Checking "}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "ticket_lookup", "arguments": '{"ticket_'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'code":"TK-1"}'}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 23, "completion_tokens": 8, "total_tokens": 31}},
        "[DONE]",
    )

    async def handler(http_request: httpx.Request):
        body = json.loads(http_request.content)
        rendered = json.dumps(body, ensure_ascii=False)
        assert user_secret not in rendered
        assert body["messages"][0]["api_key"] == "[REDACTED]"
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}
        assert body["tools"][0]["function"]["name"] == "ticket_lookup"
        assert body["response_format"]["json_schema"]["schema"] == request.response_schema
        return httpx.Response(200, text=stream, headers={"Content-Type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        events = _run(_collect_stream(provider, request))
    finally:
        _run(client.aclose())

    assert [event.kind for event in events] == ["text_delta", "tool_call", "usage", "done"]
    assert events[0].text == "Checking "
    assert events[1].tool_call_id == "call-1"
    assert events[1].tool_name == "ticket_lookup"
    assert events[1].arguments == {"ticket_code": "TK-1"}
    assert events[2].input_tokens == 23
    assert events[2].output_tokens == 8
    assert events[3].finish_reason == "tool_calls"


@pytest.mark.parametrize(
    "stream",
    [
        "event: ping\ndata: {}\n\n",
        "data: {not-json}\n\n",
        _sse({"unknown_event": {"value": 1}}, "[DONE]"),
        _sse({"choices": [{"index": 0, "delta": {"mystery": "value"}, "finish_reason": None}]}, "[DONE]"),
        _sse({"choices": [{"index": 0, "delta": {}, "finish_reason": None}]}, "[DONE]"),
        _sse({"choices": [{"index": 0, "delta": {"content": "partial"}, "finish_reason": "stop"}]}),
        _sse(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-bad",
                                    "type": "function",
                                    "function": {"name": "ticket_lookup", "arguments": '{"ticket_code":'},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            "[DONE]",
        ),
    ],
)
def test_stream_chat_fails_closed_for_unknown_malformed_or_truncated_protocol(stream):
    """Permissive parsing must turn unknown or incomplete model output into executable-looking events."""
    async def handler(_request: httpx.Request):
        return httpx.Response(200, text=stream, headers={"Content-Type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(_collect_stream(provider, _chat_request()))
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_STREAM_PROTOCOL_ERROR"


def test_stream_chat_rejects_tool_name_that_was_not_offered_in_this_request():
    """Accepting an unoffered tool name must let a model invent an executable-looking capability."""
    stream = _sse(
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-invented",
                                "type": "function",
                                "function": {"name": "invented_action", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        "[DONE]",
    )

    async def handler(_request: httpx.Request):
        return httpx.Response(200, text=stream, headers={"Content-Type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(_collect_stream(provider, _chat_request()))
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_STREAM_PROTOCOL_ERROR"


def _gateway_module():
    return importlib.import_module("app.assistant.gateway")


async def _collect_gateway(gateway, request):
    return [event async for event in gateway.stream(request)]


def _stream_response(text: str = "fallback answer") -> str:
    return _sse(
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 17, "completion_tokens": 5, "total_tokens": 22}},
        "[DONE]",
    )


def _provider_row(
    code: str,
    *,
    host: str,
    enabled: bool = True,
    probe_status: str = "success",
    last_probed_at: datetime | None = None,
    supports_tools: bool = True,
    supports_json_schema: bool = True,
    is_primary: bool = False,
):
    return AiProviderConfig(
        code=code,
        name=code,
        provider_type="openai_compatible",
        api_base_url=f"https://{host}/v1",
        model=f"{code}-model",
        timeout_seconds=30,
        max_output_tokens=512,
        temperature=0,
        capability_probe={
            "supports_tools": supports_tools,
            "supports_json_schema": supports_json_schema,
        },
        probe_status=probe_status,
        last_probed_at=last_probed_at or _utcnow_naive(),
        is_primary=is_primary,
        enabled=enabled,
    )


def test_gateway_falls_back_only_after_primary_failure_and_audits_redacted_attempts(client):
    """Removing compatible fallback or minimal audit fields must lose resilience or leak model input."""
    gateway_api = _gateway_module()
    secret = f"audit-{secrets.token_urlsafe(18)}"
    prompt = f"prompt-{secrets.token_urlsafe(18)}"
    clients = []

    with SessionLocal() as db:
        primary = _provider_row("wa0-gateway-primary", host="primary.models.example.test", is_primary=True)
        fallback = _provider_row("wa0-gateway-fallback", host="fallback.models.example.test")
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        primary.api_key_encrypted = encrypt_secret(secret)
        db.commit()

        async def primary_handler(_request: httpx.Request):
            return httpx.Response(503, text=f"authorization={secret}; prompt={prompt}")

        async def fallback_handler(_request: httpx.Request):
            return httpx.Response(
                200,
                text=_stream_response(),
                headers={"Content-Type": "text/event-stream"},
            )

        def provider_factory(config):
            handler = primary_handler if config.id == primary.id else fallback_handler
            http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return OpenAICompatibleProvider(
                config,
                allowed_hosts="*.models.example.test",
                client=http_client,
                resolver=_public_dns,
            )

        request = _chat_request(messages=({"role": "user", "content": prompt},))
        gateway = gateway_api.AssistantGateway(
            db, provider_factory=provider_factory, primary_provider_id=primary.id
        )
        events = _run(_collect_gateway(gateway, request))

        assert [event.kind for event in events] == ["text_delta", "usage", "done"]
        assert events[0].text == "fallback answer"
        calls = db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).order_by(AiProviderCall.created_at, AiProviderCall.id).all()
        assert [(call.provider_id, call.result_code, call.status) for call in calls] == [
            (primary.id, "PROVIDER_HTTP_5XX", "failed"),
            (fallback.id, "OK_FALLBACK", "completed"),
        ]
        assert calls[1].input_tokens == 17
        assert calls[1].output_tokens == 5
        rendered_audit = json.dumps([call.error_redacted for call in calls], ensure_ascii=False)
        assert secret not in rendered_audit
        assert prompt not in rendered_audit
        assert set(calls[0].error_redacted) == {"code", "message"}
        assert "messages" not in AiProviderCall.__table__.columns

    for http_client in clients:
        _run(http_client.aclose())


@pytest.mark.parametrize("risk_level", ["L2", "L3"])
@pytest.mark.parametrize(
    ("supports_tools", "supports_json_schema"),
    [(False, True), (True, False), (False, False)],
)
def test_gateway_rejects_l2_l3_provider_without_both_required_capabilities(
    client, risk_level, supports_tools, supports_json_schema
):
    """Weakening either capability check must expose a high-risk request to an incompatible model."""
    gateway_api = _gateway_module()
    transport_calls = 0
    suffix = f"{risk_level.lower()}-{int(supports_tools)}-{int(supports_json_schema)}"

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-incompatible-{suffix}",
            host=f"{suffix}.models.example.test",
            supports_tools=supports_tools,
            supports_json_schema=supports_json_schema,
            is_primary=True,
        )
        db.add(provider_row)
        db.commit()

        async def handler(_request: httpx.Request):
            nonlocal transport_calls
            transport_calls += 1
            return httpx.Response(200, text=_stream_response(), headers={"Content-Type": "text/event-stream"})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=provider_row.id,
            provider_factory=lambda config: OpenAICompatibleProvider(
                config,
                allowed_hosts="*.models.example.test",
                client=http_client,
                resolver=_public_dns,
            ),
        )
        try:
            with pytest.raises(Exception) as caught:
                _run(_collect_gateway(gateway, _chat_request(risk_level=risk_level)))
        finally:
            _run(http_client.aclose())

        assert getattr(caught.value, "code", None) == "GATEWAY_NO_COMPATIBLE_PROVIDER"
        assert transport_calls == 0
        assert db.query(AiProviderCall).filter_by(provider_id=provider_row.id).count() == 0


@pytest.mark.parametrize("fallback_state", ["disabled", "unhealthy", "stale", "incompatible"])
def test_gateway_never_calls_disabled_unhealthy_stale_or_incompatible_fallback(client, fallback_state):
    """Relaxing fallback selection must cross the request's health or capability policy."""
    gateway_api = _gateway_module()
    fallback_calls = 0
    clients = []

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-primary-{fallback_state}",
            host=f"primary-{fallback_state}.models.example.test",
            is_primary=True,
        )
        fallback = _provider_row(
            f"wa0-fallback-{fallback_state}",
            host=f"fallback-{fallback_state}.models.example.test",
            enabled=fallback_state != "disabled",
            probe_status="failed" if fallback_state == "unhealthy" else "success",
            last_probed_at=(_utcnow_naive() - timedelta(hours=2)) if fallback_state == "stale" else _utcnow_naive(),
            supports_tools=fallback_state != "incompatible",
            supports_json_schema=True,
        )
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        db.commit()

        async def primary_handler(_request: httpx.Request):
            return httpx.Response(503)

        async def fallback_handler(_request: httpx.Request):
            nonlocal fallback_calls
            fallback_calls += 1
            return httpx.Response(200, text=_stream_response(), headers={"Content-Type": "text/event-stream"})

        def provider_factory(config):
            handler = primary_handler if config.id == primary.id else fallback_handler
            http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return OpenAICompatibleProvider(
                config,
                allowed_hosts="*.models.example.test",
                client=http_client,
                resolver=_public_dns,
            )

        gateway = gateway_api.AssistantGateway(
            db, provider_factory=provider_factory, primary_provider_id=primary.id
        )
        with pytest.raises(Exception) as caught:
            _run(_collect_gateway(gateway, _chat_request(risk_level="L2")))

        assert getattr(caught.value, "code", None) == "GATEWAY_ALL_PROVIDERS_FAILED"
        assert fallback_calls == 0
        calls = db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).all()
        assert len(calls) == 1
        assert calls[0].provider_id == primary.id

    for http_client in clients:
        _run(http_client.aclose())


@pytest.mark.parametrize("risk_level", ["L4", "UNKNOWN"])
def test_gateway_rejects_forbidden_or_unknown_risk_before_provider_selection(client, risk_level):
    """Treating unrecognised risk like L1 must let L4 or malformed requests reach a model."""
    gateway_api = _gateway_module()
    transport_calls = 0

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-risk-{risk_level.lower()}",
            host=f"risk-{risk_level.lower()}.models.example.test",
            is_primary=True,
        )
        db.add(provider_row)
        db.commit()

        async def handler(_request: httpx.Request):
            nonlocal transport_calls
            transport_calls += 1
            return httpx.Response(200, text=_stream_response(), headers={"Content-Type": "text/event-stream"})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=provider_row.id,
            provider_factory=lambda config: OpenAICompatibleProvider(
                config,
                allowed_hosts="*.models.example.test",
                client=http_client,
                resolver=_public_dns,
            ),
        )
        try:
            with pytest.raises(Exception) as caught:
                _run(_collect_gateway(gateway, _chat_request(risk_level=risk_level)))
        finally:
            _run(http_client.aclose())

        assert getattr(caught.value, "code", None) == "GATEWAY_RISK_FORBIDDEN"
        assert transport_calls == 0
        assert db.query(AiProviderCall).filter_by(provider_id=provider_row.id).count() == 0


async def _read_one_gateway_event_and_close(gateway, request):
    stream = gateway.stream(request)
    first = await anext(stream)
    await stream.aclose()
    return first


def test_gateway_audits_client_cancelled_stream_without_attempting_fallback(client):
    """Dropping cancellation audit must leave a real outbound call untracked or trigger unsafe fallback."""
    gateway_api = _gateway_module()
    fallback_calls = 0
    clients = []

    with SessionLocal() as db:
        primary = _provider_row(
            "wa0-cancel-primary", host="cancel-primary.models.example.test", is_primary=True
        )
        fallback = _provider_row("wa0-cancel-fallback", host="cancel-fallback.models.example.test")
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        db.commit()

        async def primary_handler(_request: httpx.Request):
            return httpx.Response(
                200,
                text=_stream_response("first visible delta"),
                headers={"Content-Type": "text/event-stream"},
            )

        async def fallback_handler(_request: httpx.Request):
            nonlocal fallback_calls
            fallback_calls += 1
            return httpx.Response(200, text=_stream_response(), headers={"Content-Type": "text/event-stream"})

        def provider_factory(config):
            handler = primary_handler if config.id == primary.id else fallback_handler
            http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return OpenAICompatibleProvider(
                config,
                allowed_hosts="*.models.example.test",
                client=http_client,
                resolver=_public_dns,
            )

        gateway = gateway_api.AssistantGateway(
            db, primary_provider_id=primary.id, provider_factory=provider_factory
        )
        first = _run(_read_one_gateway_event_and_close(gateway, _chat_request()))

        assert first.kind == "text_delta"
        calls = db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).all()
        assert [(call.provider_id, call.result_code, call.status) for call in calls] == [
            (primary.id, "PROVIDER_STREAM_CANCELLED", "cancelled")
        ]
        assert fallback_calls == 0

    for http_client in clients:
        _run(http_client.aclose())
