"""Typed, server-owned contracts for registered assistant capabilities."""
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Callable, Mapping, get_args

from pydantic import BaseModel

from app.assistant.redaction import is_sensitive_name


_UNSAFE_INPUT_NAMES = frozenset({
    "password", "passwd", "pwd", "token", "accesstoken", "refreshtoken", "idtoken",
    "clientsecret", "secret", "apikey", "apiaccesskey", "privatekey", "credential", "credentials",
    "cookie", "setcookie", "authorization", "bearer", "jwt", "role", "roles", "audience",
    "permission", "permissions", "authuser", "authuserid", "userid", "user", "actor", "actorid",
    "currentuser", "securitycontext",
})
_SCHEMA_VALUE_KEYS = frozenset({"default", "example", "examples"})


def _normalise_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _unsafe_input_name(value: object) -> bool:
    normalized = _normalise_name(value)
    segments = _name_segments(value)
    return (
        is_sensitive_name(value)
        or normalized in _UNSAFE_INPUT_NAMES
        or normalized.startswith("internal")
        or bool(segments.intersection({"authorization", "auth", "permission", "permissions", "role", "roles", "audience"}))
    )


def _name_segments(value: object) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    return {segment.lower() for segment in re.split(r"[^A-Za-z0-9]+", text) if segment}


def _field_aliases(field_name: str, field: object) -> set[str]:
    aliases = {field_name}
    for attribute in ("alias", "validation_alias", "serialization_alias"):
        value = getattr(field, attribute, None)
        if isinstance(value, str):
            aliases.add(value)
        for choice in getattr(value, "choices", ()):
            if isinstance(choice, str):
                aliases.add(choice)
    return aliases


def _nested_models(annotation: object) -> set[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    nested: set[type[BaseModel]] = set()
    for argument in get_args(annotation):
        nested.update(_nested_models(argument))
    return nested


def validate_capability_input_model(input_model: type[BaseModel]) -> None:
    """Reject model-controlled credentials or authorization facts before registration."""
    checked: set[type[BaseModel]] = set()

    def check(model: type[BaseModel]) -> None:
        if model in checked:
            return
        checked.add(model)
        for field_name, field in model.model_fields.items():
            unsafe = next((name for name in _field_aliases(field_name, field) if _unsafe_input_name(name)), None)
            if unsafe:
                raise ValueError(f"unsafe input field: {unsafe}")
            for nested in _nested_models(field.annotation):
                check(nested)

    check(input_model)


def _sanitize_schema(value: object, *, property_map: bool = False) -> object:
    """Remove default/example values and unsafe keys before a model sees JSON Schema."""
    from app.assistant.redaction import redact_for_model

    if isinstance(value, Mapping):
        clean: dict[object, object] = {}
        for key, child in value.items():
            if property_map:
                if _unsafe_input_name(key):
                    continue
                clean[key] = _sanitize_schema(child)
                continue
            if _normalise_name(key) in _SCHEMA_VALUE_KEYS or _unsafe_input_name(key):
                continue
            clean[key] = _sanitize_schema(child, property_map=key == "properties")
        return clean
    if isinstance(value, list):
        return [_sanitize_schema(item, property_map=property_map) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_schema(item, property_map=property_map) for item in value)
    return redact_for_model(value)


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
            "input_schema": _sanitize_schema(self.input_model.model_json_schema()),
        }
