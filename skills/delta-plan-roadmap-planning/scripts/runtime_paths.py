#!/usr/bin/env python3
"""Runtime path helpers for DeltaPlan planning skill execution.

The helpers resolve paths from the installed skill location, not from any
source-tree assumptions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def installed_skill_root() -> Path:
    """Return the root of the installed skill directory (`.claude/skills/deltaplan`)."""

    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """Return the repository root that contains this skill install."""

    skill_root = installed_skill_root()
    if skill_root.parent.parent.name == ".claude":
        return skill_root.parent.parent.parent
    return skill_root.parent.parent


def repo_deltaplan_root() -> Path:
    """Return the local DeltaPlan control root (`.deltaplan`)."""

    return repo_root() / ".deltaplan"


def repo_local_venv_python() -> Path:
    """Return the repo-local Python executable path used by the runtime."""

    return repo_deltaplan_root() / ".venv" / "bin" / "python"


def packaged_prompt_dir() -> Path:
    """Return directory containing packaged prompt assets."""

    return installed_skill_root() / "resources" / "prompts"


def packaged_runtime_jar() -> Path:
    """Return the path to the packaged solver jar inside the skill pack."""

    return installed_skill_root() / "runtime" / "deltaplan-mcp.jar"


def scripts_dir() -> Path:
    """Return the directory containing runtime scripts."""

    return installed_skill_root() / "scripts"


def _read_manifest_yaml(manifest_path: Path) -> dict[str, Any]:
    """Parse a tiny subset of YAML used by `.deltaplan/manifest.yml`.

    Supports only the flat values needed by runtime path resolution.
    """

    if not manifest_path.exists():
        return {}

    text = manifest_path.read_text()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    data: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ": " not in line and line.endswith(":"):
            # nested maps are outside runtime interest for now.
            continue
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        key = key.strip()
        data[key] = _coerce_scalar(value.strip())
    return data


def _coerce_scalar(raw: str) -> Any:
    if raw == "null":
        return None
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def manifest_java_path() -> str | None:
    """Load `.deltaplan/manifest.yml` and return `javaPath` if present."""

    manifest = _read_manifest_yaml(repo_deltaplan_root() / "manifest.yml")
    value = manifest.get("javaPath")
    if not value:
        return None
    return str(Path(value))


def resolve_java_path(explicit: str | None = None) -> str | None:
    """Resolve java executable path using manifest-first precedence."""

    if explicit:
        return explicit
    return manifest_java_path()


def resolve_mcp_jar_path(explicit: str | None = None) -> Path:
    """Resolve MCP jar path from explicit arg or packaged default."""

    if explicit:
        return Path(explicit).resolve()
    return packaged_runtime_jar()
