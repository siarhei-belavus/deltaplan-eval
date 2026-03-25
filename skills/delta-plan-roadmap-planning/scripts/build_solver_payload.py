#!/usr/bin/env python3
"""
Build a DeltaPlan solve request from the candidate model and confirmed overrides.

AICODE-NOTE: Payload build is isolated from source parsing so DTO alignment can be validated and evolved against the live DeltaPlan contract without reworking intake stages.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    next_output_prefix,
    preferred_planning_signals_path,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_manifest,
    update_scenario_status,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a DeltaPlan solve-request payload.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="build_solver_payload")
    parser.add_argument("--termination-seconds", type=int, default=5)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return __import__("json").loads(path.read_text())


def md_to_weeks(days: float) -> float:
    return round(days / 5.0, 2)


def feature_profile_values(feature: dict[str, Any], estimate_profile: str, resolved_fields: dict[str, Any]) -> dict[str, float]:
    profile_values = dict(feature["estimateProfiles"][estimate_profile])
    if estimate_profile != "ai":
        return profile_values
    risk_adjustments = resolved_fields.get("riskAdjustments", {})
    ai_adjustments = risk_adjustments.get("ai", {})
    if not ai_adjustments.get("applyContingency"):
        return profile_values
    feature_adjustment = ai_adjustments.get("features", {}).get(feature["id"], {})
    profile_values["DevelopmentMd"] = round(profile_values.get("DevelopmentMd", 0.0) + feature_adjustment.get("developmentMdBuffer", 0.0), 2)
    profile_values["QAMd"] = round(profile_values.get("QAMd", 0.0) + feature_adjustment.get("qaMdBuffer", 0.0), 2)
    return profile_values


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    normalized_dir = scenario_dir / "normalized"
    solver_dir = scenario_dir / "solver"
    planning_signals_path = preferred_planning_signals_path(normalized_dir)
    candidate_model = load_json(normalized_dir / "candidate-model.json")
    validation_summary = load_json(normalized_dir / "validation-summary.json")
    planning_signals = load_json(planning_signals_path)

    if validation_summary.get("status") != "ready_to_solve" or planning_signals.get("completenessGate", {}).get("status") != "ready_to_solve":
        raise SystemExit("Scenario is not ready to solve; complete the clarification cycle first.")

    resolved_fields = candidate_model["resolvedFields"]
    estimate_profile = resolved_fields["estimateProfile"]
    monthly_capacity = candidate_model["resolvedFields"]["monthlyCapacity"]

    features = []
    for feature in candidate_model["proposedSchedule"]["features"]:
        profile_values = feature_profile_values(feature, estimate_profile, resolved_fields)
        effort_weeks: dict[str, float] = {}
        if profile_values["DevelopmentMd"] > 0:
            effort_weeks["Development"] = md_to_weeks(profile_values["DevelopmentMd"])
        if profile_values["QAMd"] > 0:
            effort_weeks["QA"] = md_to_weeks(profile_values["QAMd"])
        features.append(
            {
                "id": feature["id"],
                "title": feature["title"],
                "effortWeeks": effort_weeks,
                "qaOverhead": feature["qaOverhead"],
                "serial": feature["serial"],
                "phaseId": feature["phaseId"],
                "dependencies": feature["dependencies"],
                "deadlineWeek": None,
                "priority": None,
            }
        )

    solve_request = {
        "schedule": {
            "planningHorizonMonths": candidate_model["resolvedFields"]["planningHorizonMonths"],
            "monthlyCapacity": monthly_capacity,
            "productivityFactor": candidate_model["resolvedFields"]["productivityFactor"],
            "phases": candidate_model["proposedSchedule"]["phases"],
            "features": features,
        },
        "terminationSeconds": args.termination_seconds,
    }
    request_path = solver_dir / "solve-request.json"
    metadata_path = solver_dir / "solver-metadata.json"
    write_json(request_path, solve_request)
    write_json(
        metadata_path,
        {
            "scenarioId": args.scenario_id,
            "estimateProfile": estimate_profile,
            "planningSignalsPath": relative_to_run(run_dir, planning_signals_path),
            "payloadStatus": "built",
        },
    )
    touch_generated_artifact(run_dir, request_path)
    touch_generated_artifact(run_dir, metadata_path)
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Call the DeltaPlan MCP solve tool",
        latest_summary=f"Built solve payload using the {estimate_profile} estimate profile.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Call the DeltaPlan MCP solve tool",
        latest_summary=f"Built solve payload using the {estimate_profile} estimate profile.",
        active_scenario_id=args.scenario_id,
        resume_hint="Run call_deltaplan_mcp next.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action="Call DeltaPlan MCP",
        latest_summary=f"Solve payload built with the {estimate_profile} estimate profile.",
        latest_solve_request_path=relative_to_run(run_dir, request_path),
    )
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestSolveRequestPath=relative_to_run(run_dir, request_path),
    )
    print(f"SOLVE_REQUEST={request_path}")
    print("STATE=ready_to_solve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
