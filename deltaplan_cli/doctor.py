from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .manifests import load_yaml_text
from .paths import global_paths
from .java_runtime import discover_java
from .runtime_validation import validate_solver_jar


@dataclass
class DoctorIssue:
    name: str
    detail: str
    hard: bool = True


def _is_executable(path: Path) -> bool:
    return path.exists() and os.access(path, os.X_OK)


def check_repo(repo_root: Path) -> list[DoctorIssue]:
    issues: list[DoctorIssue] = []

    gp = global_paths()
    if not gp.cli_current.exists():
        issues.append(DoctorIssue("global-cli", "active global CLI payload missing"))

    manifest = repo_root / ".deltaplan" / "manifest.yml"
    if not manifest.exists():
        issues.append(DoctorIssue("manifest", "repo manifest missing"))
        return issues

    payload = load_yaml_text(manifest)
    if not payload:
        issues.append(DoctorIssue("manifest", "repo manifest invalid"))
        return issues

    skill_manifest = repo_root / ".claude" / "skills" / "deltaplan" / "manifest.json"
    if not skill_manifest.exists():
        issues.append(DoctorIssue("skill-manifest", "skill manifest missing"))

    venv_python = repo_root / ".deltaplan" / ".venv" / "bin" / "python"
    if not _is_executable(venv_python):
        issues.append(DoctorIssue("venv", "repo venv missing"))

    if _is_executable(venv_python):
        proc = subprocess.run(
            [str(venv_python), "-c", "import openpyxl"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            issues.append(
                DoctorIssue("openpyxl", "openpyxl import/check failed in venv")
            )

        for script in [
            "planning_workflow.py",
            "call_deltaplan_mcp.py",
        ]:
            script_path = (
                repo_root / ".claude" / "skills" / "deltaplan" / "scripts" / script
            )
            if not script_path.exists():
                issues.append(DoctorIssue("script", f"missing {script}"))
                continue
            proc = subprocess.run(
                [str(venv_python), str(script_path), "--help"],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                issues.append(DoctorIssue("script", f"{script} --help failed"))

    jar_path = (
        repo_root / ".claude" / "skills" / "deltaplan" / "runtime" / "deltaplan-mcp.jar"
    )
    jar_issue = validate_solver_jar(jar_path)
    if jar_issue:
        issues.append(DoctorIssue("jar", jar_issue))

    java_path = payload.get("javaPath") if isinstance(payload, dict) else None
    os_name, arch = ("", "")
    import platform

    os_name = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine
    runtime = discover_java(os_name, arch, java_path)
    if not runtime and not java_path:
        runtime = discover_java(os_name, arch, None)
    if not runtime:
        issues.append(DoctorIssue("java", "no compatible Java 21 found"))

    return issues


def run_doctor(repo_root: Path) -> int:
    issues = check_repo(repo_root)
    if not issues:
        print("doctor: ok")
        return 0

    hard = [item for item in issues if item.hard]
    if hard:
        print("doctor: issues found")
        for item in hard:
            print(f"- {item.name}: {item.detail}")
        return 1

    print("doctor: warnings")
    for item in issues:
        print(f"- {item.name}: {item.detail}")
    return 0
