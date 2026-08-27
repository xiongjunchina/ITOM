"""Load and validate the Git-controlled software release catalog.

The release manifest is the product-version source of truth. Runtime branding
may change developer and legal presentation, but it must never rewrite this
identity or claim that a different build is deployed.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")


class ReleaseProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name_zh: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    edition_zh: str = Field(min_length=1, max_length=100)
    edition_en: str = Field(min_length=1, max_length=100)


class ReleaseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    channel: Literal["stable", "candidate", "development"]
    status: Literal["released", "candidate", "development", "retired"]
    release_date: date

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("release version must use SemVer")
        return value


class ReleaseCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_rollback_version: str
    database_change: Literal["none", "compatible", "breaking"]

    @field_validator("minimum_rollback_version")
    @classmethod
    def validate_minimum_rollback_version(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("minimum rollback version must use SemVer")
        return value


class LocalizedReleaseNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    highlights: list[str] = Field(min_length=1, max_length=20)
    fixes: list[str] = Field(default_factory=list, max_length=20)
    known_limits: list[str] = Field(default_factory=list, max_length=20)


class ReleaseNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zh: LocalizedReleaseNotes
    en: LocalizedReleaseNotes


class SoftwareRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    product: ReleaseProduct
    release: ReleaseIdentity
    compatibility: ReleaseCompatibility
    notes: ReleaseNotes

    def public_payload(self) -> dict:
        """Return only product-facing fields; build and infrastructure data stay private."""
        return {
            "schema_version": self.schema_version,
            "product": self.product.model_dump(),
            "release": self.release.model_dump(mode="json"),
            "notes": self.notes.model_dump(),
        }


def _release_root() -> Path:
    configured = os.getenv("ITOM_RELEASE_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    source_root = Path(__file__).resolve().parents[3] / "release"
    if source_root.is_dir():
        return source_root
    return Path("/srv/release")


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"release JSON must be an object: {path.name}")
    return value


def _current_filename(root: Path) -> str:
    pointer = _read_json(root / "current.json")
    if pointer.get("schema_version") != 1:
        raise ValueError("unsupported current release pointer schema")
    filename = pointer.get("current")
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError("current release pointer must be a safe JSON filename")
    return filename


def _load_release(path: Path) -> SoftwareRelease:
    release = SoftwareRelease.model_validate(_read_json(path))
    expected_name = f"v{release.release.version}.json"
    if path.name != expected_name:
        raise ValueError(f"release filename must be {expected_name}")
    return release


@lru_cache(maxsize=1)
def current_release() -> SoftwareRelease:
    root = _release_root()
    return _load_release(root / "releases" / _current_filename(root))


@lru_cache(maxsize=1)
def release_catalog() -> tuple[SoftwareRelease, ...]:
    root = _release_root()
    releases = tuple(_load_release(path) for path in sorted((root / "releases").glob("v*.json")))
    if not releases:
        raise ValueError("release catalog must contain at least one release")
    current_version = current_release().release.version
    if current_version not in {item.release.version for item in releases}:
        raise ValueError("current release is missing from the release catalog")
    return tuple(sorted(releases, key=lambda item: item.release.release_date, reverse=True))


def clear_release_cache() -> None:
    """Testing hook for environment-scoped manifest validation."""
    current_release.cache_clear()
    release_catalog.cache_clear()
