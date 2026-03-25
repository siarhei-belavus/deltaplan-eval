#!/usr/bin/env python3
"""
Build the candidate model and clarification bundle from planning signals.

AICODE-NOTE: Candidate-model construction preserves unresolved planning facts as explicit fields so the workflow pauses cleanly instead of collapsing ambiguity into hidden assumptions.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    load_run_manifest,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_manifest,
    update_scenario_status,
    utc_now,
    write_json,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build candidate model and clarification artifacts.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="build_candidate_model")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return __import__("json").loads(path.read_text())


def next_request_id(clarifications_dir: Path) -> str:
    numbers = []
    for path in clarifications_dir.glob("request-*.json"):
        match = re.match(r"request-(\d+)\.json", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"request-{max(numbers, default=0) + 1:03d}"


def feature_to_phase_map(features: list[dict[str, Any]], milestones: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for feature in features:
        if feature.get("phaseHint"):
            mapping[feature["id"]] = feature["phaseHint"]
    for milestone in milestones:
        phase_id = milestone.get("phaseId")
        for feature_id in milestone.get("featureIds", []):
            if phase_id and feature_id not in mapping:
                mapping[feature_id] = phase_id
    return mapping


def phase_candidates(
    explicit_phases: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if explicit_phases:
        return explicit_phases, []
    phases = []
    defaults_applied = []
    previous_phase = None
    for milestone in milestones:
        phase_id = milestone.get("phaseId")
        if not phase_id:
            continue
        phase = {
            "id": phase_id,
            "name": milestone.get("title") or phase_id,
            "mustStartAfter": previous_phase,
            "overlapThreshold": 1.0 if previous_phase else None,
            "deadlineWeek": milestone.get("deadlineWeek"),
        }
        if previous_phase:
            defaults_applied.append(
                {
                    "fieldPath": f"schedule.phases[{phase_id}].overlapThreshold",
                    "value": 1.0,
                    "reason": "workflow_default",
                }
            )
        phases.append(phase)
        previous_phase = phase_id
    return phases, defaults_applied


def clarification_markdown(request_payload: dict[str, Any]) -> str:
    lines = [f"# Clarification Request {request_payload['requestId']}", ""]
    for question in request_payload["questions"]:
        lines.append(f"## {question['questionId']}")
        lines.append(question["prompt"])
        lines.append("")
        lines.append(f"- Field path: `{question['fieldPath']}`")
        lines.append(f"- Response type: `{question['responseType']}`")
        if question["defaultValue"] is not None:
            lines.append(f"- Default: `{question['defaultValue']}`")
        if question["allowedValues"]:
            lines.append("- Allowed values: " + ", ".join(f"`{item}`" for item in question["allowedValues"]))
        lines.append("")
    return "\n".join(lines)


def prompts_for_field(
    planning_facts: dict[str, Any],
    candidate_by_field: dict[str, dict[str, Any]],
    field_path: str,
) -> tuple[str, list[dict[str, Any]]]:
    candidate = candidate_by_field.get(field_path, {})
    candidate_provenance = candidate.get("provenance", [])
    if field_path == "schedule.estimateProfile":
        estimate_profiles = [item["key"] for item in planning_facts.get("estimateProfiles", []) if item.get("key")]
        prompt = (
            "Which estimate profile should this solve use: "
            + (", ".join(estimate_profiles) if estimate_profiles else "provide one explicitly")
            + "?"
        )
        provenance = candidate_provenance or planning_facts.get("estimateProfiles", [{}])[0:1]
        return prompt, provenance
    if field_path == "schedule.monthlyCapacity":
        prompt = (
            "What monthly team capacity should we use? "
            'Provide a list like [{"month":1,"roleFtes":{"Development":1.0,"QA":1.0}}].'
        )
        return prompt, candidate_provenance
    if field_path == "schedule.planningHorizonMonths":
        prompt = "How many months should the planning horizon cover for the first solve?"
        return prompt, candidate_provenance
    if field_path == "schedule.riskAdjustments.ai.applyContingency":
        prompt = "Should the AI contingency buffer be added on top of the AI profile for the first solve?"
        return prompt, candidate_provenance
    return candidate.get("prompt") or field_path, candidate_provenance


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    normalized_dir = scenario_dir / "normalized"
    clarifications_dir = scenario_dir / "clarifications"
    request_id = next_request_id(clarifications_dir)
    planning_signals = load_json(normalized_dir / "planning-signals.json")
    run_manifest = load_run_manifest(run_dir)
    planning_facts = planning_signals["planningFacts"]
    phases, phase_defaults = phase_candidates(planning_facts.get("phases", []), planning_facts.get("milestones", []))
    phase_mapping = feature_to_phase_map(planning_facts.get("features", []), planning_facts.get("milestones", []))

    defaults_applied = [
        {"fieldPath": "schedule.productivityFactor", "value": 0.75, "reason": "workflow_default"},
        {"fieldPath": "schedule.defaults.qaOverhead", "value": 0.20, "reason": "workflow_default"},
        {"fieldPath": "schedule.defaults.serial", "value": False, "reason": "workflow_default"},
        *phase_defaults,
    ]
    features = []
    for feature in planning_facts.get("features", []):
        features.append(
            {
                "id": feature["id"],
                "title": feature["title"],
                "phaseId": phase_mapping.get(feature["id"]),
                "dependencies": feature["dependencies"] or None,
                "deadlineWeek": feature.get("deadlineWeek"),
                "priority": feature.get("priority"),
                "estimateProfiles": feature["estimateProfiles"],
                "riskAdjustments": feature.get("riskAdjustments", {}),
                "qaOverhead": feature.get("qaOverhead", 0.20),
                "serial": feature.get("serial", False),
                "provenance": feature["provenance"],
            }
        )
    used_phase_ids = {feature["phaseId"] for feature in features if feature.get("phaseId")}
    phases = [phase for phase in phases if phase.get("id") in used_phase_ids]

    resolved_fields = planning_signals.get("resolvedFields", {})
    unresolved_fields = list(planning_signals.get("unresolvedFields", []))
    planning_horizon = resolved_fields.get("planningHorizonMonths")
    validation_summary = {
        "scenarioId": args.scenario_id,
        "status": planning_signals.get("completenessGate", {}).get(
            "status",
            "ready_to_solve" if not unresolved_fields else "needs_confirmation",
        ),
        "blockingIssues": list(planning_signals.get("validationSummary", {}).get("blockingIssues", [])),
        "nonBlockingWarnings": list(planning_signals.get("validationSummary", {}).get("warnings", [])),
        "confirmationRequired": bool(unresolved_fields),
    }
    if not planning_horizon:
        validation_summary["blockingIssues"].append("Planning horizon could not be resolved from source signals.")

    if validation_summary["blockingIssues"]:
        validation_summary["status"] = "needs_confirmation"
        validation_summary["confirmationRequired"] = True

    questions = []
    existing_candidates = planning_signals.get("clarificationCandidates", [])
    candidate_by_field = {item.get("fieldPath"): item for item in existing_candidates if item.get("fieldPath")}
    question_number = 1

    def append_question(field_path: str, prompt: str, response_type: str, default_value: Any, allowed_values: Any, provenance: list[dict[str, Any]]) -> None:
        nonlocal question_number
        questions.append(
            {
                "questionId": f"q-{question_number:03d}",
                "fieldPath": field_path,
                "prompt": prompt,
                "responseType": response_type,
                "required": True,
                "defaultValue": default_value,
                "allowedValues": allowed_values,
                "provenance": provenance,
                "resolutionRule": "block_solve_until_answered",
            }
        )
        question_number += 1

    if "schedule.estimateProfile" in unresolved_fields:
        estimate_profiles = [item["key"] for item in planning_facts.get("estimateProfiles", []) if item.get("key")]
        prompt, provenance = prompts_for_field(planning_facts, candidate_by_field, "schedule.estimateProfile")
        append_question(
            "schedule.estimateProfile",
            prompt,
            "enum",
            estimate_profiles[0] if estimate_profiles else None,
            estimate_profiles or None,
            provenance,
        )
    if "schedule.monthlyCapacity" in unresolved_fields:
        prompt, provenance = prompts_for_field(planning_facts, candidate_by_field, "schedule.monthlyCapacity")
        append_question(
            "schedule.monthlyCapacity",
            prompt,
            "object",
            None,
            None,
            provenance,
        )
    if "schedule.planningHorizonMonths" in unresolved_fields:
        prompt, provenance = prompts_for_field(planning_facts, candidate_by_field, "schedule.planningHorizonMonths")
        append_question(
            "schedule.planningHorizonMonths",
            prompt,
            "number",
            None,
            None,
            provenance,
        )
    if "schedule.riskAdjustments.ai.applyContingency" in unresolved_fields:
        prompt, provenance = prompts_for_field(planning_facts, candidate_by_field, "schedule.riskAdjustments.ai.applyContingency")
        append_question(
            "schedule.riskAdjustments.ai.applyContingency",
            prompt,
            "boolean",
            False,
            None,
            provenance,
        )
    append_question(
        "schedule.confirmation.firstSolve",
        "Please confirm the first solve should proceed once the answers above are applied.",
        "boolean",
        False,
        None,
        [],
    )

    candidate_model = {
        "scenarioId": args.scenario_id,
        "sourceSummary": {
            "primaryInputArtifact": run_manifest["primaryInputArtifact"],
            "supportingArtifacts": [
                path for path in planning_signals["sourceArtifacts"] if path != run_manifest["primaryInputArtifact"]
            ],
        },
        "resolvedFields": {
            "planningHorizonMonths": planning_horizon,
            "estimateProfile": resolved_fields.get("estimateProfile"),
            "monthlyCapacity": resolved_fields.get("monthlyCapacity", []),
            "productivityFactor": 0.75,
            "riskAdjustments": resolved_fields.get("riskAdjustments", {}),
            "defaultsApplied": defaults_applied,
        },
        "unresolvedFields": unresolved_fields + ["schedule.confirmation.firstSolve"],
        "proposedSchedule": {
            "planningHorizonMonths": planning_horizon,
            "monthlyCapacity": resolved_fields.get("monthlyCapacity", []),
            "productivityFactor": 0.75,
            "phases": phases,
            "features": features,
        },
        "runOverridesPath": f"scenarios/{args.scenario_id}/normalized/run-overrides.json",
        "defaultsAppliedPath": f"scenarios/{args.scenario_id}/normalized/defaults-applied.json",
        "validationSummaryPath": f"scenarios/{args.scenario_id}/normalized/validation-summary.json",
    }
    run_overrides = {"scenarioId": args.scenario_id, "overrides": []}
    open_questions = {
        "scenarioId": args.scenario_id,
        "requestId": request_id,
        "questions": questions,
    }
    request_payload = {
        "requestId": request_id,
        "scenarioId": args.scenario_id,
        "status": "open",
        "createdAt": utc_now(),
        "questions": open_questions["questions"],
    }

    assumptions_md = "\n".join(f"- {item['text']}" for item in planning_facts.get("assumptions", [])) or "- None"
    review_notes_md = "\n".join(f"- {note['message']}" for note in planning_signals.get("reviewNotes", [])) or "- None"

    files_to_write = {
        normalized_dir / "candidate-model.json": candidate_model,
        normalized_dir / "open-questions.json": open_questions,
        normalized_dir / "run-overrides.json": run_overrides,
        normalized_dir / "defaults-applied.json": {"scenarioId": args.scenario_id, "defaultsApplied": defaults_applied},
        normalized_dir / "validation-summary.json": validation_summary,
        clarifications_dir / f"{request_id}.json": request_payload,
    }
    for path, payload in files_to_write.items():
        write_json(path, payload)
        touch_generated_artifact(run_dir, path)

    write_text(normalized_dir / "assumptions.md", assumptions_md)
    write_text(normalized_dir / "review-notes.md", review_notes_md)
    write_text(clarifications_dir / f"{request_id}.md", clarification_markdown(request_payload))
    touch_generated_artifact(run_dir, normalized_dir / "assumptions.md")
    touch_generated_artifact(run_dir, normalized_dir / "review-notes.md")
    touch_generated_artifact(run_dir, clarifications_dir / f"{request_id}.md")

    latest_request_path = relative_to_run(run_dir, clarifications_dir / f"{request_id}.json")
    update_run_status(
        run_dir,
        state="waiting_for_input",
        current_stage=args.stage_id,
        next_action="Collect clarification answers and resume the run",
        latest_summary="Candidate model built; clarification is required before the first solve.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="waiting_for_input",
        current_stage=args.stage_id,
        next_action="Collect clarification answers and resume the run",
        latest_summary="Candidate model built; clarification is required before the first solve.",
        active_scenario_id=args.scenario_id,
        resume_hint=f"Write {request_id.replace('request', 'response')}.json and run merge_clarification_response.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="waiting_for_input",
        current_stage=args.stage_id,
        next_action=f"Answer {request_id} and resume",
        latest_summary="Clarification is required before the first solve.",
        latest_clarification_request_path=latest_request_path,
    )
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        defaultsApplied=[item["fieldPath"] for item in defaults_applied],
        validationSummary=relative_to_run(run_dir, normalized_dir / "validation-summary.json"),
    )

    print(f"CANDIDATE_MODEL={normalized_dir / 'candidate-model.json'}")
    print(f"CLARIFICATION_REQUEST={clarifications_dir / f'{request_id}.json'}")
    print("STATE=waiting_for_input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
