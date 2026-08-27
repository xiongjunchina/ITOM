"""WA0 secure OpenAI-compatible provider and gateway contracts."""

import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import ipaddress
import json
import secrets
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import httpcore
import httpx
import pytest

import app.assistant.providers as provider_api
from app.assistant.providers import OpenAICompatibleProvider, ProviderConfigurationError
from app.assistant.execution import BoundedToolExecutor
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
        "https://models.example.test/v1%252525252f..%252525252fadmin",
        "https://models.example.test/v1/%252525252e%252525252e/admin",
        "https://models.example.test/" + "%25" * 9 + "2fadmin",
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


def test_default_dns_resolution_never_enters_asyncio_default_executor(monkeypatch):
    """Using loop.getaddrinfo would silently enqueue DNS work on executor=None."""
    provider_module = importlib.import_module("app.assistant.providers.openai_compatible")
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
    ]
    monkeypatch.setattr(provider_module.socket, "getaddrinfo", lambda *_args, **_kwargs: records)
    provider = OpenAICompatibleProvider(_config(), allowed_hosts="models.example.test")

    async def resolve():
        loop = asyncio.get_running_loop()
        original = loop.run_in_executor
        seen_executors = []

        def guarded(executor, function, *args):
            seen_executors.append(executor)
            if executor is None:
                raise AssertionError("DNS entered the default executor")
            return original(executor, function, *args)

        monkeypatch.setattr(loop, "run_in_executor", guarded)
        addresses = await provider._validated_addresses(deadline_monotonic=time.monotonic() + 1)
        return addresses, seen_executors

    addresses, seen_executors = _run(resolve())
    assert addresses == ("2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34")
    assert None not in seen_executors


def test_dns_resolution_works_while_default_executor_is_blocked_without_queue_growth(monkeypatch):
    """A blocked default pool must not delay or accumulate provider DNS work."""
    from concurrent.futures import ThreadPoolExecutor

    provider_module = importlib.import_module("app.assistant.providers.openai_compatible")
    monkeypatch.setattr(
        provider_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )
    provider = OpenAICompatibleProvider(_config(), allowed_hosts="models.example.test")

    async def resolve():
        loop = asyncio.get_running_loop()
        default_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="blocked-default")
        loop.set_default_executor(default_executor)
        release = threading.Event()
        started = threading.Event()

        def blocker():
            started.set()
            release.wait(timeout=1)

        occupying = loop.run_in_executor(None, blocker)
        assert started.wait(timeout=0.5)
        queued_before = default_executor._work_queue.qsize()
        try:
            addresses = await asyncio.wait_for(
                provider._validated_addresses(deadline_monotonic=time.monotonic() + 0.2),
                timeout=0.25,
            )
            queued_after = default_executor._work_queue.qsize()
            return addresses, queued_before, queued_after
        finally:
            release.set()
            await occupying

    addresses, queued_before, queued_after = _run(resolve())
    assert addresses == ("93.184.216.34",)
    assert queued_after == queued_before


def test_dns_executor_saturation_rejects_before_resolver_runs():
    """A saturated DNS pool must fail closed without invoking the resolver."""
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="dns-busy")
    release = threading.Event()
    started = threading.Event()
    resolver_calls = 0

    def blocker():
        started.set()
        release.wait(timeout=1)

    def resolver(_host, _port):
        nonlocal resolver_calls
        resolver_calls += 1
        return ["93.184.216.34"]

    occupying = executor.submit(blocker)
    assert started.wait(timeout=0.5)
    provider = OpenAICompatibleProvider(
        _config(),
        allowed_hosts="models.example.test",
        resolver=resolver,
        dns_executor=executor,
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(provider._validated_addresses(deadline_monotonic=time.monotonic() + 0.2))
        assert getattr(caught.value, "code", None) == "PROVIDER_DNS_BUSY"
        assert resolver_calls == 0
    finally:
        release.set()
        occupying.result(timeout=1)
        executor.shutdown(wait=True)


def test_dns_resolution_timeout_uses_request_remaining_budget():
    """DNS waiting must stop at the request deadline instead of owning a fresh timeout."""
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="dns-timeout")
    release = threading.Event()
    closed = threading.Event()

    def resolver(_host, _port):
        try:
            release.wait(timeout=1)
            return ["93.184.216.34"]
        finally:
            closed.set()

    provider = OpenAICompatibleProvider(
        _config(),
        allowed_hosts="models.example.test",
        resolver=resolver,
        dns_executor=executor,
    )
    started = time.monotonic()
    try:
        with pytest.raises(Exception) as caught:
            _run(provider._validated_addresses(deadline_monotonic=time.monotonic() + 0.04))
        assert getattr(caught.value, "code", None) == "PROVIDER_TIMEOUT"
        assert time.monotonic() - started < 0.15
    finally:
        release.set()
        assert closed.wait(timeout=0.5)
        executor.shutdown(wait=True)


