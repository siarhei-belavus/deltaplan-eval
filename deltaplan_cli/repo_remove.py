from __future__ import annotations

from pathlib import Path

from .repo_install import (
    commit_remove,
    detect_full_existing_install,
    detect_partial_footprint,
    prepare_remove_stage,
)


def has_install(repo_root: Path) -> bool:
    return detect_full_existing_install(repo_root)


def has_partial(repo_root: Path) -> bool:
    return detect_partial_footprint(repo_root)


def remove_install(repo_root: Path, tx_root: Path) -> None:
    if not detect_full_existing_install(repo_root) and not detect_partial_footprint(
        repo_root
    ):
        print("DeltaPlan not installed in this directory.")
        return

    prepare_remove_stage(repo_root, tx_root)
    commit_remove(tx_root, repo_root)
