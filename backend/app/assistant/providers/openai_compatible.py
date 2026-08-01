"""OpenAI-compatible provider adapter."""

import asyncio
from datetime import datetime, timezone
import inspect
import ipaddress
import json
import re
import socket
from urllib.parse import unquote, urlsplit

import httpx

from app.assistant.providers.base import (
    ChatRequest,
    ModelStreamEvent,
    ProviderConfigurationError,
    ProviderError,
    ProviderProbe,
)
from app.assistant.redaction import redact_for_model
from app.services.secrets_store import decrypt_secret


class OpenAICompatibleProvider:
    def __init__(
        self,
        config,
        *,
        allowed_hosts: str,
        client: httpx.AsyncClient | None = None,
        resolver=None,
        connect_timeout_seconds: float = 5,
        read_timeout_seconds: float = 60,
    ):
        self.config = config
        self.endpoint_url = _chat_completions_url(config.api_base_url, allowed_hosts)
        self._client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self._owns_client = client is None
        self._resolver = resolver or _resolve_host
        self._timeout = httpx.Timeout(
            connect=float(connect_timeout_seconds),
            read=float(read_timeout_seconds),
            write=float(read_timeout_seconds),
            pool=float(connect_timeout_seconds),
        )

    async def probe(self) -> ProviderProbe:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": "Return a JSON status object for a capability probe."}],
            "stream": False,
            "max_tokens": min(int(self.config.max_output_tokens or 64), 64),
            "temperature": 0,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "wa0_probe",
                        "description": "WA0 capability probe",
                        "parameters": {
                            "type": "object",
                            "properties": {"status": {"type": "string"}},
                            "required": ["status"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "wa0_probe",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                        "additionalProperties": False,
                    },
                },
            },
        }
        response = await self._post(payload)
        try:
            document = response.json()
            choices = document["choices"]
            choice = choices[0]
            if len(choices) != 1 or choice.get("finish_reason") != "stop":
                raise ValueError
            content = choice["message"]["content"]
            parsed_content = json.loads(content)
            if not isinstance(parsed_content, dict):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("PROVIDER_PROTOCOL_ERROR", "provider returned an invalid probe response") from None
        return ProviderProbe(
            success=True,
            supports_streaming=False,
            supports_tools=True,
            supports_json_schema=True,
            checked_at=datetime.now(timezone.utc),
            model=str(self.config.model or ""),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def stream_chat(self, request: ChatRequest):
        """Yield only fully validated OpenAI-compatible SSE events."""
        await self._validate_resolved_addresses()
        payload = self._chat_payload(request)
        allowed_tools = _allowed_tool_names(request.tools)
        headers = self._headers(accept="text/event-stream")
        try:
            async with self._client.stream(
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
        await self._validate_resolved_addresses()
        headers = self._headers(accept="application/json")
        try:
            response = await self._client.post(
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

    async def _validate_resolved_addresses(self) -> None:
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


async def _resolve_host(host: str, port: int) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


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
    done_seen = False
    tool_parts: dict[int, dict[str, str]] = {}

    async for line in response.aiter_lines():
        if not line:
            continue
        if not line.startswith("data: ") or done_seen:
            raise _stream_error()
        raw = line[6:]
        if raw == "[DONE]":
            if finish_reason is None:
                raise _stream_error()
            done_seen = True
            continue
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

    if not done_seen or finish_reason is None:
        raise _stream_error()
    yield ModelStreamEvent(kind="done", finish_reason=finish_reason)


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
    decoded_path = raw_path
    for _ in range(3):
        expanded = unquote(decoded_path)
        if expanded == decoded_path:
            break
        decoded_path = expanded
    segments = decoded_path.replace("\\", "/").split("/")
    if (
        "\\" in decoded_path
        or any(segment in {".", ".."} for segment in segments)
        or re.search(r"(?i)%(?:2f|5c)", raw_path)
    ):
        raise ProviderConfigurationError("provider base URL path is unsafe")

    path = raw_path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return httpx.URL(f"https://{host}{f':{parsed.port}' if parsed.port else ''}{path}")


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
