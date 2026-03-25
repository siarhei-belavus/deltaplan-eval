#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deltaplan_cli.manifests import utc_now
from deltaplan_cli.runtime_validation import validate_solver_jar

OS_ARCHES = [("darwin", "arm64"), ("linux", "amd64")]


@dataclass
class Artifact:
    path: Path
    name: str
    kind: str
    os: str | None = None
    arch: str | None = None
    sha256: str = ""
    size: int = 0


def _release_version() -> str:
    raw_version = os.environ.get("DELTAPLAN_RELEASE_VERSION", "1.0.0")
    version = raw_version.strip()
    if version.startswith("v"):
        version = version[1:]
    if not version:
        raise RuntimeError("DELTAPLAN_RELEASE_VERSION resolved empty")
    return version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skill_pack_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    normalized = tarinfo.name.replace("\\", "/").lstrip("./")
    if normalized.startswith("agents/") or normalized.startswith(
        ".claude/skills/delta-plan-roadmap-planning/agents/"
    ):
        return None
    if normalized.startswith("skills/delta-plan-roadmap-planning/.DS_Store"):
        return None
    if "/.DS_Store" in normalized or normalized == ".DS_Store":
        return None
    if "/__pycache__/" in normalized or normalized == "__pycache__":
        return None
    return tarinfo


def _cli_asset_root() -> Path:
    return ROOT / "deltaplan_cli"


def build_cli_payload(
    output_dir: Path, os_name: str, arch: str, version: str
) -> Artifact:
    payload_root = output_dir / f".deltaplan-cli-{version}-{os_name}-{arch}-payload"
    if payload_root.exists():
        import shutil

        shutil.rmtree(payload_root)
    payload_root.mkdir(parents=True)

    launcher = payload_root / "launcher.py"
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        "from deltaplan_cli.cli import run\n"
        "raise SystemExit(run())\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    import shutil

    shutil.copytree(_cli_asset_root(), payload_root / "deltaplan_cli")
    tar_name = f"deltaplan-cli-{version}-{os_name}-{arch}.tar.gz"
    tar_path = output_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(payload_root, arcname=".")
    return Artifact(path=tar_path, name=tar_name, kind="cli", os=os_name, arch=arch)


def build_skill_pack(output_dir: Path, version: str) -> Artifact:
    source = ROOT / "skills" / "delta-plan-roadmap-planning"
    jar_issue = validate_solver_jar(source / "runtime" / "deltaplan-mcp.jar")
    if jar_issue:
        raise RuntimeError(f"cannot build skill pack: {jar_issue}")
    tar_name = f"deltaplan-skill-pack-{version}.tar.gz"
    tar_path = output_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(source, arcname=".claude/skills/deltaplan", filter=_skill_pack_filter)
    return Artifact(path=tar_path, name=tar_name, kind="skill-pack")


def _release_base_url(release_version: str) -> str:
    override = os.environ.get("DELTAPLAN_RELEASE_BASE_URL")
    if override:
        if override.startswith(("http://", "https://", "file://")):
            return override.rstrip("/") + "/"
        return Path(override).resolve().as_uri() + "/"

    org = os.environ.get("DELTAPLAN_RELEASE_ORG", "siarhei-belavus")
    repo = os.environ.get("DELTAPLAN_RELEASE_REPO", "deltaplan-eval")
    return f"https://github.com/{org}/{repo}/releases/download/v{release_version}/"


def _load_java_asset(base_url: str, os_name: str, arch: str) -> tuple[str, str]:
    url = os.environ.get(f"DELTAPLAN_JAVA_{os_name}_{arch}_URL")
    sha = os.environ.get(f"DELTAPLAN_JAVA_{os_name}_{arch}_SHA")
    if url and sha:
        return url, sha

    api_os = {"darwin": "mac", "linux": "linux"}.get(os_name, os_name)
    api_arch = {"arm64": "aarch64", "amd64": "x64"}.get(arch, arch)
    api_url = (
        "https://api.adoptium.net/v3/assets/latest/21/hotspot"
        f"?architecture={api_arch}&image_type=jre&os={api_os}&vendor=eclipse"
    )
    req = Request(api_url, headers={"User-Agent": "deltaplan-release-builder"})
    try:
        with urlopen(req) as response:
            payload = json.load(response)
        package = payload[0]["binary"]["package"]
        return package["link"], package["checksum"]
    except Exception:
        fallback_url = urljoin(base_url, f"temurin-jre-21-{os_name}-{arch}.tar.gz")
        fallback_sha = sha or "0000000000000000000000000000000000000000000000000000000000000000"
        return fallback_url, fallback_sha