def test_dns_async_callable_resolver_remains_compatible():
    """A callable object returning an awaitable was supported before DNS offload."""
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="dns-awaitable")

    class AwaitableResolver:
        def __call__(self, _host, _port):
            async def resolve():
                await asyncio.sleep(0)
                return ["93.184.216.34"]

            return resolve()

    provider = OpenAICompatibleProvider(
        _config(),
        allowed_hosts="models.example.test",
        resolver=AwaitableResolver(),
        dns_executor=executor,
    )
    try:
        assert _run(
            provider._validated_addresses(deadline_monotonic=time.monotonic() + 0.2)
        ) == ("93.184.216.34",)
    finally:
        executor.shutdown(wait=True)


def test_provider_allows_only_mocktransport_client_injection():
    """Accepting an injected production transport must bypass request-specific DNS pinning."""
    client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport())
    try:
        with pytest.raises(ProviderConfigurationError):
            OpenAICompatibleProvider(
                _config(),
                allowed_hosts="models.example.test",
                client=client,
                resolver=_public_dns,
            )
    finally:
        _run(client.aclose())


async def _public_dns(_host: str, _port: int):
    return ["93.184.216.34"]


def _run(awaitable):
    return asyncio.run(awaitable)


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _basic_probe_response(content: str = "ok"):
    return {
        "id": "probe-response",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
    }


def _tool_probe_response(*, name: str = "wa0_capability_probe", arguments: str = '{"status":"ok"}'):
    return {
        "id": "tool-probe-response",
        "object": "chat.completion",
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
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _schema_probe_response(content: str = '{"status":"schema-ok"}'):
    return {
        "id": "schema-probe-response",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _probe_stream_response() -> str:
    return _sse(
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "stream-ok"}, "finish_reason": "stop"}]},
        "[DONE]",
    )


def test_probe_runs_independent_exact_basic_stream_tool_and_json_schema_checks():
    """Combining or merely advertising capabilities must not mark unsupported features as healthy."""
    assert getattr(provider_api, "ProviderProbe", None) is not None
    secret = f"unit-{secrets.token_urlsafe(18)}"
    probe_kinds = []

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert request.url == httpx.URL("https://models.example.test/v1/chat/completions")
        assert request.url.query == b""
        assert request.headers["Authorization"] == f"Bearer {secret}"
        if body.get("stream") is True:
            probe_kinds.append("stream")
            assert "tools" not in body
            assert "response_format" not in body
            return httpx.Response(
                200,
                text=_probe_stream_response(),
                headers={"Content-Type": "text/event-stream"},
            )
        if "tool_choice" in body:
            probe_kinds.append("tool")
            offered_name = body["tools"][0]["function"]["name"]
            assert offered_name == "wa0_capability_probe"
            assert body["tool_choice"]["function"]["name"] == offered_name
            return httpx.Response(200, json=_tool_probe_response())
        if "response_format" in body:
            probe_kinds.append("json_schema")
            schema = body["response_format"]["json_schema"]
            assert schema["strict"] is True
            assert schema["schema"]["properties"]["status"]["const"] == "schema-ok"
            return httpx.Response(200, json=_schema_probe_response())
        probe_kinds.append("basic")
        assert body["stream"] is False
        assert "tools" not in body
        assert "response_format" not in body
        return httpx.Response(200, json=_basic_probe_response())

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
    assert probe.supports_streaming is True
    assert probe.supports_tools is True
    assert probe.supports_json_schema is True
    assert probe_kinds == ["basic", "stream", "tool", "json_schema"]


