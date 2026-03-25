#!/usr/bin/env python3
"""
Finalize scenario status after report rendering.

AICODE-NOTE: Finalization publishes the latest recommended artifact set into scenario status so the skill can summarize results without rediscovering files heuristically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    next_output_prefix,
    relative_to_run,
    update_checkpoint,
    update_run_status,
    update_scenario_manifest,
    update_scenario_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a completed scenario run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="finalize_run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    outputs_dir = scenario_dir / "outputs"
    scenario_manifest_path = scenario_dir / "scenario-manifest.json"
    scenario_manifest = json.loads(scenario_manifest_path.read_text())
    scenario_slug = scenario_manifest.get("scenarioSlug", args.scenario_id)

    latest_html = sorted(outputs_dir.glob(f"v*_{scenario_slug}-report.html"))[-1]
    prefix = latest_html.name.split("-report.html")[0]
    latest_output_paths = {
        "htmlReport": relative_to_run(run_dir, latest_html),
        "summaryText": relative_to_run(run_dir, outputs_dir / f"{prefix}-summary.txt"),
        "summaryMarkdown": relative_to_run(run_dir, outputs_dir / f"{prefix}-summary.md"),
        "roadmapMarkdown": relative_to_run(run_dir, outputs_dir / f"{prefix}-roadmap.md"),
        "heatmapMonthlyMarkdown": relative_to_run(run_dir, outputs_dir / f"{prefix}-heatmap-monthly.md"),
    }

    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestOutputVersion=prefix.split("_")[0],
        latestOutputPaths=latest_output_paths,
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="completed",
        current_stage=args.stage_id,
        next_action="Review outputs or create a what-if scenario",
        latest_summary="Scenario completed successfully.",
        latest_solve_request_path=relative_to_run(run_dir, scenario_dir / "solver" / "solve-request.json"),
        latest_solve_response_path=relative_to_run(run_dir, scenario_dir / "solver" / "solve-response.json"),
        latest_output_paths=latest_output_paths,
    )
    update_run_status(
        run_dir,
        state="completed",
        current_stage=args.stage_id,
        next_action="Review outputs or create a what-if scenario",
        latest_summary="The active scenario completed successfully.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="completed",
        current_stage=args.stage_id,
        next_action="Review outputs or create a what-if scenario",
        latest_summary="The active scenario completed successfully.",
        active_scenario_id=args.scenario_id,
        resume_hint="Create a what-if scenario or inspect the latest outputs.",
    )
    print("STATE=completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
