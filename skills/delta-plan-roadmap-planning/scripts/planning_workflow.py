#!/usr/bin/env python3
"""Thin utility helpers for creating a run workspace and inspecting artifact state.

AICODE-NOTE: This entrypoint no longer orchestrates stage execution; it only
creates the initial workspace and derives status from durable artifacts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from planning_workspace_lib import (
    RUNS_SUBDIR,
    load_run_manifest,
    load_scenario_manifest,
    slugify,
    utc_stamp,
)
from runtime_paths import scripts_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or inspect a DeltaPlan planning workspace."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--workspace-root", required=True)
    start.add_argument("--input", required=True)
    start.add_argument("--scenario-id", default="baseline")
    start.add_argument("--scenario-label", default="Baseline")

    status = subparsers.add_parser("status")
    status.add_argument("--run-dir", required=True)
    status.add_argument("--scenario-id")
    return parser.parse_args()


def latest_request_path(clarifications_dir: Path) -> Path | None:
    candidates = sorted(clarifications_dir.glob("request-*.json"))
    return candidates[-1] if candidates else None


def solve_request_outdated(scenario_dir: Path) -> bool:
    request_path = scenario_dir / "solver" / "solve-request.json"
    candidate_model_path = scenario_dir / "normalized" / "candidate-model.json"
    resolved_path = scenario_dir / "normalized" / "planning-signals-resolved.json"
    source_path = (
        resolved_path
        if resolved_path.exists()
        else scenario_dir / "normalized" / "planning-signals.json"
    )
    if (
        not request_path.exists()
        or not candidate_model_path.exists()
        or not source_path.exists()
    ):
        return False
    request_mtime = request_path.stat().st_mtime
    return (
        request_mtime < candidate_model_path.stat().st_mtime
        or request_mtime < source_path.stat().st_mtime
    )


def derive_status(run_dir: Path, scenario_id: str) -> dict[str, object]:
    scenario_dir = run_dir / "scenarios" / scenario_id
    manifest = load_run_manifest(run_dir)
    scenario_manifest = load_scenario_manifest(run_dir, scenario_id)
    normalized_dir = scenario_dir / "normalized"
    clarifications_dir = scenario_dir / "clarifications"
    solver_dir = scenario_dir / "solver"

    latest_request = latest_request_path(clarifications_dir)
    latest_request_status = None
    latest_request_path_value = None
    if latest_request:
        latest_request_path_value = str(latest_request)
        latest_request_status = json.loads(latest_request.read_text()).get("status")
        response_path = clarifications_dir / latest_request.name.replace(
            "request-", "response-"
        )
        if latest_request_status == "open" and not response_path.exists():
            state = "clarification_pending"
        elif latest_request_status == "answered" and response_path.exists():
            state = "clarification_awaiting_merge"
        else:
            state = None
    else:
        state = None

    candidate_model_path = normalized_dir / "candidate-model.json"
    validation_summary_path = normalized_dir / "validation-summary.json"
    solve_request_path = solver_dir / "solve-request.json"
    solve_response_path = solver_dir / "solve-response.json"
    if state is None and not candidate_model_path.exists():
        state = "candidate_model_missing"
    if (
        state is None
        and not solve_request_path.exists()
        and validation_summary_path.exists()
    ):
        validation_summary = json.loads(validation_summary_path.read_text())
        if validation_summary.get("status") == "ready_to_solve":
            state = "solve_request_missing"
    if state is None and solve_request_outdated(scenario_dir):
        state = "solve_request_outdated"
    if (
        state is None
        and solve_request_path.exists()
        and not solve_response_path.exists()
    ):
        state = "solve_response_missing"
    if state is None and solve_response_path.exists():
        output_paths = scenario_manifest.get("latestOutputPaths") or {}
        required_outputs_exist = bool(output_paths) and all(
            (run_dir / path).exists() for path in output_paths.values()
        )
        state = (
            "completed"
            if required_outputs_exist and scenario_manifest.get("latestOutputVersion")
            else "render_missing"
        )
    if state is None:
        state = "workspace_initialized"

    return {
        "runId": manifest.get("runId"),
        "activeScenarioId": manifest.get("activeScenarioId"),
        "inspectedScenarioId": scenario_id,
        "state": state,
        "latestClarificationRequestPath": latest_request_path_value,
        "latestClarificationRequestStatus": latest_request_status,
        "latestSolveRequestPath": scenario_manifest.get("latestSolveRequestPath"),
        "latestSolveResponsePath": scenario_manifest.get("latestSolveResponsePath"),
        "latestOutputVersion": scenario_manifest.get("latestOutputVersion"),
        "latestOutputPaths": scenario_manifest.get("latestOutputPaths", {}),
    }


def main() -> int:
    args = parse_args()
    if args.command == "status":
        run_dir = Path(args.run_dir).resolve()
        manifest = load_run_manifest(run_dir)
        scenario_id = args.scenario_id or manifest.get("activeScenarioId") or "baseline"
        print(json.dumps(derive_status(run_dir, scenario_id), indent=2))
        return 0

    input_path = Path(args.input).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    run_dir = workspace_root / RUNS_SUBDIR / f"{utc_stamp()}-{slugify(input_path.stem)}"
    command = [
        sys.executable,
        str(scripts_dir() / "create_run_workspace.py"),
        "--run-dir",
        str(run_dir),
        "--input",
        str(input_path),
        "--scenario-id",
        args.scenario_id,
        "--scenario-label",
        args.scenario_label,
    ]
    completed = subprocess.run(command, text=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