@pytest.mark.parametrize("ignored_feature", ["stream", "tool", "json_schema"])
def test_probe_reports_false_when_provider_ignores_a_requested_feature(ignored_feature):
    """A normal-looking response that ignores a forced feature must not produce a truthful capability flag."""
    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        if body.get("stream") is True:
            if ignored_feature == "stream":
                return httpx.Response(200, json=_basic_probe_response())
            return httpx.Response(
                200,
                text=_probe_stream_response(),
                headers={"Content-Type": "text/event-stream"},
            )
        if "tool_choice" in body:
            response = _basic_probe_response() if ignored_feature == "tool" else _tool_probe_response()
            return httpx.Response(200, json=response)
        if "response_format" in body:
            content = '{"status":"ignored"}' if ignored_feature == "json_schema" else '{"status":"schema-ok"}'
            return httpx.Response(200, json=_schema_probe_response(content))
        return httpx.Response(200, json=_basic_probe_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        probe = _run(provider.probe())
    finally:
        _run(client.aclose())

    assert probe.success is True
    assert probe.supports_streaming is (ignored_feature != "stream")
    assert probe.supports_tools is (ignored_feature != "tool")
    assert probe.supports_json_schema is (ignored_feature != "json_schema")


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
        return httpx.Response(200, json=_basic_probe_response())

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
    answers = iter([["93.184.216.34"]] * 4 + [["127.0.0.1"]])
    request_count = 0

    async def resolver(_host: str, _port: int):
        return next(answers)

    async def handler(_request: httpx.Request):
        nonlocal request_count
        request_count += 1
        if request_count == 2:
            return httpx.Response(
                200,
                text=_probe_stream_response(),
                headers={"Content-Type": "text/event-stream"},
            )
        if request_count == 3:
            return httpx.Response(200, json=_tool_probe_response())
        if request_count == 4:
            return httpx.Response(200, json=_schema_probe_response())
        return httpx.Response(200, json=_basic_probe_response())

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
    assert request_count == 4


class _MemoryNetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self, response: bytes):
        self._response = response
        self.request_bytes = bytearray()
        self.server_hostnames = []
        self.ssl_contexts = []
        self.closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._response:
            return b""
        chunk, self._response = self._response[:max_bytes], self._response[max_bytes:]
        return chunk

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.request_bytes.extend(buffer)

    async def aclose(self) -> None:
        self.closed = True

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ):
        self.ssl_contexts.append(ssl_context)
        self.server_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str):
        return None


class _RebindingNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver, stream: _MemoryNetworkStream):
        self.resolver = resolver
        self.stream = stream
        self.connect_hosts = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        try:
            ipaddress.ip_address(host)
            target = host
        except ValueError:
            target = (await self.resolver(host, port))[0]
        self.connect_hosts.append(target)
        return self.stream

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise AssertionError("provider transport must never use Unix sockets")

    async def sleep(self, seconds: float) -> None:
        return None


def test_default_transport_dials_only_same_request_validated_ip_and_preserves_host_and_tls_name():
    """Passing the origin hostname to the socket backend must allow a second DNS answer to steer the connection."""
    sse = _stream_response("pinned answer").encode()
    raw_response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/event-stream\r\n"
        + f"Content-Length: {len(sse)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + sse
    )
    stream = _MemoryNetworkStream(raw_response)
    resolver_calls = 0

    async def rebinding_resolver(_host: str, _port: int):
        nonlocal resolver_calls
        resolver_calls += 1
        return ["93.184.216.34"] if resolver_calls == 1 else ["127.0.0.1"]

    backend = _RebindingNetworkBackend(rebinding_resolver, stream)
    provider = OpenAICompatibleProvider(
        _config(),
        allowed_hosts="models.example.test",
        resolver=rebinding_resolver,
        network_backend=backend,
    )

    events = _run(_collect_stream(provider, _chat_request()))

    assert [event.kind for event in events] == ["text_delta", "usage", "done"]
    assert resolver_calls == 1
    assert backend.connect_hosts == ["93.184.216.34"]
    assert stream.server_hostnames == ["models.example.test"]
    assert stream.ssl_contexts[0].check_hostname is True
    assert stream.ssl_contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert b"host: models.example.test\r\n" in bytes(stream.request_bytes).lower()


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
    purpose_type = getattr(provider_api, "ProviderPurpose", None)
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
        "purpose": purpose_type.CHAT if purpose_type is not None else "chat",
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


