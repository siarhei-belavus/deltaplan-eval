from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import urllib.request

from .manifests import ReleaseManifest, ReleaseAsset


DEFAULT_MANIFEST_URL = (
    "https://github.com/siarhei-belavus/deltaplan-eval/releases/latest/download/manifest.json"
)


@dataclass(frozen=True)
class DownloadedAsset:
    path: Path
    manifest: ReleaseManifest


def _read_bytes(source: str) -> bytes:
    if source.startswith("file://"):
        return Path(source[7:]).read_bytes()
    if source.startswith("/") and Path(source).exists():
        return Path(source).read_bytes()

    if source.startswith(("https://", "http://")):
        curl = shutil.which("curl")
        if curl:
            proc = subprocess.run(
                [curl, "-fsSL", source],
                capture_output=True,
            )
            if proc.returncode == 0:
                return proc.stdout

    with urllib.request.urlopen(source) as response:
        return response.read()


def _urlopen(url: str) -> bytes:
    return _read_bytes(url)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_to_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_bytes(url)
    destination.write_bytes(payload)


def load_public_key_bytes(resource_path: Path) -> bytes:
    return resource_path.read_bytes()


def verify_signed_manifest(
    manifest_bytes: bytes, signature_bytes: bytes, public_key: bytes
) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest_path = tmp_path / "manifest.json"
        sig_path = tmp_path / "manifest.sig"
        key_path = tmp_path / "release_public_key.pem"
        manifest_path.write_bytes(manifest_bytes)
        sig_path.write_bytes(signature_bytes)
        key_path.write_bytes(public_key)

        proc = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(key_path),
                "-signature",
                str(sig_path),
                str(manifest_path),
            ],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0


def load_release(url: str, public_key_bytes: bytes) -> ReleaseManifest:
    manifest = _urlopen(url)
    signature = _urlopen(url.replace("manifest.json", "manifest.sig"))
    if not verify_signed_manifest(manifest, signature, public_key_bytes):
        raise RuntimeError("manifest signature verification failed")

    data = json.loads(manifest)
    return ReleaseManifest(
        version=data["version"],
        publishedAt=data["publishedAt"],
        signingKeyPath=data["signingKeyPath"],
        assets=[
            ReleaseAsset(
                name=item["name"],
                kind=item["kind"],
                url=item["url"],
                sha256=item["sha256"],
                os=item.get("os"),
                arch=item.get("arch"),
                size=item.get("size"),
            )
            for item in data.get("assets", [])
        ],
    )


def assert_checksum(path: Path, expected_hex: str) -> None:
    actual = sha256_file(path)
    if actual != expected_hex:
        raise RuntimeError(
            f"checksum mismatch: {path} expected={expected_hex} actual={actual}"
        )


def download_asset(
    url: str, destination: Path, expected_sha256: str | None = None
) -> None:
    download_to_file(url, destination)
    if expected_sha256:
        assert_checksum(destination, expected_sha256)


def host_os_arch() -> tuple[str, str]:
    import platform

    os_name = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine
    return os_name, arch


def pick_asset(
    manifest: ReleaseManifest,
    kind: str,
    os_name: str | None = None,
    arch: str | None = None,
) -> ReleaseAsset:
    for asset in manifest.assets:
        if asset.kind != kind:
            continue
        if os_name is not None and asset.os != os_name:
            continue
        if arch is not None and asset.arch != arch:
            continue
        return asset
    raise RuntimeError(f"missing asset kind={kind} os={os_name or ''} arch={arch or ''}")


def asset_key(asset: ReleaseAsset) -> dict[str, object]:
    return {
        "name": asset.name,
        "kind": asset.kind,
        "os": asset.os,
        "arch": asset.arch,
        "url": asset.url,
        "sha256": asset.sha256,
        "size": asset.size,
    }
