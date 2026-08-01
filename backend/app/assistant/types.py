"""Typed, server-owned contracts for registered assistant capabilities."""
from dataclasses import dataclass, field
from enum import Enum
import re
from collections.abc import Mapping as MappingABC
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError
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
        aliases.update(_alias_segments(getattr(field, attribute, None)))
    return aliases


def _alias_segments(alias: object) -> set[str]:
    """Return every string segment used by Pydantic's supported alias forms."""
    if isinstance(alias, str):
        return {alias}
    segments: set[str] = set()
    for segment in getattr(alias, "path", ()):
        if isinstance(segment, str):
            segments.add(segment)
    for choice in getattr(alias, "choices", ()):
        segments.update(_alias_segments(choice))
    return segments


def _is_unbounded_mapping(annotation: object) -> bool:
    origin = get_origin(annotation)
    return annotation in {dict, Mapping, MappingABC} or origin in {dict, MappingABC}


def _check_input_annotation(annotation: object, check_model: Callable[[type[BaseModel]], None]) -> None:
    if annotation in {Any, object} or _is_unbounded_mapping(annotation):
        raise ValueError("unbounded mapping input is forbidden")
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        check_model(annotation)
        return
    for argument in get_args(annotation):
        _check_input_annotation(argument, check_model)


