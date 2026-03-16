#!/usr/bin/env python3
"""
Merge focused analysis agent outputs into the canonical planning-signals contract.

AICODE-NOTE: The merge layer is deterministic so workbook reasoning can fan out across agents without turning final planning facts into opaque LLM-only state.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    ESTIMATE_PROFILES,
    ensure_attractor_stage_artifacts,
    load_run_manifest,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_status,
    write_json,
)


ANALYSIS_NODES = [
    "structure_agent",
    "feature_agent",
    "timeline_agent",
    "capacity_agent",
    "constraint_agent",
    "analysis_lead_summary",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge agent analysis outputs into planning signals.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="merge_planning_signals")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def extract_json(text: str) -> Any:
    payload = text.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", payload)
        payload = re.sub(r"\n```$", "", payload)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", payload)
        if not match:
            raise
        return json.loads(match.group(1))


def load_agent_output(run_dir: Path, node_id: str) -> Any:
    response_path = run_dir / "attractor" / node_id / "response.md"
    if not response_path.exists():
        raise FileNotFoundError(f"Missing analysis response for {node_id}: {response_path}")
    return extract_json(response_path.read_text())


def normalize_agent_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    def normalize_reference_list(items: Any, *, default_key: str) -> list[dict[str, Any]]:
        normalized_items: list[dict[str, Any]] = []
        for item in items or []:
            if isinstance(item, dict):
                normalized_items.append(item)
            elif isinstance(item, str):
                normalized_items.append({default_key: item})
        return normalized_items

    normalized = dict(payload)
    normalized.setdefault("summary", "")
    normalized["usedRegions"] = normalize_reference_list(normalized.get("usedRegions", []), default_key="regionId")
    normalized["expandedSearch"] = normalize_reference_list(normalized.get("expandedSearch", []), default_key="target")
    normalized["ignoredRegions"] = normalize_reference_list(normalized.get("ignoredRegions", []), default_key="target")
    normalized.setdefault("coverageAssessment", {"status": "low", "reason": "Agent did not provide coverage evidence."})
    normalized["missedRiskCandidates"] = normalize_reference_list(normalized.get("missedRiskCandidates", []), default_key="target")
    normalized.setdefault("clarificationCandidates", [])
    normalized.setdefault("reviewNotes", [])
    return normalized


def unique_by_identity(items: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            item = {"value": item}
        key = tuple(item.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def canonical_profile_key(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    aliases = {
        "regular": "regular",
        "dev_regular_md": "regular",
        "ai": "ai",
        "dev_ai_md": "ai",
        "ai_contingency": "ai_contingency",
        "aicontingency": "ai_contingency",
        "dev_ai_contingency": "ai_contingency",
    }
    return aliases.get(normalized, normalized or "custom")


def extract_reference_tokens(text: str) -> list[str]:
    candidates = re.findall(
        r"\b[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b|\b[A-Za-z]{1,10}\d{1,10}\b",
        text,
        flags=re.IGNORECASE,
    )
    results = []
    for candidate in candidates:
        normalized = candidate.strip().upper()
        if any(character.isalpha() for character in normalized) and any(character.isdigit() for character in normalized):
            results.append(normalized)
            continue
        if any(separator in normalized for separator in "-_/") and len(normalized) >= 4:
            results.append(normalized)
    return sorted(set(results))


def resolve_dependency_ids(raw_dependencies: list[Any], known_feature_ids: set[str], current_feature_id: str) -> tuple[list[str], list[str]]:
    resolved: set[str] = set()
    unresolved: list[str] = []
    for item in raw_dependencies:
        candidate = str(item).strip()
        if not candidate:
            continue
        candidate_upper = candidate.upper()
        matches = set()
        if candidate_upper in known_feature_ids:
            matches.add(candidate_upper)
        matches.update(token for token in extract_reference_tokens(candidate) if token in known_feature_ids)
        if not matches:
            for known_feature_id in known_feature_ids:
                if re.search(rf"(?<![A-Z0-9]){re.escape(known_feature_id)}(?![A-Z0-9])", candidate_upper):
                    matches.add(known_feature_id)
        matches.discard(current_feature_id)
        if matches:
            resolved.update(matches)
        else:
            unresolved.append(candidate)
    return sorted(resolved), unresolved


def normalize_numeric(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def normalize_risk_adjustments(feature: dict[str, Any], estimate_profiles: dict[str, dict[str, float]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    risk_adjustments: dict[str, Any] = {}
    clarification_candidates: list[dict[str, Any]] = []
    contingency_profile = estimate_profiles.pop("ai_contingency", None)
    ai_profile = estimate_profiles.get("ai")
    if contingency_profile:
        if ai_profile:
            development_buffer = max(
                0.0,
                round(normalize_numeric(contingency_profile.get("DevelopmentMd")) - normalize_numeric(ai_profile.get("DevelopmentMd")), 2),
            )
            qa_buffer = max(
                0.0,
                round(normalize_numeric(contingency_profile.get("QAMd")) - normalize_numeric(ai_profile.get("QAMd")), 2),
            )
            if development_buffer or qa_buffer:
                risk_adjustments["ai"] = {
                    "sourceProfile": "ai_contingency",
                    "developmentMdBuffer": development_buffer,
                    "qaMdBuffer": qa_buffer,
                }
        else:
            clarification_candidates.append(
                {
                    "fieldPath": "schedule.riskAdjustments.ai.applyContingency",
                    "prompt": f"Workbook contains an AI contingency estimate for {feature.get('id')}, but no separate AI base profile was extracted. Should that contingency be ignored or treated as the AI baseline?",
                    "reason": "AI contingency estimates cannot be modeled safely without an AI baseline profile.",
                    "provenance": feature.get("provenance", []),
                }
            )
    return risk_adjustments, clarification_candidates


def canonicalize_feature(feature: dict[str, Any]) -> dict[str, Any]:
    estimate_profiles = {}
    for key, values in feature.get("estimateProfiles", {}).items():
        canonical_key = canonical_profile_key(key)
        estimate_profiles[canonical_key] = {
            "DevelopmentMd": normalize_numeric(values.get("DevelopmentMd", 0.0)),
            "QAMd": normalize_numeric(values.get("QAMd", 0.0)),
        }
    risk_adjustments, clarification_candidates = normalize_risk_adjustments(feature, estimate_profiles)
    return {
        "id": str(feature.get("id", "")).strip().upper(),
        "title": str(feature.get("title", "")).strip(),
        "description": feature.get("description"),
        "estimateProfiles": estimate_profiles,
        "riskAdjustments": risk_adjustments,
        "dependencies": [],
        "dependencyCandidates": [str(item).strip() for item in feature.get("dependencies", []) if str(item).strip()],
        "phaseHint": feature.get("phaseHint"),
        "priority": feature.get("priority"),
        "serial": bool(feature.get("serial", False)),
        "qaOverhead": float(feature.get("qaOverhead", 0.20) or 0.20),
        "status": feature.get("status"),
        "confidence": feature.get("confidence", "medium"),
        "provenance": feature.get("provenance", []),
        "normalizationNotes": list(feature.get("normalizationNotes", [])),
        "clarificationCandidates": clarification_candidates,
    }


def canonicalize_phase(phase: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": phase.get("id"),
        "name": phase.get("name") or phase.get("title") or phase.get("id"),
        "mustStartAfter": phase.get("mustStartAfter"),
        "overlapThreshold": phase.get("overlapThreshold"),
        "deadlineWeek": phase.get("deadlineWeek"),
    }


def normalize_clarification_candidate(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        prompt = item.strip()
        return {
            "fieldPath": None,
            "prompt": prompt,
            "reason": "Agent surfaced a clarification question without an explicit field mapping.",
            "provenance": [],
        }
    prompt = item.get("prompt") or item.get("question")
    field_path = item.get("fieldPath")
    if not field_path and prompt:
        prompt_lower = prompt.lower()
        if "capacity" in prompt_lower:
            field_path = "schedule.monthlyCapacity"
        elif "week" in prompt_lower or "w1" in prompt_lower or "milestone" in prompt_lower:
            field_path = "schedule.milestones.deadlineWeek"
        elif "estimate" in prompt_lower or "effort" in prompt_lower:
            field_path = "schedule.estimateProfile"
        elif "contingency" in prompt_lower or "buffer" in prompt_lower:
            field_path = "schedule.riskAdjustments.ai.applyContingency"
    return {
        "fieldPath": field_path,
        "prompt": prompt,
        "reason": item.get("reason"),
        "provenance": item.get("provenance", []),
    }


def derived_constraints(features: list[dict[str, Any]], capacities: list[dict[str, Any]], estimate_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    constraints = []
    if len(estimate_profiles) > 1:
        constraints.append(
            {
                "type": "estimate_profile_selection_required",
                "summary": "Multiple estimate profiles were detected; choose one before solve.",
                "confidence": "high",
                "provenance": [item for profile in estimate_profiles for item in profile.get("provenance", [])][:4],
            }
        )
    if not capacities:
        constraints.append(
            {
                "type": "capacity_missing",
                "summary": "No explicit monthly capacity table was extracted from the workbook.",
                "confidence": "medium",
                "provenance": [item for feature in features[:2] for item in feature.get("provenance", [])][:4],
            }
        )
    return constraints


def coverage_rank(status: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(status).lower(), 0)


def explicitly_external_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return any(token in lowered for token in ["external", "vendor", "third party", "3rd party", "outside scope"])


def referenced_feature_ids(milestones: list[dict[str, Any]], dependencies: list[dict[str, Any]]) -> set[str]:
    referenced: set[str] = set()
    for milestone in milestones:
        referenced.update(str(item).strip().upper() for item in milestone.get("featureIds", []) if str(item).strip())
    for dependency in dependencies:
        referenced.update(str(item).strip().upper() for item in dependency.get("dependsOn", []) if str(item).strip())
        feature_id = str(dependency.get("featureId", "")).strip().upper()
        if feature_id:
            referenced.add(feature_id)
    return referenced


def risky_region_ids(inventory_refs: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for region in inventory_refs.get("regionRefs", []):
        kind_hints = set(region.get("kindHints", []))
        suspicion_flags = set(region.get("suspicionFlags", []))
        if "feature_table" in kind_hints or suspicion_flags:
            result.add(region["regionId"])
    return result


def agent_region_set(agent_output: dict[str, Any], field: str) -> set[str]:
    result: set[str] = set()
    for item in agent_output.get(field, []):
        if isinstance(item, str):
            target = item
        else:
            target = item.get("regionId") or item.get("target")
        if target:
            result.add(str(target))
    return result


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id / "normalized"
    workbook_profile = load_json(scenario_dir / "workbook-profile.json")
    inventory_refs = load_json(scenario_dir / "inventory-refs.json")
    outputs = {node_id: normalize_agent_output(load_agent_output(run_dir, node_id)) for node_id in ANALYSIS_NODES}

    structure_output = outputs["structure_agent"]
    feature_output = outputs["feature_agent"]
    timeline_output = outputs["timeline_agent"]
    capacity_output = outputs["capacity_agent"]
    constraint_output = outputs["constraint_agent"]
    lead_output = outputs["analysis_lead_summary"]

    features = unique_by_identity(
        [canonicalize_feature(item) for item in feature_output.get("features", []) if item.get("id") and item.get("title")],
        ["id"],
    )
    known_feature_ids = {feature["id"] for feature in features if feature.get("id")}
    feature_level_clarifications: list[dict[str, Any]] = []
    for feature in features:
        resolved_dependencies, unresolved_dependencies = resolve_dependency_ids(
            feature.pop("dependencyCandidates", []),
            known_feature_ids,
            feature["id"],
        )
        feature["dependencies"] = resolved_dependencies
        feature_level_clarifications.extend(feature.pop("clarificationCandidates", []))
        if unresolved_dependencies:
            feature["normalizationNotes"].append(
                "Dependency text did not resolve cleanly to extracted work item ids: "
                + "; ".join(unresolved_dependencies)
            )
            feature_level_clarifications.append(
                {
                    "fieldPath": "schedule.dependencies",
                    "prompt": f"Clarify unresolved dependencies for {feature['id']}: {', '.join(unresolved_dependencies)}",
                    "reason": "Dependency references could materially change ordering but did not resolve to known work item ids.",
                    "provenance": feature.get("provenance", []),
                }
            )
    milestones = unique_by_identity(timeline_output.get("milestones", []), ["id", "title"])
    phases = unique_by_identity(
        [canonicalize_phase(item) for item in feature_output.get("phases", []) + timeline_output.get("phases", []) if item.get("id")],
        ["id", "name"],
    )
    capacities = unique_by_identity(capacity_output.get("capacities", []), ["month"])
    roles = unique_by_identity(capacity_output.get("roles", []), ["name"])
    dependencies = unique_by_identity(
        constraint_output.get("dependencies", [])
        + [
            {
                "featureId": feature["id"],
                "dependsOn": feature.get("dependencies", []),
                "confidence": feature.get("confidence", "medium"),
                "provenance": feature.get("provenance", []),
            }
            for feature in features
            if feature.get("dependencies")
        ],
        ["featureId"],
    )

    estimate_profiles = []
    discovered_profile_keys = sorted(
        {
            canonical_profile_key(key)
            for feature in features
            for key in feature.get("estimateProfiles", {}).keys()
            if feature.get("estimateProfiles")
        }
    )
    for key in discovered_profile_keys:
        template = ESTIMATE_PROFILES.get(key)
        estimate_profiles.append(
            {
                "key": key,
                "description": template.description if template else f"Workbook-derived estimate profile {key}",
                "developmentColumn": template.development_column if template else None,
                "qaColumn": template.qa_column if template else None,
                "provenance": [item for feature in features for item in feature.get("provenance", [])][:4],
            }
        )

    planning_horizon = timeline_output.get("planningHorizonMonths")
    if not planning_horizon:
        week_numbers = [
            milestone.get("deadlineWeek", {}).get("month")
            for milestone in milestones
            if isinstance(milestone.get("deadlineWeek"), dict)
        ]
        week_numbers = [item for item in week_numbers if item]
        planning_horizon = max(week_numbers) if week_numbers else None

    clarification_candidates = unique_by_identity(
        [
            normalize_clarification_candidate(item)
            for item in (
                structure_output.get("clarificationCandidates", [])
                + feature_output.get("clarificationCandidates", [])
                + timeline_output.get("clarificationCandidates", [])
                + capacity_output.get("clarificationCandidates", [])
                + constraint_output.get("clarificationCandidates", [])
                + lead_output.get("clarificationCandidates", [])
                + feature_level_clarifications
            )
        ],
        ["fieldPath", "prompt"],
    )
    constraints = unique_by_identity(
        constraint_output.get("constraints", []) + derived_constraints(features, capacities, estimate_profiles),
        ["type", "summary"],
    )

    resolved_fields = {
        "planningHorizonMonths": planning_horizon,
        "productivityFactor": None,
        "monthlyCapacity": capacities if capacities else [],
        "estimateProfile": estimate_profiles[0]["key"] if len(estimate_profiles) == 1 else None,
        "riskAdjustments": {
            "ai": {
                "applyContingency": False,
                "features": {
                    feature["id"]: feature["riskAdjustments"]["ai"]
                    for feature in features
                    if feature.get("riskAdjustments", {}).get("ai")
                },
            }
        },
    }
    unresolved_fields = []
    if not resolved_fields["planningHorizonMonths"]:
        unresolved_fields.append("schedule.planningHorizonMonths")
    if not resolved_fields["estimateProfile"]:
        unresolved_fields.append("schedule.estimateProfile")
    if not capacities:
        unresolved_fields.append("schedule.monthlyCapacity")
    if any(feature.get("riskAdjustments", {}).get("ai") for feature in features):
        unresolved_fields.append("schedule.riskAdjustments.ai.applyContingency")

    coverage_by_agent = {
        node_id: {
            "status": outputs[node_id].get("coverageAssessment", {}).get("status", "low"),
            "reason": outputs[node_id].get("coverageAssessment", {}).get("reason"),
            "usedRegions": outputs[node_id].get("usedRegions", []),
            "expandedSearch": outputs[node_id].get("expandedSearch", []),
            "ignoredRegions": outputs[node_id].get("ignoredRegions", []),
            "missedRiskCandidates": outputs[node_id].get("missedRiskCandidates", []),
        }
        for node_id in ANALYSIS_NODES
        if node_id != "analysis_lead_summary"
    }
    used_region_ids = set().union(*(agent_region_set(agent_output, "usedRegions") for agent_output in coverage_by_agent.values()))
    ignored_region_ids = set().union(*(agent_region_set(agent_output, "ignoredRegions") for agent_output in coverage_by_agent.values()))
    unexplored_risky_regions = sorted(risky_region_ids(inventory_refs) - used_region_ids - ignored_region_ids)

    validation_summary = {
        "blockingIssues": [],
        "warnings": [
            *lead_output.get("warnings", []),
            *[item.get("summary") for item in constraints if item.get("type") == "capacity_missing"],
        ],
    }
    if not features:
        validation_summary["blockingIssues"].append("No feature-like work items were extracted from the workbook.")
    missing_estimates = [feature["id"] for feature in features if not feature.get("estimateProfiles")]
    if missing_estimates:
        validation_summary["blockingIssues"].append(
            f"Features without effort profiles were extracted: {', '.join(missing_estimates)}."
        )
    if unresolved_fields:
        validation_summary["warnings"].append("Clarification is required before the first solve.")
    low_coverage_agents = [
        node_id
        for node_id, coverage in coverage_by_agent.items()
        if coverage_rank(coverage.get("status", "low")) < coverage_rank("high")
    ]
    if low_coverage_agents:
        validation_summary["blockingIssues"].append(
            "Coverage is incomplete for focused agents: " + ", ".join(sorted(low_coverage_agents)) + "."
        )
    if unexplored_risky_regions:
        validation_summary["blockingIssues"].append(
            "Potentially important workbook regions remain unexplained: " + ", ".join(unexplored_risky_regions) + "."
        )

    referenced_ids = referenced_feature_ids(milestones, dependencies)
    unresolved_references = sorted(
        reference_id
        for reference_id in referenced_ids
        if reference_id not in known_feature_ids and not explicitly_external_reference(reference_id)
    )
    if unresolved_references:
        validation_summary["blockingIssues"].append(
            "Referenced work item ids did not resolve to extracted features: " + ", ".join(unresolved_references) + "."
        )

    if inventory_refs.get("unexplainedAreas"):
        validation_summary["warnings"].append("Inventory recorded suspicious unexplained workbook areas that require explicit coverage or justification.")

    completeness_gate_status = "ready_to_solve" if not validation_summary["blockingIssues"] and not unresolved_fields else "needs_confirmation"

    planning_signals = {
        "scenarioId": args.scenario_id,
        "sourceArtifacts": [
            "intake/workbook-manifest.json",
            f"scenarios/{args.scenario_id}/normalized/workbook-profile.json",
            f"scenarios/{args.scenario_id}/normalized/inventory-refs.json",
        ],
        "workbookProfile": workbook_profile,
        "inventoryRefs": inventory_refs,
        "planningFacts": {
            "features": features,
            "milestones": milestones,
            "capacities": capacities,
            "roles": roles,
            "phases": phases,
            "dependencies": dependencies,
            "deadlines": timeline_output.get("deadlines", []),
            "constraints": constraints,
            "assumptions": constraint_output.get("assumptions", []),
            "prioritySignals": feature_output.get("prioritySignals", []),
            "riskSignals": constraint_output.get("riskSignals", []),
            "statusSignals": feature_output.get("statusSignals", []),
            "calendarConstraints": timeline_output.get("calendarConstraints", []),
            "estimateProfiles": estimate_profiles,
            "riskAdjustments": resolved_fields["riskAdjustments"],
        },
        "resolvedFields": resolved_fields,
        "unresolvedFields": unresolved_fields,
        "clarificationCandidates": clarification_candidates,
        "validationSummary": validation_summary,
        "analysisCoverage": coverage_by_agent,
        "completenessGate": {
            "status": completeness_gate_status,
            "unexploredRiskRegions": unexplored_risky_regions,
            "unresolvedReferences": unresolved_references,
        },
        "analysisSummary": {
            "structure": structure_output.get("summary"),
            "lead": lead_output.get("summary"),
        },
        "reviewNotes": unique_by_identity(
            [
                {"message": message}
                for message in (
                    structure_output.get("reviewNotes", [])
                    + feature_output.get("reviewNotes", [])
                    + timeline_output.get("reviewNotes", [])
                    + capacity_output.get("reviewNotes", [])
                    + constraint_output.get("reviewNotes", [])
                    + lead_output.get("reviewNotes", [])
                )
                if message
            ],
            ["message"],
        ),
    }

    output_path = scenario_dir / "planning-signals.json"
    write_json(output_path, planning_signals)
    touch_generated_artifact(run_dir, output_path)

    next_action = "Build candidate model and clarification bundle"
    latest_summary = "Focused analysis agent outputs were merged into canonical planning signals."
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary=latest_summary,
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary=latest_summary,
        active_scenario_id=args.scenario_id,
        resume_hint="Run build_candidate_model next.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action="Build candidate model",
        latest_summary=latest_summary,
    )
    ensure_attractor_stage_artifacts(
        run_dir,
        stage_id=args.stage_id,
        command="merge_planning_signals.py",
        inputs={"runDir": str(run_dir), "scenarioId": args.scenario_id},
        summary=latest_summary,
        state="success",
        outputs={"planningSignalsPath": relative_to_run(run_dir, output_path)},
    )

    print(f"PLANNING_SIGNALS={output_path}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
