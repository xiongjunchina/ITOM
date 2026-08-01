"""Provider-neutral model contracts."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.assistant.types import RiskLevel


class ProviderConfigurationError(ValueError):
    """Raised when a provider endpoint violates the outbound security policy."""


class ProviderError(Exception):
    """A stable, secret-free provider failure safe for audit metadata."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ProviderProbe:
    success: bool
    supports_streaming: bool
    supports_tools: bool
    supports_json_schema: bool
    checked_at: datetime
    model: str


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[Mapping[str, Any], ...]
    tools: tuple[Mapping[str, Any], ...] = ()
    response_schema: Mapping[str, Any] | None = None
    risk_level: RiskLevel | str = RiskLevel.L1
    max_output_tokens: int | None = None
    temperature: float | None = None
    purpose: str = "chat"
    conversation_id: str | None = None
    message_id: str | None = None
    profile_version_id: str | None = None


@dataclass(frozen=True)
class ModelStreamEvent:
    kind: str
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    async def probe(self) -> ProviderProbe: ...

    def stream_chat(self, request: ChatRequest) -> AsyncIterator[ModelStreamEvent]: ...
