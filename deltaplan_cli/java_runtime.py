from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import subprocess
import tarfile

from .paths import current_java_root


@dataclass(frozen=True)
class JavaRuntime:
    path: Path
    version: str


def parse_major_java_version(text: str) -> str:
    match = re.search(r"^\s*java\.version\s*=\s*([0-9]+)", text, re.MULTILINE)
    if not match:
        match = re.search(r'java version "([0-9]+)', text)
    if not match:
        raise ValueError("cannot parse java.version")
    return match.group(1)


def check_candidate(candidate: Path) -> JavaRuntime:
    proc = subprocess.run(
        [str(candidate), "-XshowSettings:properties", "-version"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"java probe failed: {candidate}")
    version = parse_major_java_version("\n".join([proc.stdout, proc.stderr]))
    if version != "21":
        raise RuntimeError(f"java major mismatch: {version}")
    return JavaRuntime(path=candidate, version=version)


def discover_java(
    os_name: str, arch: str, repo_manifest_java_path: str | None = None
) -> JavaRuntime | None:
    if repo_manifest_java_path:
        candidate = Path(repo_manifest_java_path)
        if candidate.exists():
            try:
                return check_candidate(candidate)
            except Exception:
                pass

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java"
        if candidate.exists():
            try:
                return check_candidate(candidate)
            except Exception:
                pass

    system_java = shutil.which("java")
    if system_java:
        try:
            return check_candidate(Path(system_java))
        except Exception:
            pass

    managed = current_java_root(os_name, arch) / "bin" / "java"
    if managed.exists():
        try:
            return check_candidate(managed)
        except Exception:
            pass

    return None


def managed_install_target(os_name: str, arch: str) -> Path:
    return current_java_root(os_name, arch) / "bin" / "java"


def install_managed_java(
    os_name: str,
    arch: str,
    archive_path: Path,
    expected_sha256: str,
    candidate_sha256: callable,
) -> Path:
    candidate_sha256(archive_path, expected_sha256)

    managed_root = current_java_root(os_name, arch)
    target_root = managed_root.parent
    target_root.mkdir(parents=True, exist_ok=True)

    staging_root = target_root / ".extract"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:*") as tar:
        members = tar.getmembers()
        if not members:
            raise RuntimeError("invalid java archive")
        tar.extractall(staging_root)

    runtime_root: Path | None = None
    search_roots = [staging_root]
    search_roots.extend(item for item in staging_root.iterdir() if item.is_dir())
    for root in search_roots:
        if (root / "bin" / "java").exists():
            runtime_root = root
            break
        if (root / "Contents" / "Home" / "bin" / "java").exists():
            runtime_root = root / "Contents" / "Home"
            break

    if runtime_root is None:
        raise RuntimeError("managed java archive missing bin/java")

    if managed_root.exists():
        shutil.rmtree(managed_root)
    shutil.move(str(runtime_root), str(managed_root))
    shutil.rmtree(staging_root, ignore_errors=True)

    java_path = managed_install_target(os_name, arch)
    check_candidate(java_path)
    return java_path


def candidate_sha256_stub(_path: Path, _expected: str) -> None:
    # left intentionally as a local shim for type-compatible call sites.
    return None
