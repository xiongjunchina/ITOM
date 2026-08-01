"""Strict request contracts for the authenticated web assistant."""

import re
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


_CONTEXT_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_GLID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class PageContextIn(BaseModel):
    """Browser context limited to safe, user-visible page identifiers."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    route: str = Field(pattern=r"^/", max_length=256)
    page_type: str | None = Field(default=None, max_length=48)
    entity_type: str | None = Field(default=None, max_length=32)
    entity_id: str | None = Field(default=None, max_length=26)
    tab: str | None = Field(default=None, max_length=64)
    selected_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("route")
    @classmethod
    def require_normalized_local_route(cls, value: str) -> str:
        parsed = urlsplit(value)
        decoded = unquote(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or "%" in value
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or decoded != value
        ):
            raise ValueError("route must be a normalized local path")
        segments = value.split("/")[1:]
        if value != "/" and any(
            segment in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9_-]+", segment)
            for segment in segments
        ):
            raise ValueError("route must be a normalized local path")
        if any(segment in {".", ".."} for segment in segments):
            raise ValueError("route must be a normalized local path")
        return value

    @field_validator("page_type", "entity_type", "tab")
    @classmethod
    def require_bounded_context_identifier(cls, value: str | None) -> str | None:
        if value is not None and not _CONTEXT_VALUE.fullmatch(value):
            raise ValueError("page context value must be a safe identifier")
        return value

    @field_validator("entity_id")
    @classmethod
    def require_entity_glid(cls, value: str | None) -> str | None:
        if value is not None and not _GLID.fullmatch(value):
            raise ValueError("entity_id must be a GLID")
        return value

    @field_validator("selected_ids")
    @classmethod
    def require_selected_glids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not _GLID.fullmatch(value) for value in values):
            raise ValueError("selected_ids must be unique GLIDs")
        return values


class ConversationCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    page_context: PageContextIn
