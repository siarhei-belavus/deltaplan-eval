#!/usr/bin/env python3
"""
Merge the latest clarification response into the candidate model.

AICODE-NOTE: Clarification merging records explicit overrides separately from extracted workbook facts so reviewers can tell exactly which values were confirmed by a human.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    assign_field,
    ensure_attractor_stage_artifacts,
    load_scenario_status,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_scenario_manifest,
    update_run_status,
    update_scenario_status,
    utc_now,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge clarification answers into candidate model state.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="resume_with_clarification")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return __import__("json").loads(path.read_text())


def answer_map(response_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {answer["questionId"]: answer for answer in response_payload["answers"]}


def upsert_override(run_overrides: dict[str, Any], override: dict[str, Any]) -> None:
    overrides = run_overrides.setdefault("overrides", [])
    for existing in overrides:
        if existing.get("fieldPath") == override.get("fieldPath"):
            existing.update(override)
            return
    overrides.append(override)


def build_resolved_planning_signals(
    planning_signals: dict[str, Any],
    candidate_model: dict[str, Any],
    validation_summary: dict[str, Any],
    run_overrides: dict[str, Any],
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
) -> dict[str, Any]:
    resolved_payload = dict(planning_signals)
    resolved_payload["resolvedFields"] = dict(candidate_model.get("resolvedFields", {}))
    resolved_payload["unresolvedFields"] = list(candidate_model.get("unresolvedFields", []))
    resolved_payload["validationSummary"] = dict(validation_summary)
    completeness_gate = dict(resolved_payload.get("completenessGate", {}))
    completeness_gate["status"] = validation_summary.get("status", completeness_gate.get("status"))
    if validation_summary.get("status") == "ready_to_solve":
        completeness_gate["blockingIssues"] = []
    resolved_payload["completenessGate"] = completeness_gate
    resolved_payload["resolutionState"] = {
        "status": "resolved" if not resolved_payload["unresolvedFields"] else "partially_resolved",
        "requestId": request_payload.get("requestId"),
        "responsePath": response_payload.get("requestId", "").replace("request", "response") + ".json",
        "resolvedAt": utc_now(),
        "overrideCount": len(run_overrides.get("overrides", [])),
    }
    resolved_payload["appliedOverrides"] = list(run_overrides.get("overrides", []))
    return resolved_payload


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def apply_resolution(candidate_model: dict[str, Any], field_path: str, value: Any) -> None:
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
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    normalized_dir = scenario_dir / "normalized"
    clarifications_dir = scenario_dir / "clarifications"
    scenario_status = load_scenario_status(run_dir, args.scenario_id)
    latest_request_ref = scenario_status.get("latestClarificationRequestPath")
    if latest_request_ref:
        request_path = run_dir / latest_request_ref
    else:
        request_candidates = sorted(clarifications_dir.glob("request-*.json"))
        if not request_candidates:
            raise SystemExit("No clarification request file exists for this scenario.")
        request_path = request_candidates[-1]
    request_payload = load_json(request_path)
    response_path = clarifications_dir / f"{request_payload['requestId'].replace('request', 'response')}.json"

    if not response_path.exists():
        print("STATE=waiting_for_input")
        print(f"NEXT_ACTION=Write {response_path.name} before resuming.")
        return 0

    response_payload = load_json(response_path)
    answers_by_id = answer_map(response_payload)
    planning_signals = load_json(normalized_dir / "planning-signals.json")
    candidate_model = load_json(normalized_dir / "candidate-model.json")
    run_overrides = load_json(normalized_dir / "run-overrides.json")
    validation_summary = load_json(normalized_dir / "validation-summary.json")

    unresolved = list(candidate_model["unresolvedFields"])
    resolved_fields = candidate_model.setdefault("resolvedFields", {})
    for question in request_payload["questions"]:
        answer = answers_by_id.get(question["questionId"])
        if not answer or answer.get("status") != "answered":
            continue
        field_path = question["fieldPath"]
        value = answer["value"]
        apply_resolution(candidate_model, field_path, value)

        if field_path in unresolved:
            unresolved.remove(field_path)

        upsert_override(
            run_overrides,
            {
                "fieldPath": field_path,
                "value": value,
                "source": answer.get("source", "user"),
                "reason": f"Resolved via {response_payload['requestId']}",
            },
        )

    candidate_model["unresolvedFields"] = unresolved
    ready = not unresolved and bool(resolved_fields.get("firstSolveConfirmed"))
    validation_summary["status"] = "ready_to_solve" if ready else "needs_confirmation"
    validation_summary["confirmationRequired"] = not ready
    non_blocking_warnings = validation_summary.setdefault("nonBlockingWarnings", [])
    if ready and "All blocking clarification answers were supplied." not in non_blocking_warnings:
        non_blocking_warnings.append("All blocking clarification answers were supplied.")
    validation_summary["nonBlockingWarnings"] = dedupe_strings(non_blocking_warnings)

    write_json(normalized_dir / "candidate-model.json", candidate_model)
    write_json(normalized_dir / "run-overrides.json", run_overrides)
    write_json(normalized_dir / "validation-summary.json", validation_summary)
    resolved_signals_path = normalized_dir / "planning-signals-resolved.json"
    write_json(
        resolved_signals_path,
        build_resolved_planning_signals(
            planning_signals,
            candidate_model,
            validation_summary,
            run_overrides,
            request_payload,
            response_payload,
        ),
    )
    request_payload["status"] = "resolved" if ready else "open"
    write_json(request_path, request_payload)
    touch_generated_artifact(run_dir, normalized_dir / "candidate-model.json")
    touch_generated_artifact(run_dir, normalized_dir / "run-overrides.json")
    touch_generated_artifact(run_dir, normalized_dir / "validation-summary.json")
    touch_generated_artifact(run_dir, resolved_signals_path)
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestResolvedPlanningSignalsPath=relative_to_run(run_dir, resolved_signals_path),
    )

    if ready:
        update_run_status(
            run_dir,
            state="running",
            current_stage=args.stage_id,
            next_action="Build the solver payload",
            latest_summary="Clarification answers merged; scenario is ready for payload build.",
            active_scenario_id=args.scenario_id,
        )
        update_checkpoint(
            run_dir,
            state="running",
            current_stage=args.stage_id,
            next_action="Build the solver payload",
            latest_summary="Clarification answers merged; scenario is ready for payload build.",
            active_scenario_id=args.scenario_id,
            resume_hint="Run build_solver_payload next.",
        )
        update_scenario_status(
            run_dir,
            args.scenario_id,
            state="running",
            current_stage=args.stage_id,
            next_action="Build solver payload",
            latest_summary="Clarification answers merged successfully.",
            latest_clarification_request_path=relative_to_run(run_dir, request_path),
        )
    else:
        update_run_status(
            run_dir,
            state="waiting_for_input",
            current_stage=args.stage_id,
            next_action="Supply the remaining clarification answers",
            latest_summary="Clarification merge completed but blocking questions remain.",
            active_scenario_id=args.scenario_id,
        )
        update_checkpoint(
            run_dir,
            state="waiting_for_input",
            current_stage=args.stage_id,
            next_action="Supply the remaining clarification answers",
            latest_summary="Clarification merge completed but blocking questions remain.",
            active_scenario_id=args.scenario_id,
            resume_hint=f"Update {response_path.name} and resume clarification merge.",
        )
        update_scenario_status(
            run_dir,
            args.scenario_id,
            state="waiting_for_input",
            current_stage=args.stage_id,
            next_action="Supply the remaining clarification answers",
            latest_summary="Clarification answers are still incomplete.",
            latest_clarification_request_path=relative_to_run(run_dir, request_path),
        )

    ensure_attractor_stage_artifacts(
        run_dir,
        stage_id=args.stage_id,
        command="merge_clarification_response.py",
        inputs={"runDir": str(run_dir), "scenarioId": args.scenario_id},
        summary="Merged clarification response into the candidate model.",
        state="success" if ready else "waiting_for_input",
        outputs={
            "responsePath": relative_to_run(run_dir, response_path),
            "readyToSolve": ready,
            "resolvedPlanningSignalsPath": relative_to_run(run_dir, resolved_signals_path),
        },
    )
    print(f"READY_TO_SOLVE={'true' if ready else 'false'}")
    print(f"STATE={'ready_to_solve' if ready else 'waiting_for_input'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
