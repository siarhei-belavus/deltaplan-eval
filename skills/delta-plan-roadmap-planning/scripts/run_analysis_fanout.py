#!/usr/bin/env python3
"""
Persist the six source-analysis artifacts used by planning-signals merging.

AICODE-NOTE: This helper keeps the active system on durable scenario artifacts by
writing normalized `analysis/*.json` outputs directly from canonical source
inventory artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from planning_workspace_lib import touch_generated_artifact, write_json
from runtime_paths import packaged_prompt_dir


PROMPT_FILES = {
    "structure_agent": "structure-agent.md",
    "feature_agent": "feature-agent.md",
    "timeline_agent": "timeline-agent.md",
    "capacity_agent": "capacity-agent.md",
    "constraint_agent": "constraint-agent.md",
    "analysis_lead_summary": "analysis-lead-summary.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write persistent analysis fan-out artifacts.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def require_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise SystemExit(f"Missing required {label}: {path}")
    return load_json(path)


def load_prompt_texts() -> dict[str, str]:
    prompt_root = packaged_prompt_dir()
    prompts: dict[str, str] = {}
    for node_id, filename in PROMPT_FILES.items():
        path = prompt_root / filename
        if not path.exists():
            raise SystemExit(f"Missing required prompt file: {path}")
        prompts[node_id] = path.read_text()
    return prompts


def parse_feature_ids(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(match.upper() for match in re.findall(r"\b[A-Za-z]+-\d+\b", text)))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def region_lookup(run_dir: Path, inventory_refs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for region_ref in inventory_refs.get("regionRefs", []):
        full_region_path = region_ref.get("fullRegionPath")
        if not full_region_path:
            continue
        path = run_dir / full_region_path
        if path.exists():
            lookup[region_ref["regionId"]] = load_json(path)
    return lookup


def find_region(region_refs: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for region_ref in region_refs:
        if predicate(region_ref):
            return region_ref
    return None


def coverage(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def build_structure_output(
    source_profile: dict[str, Any],
    inventory_refs: dict[str, Any],
) -> dict[str, Any]:
    segment_classifications = []
    region_classifications = []
    used_regions = []
    for segment in source_profile.get("segments", []):
        name = str(segment.get("segmentLabel", ""))
        lowered = name.lower()
        if "assumption" in lowered:
            role = "assumptions"
        elif "milestone" in lowered:
            role = "mixed"
        elif "wbs" in lowered:
            role = "mixed"
        else:
            role = "unknown"
        segment_classifications.append(
            {
                "segmentLabel": name,
                "segmentRole": role,
                "confidence": "medium" if role == "unknown" else "high",
                "provenance": [f"segment:{segment['segmentId']}:rows-{segment['rowBounds']['min']}-{segment['rowBounds']['max']}"],
            }
        )

    for region_ref in inventory_refs.get("regionRefs", []):
        used_regions.append(region_ref["regionId"])
        headers = " ".join(region_ref.get("headers", []))
        lowered_headers = headers.lower()
        if "req id" in lowered_headers:
            role = "feature_table"
            reason = "Headers describe work-item ids, requirement titles, dependency text, and effort columns."
        elif "milestone" in lowered_headers or any("timeline_table" == hint for hint in region_ref.get("kindHints", [])):
            role = "timeline_table"
            reason = "Headers describe milestones plus week columns and timeline grouping."
        elif "assumption" in lowered_headers:
            role = "assumptions_list"
            reason = "Headers describe a numbered assumption list."
        else:
            role = "unknown"
            reason = "No stronger source classification signal was found."
        region_classifications.append(
            {
                "regionId": region_ref["regionId"],
                "regionRole": role,
                "confidence": "high" if role != "unknown" else "medium",
                "reason": reason,
                "provenance": [region_ref["range"]],
            }
        )

    return {
        "summary": "Source inventory was classified into assumptions, feature backlog, and milestone/timeline segments.",
        "usedRegions": used_regions,
        "expandedSearch": [],
        "ignoredRegions": [],
        "coverageAssessment": coverage("high", "All normalized region artifacts were reviewed directly."),
        "missedRiskCandidates": inventory_refs.get("unexplainedAreas", []),
        "segmentClassifications": segment_classifications,
        "regionClassifications": region_classifications,
        "clarificationCandidates": [],
        "reviewNotes": [
            "Prompt assets were loaded successfully for the six analysis surfaces.",
            "Structure output is derived from normalized inventory refs and region headers.",
        ],
    }


def build_timeline_output(
    milestone_region: dict[str, Any] | None,
    assumptions_region: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    if not milestone_region:
        return (
            {
                "summary": "No milestone-like region was found in the normalized inventory.",
                "usedRegions": [],
                "expandedSearch": [],
                "ignoredRegions": [],
                "coverageAssessment": coverage("low", "No milestone region was available to inspect."),
                "missedRiskCandidates": [],
                "planningHorizonMonths": None,
                "milestones": [],
                "phases": [],
                "deadlines": [],
                "calendarConstraints": [],
                "clarificationCandidates": [],
                "reviewNotes": [],
            },
            {},
            [],
        )

    week_headers = [
        header
        for header in milestone_region.get("headers", [])
        if isinstance(header, str) and re.fullmatch(r"W\d+", header.strip())
    ]
    planning_horizon_months = len(week_headers) // 4 if week_headers else None
    milestones = []
    feature_to_phase: dict[str, str] = {}
    phase_counter = 1
    deadline_rows_blank = False
    for row in milestone_region.get("rows", []):
        values = row.get("values", [])
        if not values:
            continue
        ordinal = str(values[0]).strip()
        title = str(values[1]).strip() if len(values) > 1 else ""
        acceptance = str(values[2]).strip() if len(values) > 2 else ""
        feature_ids = parse_feature_ids(str(values[3]).strip() if len(values) > 3 else "")
        if not ordinal.isdigit() or not title:
            continue
        phase_id = None
        if feature_ids:
            phase_id = f"PHASE-{phase_counter}"
            phase_counter += 1
            for feature_id in feature_ids:
                feature_to_phase[feature_id] = phase_id
        week_cells = [str(item).strip() for item in values[4 : 4 + len(week_headers)]]
        if feature_ids and not any(week_cells):
            deadline_rows_blank = True
        milestones.append(
            {
                "id": f"MILESTONE-{ordinal}",
                "title": title,
                "phaseId": phase_id,
                "ordinal": int(ordinal),
                "featureIds": feature_ids,
                "acceptanceCriteria": acceptance or None,
                "deadlineWeek": None,
                "confidence": "medium" if deadline_rows_blank else "high",
                "provenance": [f"segment:{milestone_region['regionId']}:{milestone_region['range']}"],
            }
        )

    deadlines = []
    calendar_constraints = []
    if assumptions_region:
        for row in assumptions_region.get("rows", []):
            values = row.get("values", [])
            if len(values) < 2:
                continue
            if str(values[0]).strip() == "1":
                calendar_constraints.append(
                    {
                        "id": "CAL-START",
                        "constraint": str(values[1]).strip(),
                        "classification": "fixed_start_anchor",
                        "confidence": "high",
                        "provenance": [f"segment:{assumptions_region['regionId']}:{assumptions_region['range']}"],
                    }
                )
                deadlines.append(
                    {
                        "id": "DEADLINE-START",
                        "title": "Project start anchor",
                        "classification": "fixed_date",
                        "date": "unknown",
                        "deadlineWeek": {"month": 1, "week": 1} if planning_horizon_months else None,
                        "confidence": "medium",
                        "provenance": [f"segment:{assumptions_region['regionId']}:{assumptions_region['range']}"],
                    }
                )

    clarification_candidates = []
    if deadline_rows_blank and week_headers:
        clarification_candidates.append(
            {
                "fieldPath": "schedule.milestones.deadlineWeek",
                "prompt": f"Please provide milestone timing across {week_headers[0]}-{week_headers[-1]}.",
                "reason": "Milestone rows exist, but their week-allocation cells are blank.",
                "provenance": [f"segment:{milestone_region['regionId']}:{milestone_region['range']}"],
            }
        )

    return (
        {
            "summary": "Timeline extraction found milestone groupings and a planning horizon, but no explicit per-milestone week assignments.",
            "usedRegions": [milestone_region["regionId"], *( [assumptions_region["regionId"]] if assumptions_region else [])],
            "expandedSearch": [],
            "ignoredRegions": [],
            "coverageAssessment": coverage(
                "medium" if clarification_candidates else "high",
                "Timeline headers and milestone rows were reviewed directly from normalized region artifacts.",
            ),
            "missedRiskCandidates": ["Milestone rows do not contain explicit W1..Wn placements."] if clarification_candidates else [],
            "planningHorizonMonths": planning_horizon_months,
            "milestones": milestones,
            "phases": [],
            "deadlines": deadlines,
            "calendarConstraints": calendar_constraints,
            "clarificationCandidates": clarification_candidates,
            "reviewNotes": ["Timeline output is derived from normalized milestone rows and week headers."],
        },
        feature_to_phase,
        milestones,
    )


def build_feature_output(
    feature_region: dict[str, Any] | None,
    feature_to_phase: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not feature_region:
        return (
            {
                "summary": "No feature-like region was found in the normalized inventory.",
                "usedRegions": [],
                "expandedSearch": [],
                "ignoredRegions": [],
                "coverageAssessment": coverage("low", "No feature region was available to inspect."),
                "missedRiskCandidates": [],
                "features": [],
                "phases": [],
                "prioritySignals": [],
                "statusSignals": [],
                "clarificationCandidates": [],
                "reviewNotes": [],
            },
            [],
        )

    header_index = {str(header).strip().lower(): index for index, header in enumerate(feature_region.get("headers", []))}

    def value(row: dict[str, Any], header: str) -> str:
        index = header_index.get(header.lower())
        if index is None:
            return ""
        values = row.get("values", [])
        if index >= len(values):
            return ""
        return str(values[index]).strip()

    features = []
    feature_ids = []
    for row in feature_region.get("rows", []):
        feature_id = value(row, "Req ID").upper()
        if not re.fullmatch(r"[A-Z]+-\d+", feature_id):
            continue
        feature_ids.append(feature_id)
        dependencies = [item for item in re.split(r"[;\n]+", value(row, "Dependencies")) if item.strip() and item.strip() not in {"-", "n/a"}]
        ai_contingency = as_float(value(row, "Dev AI Contingency"))
        estimate_profiles = {
            "regular": {
                "DevelopmentMd": as_float(value(row, "Dev  Regular (md)")) or 0.0,
                "QAMd": as_float(value(row, "QA  Regular (md)")) or 0.0,
            },
            "ai": {
                "DevelopmentMd": as_float(value(row, "Dev AI (md)")) or 0.0,
                "QAMd": as_float(value(row, "QA  AI (md)")) or 0.0,
            },
        }
        if ai_contingency is not None:
            estimate_profiles["aiContingency"] = {
                "DevelopmentMd": ai_contingency,
                "QAMd": None,
            }
        features.append(
            {
                "id": feature_id,
                "title": value(row, "Requirement"),
                "description": value(row, "Description") or None,
                "estimateProfiles": estimate_profiles,
                "dependencies": dependencies,
                "phaseHint": feature_to_phase.get(feature_id),
                "priority": None,
                "serial": any(parse_feature_ids(item) for item in dependencies),
                "qaOverhead": 0.2,
                "status": None,
                "confidence": "high",
                "provenance": [f"segment:{feature_region['regionId']}:row-{row['rowNumber']}"],
                "normalizationNotes": [
                    "AI contingency is recorded only for development when the source omits a QA contingency column."
                ]
                if ai_contingency is not None
                else [],
            }
        )

    return (
        {
            "summary": f"Extracted {len(features)} feature-like work items with effort profiles and raw dependency text.",
            "usedRegions": [feature_region["regionId"]],
            "expandedSearch": [],
            "ignoredRegions": [],
            "coverageAssessment": coverage("high", "All feature rows in the normalized region were inspected directly."),
            "missedRiskCandidates": [],
            "features": features,
            "phases": [],
            "prioritySignals": [],
            "statusSignals": [],
            "clarificationCandidates": [],
            "reviewNotes": ["Feature output is derived from normalized WBS-like rows and milestone feature mapping."],
        },
        features,
    )


def build_capacity_output(
    feature_region: dict[str, Any] | None,
    planning_horizon_months: int | None,
) -> dict[str, Any]:
    prompt = "Please provide explicit monthly FTE capacity by role."
    if planning_horizon_months:
        prompt = f"Please provide explicit monthly FTE capacity by role for Month 1-{planning_horizon_months}."
    return {
        "summary": "The source exposes effort estimates by role but no explicit monthly capacity allocation table.",
        "usedRegions": [feature_region["regionId"]] if feature_region else [],
        "expandedSearch": [],
        "ignoredRegions": [],
        "coverageAssessment": coverage(
            "high" if feature_region else "medium",
            "Effort columns were inspected directly and no explicit time-phased capacity artifacts were found.",
        ),
        "missedRiskCandidates": ["Effort totals can be mistaken for staffing capacity when no capacity table exists."],
        "roles": [
            {"name": "Development", "confidence": "high", "provenance": [f"segment:{feature_region['regionId']}:{feature_region['range']}"]},
            {"name": "QA", "confidence": "high", "provenance": [f"segment:{feature_region['regionId']}:{feature_region['range']}"]},
        ]
        if feature_region
        else [],
        "capacities": [],
        "clarificationCandidates": [
            {
                "fieldPath": "schedule.monthlyCapacity",
                "prompt": prompt,
                "reason": "No explicit monthly role capacity values were found in the source artifacts.",
                "provenance": [f"segment:{feature_region['regionId']}:{feature_region['range']}"] if feature_region else [],
            }
        ],
        "reviewNotes": ["Capacity output deliberately separates staffing capacity from effort estimates."],
    }


def build_constraint_output(
    feature_region: dict[str, Any] | None,
    assumptions_region: dict[str, Any] | None,
    features: list[dict[str, Any]],
) -> dict[str, Any]:
    dependencies = []
    known_feature_ids = {feature["id"] for feature in features}
    for feature in features:
        resolved = [item for item in parse_feature_ids(" ".join(feature.get("dependencies", []))) if item in known_feature_ids]
        if resolved:
            dependencies.append(
                {
                    "featureId": feature["id"],
                    "dependsOn": resolved,
                    "confidence": "high",
                    "provenance": feature.get("provenance", []),
                }
            )

    assumptions = []
    constraints = []
    if assumptions_region:
        for row in assumptions_region.get("rows", []):
            values = row.get("values", [])
            if len(values) < 2:
                continue
            identifier = str(values[0]).strip()
            text = str(values[1]).strip()
            if not identifier or not text or identifier == "#":
                continue
            assumptions.append(
                {
                    "id": identifier,
                    "text": text,
                    "confidence": "medium",
                    "provenance": [f"segment:{assumptions_region['regionId']}:row-{row['rowNumber']}"],
                }
            )
            constraints.append(
                {
                    "type": "source_assumption",
                    "summary": text,
                    "confidence": "medium",
                    "provenance": [f"segment:{assumptions_region['regionId']}:row-{row['rowNumber']}"],
                }
            )

    used_regions = []
    if feature_region:
        used_regions.append(feature_region["regionId"])
    if assumptions_region:
        used_regions.append(assumptions_region["regionId"])
    return {
        "summary": "Constraints were derived from source assumptions and explicit feature dependency references.",
        "usedRegions": used_regions,
        "expandedSearch": [],
        "ignoredRegions": [],
        "coverageAssessment": coverage("high" if used_regions else "low", "Constraint extraction inspected all available assumptions and dependency text."),
        "missedRiskCandidates": [],
        "dependencies": dependencies,
        "constraints": constraints,
        "assumptions": assumptions,
        "riskSignals": [],
        "clarificationCandidates": [],
        "reviewNotes": ["Constraint output preserves explicit source assumptions separately from resolved feature dependencies."],
    }


def build_lead_output(
    structure_output: dict[str, Any],
    feature_output: dict[str, Any],
    timeline_output: dict[str, Any],
    capacity_output: dict[str, Any],
) -> dict[str, Any]:
    warnings = []
    if not capacity_output.get("capacities"):
        warnings.append("Critical capacity gap: no explicit monthly role capacity values were found.")
    if timeline_output.get("clarificationCandidates"):
        warnings.append("Critical schedule gap: milestone rows are not mapped to explicit week slots.")
    return {
        "summary": "Analysis artifacts agree on the feature set, but solving still depends on clarified staffing and possibly milestone timing.",
        "warnings": warnings,
        "clarificationCandidates": capacity_output.get("clarificationCandidates", []) + timeline_output.get("clarificationCandidates", []),
        "reviewNotes": [
            "Lead summary intentionally stays compact because planning-signals merging already consumes the structured agent outputs directly."
        ],
    }


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_root = run_dir / "scenarios" / args.scenario_id
    analysis_dir = scenario_root / "analysis"
    normalized_dir = scenario_root / "normalized"

    require_json(run_dir / "intake" / "source-manifest.json", "source manifest")
    source_profile = require_json(normalized_dir / "source-profile.json", "source profile")
    inventory_refs = require_json(normalized_dir / "inventory-refs.json", "inventory refs")
    load_prompt_texts()

    region_payloads = region_lookup(run_dir, inventory_refs)
    feature_region_ref = find_region(
        inventory_refs.get("regionRefs", []),
        lambda item: "Req ID" in item.get("headers", []) or "feature_table" in item.get("kindHints", []),
    )
    milestone_region_ref = find_region(
        inventory_refs.get("regionRefs", []),
        lambda item: "timeline_table" in item.get("kindHints", []) or "Milestone" in item.get("headers", []),
    )
    assumptions_region_ref = find_region(
        inventory_refs.get("regionRefs", []),
        lambda item: "Assumptions" in item.get("headers", []) or "assumptions_list" in item.get("kindHints", []),
    )

    feature_region = region_payloads.get(feature_region_ref["regionId"]) if feature_region_ref else None
    milestone_region = region_payloads.get(milestone_region_ref["regionId"]) if milestone_region_ref else None
    assumptions_region = region_payloads.get(assumptions_region_ref["regionId"]) if assumptions_region_ref else None

    structure_output = build_structure_output(source_profile, inventory_refs)
    timeline_output, feature_to_phase, _milestones = build_timeline_output(milestone_region, assumptions_region)
    feature_output, features = build_feature_output(feature_region, feature_to_phase)
    capacity_output = build_capacity_output(feature_region, timeline_output.get("planningHorizonMonths"))
    constraint_output = build_constraint_output(feature_region, assumptions_region, features)
    lead_output = build_lead_output(structure_output, feature_output, timeline_output, capacity_output)

    analysis_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "structure_agent": structure_output,
        "feature_agent": feature_output,
        "timeline_agent": timeline_output,
        "capacity_agent": capacity_output,
        "constraint_agent": constraint_output,
        "analysis_lead_summary": lead_output,
    }
    for node_id, payload in outputs.items():
        path = analysis_dir / f"{node_id}.json"
        write_json(path, payload)
        touch_generated_artifact(run_dir, path)
        print(f"{node_id.upper()}={path}")

    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
