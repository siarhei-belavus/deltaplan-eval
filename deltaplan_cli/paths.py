from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GlobalPaths:
    base: Path
    cli_root: Path
    cli_current: Path

    @property
    def launcher_candidates(self) -> tuple[Path, Path]:
        return (
            self.base / "local" / "bin" / "deltaplan",
            self.base / ".local" / "bin" / "deltaplan",
        )


def global_paths() -> GlobalPaths:
    base = Path.home() / ".deltaplan"
    return GlobalPaths(
        base=base, cli_root=base / "cli", cli_current=base / "cli" / "current"
    )


def resolve_git_toplevel(cwd: Path | None = None) -> Path | None:
    import subprocess

    cmd = ["git", "rev-parse", "--show-toplevel"]
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd or Path.cwd()), capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    return Path(text)


def repo_paths(repo_root: Path) -> dict[str, Path]:
    return {
        "repo_root": repo_root,
        "claude_skills": repo_root / ".claude" / "skills",
        "deltaplan_skill": repo_root / ".claude" / "skills" / "deltaplan",
        "deltaplan_root": repo_root / ".deltaplan",
        "manifest": repo_root / ".deltaplan" / "manifest.yml",
        "config": repo_root / ".deltaplan" / "config.yml",
        "state": repo_root / ".deltaplan" / "state.json",
        "logs": repo_root / ".deltaplan" / "logs",
        "tmp": repo_root / ".deltaplan" / "tmp",
        "venv": repo_root / ".deltaplan" / ".venv",
        "venv_python": repo_root / ".deltaplan" / ".venv" / "bin" / "python",
        "install_lock": repo_root / ".deltaplan.install.lock",
        "tx_root": repo_root / ".deltaplan-tx",
    }


def current_gitignore_path(repo_root: Path) -> Path:
    return repo_root / ".gitignore"


def current_java_root(os_name: str, arch: str) -> Path:
    return Path.home() / ".deltaplan" / "java" / "temurin-21" / f"{os_name}-{arch}"


def managed_block_markers() -> tuple[str, str]:
    return ("# BEGIN DELTAPLAN MANAGED", "# END DELTAPLAN MANAGED")


def canonical_managed_block() -> str:
    managed_lines = [
        "# BEGIN DELTAPLAN MANAGED\n",
        ".deltaplan/.venv/\n",
        ".deltaplan/state.json\n",
        ".deltaplan/logs/\n",
        ".deltaplan/tmp/\n",
        ".deltaplan.install.lock\n",
        ".deltaplan-tx/\n",
        "# END DELTAPLAN MANAGED\n",
    ]
    return "".join(managed_lines)


def ensure_launcher_paths() -> list[tuple[Path, int]]:
    return [
        (Path("/usr/local/bin"), 0o755),
        (Path.home() / ".local" / "bin", 0o755),
    ]


def expand_path(value: str) -> Path:
    return Path(os.path.expanduser(value))