def test_provider_rejects_raw_purpose_before_dns_or_transport():
    """Calling the adapter directly with caller purpose text must not bypass the gateway boundary."""
    resolver_calls = 0
    transport_calls = 0

    async def resolver(_host: str, _port: int):
        nonlocal resolver_calls
        resolver_calls += 1
        return ["93.184.216.34"]

    async def handler(_request: httpx.Request):
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(
            200,
            text=_stream_response(),
            headers={"Content-Type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=resolver
    )
    try:
        with pytest.raises(Exception) as caught:
            _run(_collect_stream(provider, _chat_request(purpose="chat")))
    finally:
        _run(client.aclose())

    assert getattr(caught.value, "code", None) == "PROVIDER_REQUEST_INVALID"
    assert resolver_calls == 0
    assert transport_calls == 0


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


class _NeverEndingAfterDoneStream(httpx.AsyncByteStream):
    def __init__(self):
        self.read_after_done = False
        self.closed = False

    async def __aiter__(self):
        yield _stream_response("terminal answer").encode()
        self.read_after_done = True
        yield b": heartbeat that must never be consumed\n\n"

    async def aclose(self):
        self.closed = True


def test_stream_chat_stops_reading_and_closes_response_immediately_after_done():
    """Continuing to await socket EOF after DONE must hang on provider heartbeats."""
    response_stream = _NeverEndingAfterDoneStream()

    async def handler(_request: httpx.Request):
        return httpx.Response(
            200,
            stream=response_stream,
            headers={"Content-Type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        _config(), allowed_hosts="models.example.test", client=client, resolver=_public_dns
    )
    try:
        events = _run(_collect_stream(provider, _chat_request()))
    finally:
        _run(client.aclose())

    assert [event.kind for event in events] == ["text_delta", "usage", "done"]
    assert response_stream.read_after_done is False
    assert response_stream.closed is True


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


class _ScriptedProvider:
    def __init__(self, events, *, error=None):
        self.events = events
        self.error = error

    async def stream_chat(self, _request):
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


def _successful_gateway_events(text: str = "gateway answer"):
    return [
        provider_api.ModelStreamEvent(kind="text_delta", text=text),
        provider_api.ModelStreamEvent(kind="usage", input_tokens=7, output_tokens=3),
        provider_api.ModelStreamEvent(kind="done", finish_reason="stop"),
    ]


def _provider_row(
    code: str,
    *,
    host: str,
    enabled: bool = True,
    probe_status: str = "success",
    last_probed_at: datetime | None = None,
    supports_tools: bool = True,
    supports_json_schema: bool = True,
    supports_streaming: bool = True,
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
            "supports_streaming": supports_streaming,
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
        ).all()
        calls_by_provider = {call.provider_id: call for call in calls}
        assert {
            provider_id: (call.result_code, call.status)
            for provider_id, call in calls_by_provider.items()
        } == {
            primary.id: ("PROVIDER_HTTP_5XX", "failed"),
            fallback.id: ("OK_FALLBACK", "completed"),
        }
        assert calls_by_provider[fallback.id].input_tokens == 17
        assert calls_by_provider[fallback.id].output_tokens == 5
        rendered_audit = json.dumps([call.error_redacted for call in calls], ensure_ascii=False)
        assert secret not in rendered_audit
        assert prompt not in rendered_audit
        assert set(calls_by_provider[primary.id].error_redacted) == {"code", "message"}
        assert "messages" not in AiProviderCall.__table__.columns

    for http_client in clients:
        _run(http_client.aclose())


@pytest.mark.parametrize("risk_level", ["L2", "L3"])
@pytest.mark.parametrize(
    ("supports_streaming", "supports_tools", "supports_json_schema"),
    [(False, True, True), (True, False, True), (True, True, False), (False, False, False)],
)
def test_gateway_rejects_l2_l3_provider_without_both_required_capabilities(
    client, risk_level, supports_streaming, supports_tools, supports_json_schema
):
    """Weakening any capability check must expose a high-risk request to an incompatible model."""
    gateway_api = _gateway_module()
    transport_calls = 0
    suffix = (
        f"{risk_level.lower()}-{int(supports_streaming)}-"
        f"{int(supports_tools)}-{int(supports_json_schema)}"
    )

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-incompatible-{suffix}",
            host=f"{suffix}.models.example.test",
            supports_streaming=supports_streaming,
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
        audit_deadline = time.monotonic() + 1.0
        calls = []
        while time.monotonic() < audit_deadline:
            with SessionLocal() as audit_db:
                calls = audit_db.query(AiProviderCall).filter(
                    AiProviderCall.provider_id.in_([primary.id, fallback.id])
                ).all()
            if calls:
                break
            time.sleep(0.01)
        assert [(call.provider_id, call.result_code, call.status) for call in calls] == [
            (primary.id, "PROVIDER_STREAM_CANCELLED", "cancelled")
        ]
        assert fallback_calls == 0

    for http_client in clients:
        _run(http_client.aclose())


def test_gateway_cancellation_does_not_wait_for_slow_audit_and_worker_closes_session(client):
    """Awaiting cancellation audit would delay disconnect propagation by its 0.30s commit."""
    gateway_api = _gateway_module()
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="cancel-audit")
    audit_started = threading.Event()
    audit_closed = threading.Event()

    class SlowAuditSession:
        def add(self, _record):
            return None

        def commit(self):
            audit_started.set()
            time.sleep(0.30)

        def rollback(self):
            return None

        def close(self):
            audit_closed.set()

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-cancel-slow-audit-{secrets.token_hex(4)}",
            host="cancel-slow-audit.models.example.test",
            is_primary=True,
        )
        db.add(primary)
        db.commit()
        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=lambda _config: _ScriptedProvider(_successful_gateway_events()),
            audit_session_factory=SlowAuditSession,
            db_executor=executor,
        )
        started = time.monotonic()
        first = _run(_read_one_gateway_event_and_close(gateway, _chat_request()))
        elapsed = time.monotonic() - started

    try:
        assert first.kind == "text_delta"
        assert elapsed < 0.10
        assert audit_started.wait(timeout=0.2)
        assert audit_closed.wait(timeout=0.6)
    finally:
        executor.shutdown(wait=True)


