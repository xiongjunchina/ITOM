"""Typed, server-owned contracts for registered assistant capabilities."""
from datetime import date, datetime, time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import re
import threading
import time as monotonic_time
from collections.abc import Mapping as MappingABC
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, get_args, get_origin
from uuid import UUID
from weakref import WeakKeyDictionary

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import (
    BindParameter,
    BinaryExpression,
    BooleanClauseList,
    False_,
    Grouping,
    Label,
    Null,
    TextClause,
    True_,
    UnaryExpression,
)
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.schema import Column, Table
from sqlalchemy.sql.selectable import (
    Alias,
    CTE,
    CompoundSelect,
    Join,
    ScalarSelect,
    Select,
    Subquery,
    _OffsetLimitParam,
)

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


class CapabilityExecutionCancelled(RuntimeError):
    """Raised cooperatively inside a capability worker after cancellation."""


@dataclass(frozen=True)
class CapabilityExecutionContext:
    """Cooperative deadline/cancellation signal for synchronous L1/L2 handlers.

    This is not a thread-kill primitive.  A handler that performs long CPU work
    or blocking I/O must poll ``is_cancelled`` or call ``raise_if_cancelled``.
    """

    deadline_monotonic: float
    _cancelled: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set() or monotonic_time.monotonic() >= self.deadline_monotonic

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise CapabilityExecutionCancelled("assistant capability execution cancelled")


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
    owner_token: object


@dataclass(frozen=True)
class _LockedRecordState:
    db: Session
    entity: Any
    selected_fields: frozenset[str]
    primary_key_fields: frozenset[str]
    owner_token: object
    outer_transaction: Any
    nested_transaction: Any
    nonce: object


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


_ALLOWED_BINARY_OPERATORS = frozenset({
    operators.eq,
    operators.ne,
    operators.lt,
    operators.le,
    operators.gt,
    operators.ge,
    operators.is_,
    operators.is_not,
    operators.like_op,
    operators.not_like_op,
    operators.in_op,
    operators.not_in_op,
})
_ALLOWED_BOOLEAN_OPERATORS = frozenset({operators.and_, operators.or_})
_ALLOWED_ORDER_MODIFIERS = frozenset({operators.asc_op, operators.desc_op})


def _literal_bound_value(value: Any, *, violation: Callable[[], AppError]) -> None:
    try:
        _freeze_value(value)
    except ValueError:
        raise violation() from None


def _direct_column(value: Any, table: Table, *, violation: Callable[[], AppError]) -> Column:
    column = value.element if isinstance(value, Label) else value
    if not isinstance(column, Column) or column.table is not table:
        raise violation()
    return column


def _validate_predicate(value: Any, table: Table, *, violation: Callable[[], AppError]) -> None:
    if isinstance(value, Grouping):
        _validate_predicate(value.element, table, violation=violation)
        return
    if isinstance(value, BooleanClauseList):
        if value.operator not in _ALLOWED_BOOLEAN_OPERATORS:
            raise violation()
        for clause in value.clauses:
            _validate_predicate(clause, table, violation=violation)
        return
    if isinstance(value, BinaryExpression):
        if value.operator not in _ALLOWED_BINARY_OPERATORS:
            raise violation()
        for operand in (value.left, value.right):
            if isinstance(operand, Column):
                _direct_column(operand, table, violation=violation)
            elif isinstance(operand, BindParameter):
                _literal_bound_value(operand.value, violation=violation)
            elif isinstance(operand, (True_, False_, Null)):
                continue
            else:
                raise violation()
        return
    if isinstance(value, UnaryExpression) and value.operator is operators.inv:
        _validate_predicate(value.element, table, violation=violation)
        return
    raise violation()


def _validate_ordering(value: Any, table: Table, *, violation: Callable[[], AppError]) -> None:
    if isinstance(value, Column):
        _direct_column(value, table, violation=violation)
        return
    if isinstance(value, UnaryExpression) and value.modifier in _ALLOWED_ORDER_MODIFIERS:
        _direct_column(value.element, table, violation=violation)
        return
    raise violation()


def _compile_time_int(
    value: Any,
    *,
    maximum: int,
    violation: Callable[[], AppError],
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, _OffsetLimitParam) or type(value.value) is not int:
        raise violation()
    literal = value.value
    if literal < 0 or literal > maximum:
        raise violation()
    return literal


