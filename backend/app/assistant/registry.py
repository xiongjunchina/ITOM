"""Fixed, code-owned assistant capability registry."""
from collections.abc import Iterable

from pydantic import BaseModel

from app.assistant.types import CapabilityDefinition, RiskLevel, validate_capability_input_model


class CapabilityRegistry:
    """Reject unsafe definitions before they can become executable capabilities."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> CapabilityDefinition:
        if not definition.code or definition.code in self._definitions:
            raise ValueError("duplicate or empty capability code")
        if not isinstance(definition.risk, RiskLevel):
            raise ValueError("capability risk must be a RiskLevel")
        if definition.risk is RiskLevel.L4:
            raise ValueError("L4 capabilities are forbidden")
        if definition.risk is RiskLevel.L3 and not definition.requires_confirmation:
            raise ValueError("L3 capabilities require confirmation")
        if not isinstance(definition.input_model, type) or not issubclass(definition.input_model, BaseModel):
            raise ValueError("capability input_model must be a Pydantic BaseModel")
        validate_capability_input_model(definition.input_model)
        if not callable(definition.handler):
            raise ValueError("capability handler is required")
        self._definitions[definition.code] = definition
        return definition

    def get(self, code: str) -> CapabilityDefinition | None:
        return self._definitions.get(code)

    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(self._definitions.values())

    def model_schemas(self, definitions: Iterable[CapabilityDefinition] | None = None) -> list[dict]:
        source = self.definitions() if definitions is None else definitions
        return [definition.model_schema() for definition in source]


registry = CapabilityRegistry()


def register_capability(definition: CapabilityDefinition) -> CapabilityDefinition:
    """Register a fixed server handler in the process-wide registry."""
    return registry.register(definition)
