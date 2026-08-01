"""Typed, server-owned contracts for registered assistant capabilities."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

from pydantic import BaseModel


class RiskLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"

    @property
    def rank(self) -> int:
        return (RiskLevel.L0, RiskLevel.L1, RiskLevel.L2, RiskLevel.L3, RiskLevel.L4).index(self)

    @classmethod
    def coerce(cls, value: "RiskLevel | str") -> "RiskLevel":
        return value if isinstance(value, cls) else cls(value)


class AssistantChannel(str, Enum):
    WEB = "web"
    AILY = "aily"

    @classmethod
    def coerce(cls, value: "AssistantChannel | str") -> "AssistantChannel":
        return value if isinstance(value, cls) else cls(value)


@dataclass(frozen=True)
class CapabilityResult:
    status: str
    data: Mapping[str, Any] = field(default_factory=dict)
    message: str | None = None


@dataclass(frozen=True)
class CapabilityContext:
    """Request-time facts derived from the active ITOM account and policy rows."""

    channel: AssistantChannel
    audience: str
    effective_roles: frozenset[str]
    permissions: Mapping[str, list[str]]
    max_risk: RiskLevel


CapabilityHandler = Callable[[Any, Any, BaseModel], CapabilityResult]


@dataclass(frozen=True)
class CapabilityDefinition:
    """A capability whose executable handler exists only in server code."""

    code: str
    channels: frozenset[AssistantChannel]
    audiences: frozenset[str]
    module: str | None
    action: str | None
    risk: RiskLevel
    input_model: type[BaseModel]
    handler: CapabilityHandler | None
    requires_confirmation: bool = False
    description: str | None = None

    def model_schema(self) -> dict[str, Any]:
        """Return the only capability representation permitted to reach a model."""
        return {
            "code": self.code,
            "description": self.description or self.code,
            "risk": self.risk.value,
            "input_schema": self.input_model.model_json_schema(),
        }
