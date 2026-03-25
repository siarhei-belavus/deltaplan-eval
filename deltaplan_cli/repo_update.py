from __future__ import annotations

from pathlib import Path
import hashlib

from .manifests import load_yaml_text
from .paths import (
    canonical_managed_block,
    current_gitignore_path,
    managed_block_markers,
)
from .repo_install import (
    detect_full_existing_install,
    detect_partial_footprint,
)


def managed_edit_detected(
    repo_root: Path, manifest: dict, staged_skill_dir: Path
) -> bool:
    if not manifest:
        raise RuntimeError("missing manifest.yml")

    managed = {
        entry["path"]: entry.get("sha256", "")
        for entry in manifest.get("managedStaticFiles", [])
        if entry.get("path")
    }

    for rel_path, expected in managed.items():
        path = repo_root / rel_path
        if not path.exists():
            return True
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            return True

    skill_root = repo_root / ".claude" / "skills" / "deltaplan"
    for path in skill_root.rglob("*"):
        if not path.is_file():
            continue
        rel = f".claude/skills/deltaplan/{path.relative_to(skill_root).as_posix()}"
        if rel not in managed:
            return True

    start_marker, end_marker = managed_block_markers()
    gitignore = current_gitignore_path(repo_root)
    if gitignore.exists():
        marker_text = gitignore.read_text(encoding="utf-8")
        if (start_marker in marker_text) != (end_marker in marker_text):
            raise RuntimeError("unmatched .deltaplan managed markers")
        if start_marker in marker_text and end_marker in marker_text:
            if canonical_managed_block() not in marker_text:
                return True
    return False


def has_valid_installation(repo_root: Path) -> bool:
    return detect_full_existing_install(repo_root)


def has_partial_install(repo_root: Path) -> bool:
    return detect_partial_footprint(repo_root)


def load_current_manifest(repo_root: Path) -> dict:
    manifest_path = repo_root / ".deltaplan" / "manifest.yml"
    if not manifest_path.exists():
        raise FileNotFoundError("repo manifest missing")
    payload = load_yaml_text(manifest_path)
    if not isinstance(payload, dict):
        raise RuntimeError("corrupt manifest.yml")
    return payload


def load_current_config(repo_root: Path) -> dict:
    config_path = repo_root / ".deltaplan" / "config.yml"
    if not config_path.exists():
        raise FileNotFoundError("repo config missing")
    payload = load_yaml_text(config_path)
    if not isinstance(payload, dict):
        raise RuntimeError("corrupt config.yml")
    return payload
