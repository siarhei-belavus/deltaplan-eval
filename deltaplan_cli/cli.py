from __future__ import annotations

import argparse
import os
import shutil
import tarfile
from pathlib import Path

from . import __version__
from . import releases
from .doctor import run_doctor
from .java_runtime import current_java_root
from .java_runtime import discover_java, install_managed_java
from .manifests import ReleaseManifest
from .paths import global_paths, resolve_git_toplevel
from .python_env import create_venv, install_requirements
from .releases import (
    DEFAULT_MANIFEST_URL,
    download_asset,
    host_os_arch,
    load_release,
    pick_asset,
)
from .repo_install import (
    commit_install,
    commit_remove,
    detect_full_existing_install,
    detect_partial_footprint,
    load_current_config,
    load_current_manifest,
    operation_kind,
    prepare_install_stage,
    prepare_remove_stage,
    transaction_root,
)
from .repo_update import managed_edit_detected
from .tui import choose


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deltaplan", description="DeltaPlan lifecycle CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="install DeltaPlan into current repo")
    sub.add_parser("update", help="update installed DeltaPlan")
    sub.add_parser("remove", help="remove installed DeltaPlan")
    sub.add_parser("doctor", help="diagnose installed DeltaPlan")
    sub.add_parser("self-update", help="update global CLI payload")

    parser.add_argument(
        "--version", action="version", version=f"deltaplan {__version__}"
    )
    return parser


def _release_url() -> str:
    return os.environ.get("DELTAPLAN_MANIFEST_URL", DEFAULT_MANIFEST_URL)


def _release_key() -> bytes:
    gp = global_paths()
    key_path = gp.base / "release_public_key.pem"
    if key_path.exists():
        return key_path.read_bytes()
    return (Path(__file__).parent / "resources" / "release_public_key.pem").read_bytes()


def _load_release() -> ReleaseManifest:
    return load_release(_release_url(), _release_key())


def _repo_root() -> Path:
    return resolve_git_toplevel() or Path.cwd()


def _prompt_for_repo_root() -> Path:
    root = resolve_git_toplevel()
    if root:
        return root
    if (
        choose(
            "Current directory is not a Git repository. Install DeltaPlan in this directory anyway?",
            ["Yes", "No"],
        )
        == "No"
    ):
        raise RuntimeError("aborted")
    return Path.cwd()


def _assistant_choice() -> str:
    return choose(
        "Select primary assistant", ["Claude Code", "Cursor", "GitHub Copilot"]
    )


def _resolve_java(
    os_name: str, arch: str, manifest: dict | None, tx_root: Path
) -> tuple[str, str, str]:
    manifest_java = manifest.get("javaPath") if isinstance(manifest, dict) else None
    current = discover_java(os_name, arch, manifest_java)
    if current:
        managed = str(current.path).startswith(str(current_java_root(os_name, arch)))
        return ("managed" if managed else "system", str(current.path), current.version)

    if (
        choose(
            f"Java 21 not found. Install managed Temurin 21 under ~/.deltaplan/java/temurin-21/{os_name}-{arch}?",
            ["Yes", "No"],
        )
        == "No"
    ):
        raise RuntimeError("Java 21 not available")

    release = _load_release()
    try:
        java_asset = pick_asset(release, "java", os_name=os_name, arch=arch)
    except Exception as exc:
        raise RuntimeError("No Java 21 managed asset in release manifest") from exc

    java_archive = tx_root / "java" / java_asset.name
    download_asset(java_asset.url, java_archive, expected_sha256=java_asset.sha256)
    runtime_path = install_managed_java(
        os_name,
        arch,
        java_archive,
        expected_sha256=java_asset.sha256,
        candidate_sha256=lambda path, expected: releases.assert_checksum(path, expected),
    )
    return "managed", str(runtime_path), "21"

def _prepare_stage(
    repo_root: Path,
    release: ReleaseManifest,
    assistant: str,
    operation: str,
    existing_manifest: dict | None,
    existing_config: dict | None,
) -> tuple[Path, Path]:
    os_name, arch = host_os_arch()
    tx_root = transaction_root(repo_root)
    java_mode, java_path, java_version = _resolve_java(
        os_name, arch, existing_manifest, tx_root
    )

    skill_pack = pick_asset(release, "skill-pack")
    skill_local = tx_root / "skill-pack.tar.gz"
    download_asset(skill_pack.url, skill_local, expected_sha256=skill_pack.sha256)

    tx_stage = prepare_install_stage(
        repo_root=repo_root,
        skill_pack=skill_local,
        selected_assistant=assistant,
        java_mode=java_mode,
        java_path=java_path,
        java_version=java_version,
        operation=operation,
        existing_manifest=existing_manifest,
        existing_config=existing_config,
    )

    stage_root = tx_stage / "stage"
    create_venv(stage_root / ".deltaplan" / ".venv")
    install_requirements(
        stage_root / ".deltaplan" / ".venv",
        stage_root / ".claude" / "skills" / "deltaplan" / "requirements.txt",
    )

    jar_path = (
        stage_root
        / ".claude"
        / "skills"
        / "deltaplan"
        / "runtime"
        / "deltaplan-mcp.jar"
    )
    if not jar_path.exists():
        raise RuntimeError("solver jar missing from staged skill pack")

    return tx_stage, stage_root


