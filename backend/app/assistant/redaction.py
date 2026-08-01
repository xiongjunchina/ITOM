"""Deterministic recursive redaction for assistant-bound representations."""
from collections.abc import Mapping
import re
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset({"password", "token", "secret", "cookie", "authorization", "api_key"})
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT = re.compile(r"(?<![A-Za-z0-9_-])(?:eyJ[A-Za-z0-9_-]*\.){2}[A-Za-z0-9_-]+")


def _normalise_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_sensitive_key(key: object, sensitive_fields: set[str]) -> bool:
    normalized = _normalise_key(key)
    return normalized in {_normalise_key(item) for item in SENSITIVE_KEYS | sensitive_fields}


def _redact_text(value: str) -> str:
    return _JWT.sub(REDACTED, _BEARER.sub(REDACTED, value))


def redact_mapping(value: object, sensitive_fields: set[str] | frozenset[str] = frozenset()) -> object:
    """Return a redacted deep copy, preserving non-sensitive JSON-like content."""
    fields = set(sensitive_fields)
    if isinstance(value, Mapping):
        dynamic_sensitive = value.get("sensitive") is True
        redacted: dict[object, object] = {}
        for key, child in value.items():
            if _is_sensitive_key(key, fields) or (dynamic_sensitive and _normalise_key(key) in {"value", "answer", "content"}):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_mapping(child, fields)
        return redacted
    if isinstance(value, list):
        return [redact_mapping(item, fields) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_mapping(item, fields) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def redact_for_model(value: object, sensitive_fields: set[str] | frozenset[str] = frozenset()) -> object:
    return redact_mapping(value, sensitive_fields)


def redact_for_message(value: object, sensitive_fields: set[str] | frozenset[str] = frozenset()) -> object:
    return redact_mapping(value, sensitive_fields)


def redact_for_log(value: object, sensitive_fields: set[str] | frozenset[str] = frozenset()) -> object:
    return redact_mapping(value, sensitive_fields)
