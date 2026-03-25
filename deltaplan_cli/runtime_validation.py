from __future__ import annotations

from pathlib import Path
import zipfile

EXPECTED_MCP_MAIN_CLASS = "com/deltaplan/solver/tools/mcp/McpSolveCliKt.class"


def validate_solver_jar(jar_path: Path) -> str | None:
    if not jar_path.exists():
        return "solver jar missing"
    if jar_path.stat().st_size <= 0:
        return "solver jar is empty"
    try:
        with zipfile.ZipFile(jar_path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return "solver jar is not a valid zip archive"
    if EXPECTED_MCP_MAIN_CLASS not in names:
        return "solver jar missing MCP solve entrypoint"
    return None