def test_gateway_cancellation_audit_saturation_drops_before_session_creation(client):
    """Best-effort cancellation audit must not open a Session when bounded admission is full."""
    gateway_api = _gateway_module()
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="cancel-audit-busy")
    release = threading.Event()
    started = threading.Event()
    audit_sessions = 0

    def blocker():
        started.set()
        release.wait(timeout=1)

    def audit_session_factory():
        nonlocal audit_sessions
        audit_sessions += 1
        return SessionLocal()

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-cancel-busy-audit-{secrets.token_hex(4)}",
            host="cancel-busy-audit.models.example.test",
            is_primary=True,
        )
        db.add(primary)
        db.commit()
        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=lambda _config: _ScriptedProvider(_successful_gateway_events()),
            audit_session_factory=audit_session_factory,
            db_executor=executor,
        )

        async def consume_after_selection():
            stream = gateway.stream(_chat_request())
            first = await anext(stream)
            occupying = executor.submit(blocker)
            assert started.wait(timeout=0.5)
            try:
                await stream.aclose()
            finally:
                release.set()
                occupying.result(timeout=1)
            return first

        try:
            first = _run(consume_after_selection())
            assert first.kind == "text_delta"
            assert audit_sessions == 0
        finally:
            release.set()
            executor.shutdown(wait=True)


def test_gateway_background_cancellation_audit_exception_is_consumed(client):
    """A background audit failure must not create an unhandled asyncio task exception."""
    gateway_api = _gateway_module()
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0, thread_name_prefix="cancel-audit-error")
    audit_finished = threading.Event()
    unhandled = []

    class ExplodingGateway(gateway_api.AssistantGateway):
        def _audit(self, *_args, **_kwargs):
            try:
                raise RuntimeError("sensitive cancellation audit failure")
            finally:
                audit_finished.set()

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-cancel-error-audit-{secrets.token_hex(4)}",
            host="cancel-error-audit.models.example.test",
            is_primary=True,
        )
        db.add(primary)
        db.commit()
        gateway = ExplodingGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=lambda _config: _ScriptedProvider(_successful_gateway_events()),
            db_executor=executor,
        )

        async def consume():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
            first = await _read_one_gateway_event_and_close(gateway, _chat_request())
            while not audit_finished.is_set():
                await asyncio.sleep(0.005)
            await asyncio.sleep(0)
            return first

        try:
            assert _run(consume()).kind == "text_delta"
            assert unhandled == []
        finally:
            executor.shutdown(wait=True)


class _FailingAuditSession:
    def __init__(self, secret: str):
        self.secret = secret
        self.rollback_called = False
        self.close_called = False

    def add(self, _record):
        raise RuntimeError(f"audit storage failed: {self.secret}")

    def commit(self):
        raise RuntimeError(f"audit commit failed: {self.secret}")

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.close_called = True


