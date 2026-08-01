"""OpenAI-compatible provider adapter."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import inspect
import ipaddress
import json
import socket
import ssl
from urllib.parse import unquote, urlsplit

import httpcore
import httpx

from app.assistant.providers.base import (
    ChatRequest,
    ModelStreamEvent,
    ProviderConfigurationError,
    ProviderError,
    ProviderPurpose,
    ProviderProbe,
)
from app.assistant.redaction import redact_for_model
from app.services.secrets_store import decrypt_secret


_CAPABILITY_NEGATIVE_CODES = {
    "PROVIDER_HTTP_ERROR",
    "PROVIDER_PROTOCOL_ERROR",
    "PROVIDER_STREAM_PROTOCOL_ERROR",
}
_MAX_PATH_LENGTH = 2048
_MAX_PATH_DECODE_ROUNDS = 8


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Dial only validated literals while httpcore retains the original HTTPS origin."""

    def __init__(
        self,
        origin_host: str,
        addresses: tuple[str, ...],
        delegate: httpcore.AsyncNetworkBackend,
    ):
        self._origin_host = origin_host
        self._addresses = addresses
        self._delegate = delegate

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        if host.lower().rstrip(".") != self._origin_host:
            raise httpcore.ConnectError("provider transport origin mismatch")
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return await self._delegate.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("provider transport has no validated address")

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise httpcore.ConnectError("provider Unix sockets are forbidden")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport backed by a request-specific pinned DNS result."""

    def __init__(self, network_backend: httpcore.AsyncNetworkBackend):
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=network_backend,
            retries=0,
        )


class OpenAICompatibleProvider:
    def __init__(
        self,
        config,
        *,
        allowed_hosts: str,
        client: httpx.AsyncClient | None = None,
        resolver=None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        connect_timeout_seconds: float = 5,
        read_timeout_seconds: float = 60,
    ):
        self.config = config
        self.endpoint_url = _chat_completions_url(config.api_base_url, allowed_hosts)
        if client is not None and not isinstance(getattr(client, "_transport", None), httpx.MockTransport):
            raise ProviderConfigurationError("only MockTransport client injection is permitted")
        self._client = client
        self._resolver = resolver or _resolve_host
        self._network_backend = network_backend or httpcore.AnyIOBackend()
        self._timeout = httpx.Timeout(
            connect=float(connect_timeout_seconds),
            read=float(read_timeout_seconds),
            write=float(read_timeout_seconds),
            pool=float(connect_timeout_seconds),
        )

    async def probe(self) -> ProviderProbe:
        common = {
            "model": self.config.model,
            "max_tokens": min(int(self.config.max_output_tokens or 64), 64),
            "temperature": 0,
        }
        basic_response = await self._post(
            {
                **common,
                "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
                "stream": False,
            }
        )
        _validate_basic_probe(basic_response)

        streaming = await self._probe_capability(
            self._probe_streaming(
                {
                    **common,
                    "messages": [{"role": "user", "content": "Reply with exactly: stream-ok"}],
                    "stream": True,
                }
            )
        )

        tool_name = "wa0_capability_probe"
        tool_response = self._post(
            {
                **common,
                "messages": [{"role": "user", "content": "Call the offered probe tool with status ok."}],
                "stream": False,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": "WA0 forced tool capability probe",
                            "parameters": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "const": "ok"}},
                                "required": ["status"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "tool_choice": {"type": "function", "function": {"name": tool_name}},
            }
        )
        tools = await self._probe_capability(_validate_tool_probe_async(tool_response, tool_name))

        schema = {
            "type": "object",
            "properties": {"status": {"type": "string", "const": "schema-ok"}},
            "required": ["status"],
            "additionalProperties": False,
        }
        schema_response = self._post(
            {
                **common,
                "messages": [{"role": "user", "content": "Return the requested schema value."}],
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "wa0_schema_probe", "strict": True, "schema": schema},
                },
            }
        )
        json_schema = await self._probe_capability(_validate_schema_probe_async(schema_response))

        return ProviderProbe(
            success=True,
            supports_streaming=streaming,
            supports_tools=tools,
            supports_json_schema=json_schema,
            checked_at=datetime.now(timezone.utc),
            model=str(self.config.model or ""),
        )

    async def aclose(self) -> None:
        return None

    async def _probe_capability(self, check) -> bool:
        try:
            await check
            return True
        except ProviderError as exc:
            if exc.code in _CAPABILITY_NEGATIVE_CODES:
                return False
            raise

    async def _probe_streaming(self, payload: dict) -> None:
        events = [event async for event in self._stream(payload, frozenset())]
        text = "".join(event.text or "" for event in events if event.kind == "text_delta")
        done = [event for event in events if event.kind == "done"]
        if text != "stream-ok" or len(done) != 1 or done[0].finish_reason != "stop":
            raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider returned an invalid streaming probe")

    async def stream_chat(self, request: ChatRequest):
        """Yield only fully validated OpenAI-compatible SSE events."""
        if not isinstance(request.purpose, ProviderPurpose):
            raise ProviderError("PROVIDER_REQUEST_INVALID", "provider request purpose is invalid")
        payload = self._chat_payload(request)
        allowed_tools = _allowed_tool_names(request.tools)
        async for event in self._stream(payload, allowed_tools):
            yield event

    async def _stream(self, payload: dict, allowed_tools: frozenset[str]):
        addresses = await self._validated_addresses()
        headers = self._headers(accept="text/event-stream")
        try:
            async with self._request_client(addresses) as client:
                async with client.stream(
                    "POST",
                    self.endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as response:
                    _raise_for_status(response)
                    if not response.headers.get("content-type", "").lower().startswith("text/event-stream"):
                        raise _stream_error()
                    async for event in _parse_sse(response, allowed_tools):
                        yield event
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("PROVIDER_TIMEOUT", "provider request timed out") from None
        except httpx.RequestError:
            raise ProviderError("PROVIDER_CONNECT_FAILED", "provider connection failed") from None

    def _chat_payload(self, request: ChatRequest) -> dict:
        payload = {
            "model": self.config.model,
            "messages": redact_for_model(list(request.messages)),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": int(request.max_output_tokens or self.config.max_output_tokens or 2048),
        }
        temperature = request.temperature if request.temperature is not None else self.config.temperature
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if request.tools:
            payload["tools"] = redact_for_model(list(request.tools))
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "itom_response",
                    "strict": True,
                    "schema": redact_for_model(dict(request.response_schema)),
                },
            }
        return payload

    def _headers(self, *, accept: str) -> dict[str, str]:
        headers = {"Accept": accept, "Content-Type": "application/json"}
        try:
            secret = decrypt_secret(self.config.api_key_encrypted)
        except Exception:
            raise ProviderError("PROVIDER_SECRET_INVALID", "provider credential could not be read") from None
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return headers

    async def _post(self, payload: dict) -> httpx.Response:
        addresses = await self._validated_addresses()
        headers = self._headers(accept="application/json")
        try:
            async with self._request_client(addresses) as client:
                response = await client.post(
                    self.endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
        except httpx.TimeoutException:
            raise ProviderError("PROVIDER_TIMEOUT", "provider request timed out") from None
        except httpx.RequestError:
            raise ProviderError("PROVIDER_CONNECT_FAILED", "provider connection failed") from None
        _raise_for_status(response)
        return response

    @asynccontextmanager
    async def _request_client(self, addresses: tuple[str, ...]):
        if self._client is not None:
            yield self._client
            return
        backend = _PinnedNetworkBackend(self.endpoint_url.host, addresses, self._network_backend)
        transport = _PinnedAsyncHTTPTransport(backend)
        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            yield client

    async def _validated_addresses(self) -> tuple[str, ...]:
        host = self.endpoint_url.host
        port = self.endpoint_url.port or 443
        try:
            literal = ipaddress.ip_address(host)
            addresses = [str(literal)]
        except ValueError:
            try:
                resolved = self._resolver(host, port)
                addresses = await resolved if inspect.isawaitable(resolved) else resolved
            except Exception:
                raise ProviderError("PROVIDER_DNS_FAILED", "provider DNS resolution failed") from None
        if not addresses:
            raise ProviderError("PROVIDER_DNS_FAILED", "provider DNS resolution returned no addresses")
        validated = []
        for value in addresses:
            try:
                address = ipaddress.ip_address(str(value))
            except ValueError:
                raise ProviderError("PROVIDER_DNS_FAILED", "provider DNS returned an invalid address") from None
            if (
                not address.is_global
                or address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_unspecified
                or address.is_reserved
            ):
                raise ProviderError("PROVIDER_ADDRESS_FORBIDDEN", "provider resolved to a forbidden address")
            normalized = str(address)
            if normalized not in validated:
                validated.append(normalized)
        return tuple(validated)


async def _resolve_host(host: str, port: int) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


def _probe_choice(response: httpx.Response) -> tuple[dict, str]:
    try:
        document = response.json()
        choices = document["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index") != 0:
            raise ValueError
        message = choice["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError
        finish_reason = choice["finish_reason"]
        if not isinstance(finish_reason, str):
            raise ValueError
        return message, finish_reason
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider returned an invalid probe response") from None


def _validate_basic_probe(response: httpx.Response) -> None:
    message, finish_reason = _probe_choice(response)
    if finish_reason != "stop" or message.get("content") != "ok" or message.get("tool_calls"):
        raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider returned an invalid basic probe")


async def _validate_tool_probe_async(response_awaitable, tool_name: str) -> None:
    response = await response_awaitable
    message, finish_reason = _probe_choice(response)
    try:
        calls = message["tool_calls"]
        if finish_reason != "tool_calls" or not isinstance(calls, list) or len(calls) != 1:
            raise ValueError
        call = calls[0]
        function = call["function"]
        if call.get("type") != "function" or function.get("name") != tool_name:
            raise ValueError
        arguments = json.loads(function["arguments"])
        if arguments != {"status": "ok"}:
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider ignored the forced tool probe") from None


async def _validate_schema_probe_async(response_awaitable) -> None:
    response = await response_awaitable
    message, finish_reason = _probe_choice(response)
    try:
        document = json.loads(message["content"])
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider ignored the JSON schema probe") from None
    if finish_reason != "stop" or document != {"status": "schema-ok"}:
        raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider ignored the JSON schema probe")


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if 300 <= status < 400:
        raise ProviderError("PROVIDER_REDIRECT_FORBIDDEN", "provider redirect was refused", status_code=status)
    if status in {401, 403}:
        raise ProviderError("PROVIDER_AUTH_FAILED", "provider authentication failed", status_code=status)
    if status == 429:
        raise ProviderError("PROVIDER_RATE_LIMITED", "provider rate limit was reached", status_code=status)
    if 500 <= status:
        raise ProviderError("PROVIDER_HTTP_5XX", "provider service failed", status_code=status)
    if status >= 400:
        raise ProviderError("PROVIDER_HTTP_ERROR", "provider request was rejected", status_code=status)


def _stream_error() -> ProviderError:
    return ProviderError("PROVIDER_STREAM_PROTOCOL_ERROR", "provider stream protocol validation failed")


async def _parse_sse(response: httpx.Response, allowed_tools: frozenset[str]):
    finish_reason: str | None = None
    tool_parts: dict[int, dict[str, str]] = {}

    async for line in response.aiter_lines():
        if not line:
            continue
        if not line.startswith("data: "):
            raise _stream_error()
        raw = line[6:]
        if raw == "[DONE]":
            if finish_reason is None:
                raise _stream_error()
            yield ModelStreamEvent(kind="done", finish_reason=finish_reason)
            return
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            raise _stream_error() from None
        if not isinstance(document, dict) or "choices" not in document:
            raise _stream_error()
        choices = document["choices"]
        if choices == []:
            usage = document.get("usage")
            if finish_reason is None or not isinstance(usage, dict):
                raise _stream_error()
            try:
                input_tokens = int(usage["prompt_tokens"])
                output_tokens = int(usage["completion_tokens"])
            except (KeyError, TypeError, ValueError):
                raise _stream_error() from None
            if input_tokens < 0 or output_tokens < 0:
                raise _stream_error()
            yield ModelStreamEvent(kind="usage", input_tokens=input_tokens, output_tokens=output_tokens)
            continue
        if finish_reason is not None or not isinstance(choices, list) or len(choices) != 1:
            raise _stream_error()
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index") != 0 or "finish_reason" not in choice:
            raise _stream_error()
        delta = choice.get("delta")
        if not isinstance(delta, dict) or set(delta) - {"role", "content", "tool_calls"}:
            raise _stream_error()
        if "role" in delta and delta["role"] != "assistant":
            raise _stream_error()
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise _stream_error()
            if content:
                yield ModelStreamEvent(kind="text_delta", text=content)
        if "tool_calls" in delta:
            _consume_tool_chunks(tool_parts, delta["tool_calls"])

        terminal = choice["finish_reason"]
        if terminal is not None:
            if terminal not in {"stop", "tool_calls"}:
                raise _stream_error()
            finish_reason = terminal
            if terminal == "stop" and tool_parts:
                raise _stream_error()
            if terminal == "tool_calls":
                if not tool_parts:
                    raise _stream_error()
                for event in _tool_events(tool_parts, allowed_tools):
                    yield event

    raise _stream_error()


def _consume_tool_chunks(parts: dict[int, dict[str, str]], chunks: object) -> None:
    if not isinstance(chunks, list) or not chunks:
        raise _stream_error()
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("index"), int) or chunk["index"] < 0:
            raise _stream_error()
        if set(chunk) - {"index", "id", "type", "function"}:
            raise _stream_error()
        if "type" in chunk and chunk["type"] != "function":
            raise _stream_error()
        state = parts.setdefault(chunk["index"], {"id": "", "name": "", "arguments": ""})
        if "id" in chunk:
            if not isinstance(chunk["id"], str) or (state["id"] and state["id"] != chunk["id"]):
                raise _stream_error()
            state["id"] = chunk["id"]
        function = chunk.get("function")
        if function is not None:
            if not isinstance(function, dict) or set(function) - {"name", "arguments"}:
                raise _stream_error()
            for key in ("name", "arguments"):
                value = function.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise _stream_error()
                    state[key] += value


def _tool_events(
    parts: dict[int, dict[str, str]], allowed_tools: frozenset[str]
) -> list[ModelStreamEvent]:
    events = []
    for index in sorted(parts):
        state = parts[index]
        if (
            not state["id"]
            or not state["name"]
            or state["name"] not in allowed_tools
            or not state["arguments"]
        ):
            raise _stream_error()
        try:
            arguments = json.loads(state["arguments"])
        except json.JSONDecodeError:
            raise _stream_error() from None
        if not isinstance(arguments, dict):
            raise _stream_error()
        events.append(
            ModelStreamEvent(
                kind="tool_call",
                tool_call_id=state["id"],
                tool_name=state["name"],
                arguments=arguments,
            )
        )
    return events


def _allowed_tool_names(tools: tuple) -> frozenset[str]:
    names = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ProviderError("PROVIDER_REQUEST_INVALID", "provider request tools are invalid")
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name or name in names:
            raise ProviderError("PROVIDER_REQUEST_INVALID", "provider request tools are invalid")
        names.add(name)
    return frozenset(names)


def _chat_completions_url(base_url: str | None, allowed_hosts: str) -> httpx.URL:
    if not base_url or any(ord(character) < 32 for character in base_url):
        raise ProviderConfigurationError("provider base URL is required")
    parsed = urlsplit(base_url)
    if parsed.scheme.lower() != "https":
        raise ProviderConfigurationError("provider base URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderConfigurationError("provider base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError("provider base URL must not contain query or fragment")
    try:
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ProviderConfigurationError("provider base URL host or port is invalid") from exc
    if not host or not _host_allowed(host, allowed_hosts):
        raise ProviderConfigurationError("provider host is not allowlisted")

    raw_path = parsed.path or ""
    decoded_path = _decode_path_to_stability(raw_path)
    segments = decoded_path.replace("\\", "/").split("/")
    if (
        "\\" in decoded_path
        or any(segment in {".", ".."} for segment in segments)
        or decoded_path.count("/") != raw_path.count("/")
    ):
        raise ProviderConfigurationError("provider base URL path is unsafe")

    path = raw_path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return httpx.URL(f"https://{host}{f':{parsed.port}' if parsed.port else ''}{path}")


def _decode_path_to_stability(raw_path: str) -> str:
    if len(raw_path) > _MAX_PATH_LENGTH:
        raise ProviderConfigurationError("provider base URL path is unsafe")
    decoded = raw_path
    seen = {decoded}
    for _ in range(_MAX_PATH_DECODE_ROUNDS):
        try:
            expanded = unquote(decoded, errors="strict")
        except UnicodeDecodeError:
            raise ProviderConfigurationError("provider base URL path is unsafe") from None
        if len(expanded) > _MAX_PATH_LENGTH or (expanded in seen and expanded != decoded):
            raise ProviderConfigurationError("provider base URL path is unsafe")
        if expanded == decoded:
            if "%" in decoded:
                raise ProviderConfigurationError("provider base URL path is unsafe")
            return decoded
        seen.add(expanded)
        decoded = expanded
    raise ProviderConfigurationError("provider base URL path is unsafe")


def _host_allowed(host: str, configured: str) -> bool:
    entries = [entry.strip().lower().rstrip(".") for entry in configured.split(",") if entry.strip()]
    for entry in entries:
        if entry.startswith("*."):
            suffix = entry[2:]
            if suffix.count(".") >= 1 and host != suffix and host.endswith(f".{suffix}"):
                return True
        elif host == entry:
            return True
    return False
