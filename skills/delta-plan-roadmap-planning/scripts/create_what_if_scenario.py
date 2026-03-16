#!/usr/bin/env python3
"""
Create a sibling what-if scenario from an existing scenario.

AICODE-NOTE: What-if branches reuse extracted signals and clarified context while preserving baseline outputs in separate scenario directories.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    assign_field,
    load_run_manifest,
    relative_to_run,
    update_checkpoint,
    update_run_status,
    utc_now,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a what-if scenario branch.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source-scenario", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--scenario-label", required=True)
    parser.add_argument("--override-file", required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def override_items(override_payload: Any) -> list[dict[str, Any]]:
    if isinstance(override_payload, dict) and "overrides" in override_payload:
        return override_payload["overrides"]
    if isinstance(override_payload, dict):
        return [{"fieldPath": key, "value": value, "source": "user", "reason": "what_if_branch"} for key, value in override_payload.items()]
    raise ValueError("override-file must contain either {'overrides': [...]} or a fieldPath->value object.")


def apply_override(candidate_model: dict[str, Any], field_path: str, value: Any) -> None:
    resolved_fields = candidate_model.setdefault("resolvedFields", {})
    if field_path == "schedule.estimateProfile":
        resolved_fields["estimateProfile"] = value
    elif field_path == "schedule.monthlyCapacity":
        resolved_fields["monthlyCapacity"] = value
        candidate_model["proposedSchedule"]["monthlyCapacity"] = value
    elif field_path == "schedule.planningHorizonMonths":
        resolved_fields["planningHorizonMonths"] = value
        candidate_model["proposedSchedule"]["planningHorizonMonths"] = value
    elif field_path == "schedule.confirmation.firstSolve":
        resolved_fields["firstSolveConfirmed"] = value
    elif field_path.startswith("schedule.riskAdjustments."):
        risk_adjustments = resolved_fields.setdefault("riskAdjustments", {})
        assign_field({"schedule": risk_adjustments}, field_path, value)
    else:
        resolved_fields[field_path] = value


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    source_dir = run_dir / "scenarios" / args.source_scenario
    target_dir = run_dir / "scenarios" / args.scenario_id
    if target_dir.exists():
        raise SystemExit(f"Scenario already exists: {args.scenario_id}")

    for subdir in ["normalized", "clarifications", "solver", "outputs"]:
        (target_dir / subdir).mkdir(parents=True, exist_ok=True)

    for filename in [
        "planning-signals.json",
        "planning-signals-resolved.json",
        "candidate-model.json",
        "defaults-applied.json",
        "validation-summary.json",
        "run-overrides.json",
        "assumptions.md",
        "review-notes.md",
    ]:
        source_path = source_dir / "normalized" / filename
        if source_path.exists():
            shutil.copy2(source_path, target_dir / "normalized" / filename)

    override_payload = load_json(Path(args.override_file).resolve())
    overrides = override_items(override_payload)
    candidate_model_path = target_dir / "normalized" / "candidate-model.json"
    validation_summary_path = target_dir / "normalized" / "validation-summary.json"
    candidate_model = load_json(candidate_model_path) if candidate_model_path.exists() else None
    validation_summary = load_json(validation_summary_path) if validation_summary_path.exists() else None

    if candidate_model:
        unresolved_fields = list(candidate_model.get("unresolvedFields", []))
        for override in overrides:
            field_path = override["fieldPath"]
            value = override["value"]
            apply_override(candidate_model, field_path, value)
            if field_path in unresolved_fields:
                unresolved_fields.remove(field_path)
        candidate_model["unresolvedFields"] = unresolved_fields
        write_json(candidate_model_path, candidate_model)

    if validation_summary:
        validation_summary["status"] = "ready_to_solve" if candidate_model and not candidate_model.get("unresolvedFields") else "needs_confirmation"
        validation_summary["confirmationRequired"] = validation_summary["status"] != "ready_to_solve"
        write_json(validation_summary_path, validation_summary)

    override_path = target_dir / "normalized" / "run-overrides.json"
    write_json(override_path, {"scenarioId": args.scenario_id, "overrides": overrides})

    scenario_manifest = {
        "scenarioId": args.scenario_id,
        "scenarioSlug": args.scenario_id,
        "scenarioLabel": args.scenario_label,
        "scenarioType": "what_if",
        "parentScenarioId": args.source_scenario,
        "createdAt": utc_now(),
        "defaultsApplied": [],
        "validationSummary": relative_to_run(run_dir, target_dir / "normalized" / "validation-summary.json"),
        "latestSolveRequestPath": None,
        "latestSolveResponsePath": None,
        "latestOutputVersion": None,
        "latestOutputPaths": {},
    }
    write_json(target_dir / "scenario-manifest.json", scenario_manifest)
    write_json(
        target_dir / "scenario-status.json",
        {
            "state": "running",
            "scenarioId": args.scenario_id,
            "scenarioSlug": args.scenario_id,
            "currentStage": "what_if_branch",
            "nextAction": "Build solver payload for the what-if scenario",
            "latestSummary": f"What-if scenario {args.scenario_id} created from {args.source_scenario}.",
            "latestClarificationRequestPath": None,
            "latestSolveRequestPath": None,
            "latestSolveResponsePath": None,
            "latestOutputPaths": {},
        },
    )

    run_manifest = load_run_manifest(run_dir)
    children = set(run_manifest.get("scenarioChildren", []))
    children.add(args.scenario_id)
    run_manifest["scenarioChildren"] = sorted(children)
    run_manifest["activeScenarioId"] = args.scenario_id
    write_json(run_dir / "manifest.json", run_manifest)
    update_run_status(
        run_dir,
        state="running",
        current_stage="what_if_branch",
        next_action="Build solver payload for the what-if scenario",
        latest_summary=f"What-if scenario {args.scenario_id} created from {args.source_scenario}.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage="what_if_branch",
        next_action="Build solver payload for the what-if scenario",
        latest_summary=f"What-if scenario {args.scenario_id} created from {args.source_scenario}.",
        active_scenario_id=args.scenario_id,
        resume_hint="Build the what-if scenario payload and solve it.",
    )
    print(f"WHAT_IF_SCENARIO={args.scenario_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