@pytest.mark.parametrize(
    "raw_purpose",
    [
        "chat",
        "unknown-purpose",
        "x" * 128,
        "chat bearer secret-purpose-value",
    ],
)
def test_gateway_rejects_non_enum_purpose_before_provider_or_audit(client, raw_purpose):
    """Persisting caller-controlled purpose text must permit unbounded or secret-bearing audit data."""
    gateway_api = _gateway_module()
    provider_constructions = 0

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-purpose-{secrets.token_hex(6)}",
            host="purpose.models.example.test",
            is_primary=True,
        )
        db.add(provider_row)
        db.commit()

        def provider_factory(_config):
            nonlocal provider_constructions
            provider_constructions += 1
            return _ScriptedProvider(_successful_gateway_events())

        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=provider_row.id,
            provider_factory=provider_factory,
        )
        with pytest.raises(Exception) as caught:
            _run(_collect_gateway(gateway, _chat_request(purpose=raw_purpose)))

        assert getattr(caught.value, "code", None) == "GATEWAY_PURPOSE_INVALID"
        assert provider_constructions == 0
        assert db.query(AiProviderCall).filter_by(provider_id=provider_row.id).count() == 0


def test_gateway_audit_uses_independent_transaction_and_leaves_caller_pending_work_rollbackable(client):
    """Committing an audit through the caller session must accidentally commit unrelated pending work."""
    gateway_api = _gateway_module()
    assert getattr(provider_api, "ProviderPurpose", None) is not None
    pending_code = f"wa0-pending-{secrets.token_hex(6)}"

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-audit-owner-{secrets.token_hex(6)}",
            host="audit-owner.models.example.test",
            is_primary=True,
        )
        db.add(provider_row)
        db.commit()
        pending = _provider_row(pending_code, host="pending.models.example.test")
        db.add(pending)

        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=provider_row.id,
            provider_factory=lambda _config: _ScriptedProvider(_successful_gateway_events()),
        )
        events = _run(_collect_gateway(gateway, _chat_request()))

        assert [event.kind for event in events] == ["text_delta", "usage", "done"]
        assert pending in db.new
        with SessionLocal() as verifier:
            assert verifier.query(AiProviderConfig).filter_by(code=pending_code).count() == 0
            audit = verifier.query(AiProviderCall).filter_by(provider_id=provider_row.id).one()
            assert (audit.result_code, audit.status, audit.purpose) == ("OK", "completed", "chat")
        db.rollback()

    with SessionLocal() as verifier:
        assert verifier.query(AiProviderConfig).filter_by(code=pending_code).count() == 0


def test_audit_failure_during_primary_failure_does_not_block_compatible_fallback(client):
    """Letting failed audit persistence escape must suppress an otherwise safe fallback response."""
    gateway_api = _gateway_module()
    secret = f"audit-{secrets.token_urlsafe(18)}"
    failing_session = _FailingAuditSession(secret)
    audit_session_count = 0
    fallback_calls = 0

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-audit-fail-primary-{secrets.token_hex(4)}",
            host="audit-fail-primary.models.example.test",
            is_primary=True,
        )
        fallback = _provider_row(
            f"wa0-audit-fail-fallback-{secrets.token_hex(4)}",
            host="audit-fail-fallback.models.example.test",
        )
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        db.commit()

        def provider_factory(config):
            nonlocal fallback_calls
            if config.id == primary.id:
                return _ScriptedProvider(
                    [],
                    error=provider_api.ProviderError("PROVIDER_HTTP_5XX", "provider service failed"),
                )
            fallback_calls += 1
            return _ScriptedProvider(_successful_gateway_events("fallback after audit failure"))

        def audit_session_factory():
            nonlocal audit_session_count
            audit_session_count += 1
            return failing_session if audit_session_count == 1 else SessionLocal()

        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=provider_factory,
            audit_session_factory=audit_session_factory,
        )
        events = _run(_collect_gateway(gateway, _chat_request()))

        assert [event.kind for event in events] == ["text_delta", "usage", "done"]
        assert events[0].text == "fallback after audit failure"
        assert fallback_calls == 1
        assert failing_session.rollback_called is True
        assert failing_session.close_called is True
        calls = db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).all()
        assert [(call.provider_id, call.result_code, call.status) for call in calls] == [
            (fallback.id, "OK_FALLBACK", "completed")
        ]