def _has_unbounded_schema_object(value: object) -> bool:
    if isinstance(value, Mapping):
        if "additionalProperties" in value and value["additionalProperties"] is not False:
            return True
        return any(_has_unbounded_schema_object(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_unbounded_schema_object(child) for child in value)
    return False


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
            _check_input_annotation(field.annotation, check)
        if _has_unbounded_schema_object(model.model_json_schema()):
            raise ValueError("unbounded mapping input is forbidden")

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


def _preview_violation() -> AppError:
    return AppError(
        "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION",
        "动作预览不得修改数据或控制事务",
        409,
    )


def _transaction_violation() -> AppError:
    return AppError(
        "AI_ACTION_TRANSACTION_VIOLATION",
        "动作处理器不能自行提交或回滚事务",
        409,
    )


@dataclass(frozen=True)
class ActionActorContext:
    id: str
    username: str | None
    person_id: str | None
    is_active: bool
    preferences: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_auth_user(cls, actor: Any) -> "ActionActorContext":
        preferences = getattr(actor, "preferences", None)
        if not isinstance(preferences, Mapping):
            preferences = {}
        return cls(
            id=str(actor.id),
            username=getattr(actor, "username", None),
            person_id=getattr(actor, "person_id", None),
            is_active=bool(getattr(actor, "is_active", False)),
            preferences=MappingProxyType(dict(preferences)),
        )


class _ReadOnlyRecordProxy:
    __slots__ = ("_record",)

    def __init__(self, record: Any) -> None:
        object.__setattr__(self, "_record", record)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise _preview_violation()

    def __repr__(self) -> str:
        return f"<ReadOnlyRecordProxy {type(self._record).__name__}>"


class _SelectOnlyMixin:
    __slots__ = ("_db",)

    def __init__(self, db: Session) -> None:
        self._db = db

    def _select_statement(self, statement: Any, *, violation: Callable[[], AppError]) -> Any:
        if not bool(getattr(statement, "is_select", False)):
            raise violation()
        return statement

    def _fetch_first(self, statement: Any, *, with_for_update: bool = False) -> Any:
        statement = self._select_statement(statement, violation=self._violation)
        query = self._query_from_entity_select(statement, with_for_update=with_for_update)
        if query is not None:
            return self._materialize_first(query.first())
        if with_for_update and callable(getattr(statement, "with_for_update", None)):
            statement = statement.with_for_update()
        return self._materialize_first(self._db.execute(statement).scalars().first())

    def _fetch_all(self, statement: Any, *, with_for_update: bool = False) -> list[Any]:
        statement = self._select_statement(statement, violation=self._violation)
        query = self._query_from_entity_select(statement, with_for_update=with_for_update)
        if query is not None:
            return [self._materialize_first(row) for row in query.all()]
        if with_for_update and callable(getattr(statement, "with_for_update", None)):
            statement = statement.with_for_update()
        return [self._materialize_first(row) for row in self._db.execute(statement).scalars().all()]

    def _materialize_first(self, value: Any) -> Any:
        return value

    def _query_from_entity_select(self, statement: Any, *, with_for_update: bool):
        descriptions = getattr(statement, "column_descriptions", None) or ()
        entity = descriptions[0].get("entity") if len(descriptions) == 1 else None
        if entity is None:
            return None
        query = self._db.query(entity)
        where_criteria = tuple(getattr(statement, "_where_criteria", ()) or ())
        if where_criteria:
            query = query.filter(*where_criteria)
        order_by = tuple(getattr(statement, "_order_by_clauses", ()) or ())
        if order_by:
            query = query.order_by(*order_by)
        limit_clause = getattr(statement, "_limit_clause", None)
        if limit_clause is not None:
            query = query.limit(limit_clause)
        if with_for_update:
            query = query.with_for_update()
        return query

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class ReadOnlyActionData(_SelectOnlyMixin):
    _BLOCKED_NAMES = frozenset({
        "add",
        "add_all",
        "begin",
        "bind",
        "bulk_insert_mappings",
        "bulk_save_objects",
        "bulk_update_mappings",
        "commit",
        "connection",
        "delete",
        "flush",
        "get_bind",
        "get_transaction",
        "merge",
        "query",
        "rollback",
        "scalar",
        "scalars",
    })

    def _violation(self) -> AppError:
        return _preview_violation()

    def _materialize_first(self, value: Any) -> Any:
        if hasattr(value, "_sa_instance_state"):
            return _ReadOnlyRecordProxy(value)
        return value

    def fetch_first(self, statement: Any, *, with_for_update: bool = False) -> Any:
        return self._fetch_first(statement, with_for_update=with_for_update)

    def fetch_all(self, statement: Any, *, with_for_update: bool = False) -> list[Any]:
        return self._fetch_all(statement, with_for_update=with_for_update)

    def execute(self, statement: Any, *, with_for_update: bool = False) -> tuple[Any, ...]:
        return tuple(self._fetch_all(statement, with_for_update=with_for_update))

    def __getattr__(self, name: str) -> Any:
        if name in self._BLOCKED_NAMES:
            raise _preview_violation()
        raise AttributeError(name)


class ActionUnitOfWork(_SelectOnlyMixin):
    _BLOCKED_NAMES = frozenset({
        "begin",
        "begin_nested",
        "bind",
        "commit",
        "connection",
        "execute",
        "flush",
        "get_bind",
        "get_transaction",
        "query",
        "rollback",
        "scalar",
        "scalars",
    })

    def _violation(self) -> AppError:
        return _transaction_violation()

    def fetch_first(self, statement: Any, *, with_for_update: bool = False) -> Any:
        return self._fetch_first(statement, with_for_update=with_for_update)

    def fetch_all(self, statement: Any, *, with_for_update: bool = False) -> list[Any]:
        return self._fetch_all(statement, with_for_update=with_for_update)

    def __getattr__(self, name: str) -> Any:
        if name in self._BLOCKED_NAMES:
            raise _transaction_violation()
        raise AttributeError(name)


class ConfirmedCapabilityHandler(Protocol):
    def authorize_preview(self, db: ReadOnlyActionData, actor: ActionActorContext, data: BaseModel) -> None: ...
    def preview(self, db: ReadOnlyActionData, actor: ActionActorContext, data: BaseModel) -> CapabilityResult: ...
    def authorize_record(self, db: ActionUnitOfWork, actor: ActionActorContext, data: BaseModel) -> None: ...
    def __call__(self, db: ActionUnitOfWork, actor: ActionActorContext, data: BaseModel) -> CapabilityResult: ...


CapabilityHandler = Callable[[ActionUnitOfWork, ActionActorContext, BaseModel], CapabilityResult] | ConfirmedCapabilityHandler


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
        validate_capability_input_model(self.input_model)
        return {
            "code": self.code,
            "description": self.description or self.code,
            "risk": self.risk.value,
            "input_schema": _sanitize_schema(self.input_model.model_json_schema()),
        }
