from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    kind: str
    url: str
    sha256: str
    os: str | None = None
    arch: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    publishedAt: str
    signingKeyPath: str
    assets: list[ReleaseAsset]


def _cast_asset(row: dict[str, Any]) -> ReleaseAsset:
    return ReleaseAsset(
        name=row["name"],
        kind=row["kind"],
        url=row["url"],
        sha256=row["sha256"],
        os=row.get("os"),
        arch=row.get("arch"),
        size=row.get("size"),
    )


def parse_release_manifest(path: Path) -> ReleaseManifest:
    payload = json.loads(path.read_text())
    return ReleaseManifest(
        version=payload["version"],
        publishedAt=payload["publishedAt"],
        signingKeyPath=payload["signingKeyPath"],
        assets=[_cast_asset(item) for item in payload.get("assets", [])],
    )


def release_asset(
    manifest: ReleaseManifest,
    kind: str,
    os_name: str | None = None,
    arch: str | None = None,
) -> ReleaseAsset:
    for item in manifest.assets:
        if item.kind != kind:
            continue
        if os_name is not None and item.os != os_name:
            continue
        if arch is not None and item.arch != arch:
            continue
        return item
    raise FileNotFoundError(
        f"missing asset kind={kind} os={os_name or ''} arch={arch or ''}"
    )


def write_yaml_text(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def load_yaml_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        return {}

    try:
        return json.loads(text)
    except Exception:
        # allow a tiny YAML-like subset used by this project.
        data: dict[str, Any] = {}
        current_key = None
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            if raw.startswith(" ") and current_key:
                if line.startswith("- "):
                    data.setdefault(current_key, []).append(line[2:])
                continue
            if ": " in line:
                key, value = line.split(": ", 1)
                data[key.strip()] = _coerce_scalar(value.strip())
                current_key = key.strip()
            elif line.endswith(":"):
                current_key = line[:-1]
                data[current_key] = []
            else:
                continue
        return data


def _coerce_scalar(raw: str) -> Any:
    if raw == "null":
        return None
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def build_manifest(
    *,
    toolkit_version: str,
    install_root: str,
    selected_assistant: str,
    java_mode: str,
    java_path: str,
    java_version: str,
    gitignore_managed: bool,
    gitignore_created_by_deltaplan: bool,
    installed_at: str,
    updated_at: str,
    managed_static_files: list[dict[str, str]],
) -> dict[str, Any]:
    managed_mutable_paths = [
        ".deltaplan/.venv/",
        ".deltaplan/state.json",
        ".deltaplan/logs/",
        ".deltaplan/tmp/",
        ".deltaplan.install.lock",
        ".deltaplan-tx/",
    ]

    return {
        "toolkitVersion": toolkit_version,
        "installRoot": install_root,
        "pythonVenv": ".deltaplan/.venv",
        "selectedAssistant": selected_assistant,
        "installedAt": installed_at,
        "updatedAt": updated_at,
        "managedOwnedDirectories": [
            ".claude/skills/deltaplan",
            ".deltaplan",
        ],
        "managedMutablePaths": managed_mutable_paths,
        "managedStaticFiles": managed_static_files,
        "gitignoreManaged": bool(gitignore_managed),
        "gitignoreCreatedByDeltaPlan": bool(gitignore_created_by_deltaplan),
        "javaMode": java_mode,
        "javaPath": java_path,
        "javaVersion": java_version,
    }


def build_config(
    selected_assistant: str, last_doctor_at: str | None, last_update_at: str | None
) -> dict[str, Any]:
    return {
        "selectedAssistant": selected_assistant,
        "lastDoctorAt": last_doctor_at,
        "lastUpdateAt": last_update_at,
    }