def _projection_metadata(statement: Any, *, violation: Callable[[], AppError]) -> tuple[str, tuple[tuple[str, str], ...], Any | None]:
    if not isinstance(statement, Select):
        raise violation()
    if (
        getattr(statement, "_with_options", ())
        or getattr(statement, "_for_update_arg", None) is not None
        or getattr(statement, "_independent_ctes", ())
        or getattr(statement, "_group_by_clauses", ())
        or getattr(statement, "_having_criteria", ())
        or bool(getattr(statement, "_distinct", False))
        or getattr(statement, "_distinct_on", ())
        or getattr(statement, "_prefixes", ())
        or getattr(statement, "_suffixes", ())
        or getattr(statement, "_statement_hints", ())
        or getattr(statement, "_hints", {})
    ):
        raise violation()
    for node in visitors.iterate(statement):
        if node is statement:
            continue
        if isinstance(
            node,
            (Select, CompoundSelect, ScalarSelect, CTE, Join, Alias, Subquery, FunctionElement, TextClause),
        ):
            raise violation()
        if getattr(node, "_for_update_arg", None) is not None:
            raise violation()
    descriptions = tuple(getattr(statement, "column_descriptions", ()) or ())
    selected = tuple(statement.selected_columns)
    if not descriptions or len(descriptions) != len(selected):
        raise violation()
    if any(desc.get("entity") is None or desc.get("aliased") for desc in descriptions):
        raise violation()
    entity_candidates = {desc.get("entity") for desc in descriptions}
    if len(entity_candidates) != 1:
        raise violation()
    entity = next(iter(entity_candidates))
    try:
        mapper = sa_inspect(entity)
    except Exception:
        raise violation() from None
    table = mapper.local_table
    if not isinstance(table, Table):
        raise violation()
    final_froms = tuple(statement.get_final_froms())
    if len(final_froms) != 1 or final_froms[0] is not table:
        raise violation()
    fields: list[tuple[str, str]] = []
    for desc, selected_value in zip(descriptions, selected):
        expr = desc.get("expr")
        desc_entity = desc.get("entity")
        if expr is desc_entity or isinstance(expr, type):
            raise violation()
        column = _direct_column(selected_value, table, violation=violation)
        try:
            mapper.get_property_by_column(column)
        except Exception:
            raise violation() from None
        field_name = str(desc.get("name") or "")
        source_key = column.key
        if not field_name or not source_key:
            raise violation()
        fields.append((field_name, str(source_key)))
    for criterion in tuple(getattr(statement, "_where_criteria", ()) or ()):
        _validate_predicate(criterion, table, violation=violation)
    for criterion in tuple(getattr(statement, "_order_by_clauses", ()) or ()):
        _validate_ordering(criterion, table, violation=violation)
    model_name = mapper.class_.__name__
    return model_name, tuple(fields), entity


def _bounded_select(statement: Any, *, violation: Callable[[], AppError], max_rows: int = _ACTION_PORT_MAX_ROWS) -> Any:
    _compile_time_int(
        getattr(statement, "_offset_clause", None),
        maximum=_ACTION_PORT_MAX_OFFSET,
        violation=violation,
    )
    limit = _compile_time_int(
        getattr(statement, "_limit_clause", None),
        maximum=max_rows,
        violation=violation,
    )
    if limit is None:
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
        _PORT_STATE[self] = _PortState(
            db=db,
            violation=_preview_violation,
            owner_token=object(),
        )

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
        _PORT_STATE[self] = _PortState(
            db=db,
            violation=_transaction_violation,
            owner_token=object(),
        )

    def lock_one(self, statement: Any) -> LockedActionRecord | None:
        state = _state_for(self)
        model_name, fields, entity = _projection_metadata(statement, violation=state.violation)
        if entity is None:
            raise state.violation()
        if any(field_name != source_key for field_name, source_key in fields):
            raise state.violation()
        bounded = _bounded_select(statement, violation=state.violation, max_rows=1)
        offset = _compile_time_int(
            getattr(bounded, "_offset_clause", None),
            maximum=_ACTION_PORT_MAX_OFFSET,
            violation=state.violation,
        )
        limit = _compile_time_int(
            getattr(bounded, "_limit_clause", None),
            maximum=2,
            violation=state.violation,
        )
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
            owner_token=state.owner_token,
            outer_transaction=state.db.get_transaction(),
            nested_transaction=state.db.get_nested_transaction(),
            nonce=object(),
        )
        return handle

    def update_locked(self, handle: LockedActionRecord, values: Mapping[str, Any]) -> LockedActionRecord:
        state = _state_for(self)
        locked_state = _LOCKED_STATE.get(handle)
        if (
            locked_state is None
            or locked_state.db is not state.db
            or locked_state.owner_token is not state.owner_token
            or state.db.get_transaction() is not locked_state.outer_transaction
            or state.db.get_nested_transaction() is not locked_state.nested_transaction
            or locked_state.outer_transaction is None
            or not locked_state.outer_transaction.is_active
            or (
                locked_state.nested_transaction is not None
                and not locked_state.nested_transaction.is_active
            )
        ):
            raise state.violation()
        inspection = sa_inspect(locked_state.entity)
        if (
            inspection.session is not state.db
            or not inspection.persistent
            or inspection.detached
            or inspection.deleted
        ):
            raise state.violation()
        updates = dict(values)
        for key, value in updates.items():
            if key not in locked_state.selected_fields or key in locked_state.primary_key_fields:
                raise state.violation()
            _freeze_value(value)
        _LOCKED_STATE.pop(handle, None)
        for key, value in updates.items():
            setattr(locked_state.entity, key, value)
        merged = handle.snapshot.as_dict()
        merged.update(updates)
        snapshot = _record_from_mapping(
            handle.snapshot.model_name,
            merged,
            violation=state.violation,
        )
        rotated = LockedActionRecord(snapshot=snapshot)
        _LOCKED_STATE[rotated] = _LockedRecordState(
            db=locked_state.db,
            entity=locked_state.entity,
            selected_fields=locked_state.selected_fields,
            primary_key_fields=locked_state.primary_key_fields,
            owner_token=locked_state.owner_token,
            outer_transaction=locked_state.outer_transaction,
            nested_transaction=locked_state.nested_transaction,
            nonce=object(),
        )
        return rotated

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


CapabilityHandler = (
    Callable[[ReadOnlyActionData, ActionActorContext, BaseModel, CapabilityExecutionContext], CapabilityResult]
    | ConfirmedCapabilityHandler
)


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
