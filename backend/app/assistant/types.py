"""Typed, server-owned contracts for registered assistant capabilities."""
from datetime import date, datetime, time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import re
from collections.abc import Mapping as MappingABC
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, get_args, get_origin
from uuid import UUID
from weakref import WeakKeyDictionary

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
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
        frozen_preferences = _freeze_value(dict(preferences))
        return cls(
            id=str(actor.id),
            username=getattr(actor, "username", None),
            person_id=getattr(actor, "person_id", None),
            is_active=bool(getattr(actor, "is_active", False)),
            preferences=frozen_preferences,
        )


_ACTION_PORT_MAX_ROWS = 25
_ACTION_PORT_MAX_OFFSET = 1000
_SAFE_SCALARS = (str, int, float, bool, type(None), bytes, date, datetime, time, Decimal, UUID)
_READ_ONLY_BLOCKED_NAMES = frozenset({
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
_UOW_BLOCKED_NAMES = frozenset({
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


@dataclass(frozen=True)
class _FrozenRecordState:
    values: Mapping[str, Any]
    violation: Callable[[], AppError]


_FROZEN_RECORD_STATE: WeakKeyDictionary[Any, _FrozenRecordState] = WeakKeyDictionary()


class FrozenActionRecord:
    __slots__ = ("model_name", "__weakref__")

    def __init__(self, *, model_name: str) -> None:
        object.__setattr__(self, "model_name", model_name)

    def __getattr__(self, name: str) -> Any:
        state = _FROZEN_RECORD_STATE.get(self)
        if state is not None and name in state.values:
            return state.values[name]
        raise AttributeError(name)

    def __setattr__(self, _name: str, _value: Any) -> None:
        state = _FROZEN_RECORD_STATE.get(self)
        raise state.violation() if state is not None else _preview_violation()

    def __dir__(self) -> list[str]:
        state = _FROZEN_RECORD_STATE.get(self)
        public = {name for name in object.__dir__(self) if not name.startswith("_")}
        return sorted(public.union(state.values.keys() if state is not None else ()))

    def as_dict(self) -> dict[str, Any]:
        state = _FROZEN_RECORD_STATE.get(self)
        return dict(state.values) if state is not None else {}

    def __repr__(self) -> str:
        state = _FROZEN_RECORD_STATE.get(self)
        fields = ", ".join(sorted(state.values)) if state is not None else ""
        return f"<FrozenActionRecord {self.model_name} fields=[{fields}]>"


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class LockedActionRecord:
    snapshot: FrozenActionRecord

    def __repr__(self) -> str:
        return f"<LockedActionRecord {self.snapshot.model_name}>"


@dataclass(frozen=True)
class _PortState:
    db: Session
    violation: Callable[[], AppError]


@dataclass(frozen=True)
class _LockedRecordState:
    db: Session
    entity: Any
    selected_fields: frozenset[str]
    primary_key_fields: frozenset[str]


_PORT_STATE: WeakKeyDictionary[Any, _PortState] = WeakKeyDictionary()
_LOCKED_STATE: WeakKeyDictionary[Any, _LockedRecordState] = WeakKeyDictionary()


def _freeze_value(value: Any) -> Any:
    if isinstance(value, _SAFE_SCALARS):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(child) for child in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_value(child) for child in value))
    if callable(value) or hasattr(value, "_sa_instance_state"):
        raise ValueError("unsafe action record value")
    raise ValueError("non-scalar action record value")


def _clause_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    literal = getattr(value, "value", None)
    if isinstance(literal, int):
        return literal
    return None


def _projection_metadata(statement: Any, *, violation: Callable[[], AppError]) -> tuple[str, tuple[tuple[str, str], ...], Any | None]:
    if not bool(getattr(statement, "is_select", False)):
        raise violation()
    if getattr(statement, "_with_options", ()):
        raise violation()
    if getattr(statement, "_for_update_arg", None) is not None:
        raise violation()
    descriptions = tuple(getattr(statement, "column_descriptions", ()) or ())
    if not descriptions:
        raise violation()
    entity_candidates = {desc.get("entity") for desc in descriptions if desc.get("entity") is not None}
    entity = next(iter(entity_candidates)) if len(entity_candidates) == 1 else None
    fields: list[tuple[str, str]] = []
    for desc in descriptions:
        expr = desc.get("expr")
        desc_entity = desc.get("entity")
        if expr is desc_entity or isinstance(expr, type):
            raise violation()
        annotations = getattr(expr, "_annotations", {})
        proxy_owner = annotations.get("proxy_owner")
        proxy_key = annotations.get("proxy_key")
        if proxy_owner is not None and proxy_key:
            mapped_property = getattr(getattr(proxy_owner, "attrs", None), "get", lambda _key: None)(proxy_key)
            if mapped_property is not None and hasattr(mapped_property, "direction"):
                raise violation()
        field_name = str(desc.get("name") or "")
        source_key = getattr(getattr(expr, "element", None), "key", None) or getattr(expr, "key", None) or field_name
        if not field_name or not source_key:
            raise violation()
        fields.append((field_name, str(source_key)))
    model_name = entity.__name__ if entity is not None else "Projection"
    return model_name, tuple(fields), entity


def _bounded_select(statement: Any, *, violation: Callable[[], AppError], max_rows: int = _ACTION_PORT_MAX_ROWS) -> Any:
    offset = _clause_int(getattr(statement, "_offset_clause", None)) or 0
    if offset > _ACTION_PORT_MAX_OFFSET:
        raise violation()
    limit = _clause_int(getattr(statement, "_limit_clause", None))
    if limit is None or limit > max_rows + 1:
        return statement.limit(max_rows + 1)
    return statement


def _record_from_mapping(
    model_name: str,
    mapping: Mapping[str, Any],
    *,
    violation: Callable[[], AppError],
) -> FrozenActionRecord:
    frozen = {str(key): _freeze_value(value) for key, value in mapping.items()}
    record = FrozenActionRecord(model_name=model_name)
    _FROZEN_RECORD_STATE[record] = _FrozenRecordState(
        values=MappingProxyType(frozen),
        violation=violation,
    )
    return record


def _state_for(port: Any) -> _PortState:
    state = _PORT_STATE.get(port)
    if state is None:
        raise RuntimeError("action port state missing")
    return state


def _blocked_readonly_method(*_args, **_kwargs) -> None:
    raise _preview_violation()


class ReadOnlyActionData:
    __slots__ = ("__weakref__",)

    add = _blocked_readonly_method
    add_all = _blocked_readonly_method
    begin = _blocked_readonly_method
    bulk_insert_mappings = _blocked_readonly_method
    bulk_save_objects = _blocked_readonly_method
    bulk_update_mappings = _blocked_readonly_method
    commit = _blocked_readonly_method
    connection = _blocked_readonly_method
    delete = _blocked_readonly_method
    flush = _blocked_readonly_method
    get_bind = _blocked_readonly_method
    get_transaction = _blocked_readonly_method
    merge = _blocked_readonly_method
    query = _blocked_readonly_method
    rollback = _blocked_readonly_method
    scalar = _blocked_readonly_method
    scalars = _blocked_readonly_method

    def __init__(self, db: Session) -> None:
        _PORT_STATE[self] = _PortState(db=db, violation=_preview_violation)

    def fetch_first(self, statement: Any, *, with_for_update: bool = False) -> FrozenActionRecord | None:
        if with_for_update:
            raise _preview_violation()
        rows = self.fetch_all(statement)
        return rows[0] if rows else None

    def fetch_all(self, statement: Any, *, with_for_update: bool = False) -> tuple[FrozenActionRecord, ...]:
        if with_for_update:
            raise _preview_violation()
        state = _state_for(self)
        model_name, _fields, _entity = _projection_metadata(statement, violation=state.violation)
        bounded = _bounded_select(statement, violation=state.violation)
        rows = state.db.execute(bounded).mappings().all()
        if len(rows) > _ACTION_PORT_MAX_ROWS:
            raise state.violation()
        return tuple(_record_from_mapping(model_name, row, violation=state.violation) for row in rows)

    def execute(self, statement: Any, *, with_for_update: bool = False) -> tuple[FrozenActionRecord, ...]:
        return self.fetch_all(statement, with_for_update=with_for_update)

    def __dir__(self) -> list[str]:
        return ["execute", "fetch_all", "fetch_first"]

    def __getattribute__(self, name: str) -> Any:
        if name in _READ_ONLY_BLOCKED_NAMES:
            raise _preview_violation()
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        if name in _READ_ONLY_BLOCKED_NAMES:
            raise _preview_violation()
        raise AttributeError(name)

    def __repr__(self) -> str:
        return "<ReadOnlyActionData>"


def _blocked_uow_method(*_args, **_kwargs) -> None:
    raise _transaction_violation()


class ActionUnitOfWork:
    __slots__ = ("__weakref__",)

    begin = _blocked_uow_method
    begin_nested = _blocked_uow_method
    commit = _blocked_uow_method
    connection = _blocked_uow_method
    flush = _blocked_uow_method
    get_bind = _blocked_uow_method
    get_transaction = _blocked_uow_method
    query = _blocked_uow_method
    rollback = _blocked_uow_method
    scalar = _blocked_uow_method
    scalars = _blocked_uow_method

    def __init__(self, db: Session) -> None:
        _PORT_STATE[self] = _PortState(db=db, violation=_transaction_violation)

    def lock_one(self, statement: Any) -> LockedActionRecord | None:
        state = _state_for(self)
        model_name, fields, entity = _projection_metadata(statement, violation=state.violation)
        if entity is None:
            raise state.violation()
        if any(field_name != source_key for field_name, source_key in fields):
            raise state.violation()
        bounded = _bounded_select(statement, violation=state.violation, max_rows=1)
        offset = _clause_int(getattr(bounded, "_offset_clause", None))
        limit = _clause_int(getattr(bounded, "_limit_clause", None))
        query = state.db.query(entity)
        where_criteria = tuple(getattr(bounded, "_where_criteria", ()) or ())
        if where_criteria:
            query = query.filter(*where_criteria)
        order_by = tuple(getattr(bounded, "_order_by_clauses", ()) or ())
        if order_by:
            query = query.order_by(*order_by)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        row = query.with_for_update().populate_existing().first()
        if row is None:
            return None
        snapshot = _record_from_mapping(
            model_name,
            {field_name: getattr(row, source_key) for field_name, source_key in fields},
            violation=state.violation,
        )
        mapper = sa_inspect(entity)
        primary_key_fields = frozenset(column.key for column in mapper.primary_key)
        handle = LockedActionRecord(snapshot=snapshot)
        _LOCKED_STATE[handle] = _LockedRecordState(
            db=state.db,
            entity=row,
            selected_fields=frozenset(field_name for field_name, _source_key in fields),
            primary_key_fields=primary_key_fields,
        )
        return handle

    def update_locked(self, handle: LockedActionRecord, values: Mapping[str, Any]) -> FrozenActionRecord:
        state = _state_for(self)
        locked_state = _LOCKED_STATE.get(handle)
        if locked_state is None or locked_state.db is not state.db:
            raise state.violation()
        updates = dict(values)
        if not updates:
            return handle.snapshot
        for key, value in updates.items():
            if key not in locked_state.selected_fields or key in locked_state.primary_key_fields:
                raise state.violation()
            _freeze_value(value)
            setattr(locked_state.entity, key, value)
        merged = handle.snapshot.as_dict()
        merged.update(updates)
        return _record_from_mapping(
            handle.snapshot.model_name,
            merged,
            violation=state.violation,
        )

    def __dir__(self) -> list[str]:
        return ["lock_one", "update_locked"]

    def __getattribute__(self, name: str) -> Any:
        if name in _UOW_BLOCKED_NAMES:
            raise _transaction_violation()
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        if name in _UOW_BLOCKED_NAMES:
            raise _transaction_violation()
        raise AttributeError(name)

    def __repr__(self) -> str:
        return "<ActionUnitOfWork>"


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
