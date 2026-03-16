#!/usr/bin/env python3
"""
Call the DeltaPlan MCP solve tool through the shaded jar over stdio.

AICODE-NOTE: This keeps the planning workspace aligned to the MCP boundary instead of linking directly against in-repo Kotlin classes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    ensure_attractor_stage_artifacts,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_manifest,
    update_scenario_status,
    utc_now,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call DeltaPlan MCP solve via stdio.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="solve_via_mcp")
    parser.add_argument("--mcp-jar", required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def resolve_java_command() -> str:
    java_home = __import__("os").environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "java"
        if candidate.exists():
            return str(candidate)
    probe = subprocess.run(
        ["/usr/libexec/java_home", "-v", "21"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0:
        candidate = Path(probe.stdout.strip()) / "bin" / "java"
        if candidate.exists():
            return str(candidate)
    return "java"


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    solver_dir = scenario_dir / "solver"
    request_path = solver_dir / "solve-request.json"
    response_path = solver_dir / "solve-response.json"
    metadata_path = solver_dir / "solver-metadata.json"

    solve_request = load_json(request_path)
    command = [
        resolve_java_command(),
        "-cp",
        str(Path(args.mcp_jar).resolve()),
        "com.deltaplan.solver.tools.mcp.McpSolveCliKt",
        "--request",
        str(request_path),
        "--response",
        str(response_path),
        "--metadata",
        str(metadata_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        write_json(
            metadata_path,
            {
                "scenarioId": args.scenario_id,
                "calledAt": utc_now(),
                "status": "error",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
        raise SystemExit("DeltaPlan MCP solve helper failed.")

    structured_content = load_json(response_path)
    helper_metadata = load_json(metadata_path)

    write_json(response_path, structured_content)
    write_json(
        metadata_path,
        {
            "scenarioId": args.scenario_id,
            "calledAt": utc_now(),
            "status": "success",
            "mcpJar": str(Path(args.mcp_jar).resolve()),
            "helper": helper_metadata,
        },
    )
    touch_generated_artifact(run_dir, response_path)
    touch_generated_artifact(run_dir, metadata_path)
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Render roadmap and heatmap reports",
        latest_summary="DeltaPlan MCP solve completed successfully.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Render roadmap and heatmap reports",
        latest_summary="DeltaPlan MCP solve completed successfully.",
        active_scenario_id=args.scenario_id,
        resume_hint="Run save_and_render_schedule next.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action="Render reports",
        latest_summary="DeltaPlan MCP solve completed successfully.",
        latest_solve_request_path=relative_to_run(run_dir, request_path),
        latest_solve_response_path=relative_to_run(run_dir, response_path),
    )
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestSolveRequestPath=relative_to_run(run_dir, request_path),
        latestSolveResponsePath=relative_to_run(run_dir, response_path),
    )
    ensure_attractor_stage_artifacts(
        run_dir,
        stage_id=args.stage_id,
        command="call_deltaplan_mcp.py",
        inputs={"runDir": str(run_dir), "scenarioId": args.scenario_id, "mcpJar": args.mcp_jar},
        summary="Solved the scenario through the DeltaPlan MCP server.",
        state="success",
        outputs={"solveResponsePath": relative_to_run(run_dir, response_path)},
    )
    print(f"SOLVE_RESPONSE={response_path}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