def test_audit_failure_during_cancellation_never_masks_cancel_or_attempts_fallback(client):
    """An audit exception during generator close must not escape cancellation or start a second provider."""
    gateway_api = _gateway_module()
    secret = f"cancel-audit-{secrets.token_urlsafe(18)}"
    failing_session = _FailingAuditSession(secret)
    fallback_calls = 0

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-cancel-audit-primary-{secrets.token_hex(4)}",
            host="cancel-audit-primary.models.example.test",
            is_primary=True,
        )
        fallback = _provider_row(
            f"wa0-cancel-audit-fallback-{secrets.token_hex(4)}",
            host="cancel-audit-fallback.models.example.test",
        )
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        db.commit()

        def provider_factory(config):
            nonlocal fallback_calls
            if config.id == fallback.id:
                fallback_calls += 1
            return _ScriptedProvider(_successful_gateway_events())

        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=provider_factory,
            audit_session_factory=lambda: failing_session,
        )
        first = _run(_read_one_gateway_event_and_close(gateway, _chat_request()))

        assert first.kind == "text_delta"
        assert fallback_calls == 0
        assert failing_session.rollback_called is True
        assert failing_session.close_called is True
        assert db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).count() == 0


async def _collect_gateway_failure(gateway, request):
    events = []
    try:
        async for event in gateway.stream(request):
            events.append(event)
    except Exception as exc:
        return events, exc
    raise AssertionError("gateway unexpectedly completed")


def test_success_audit_failure_is_redacted_and_never_emits_terminal_success(client):
    """Emitting done before durable audit must falsely claim an unaudited provider call succeeded."""
    gateway_api = _gateway_module()
    secret = f"success-audit-{secrets.token_urlsafe(18)}"
    failing_session = _FailingAuditSession(secret)

    with SessionLocal() as db:
        provider_row = _provider_row(
            f"wa0-success-audit-{secrets.token_hex(4)}",
            host="success-audit.models.example.test",
            is_primary=True,
        )
        db.add(provider_row)
        db.commit()
        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=provider_row.id,
            provider_factory=lambda _config: _ScriptedProvider(_successful_gateway_events()),
            audit_session_factory=lambda: failing_session,
        )

        events, error = _run(_collect_gateway_failure(gateway, _chat_request()))

        assert [event.kind for event in events] == ["text_delta", "usage"]
        assert getattr(error, "code", None) == "GATEWAY_AUDIT_FAILED"
        assert secret not in str(error)
        assert secret not in repr(error)
        assert failing_session.rollback_called is True
        assert failing_session.close_called is True


def test_partial_primary_output_then_protocol_failure_never_falls_back_or_claims_success(client):
    """Fallback or done after a visible partial delta must mix providers or falsely complete the answer."""
    gateway_api = _gateway_module()
    fallback_calls = 0
    clients = []
    broken_stream = (
        _sse(
            {"choices": [{"index": 0, "delta": {"content": "partial output"}, "finish_reason": None}]}
        )
        + "data: {not-json}\n\n"
    )

    with SessionLocal() as db:
        primary = _provider_row(
            f"wa0-partial-primary-{secrets.token_hex(4)}",
            host="partial-primary.models.example.test",
            is_primary=True,
        )
        fallback = _provider_row(
            f"wa0-partial-fallback-{secrets.token_hex(4)}",
            host="partial-fallback.models.example.test",
        )
        db.add_all([primary, fallback])
        db.flush()
        primary.fallback_provider_id = fallback.id
        db.commit()

        async def primary_handler(_request: httpx.Request):
            return httpx.Response(
                200,
                text=broken_stream,
                headers={"Content-Type": "text/event-stream"},
            )

        async def fallback_handler(_request: httpx.Request):
            nonlocal fallback_calls
            fallback_calls += 1
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

        gateway = gateway_api.AssistantGateway(
            db,
            primary_provider_id=primary.id,
            provider_factory=provider_factory,
        )
        events, error = _run(_collect_gateway_failure(gateway, _chat_request()))

        assert [event.kind for event in events] == ["text_delta"]
        assert events[0].text == "partial output"
        assert getattr(error, "code", None) == "GATEWAY_STREAM_FAILED"
        assert fallback_calls == 0
        calls = db.query(AiProviderCall).filter(
            AiProviderCall.provider_id.in_([primary.id, fallback.id])
        ).all()
        assert [(call.provider_id, call.result_code, call.status) for call in calls] == [
            (primary.id, "PROVIDER_STREAM_PROTOCOL_ERROR", "failed")
        ]

    for http_client in clients:
        _run(http_client.aclose())
