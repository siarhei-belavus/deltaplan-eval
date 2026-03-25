#!/usr/bin/env python3
"""Call the DeltaPlan MCP solve tool through the shaded jar over stdio.

AICODE-NOTE: This keeps the planning workspace aligned to the MCP boundary
instead of linking directly against in-repo Kotlin classes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from planning_workspace_lib import touch_generated_artifact, update_scenario_manifest
from runtime_paths import resolve_java_path, resolve_mcp_jar_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call DeltaPlan MCP solve via stdio.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--mcp-jar", default=None)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def resolve_java_command() -> str:
    explicit_java = resolve_java_path()
    if explicit_java:
        candidate = Path(explicit_java)
        if candidate.exists():
            return str(candidate)

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java"
        if candidate.exists():
            return str(candidate)

    system_java = shutil.which("java")
    if system_java:
        return system_java

    return "java"


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    solver_dir = scenario_dir / "solver"
    request_path = solver_dir / "solve-request.json"
    response_path = solver_dir / "solve-response.json"

    load_json(request_path)
    mcp_jar = resolve_mcp_jar_path(args.mcp_jar)
    if not mcp_jar.exists():
        raise SystemExit(f"Missing MCP jar: {mcp_jar}")

    command = [
        resolve_java_command(),
        "-cp",
        str(mcp_jar),
        "com.deltaplan.solver.tools.mcp.McpSolveCliKt",
        "--request",
        str(request_path),
        "--response",
        str(response_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            "DeltaPlan MCP solve helper failed.\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    load_json(response_path)
    touch_generated_artifact(run_dir, response_path)
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestSolveRequestPath=f"scenarios/{args.scenario_id}/solver/solve-request.json",
        latestSolveResponsePath=f"scenarios/{args.scenario_id}/solver/solve-response.json",
    )
    print(f"SOLVE_RESPONSE={response_path}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