def build_manifest(output_dir: Path, artifacts: list[Artifact], version: str) -> Path:
    base_url = _release_base_url(version)

    manifest = {
        "version": version,
        "publishedAt": utc_now(),
        "signingKeyPath": "release/release_public_key.pem",
        "assets": [],
    }

    for artifact in artifacts:
        artifact.sha256 = _sha256(artifact.path)
        artifact.size = artifact.path.stat().st_size
        item = {
            "name": artifact.name,
            "kind": artifact.kind,
            "url": urljoin(base_url, artifact.name),
            "sha256": artifact.sha256,
            "size": artifact.size,
        }
        if artifact.os:
            item["os"] = artifact.os
        if artifact.arch:
            item["arch"] = artifact.arch
        manifest["assets"].append(item)

    for os_name, arch in OS_ARCHES:
        java_url, java_sha = _load_java_asset(base_url, os_name, arch)
        manifest["assets"].append(
            {
                "name": f"temurin-jre-21-{os_name}-{arch}.tar.gz",
                "kind": "java",
                "os": os_name,
                "arch": arch,
                "url": java_url,
                "sha256": java_sha,
                "size": 0,
            }
        )

    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _materialize_secret_file(value: str, suffix: str) -> tuple[str, bool]:
    candidate = Path(value)
    if "\n" not in value and candidate.exists():
        return str(candidate), False

    tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=suffix)
    try:
        tmp.write(value)
        if not value.endswith("\n"):
            tmp.write("\n")
        tmp.flush()
    finally:
        tmp.close()
    return tmp.name, True


def sign_manifest(manifest: Path, out_dir: Path) -> Path:
    key_value = os.environ.get("DELTAPLAN_RELEASE_PRIVATE_KEY")
    if not key_value:
        raise RuntimeError("DELTAPLAN_RELEASE_PRIVATE_KEY is required for signing")

    key_path, cleanup = _materialize_secret_file(key_value, ".pem")
    try:
        sig = out_dir / "manifest.sig"
        proc = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                key_path,
                "-out",
                str(sig),
                str(manifest),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"manifest signing failed: {proc.stderr or proc.stdout}")
        return sig
    finally:
        if cleanup:
            Path(key_path).unlink(missing_ok=True)


def build_checksums(output_dir: Path, files: list[Path]) -> Path:
    path = output_dir / "checksums.txt"
    lines = [f"{_sha256(item)}  {item.name}" for item in files]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def copy_install_script(output_dir: Path) -> None:
    source_script = ROOT / "scripts" / "release" / "install.sh"
    target = output_dir / "install.sh"
    target.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")

    key_value = os.environ.get(
        "DELTAPLAN_RELEASE_PUBLIC_KEY",
        str(ROOT / "release" / "release_public_key.pem"),
    )
    if "\n" not in key_value and Path(key_value).exists():
        public_key = Path(key_value).read_text(encoding="utf-8")
    else:
        public_key = key_value if key_value.endswith("\n") else key_value + "\n"
    (output_dir / "release_public_key.pem").write_text(
        public_key,
        encoding="utf-8",
    )


def main() -> int:
    version = _release_version()
    output_dir = Path(os.environ.get("DELTAPLAN_RELEASE_DIR", str(ROOT / "release")))
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = [
        build_cli_payload(output_dir, os_name, arch, version)
        for os_name, arch in OS_ARCHES
    ]
    artifacts.append(build_skill_pack(output_dir, version))

    manifest = build_manifest(output_dir, artifacts, version)
    signature = sign_manifest(manifest, output_dir)
    build_checksums(output_dir, [a.path for a in artifacts] + [manifest, signature])
    copy_install_script(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
