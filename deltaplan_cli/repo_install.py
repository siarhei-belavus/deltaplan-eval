from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import uuid
from pathlib import Path

from .manifests import (
    build_config,
    build_manifest,
    load_yaml_text,
    utc_now,
    write_yaml_text,
)
from .paths import (
    canonical_managed_block,
    current_gitignore_path,
    managed_block_markers,
)

RESERVED_PATHS = (
    ".claude/skills/deltaplan",
    ".deltaplan",
    ".deltaplan.install.lock",
    ".deltaplan-tx",
    ".gitignore",
)


def transaction_root(repo_root: Path) -> Path:
    return repo_root / ".deltaplan-tx" / str(uuid.uuid4())


def detect_full_existing_install(repo_root: Path) -> bool:
    manifest_path = repo_root / ".deltaplan" / "manifest.yml"
    skill_dir = repo_root / ".claude" / "skills" / "deltaplan"
    if not manifest_path.exists() or not skill_dir.exists():
        return False
    try:
        payload = load_yaml_text(manifest_path)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if not payload.get("toolkitVersion"):
        return False
    if not payload.get("managedOwnedDirectories"):
        return False
    owned = payload.get("managedOwnedDirectories", [])
    for rel in owned:
        if rel in {".claude/skills/deltaplan", ".deltaplan"}:
            if not (repo_root / rel).exists():
                return False
    return True


def detect_partial_footprint(repo_root: Path) -> bool:
    if detect_full_existing_install(repo_root):
        return False
    return any((repo_root / rel).exists() for rel in RESERVED_PATHS)


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _scan_managed_blocks(lines: list[str]) -> list[tuple[int, int]]:
    start_marker, end_marker = managed_block_markers()
    starts = [idx for idx, line in enumerate(lines) if line.strip() == start_marker]
    ends = [idx for idx, line in enumerate(lines) if line.strip() == end_marker]
    if len(starts) != len(ends):
        raise RuntimeError("unmatched .deltaplan managed markers")
    spans: list[tuple[int, int]] = []
    for start, end in zip(starts, ends):
        if end < start:
            raise RuntimeError("unmatched .deltaplan managed markers")
        spans.append((start, end))
    return spans


def _render_gitignore(existing: str | None, keep_managed: bool) -> tuple[str, bool]:
    block = canonical_managed_block()
    if existing is None:
        rendered = f"{block}\n"
        return rendered, True

    lines = existing.splitlines(keepends=True)
    spans = _scan_managed_blocks(lines)
    kept: list[str] = []
    cursor = 0
    for start, end in spans:
        kept.extend(lines[cursor:start])
        cursor = end + 1
    kept.extend(lines[cursor:])
    remainder = "".join(kept)

    if spans:
        tail = remainder.rstrip("\n")
        if tail:
            rendered = f"{tail}\n\n{block}\n"
        else:
            rendered = f"{block}\n"
    else:
        base = existing.rstrip("\n")
        rendered = f"{base}\n\n{block}\n" if base else f"{block}\n"

    return rendered, rendered == f"{block}\n" and keep_managed


def render_gitignore_for_install(repo_root: Path) -> tuple[bytes, bool]:
    existing = _safe_read_text(current_gitignore_path(repo_root))
    if not current_gitignore_path(repo_root).exists():
        existing = None
    text, created = _render_gitignore(existing, keep_managed=True)
    return text.encode("utf-8"), created