def handle_init(args: argparse.Namespace) -> int:
    try:
        repo_root = _prompt_for_repo_root()
    except RuntimeError:
        return 1

    if detect_full_existing_install(repo_root):
        if (
            choose(
                "DeltaPlan already installed in this directory.\nOverwrite the existing DeltaPlan install?",
                ["Yes", "No"],
            )
            == "No"
        ):
            return 0
    elif detect_partial_footprint(repo_root):
        if (
            choose(
                "Partial DeltaPlan footprint detected in this directory.\nOverwrite the partial DeltaPlan footprint?",
                ["Yes", "No"],
            )
            == "No"
        ):
            return 0

    assistant = _assistant_choice()
    op = operation_kind(repo_root)
    existing_manifest = (
        load_current_manifest(repo_root)
        if detect_full_existing_install(repo_root)
        else None
    )
    existing_config = (
        load_current_config(repo_root)
        if detect_full_existing_install(repo_root)
        else None
    )
    tx_root: Path | None = None

    try:
        release = _load_release()
        tx_root, _ = _prepare_stage(
            repo_root=repo_root,
            release=release,
            assistant=assistant,
            operation=op,
            existing_manifest=existing_manifest,
            existing_config=existing_config,
        )
        commit_install(tx_root, repo_root)
    except Exception as exc:
        if tx_root is not None and tx_root.exists():
            shutil.rmtree(tx_root)
        print(f"init failed: {exc}")
        return 1

    print("DeltaPlan init complete")
    print(
        "Next step: .deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/planning_workflow.py start ..."
    )
    return 0


def handle_update(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    if not detect_full_existing_install(repo_root):
        print("DeltaPlan not installed in this directory.")
        return 1

    manifest = load_current_manifest(repo_root)
    config = load_current_config(repo_root)
    if not isinstance(manifest, dict) or not isinstance(config, dict):
        print("DeltaPlan config invalid")
        return 1

    tx_root: Path | None = None
    probe_root: Path | None = None
    try:
        release = _load_release()
        existing_assistant = manifest.get("selectedAssistant", "claude-code")

        skill_pack = pick_asset(release, "skill-pack")
        probe_root = transaction_root(repo_root)
        probe_pack = probe_root / "probe-skill-pack.tar.gz"
        download_asset(skill_pack.url, probe_pack, expected_sha256=skill_pack.sha256)
        probe_stage = probe_root / "probe"
        from .repo_install import extract_skill_pack

        extract_skill_pack(probe_pack, probe_stage)
        if managed_edit_detected(repo_root, manifest, probe_stage):
            if (
                choose(
                    "DeltaPlan-managed files were modified.\nRewrite the managed install with the latest version?",
                    ["Yes", "No"],
                )
                == "No"
            ):
                return 0

        tx_root, _ = _prepare_stage(
            repo_root=repo_root,
            release=release,
            assistant=existing_assistant,
            operation="update",
            existing_manifest=manifest,
            existing_config=config,
        )
        commit_install(tx_root, repo_root)
    except Exception as exc:
        if tx_root is not None and tx_root.exists():
            shutil.rmtree(tx_root)
        print(f"update failed: {exc}")
        return 1
    finally:
        if probe_root is not None and probe_root.exists():
            shutil.rmtree(probe_root)

    return 0


def handle_remove(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    if not detect_full_existing_install(repo_root) and not detect_partial_footprint(
        repo_root
    ):
        print("DeltaPlan not installed in this directory.")
        return 0

    if (
        choose("Remove the DeltaPlan install from this directory?", ["Yes", "No"])
        == "No"
    ):
        return 0

    tx_root = transaction_root(repo_root)
    try:
        prepare_remove_stage(repo_root, tx_root)
        commit_remove(tx_root, repo_root)
    except Exception as exc:
        if tx_root.exists():
            shutil.rmtree(tx_root)
        print(f"remove failed: {exc}")
        return 1
    return 0


def handle_doctor(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    return run_doctor(repo_root)


def _verify_payload(payload_root: Path) -> None:
    import subprocess

    proc = subprocess.run(
        ["python3", str(payload_root / "launcher.py"), "--help"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("staged payload check failed")


def handle_self_update(args: argparse.Namespace) -> int:
    gp = global_paths()
    release = _load_release()
    os_name, arch = host_os_arch()
    cli_asset = pick_asset(release, "cli", os_name=os_name, arch=arch)

    staged_root = gp.base / "cli" / f"{release.version}.staged"
    if staged_root.exists():
        shutil.rmtree(staged_root)
    staged_root.mkdir(parents=True, exist_ok=True)

    tar_path = staged_root / cli_asset.name
    download_asset(cli_asset.url, tar_path, expected_sha256=cli_asset.sha256)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(staged_root)

    _verify_payload(staged_root)

    live_root = gp.base / "cli" / release.version
    if live_root.exists():
        shutil.rmtree(live_root)
    staged_root.rename(live_root)

    gp.cli_current.parent.mkdir(parents=True, exist_ok=True)
    if gp.cli_current.exists() or gp.cli_current.is_symlink():
        gp.cli_current.unlink()
    gp.cli_current.symlink_to(live_root)

    return 0


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init": handle_init,
        "update": handle_update,
        "remove": handle_remove,
        "doctor": handle_doctor,
        "self-update": handle_self_update,
    }
    return handlers[args.command](args)
