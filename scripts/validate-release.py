#!/usr/bin/env python3
"""Validate the Git-controlled ITOM software release contract with stdlib only."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path


SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
CHANNELS = {"stable", "candidate", "development"}
STATUSES = {"released", "candidate", "development", "retired"}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_release(repo_root: Path) -> str:
    release_root = repo_root / "release"
    pointer = read_json(release_root / "current.json")
    if set(pointer) != {"schema_version", "current"} or pointer["schema_version"] != 1:
        raise ValueError("release/current.json has an unsupported contract")
    filename = pointer["current"]
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError("current release pointer must be a safe JSON filename")
    manifest = read_json(release_root / "releases" / filename)
    if manifest.get("schema_version") != 1:
        raise ValueError("release manifest schema_version must be 1")
    identity = manifest.get("release")
    if not isinstance(identity, dict):
        raise ValueError("release identity is missing")
    version = identity.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        raise ValueError("release version must use SemVer")
    if filename != f"v{version}.json":
        raise ValueError(f"release filename must be v{version}.json")
    if identity.get("channel") not in CHANNELS or identity.get("status") not in STATUSES:
        raise ValueError("release channel or status is invalid")
    date.fromisoformat(str(identity.get("release_date")))
    notes = manifest.get("notes")
    if not isinstance(notes, dict) or set(notes) != {"zh", "en"}:
        raise ValueError("release notes must contain exact zh and en mirrors")
    for lang in ("zh", "en"):
        localized = notes[lang]
        if not isinstance(localized, dict) or not localized.get("title") or not localized.get("summary") or not localized.get("highlights"):
            raise ValueError(f"release notes are incomplete for {lang}")
    package = read_json(repo_root / "frontend" / "package.json")
    if package.get("version") != version:
        raise ValueError("frontend package version must match the current software release")
    for path in (
        repo_root / "docs" / "releases" / f"v{version}.md",
        repo_root / "docs" / "en" / "releases" / f"v{version}.md",
    ):
        if not path.is_file():
            raise ValueError(f"release note mirror is missing: {path.relative_to(repo_root)}")
    return version


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        version = validate_release(repo_root)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"release contract invalid: {exc}", file=sys.stderr)
        return 1
    print(f"release contract OK: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