def render_gitignore_for_remove(
    repo_root: Path,
) -> tuple[bytes, bool]:
    path = current_gitignore_path(repo_root)
    if not path.exists():
        return b"", False

    original = _safe_read_text(path)
    lines = original.splitlines(keepends=True)
    spans = _scan_managed_blocks(lines)
    kept: list[str] = []
    cursor = 0
    for start, end in spans:
        kept.extend(lines[cursor:start])
        cursor = end + 1
    kept.extend(lines[cursor:])

    remainder = "".join(kept)
    has_nonblank_nonmanaged = bool(remainder.strip())
    rendered = remainder.rstrip("\n")
    rendered = f"{rendered}\n" if rendered else ""
    # If no non-blank non-managed content exists, this is all-managed-or-blank.
    all_managed_or_blank = not has_nonblank_nonmanaged
    return rendered.encode("utf-8"), all_managed_or_blank


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_managed_static_files(
    staged_skill_root: Path, staged_config_path: Path
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(staged_skill_root.rglob("*")):
        if not path.is_file():
            continue
        rel = (
            f".claude/skills/deltaplan/{path.relative_to(staged_skill_root).as_posix()}"
        )
        entries.append({"path": rel, "sha256": _sha256(path)})

    if staged_config_path.exists():
        entries.append(
            {"path": ".deltaplan/config.yml", "sha256": _sha256(staged_config_path)}
        )

    return sorted(entries, key=lambda item: item["path"])


def extract_skill_pack(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tar:
        tar.extractall(target)


def write_repo_manifests(
    *,
    staged_root: Path,
    repo_root: Path,
    selected_assistant: str,
    java_mode: str,
    java_path: str,
    java_version: str,
    existing_manifest: dict | None = None,
    existing_config: dict | None = None,
    operation: str,
) -> None:
    timestamp = utc_now()
    selected = {
        "Claude Code": "claude-code",
        "Cursor": "cursor",
        "GitHub Copilot": "copilot",
    }.get(selected_assistant, selected_assistant)

    if operation == "update":
        installed_at = (
            existing_manifest.get("installedAt", timestamp)
            if existing_manifest
            else timestamp
        )
        updated_at = timestamp
        last_update_at = timestamp
    else:
        installed_at = timestamp
        updated_at = timestamp
        last_update_at = None

    gitignore_path = staged_root / "gitignore.rendered"
    gitignore_bytes, gitignore_created = render_gitignore_for_install(repo_root)
    gitignore_path.write_bytes(gitignore_bytes)

    staged_deltaplan = staged_root / ".deltaplan"
    staged_deltaplan.mkdir(parents=True, exist_ok=True)

    config_payload = build_config(
        selected_assistant=selected,
        last_doctor_at=(
            existing_config.get("lastDoctorAt")
            if operation == "update" and existing_config
            else None
        ),
        last_update_at=last_update_at,
    )
    config_path = staged_deltaplan / "config.yml"
    write_yaml_text(config_payload, config_path)

    staged_skill_root = staged_root / ".claude" / "skills" / "deltaplan"
    manifest_payload = build_manifest(
        toolkit_version="1.0.0",
        install_root=".claude/skills/deltaplan",
        selected_assistant=selected,
        java_mode=java_mode,
        java_path=java_path,
        java_version=java_version,
        gitignore_managed=True,
        gitignore_created_by_deltaplan=gitignore_created,
        installed_at=installed_at,
        updated_at=updated_at,
        managed_static_files=compute_managed_static_files(
            staged_skill_root, config_path
        ),
    )
    write_yaml_text(manifest_payload, staged_deltaplan / "manifest.yml")


def prepare_install_stage(
    *,
    repo_root: Path,
    skill_pack: Path,
    selected_assistant: str,
    java_mode: str,
    java_path: str,
    java_version: str,
    operation: str,
    existing_manifest: dict | None = None,
    existing_config: dict | None = None,
) -> Path:
    tx_root = transaction_root(repo_root)
    stage_root = tx_root / "stage"
    extract_skill_pack(skill_pack, stage_root)

    # Ensure repo-local runtime dirs exist in staging before commit.
    (stage_root / ".claude" / "skills" / "deltaplan").mkdir(parents=True, exist_ok=True)
    (stage_root / ".deltaplan").mkdir(parents=True, exist_ok=True)

    write_repo_manifests(
        staged_root=stage_root,
        repo_root=repo_root,
        selected_assistant=selected_assistant,
        java_mode=java_mode,
        java_path=java_path,
        java_version=java_version,
        existing_manifest=existing_manifest,
        existing_config=existing_config,
        operation=operation,
    )

    return tx_root


def _fsync_parent(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        target = path
    else:
        target = path.parent
    fd = os.open(str(target), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def commit_install(tx_root: Path, repo_root: Path) -> None:
    stage = tx_root / "stage"
    backup = tx_root / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    lock = repo_root / ".deltaplan.install.lock"

    if lock.exists():
        raise RuntimeError("install lock exists")
    lock.write_text("", encoding="utf-8")

    live_gitignore = repo_root / ".gitignore"
    staged_gitignore = stage / "gitignore.rendered"

    live_skill = repo_root / ".claude" / "skills" / "deltaplan"
    live_deltaplan = repo_root / ".deltaplan"

    try:
        if live_gitignore.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live_gitignore, backup / "gitignore.original")

        if live_skill.exists():
            target = backup / ".claude" / "skills" / "deltaplan"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            os.replace(live_skill, target)

        if live_deltaplan.exists():
            target = backup / ".deltaplan"
            if target.exists():
                shutil.rmtree(target)
            os.replace(live_deltaplan, target)

        staged_skill = stage / ".claude" / "skills" / "deltaplan"
        staged_deltaplan = stage / ".deltaplan"

        (repo_root / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
        if staged_skill.exists():
            if live_skill.exists():
                shutil.rmtree(live_skill)
            os.replace(staged_skill, live_skill)

        if staged_deltaplan.exists():
            if live_deltaplan.exists():
                shutil.rmtree(live_deltaplan)
            os.replace(staged_deltaplan, live_deltaplan)

        if staged_gitignore.exists():
            rendered = staged_gitignore.read_bytes()
            if live_gitignore.exists():
                tmp = repo_root / ".gitignore.tmp"
                tmp.write_bytes(rendered)
                os.replace(tmp, live_gitignore)
            else:
                os.replace(staged_gitignore, live_gitignore)

        _fsync_parent(repo_root / ".claude")
        _fsync_parent(repo_root / ".deltaplan")
        _fsync_parent(live_gitignore)

        lock.unlink()
        shutil.rmtree(tx_root)
    except Exception:
        try:
            # rollback from partial state
            if (repo_root / ".claude" / "skills" / "deltaplan").exists():
                shutil.rmtree(repo_root / ".claude" / "skills" / "deltaplan")
            if (repo_root / ".deltaplan").exists():
                shutil.rmtree(repo_root / ".deltaplan")

            if (backup / ".claude" / "skills" / "deltaplan").exists():
                os.replace(
                    backup / ".claude" / "skills" / "deltaplan",
                    repo_root / ".claude" / "skills" / "deltaplan",
                )
            if (backup / ".deltaplan").exists():
                os.replace(backup / ".deltaplan", repo_root / ".deltaplan")

            if (backup / "gitignore.original").exists():
                shutil.copy2(backup / "gitignore.original", live_gitignore)
            elif live_gitignore.exists():
                live_gitignore.unlink()
        finally:
            if lock.exists():
                lock.unlink()
            raise


def prepare_remove_stage(repo_root: Path, tx_root: Path) -> tuple[bool, bool]:
    rendered, all_managed_or_blank = render_gitignore_for_remove(repo_root)
    stage = tx_root / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "gitignore.rendered").write_bytes(rendered)

    manifest = load_yaml_text(repo_root / ".deltaplan" / "manifest.yml")
    if not isinstance(manifest, dict):
        manifest = {}
    gitignore_created_by_delta = bool(
        manifest.get("gitignoreCreatedByDeltaPlan", False)
    )
    return all_managed_or_blank, gitignore_created_by_delta


def commit_remove(tx_root: Path, repo_root: Path) -> None:
    stage = tx_root / "stage"
    backup = tx_root / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    lock = repo_root / ".deltaplan.install.lock"

    if lock.exists():
        raise RuntimeError("install lock exists")
    lock.write_text("", encoding="utf-8")

    rendered, all_managed_or_blank = render_gitignore_for_remove(repo_root)
    manifest = load_yaml_text(repo_root / ".deltaplan" / "manifest.yml")
    manifest_created = bool(
        manifest.get("gitignoreCreatedByDeltaPlan")
        if isinstance(manifest, dict)
        else False
    )

    live_gitignore = repo_root / ".gitignore"
    staged_gitignore = stage / "gitignore.rendered"
    live_skill = repo_root / ".claude" / "skills" / "deltaplan"
    live_deltaplan = repo_root / ".deltaplan"

    try:
        if live_gitignore.exists():
            shutil.copy2(live_gitignore, backup / "gitignore.original")

        if live_skill.exists():
            target = backup / ".claude" / "skills" / "deltaplan"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            os.replace(live_skill, target)

        if live_deltaplan.exists():
            target = backup / ".deltaplan"
            if target.exists():
                shutil.rmtree(target)
            os.replace(live_deltaplan, target)

        staged_bytes = (
            staged_gitignore.read_bytes() if staged_gitignore.exists() else b""
        )

        if staged_bytes:
            if live_gitignore.exists():
                tmp = repo_root / ".gitignore.tmp"
                tmp.write_bytes(staged_bytes)
                os.replace(tmp, live_gitignore)
            else:
                live_gitignore.write_bytes(staged_bytes)
        else:
            if manifest_created and all_managed_or_blank:
                if live_gitignore.exists():
                    live_gitignore.unlink()
            elif not manifest_created and all_managed_or_blank:
                if live_gitignore.exists() and live_gitignore.name:
                    if not live_gitignore.read_text(encoding="utf-8").strip():
                        live_gitignore.unlink()

        lock.unlink()
        shutil.rmtree(tx_root)
    except Exception:
        try:
            if live_skill.exists():
                shutil.rmtree(live_skill)
            if live_deltaplan.exists():
                shutil.rmtree(live_deltaplan)

            if (backup / ".claude" / "skills" / "deltaplan").exists():
                os.replace(
                    backup / ".claude" / "skills" / "deltaplan",
                    repo_root / ".claude" / "skills" / "deltaplan",
                )
            if (backup / ".deltaplan").exists():
                os.replace(backup / ".deltaplan", repo_root / ".deltaplan")

            if (backup / "gitignore.original").exists():
                shutil.copy2(backup / "gitignore.original", live_gitignore)
            elif live_gitignore.exists():
                live_gitignore.unlink()
        finally:
            if lock.exists():
                lock.unlink()
            raise


def operation_kind(repo_root: Path) -> str:
    existing_manifest = load_yaml_text(repo_root / ".deltaplan" / "manifest.yml")
    if detect_partial_footprint(repo_root):
        return "partial-overwrite-init"
    if isinstance(existing_manifest, dict) and existing_manifest.get("toolkitVersion"):
        return "overwrite-init"
    return "first-init"


def load_current_manifest(repo_root: Path) -> dict:
    manifest_path = repo_root / ".deltaplan" / "manifest.yml"
    return load_yaml_text(manifest_path)


def load_current_config(repo_root: Path) -> dict:
    return load_yaml_text(repo_root / ".deltaplan" / "config.yml")
