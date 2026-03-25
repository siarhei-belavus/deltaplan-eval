from __future__ import annotations

from pathlib import Path
import subprocess


def ensure_python(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def create_venv(venv_path: Path) -> None:
    import venv

    venv.create(venv_path, with_pip=True)


def install_requirements(venv_path: Path, requirements: Path) -> None:
    if not requirements.exists():
        return
    python_exe = venv_path / "bin" / "python"
    cmd = [str(python_exe), "-m", "pip", "install", "-r", str(requirements)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"venv bootstrap failed: {proc.stderr}")


def venv_python_exists(venv_path: Path) -> bool:
    return (venv_path / "bin" / "python").exists()


def python_exec(venv_path: Path) -> Path:
    return venv_path / "bin" / "python"


def run_python_check(venv_path: Path, module: str) -> tuple[bool, str]:
    python = python_exec(venv_path)
    proc = subprocess.run([str(python), "-c", module], capture_output=True, text=True)
    return (proc.returncode == 0, proc.stderr or proc.stdout)
