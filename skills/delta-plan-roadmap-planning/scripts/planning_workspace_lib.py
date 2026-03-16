#!/usr/bin/env python3
"""
Shared helpers for the DeltaPlan planning workspace bundle.

AICODE-NOTE: The run workspace files are the durable source of truth for planning execution; these helpers keep the run and scenario metadata synchronized across deterministic stages.
"""

from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_VERSION = "1.0"
RUNS_SUBDIR = Path(".codex-artifacts/delta-plan/runs")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    collapsed = re.sub(r"-{2,}", "-", normalized).strip("-")
    return collapsed or "delta-plan-run"


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n")


def relative_to_run(run_dir: Path, target: Path) -> str:
    return str(target.resolve().relative_to(run_dir.resolve()))


def classify_input(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return "excel_workbook"
    if suffix == ".csv":
        return "csv"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt":
        return "text"
    return "unknown"


def choose_primary_input(source_paths: list[Path]) -> Path:
    ranked = sorted(
        source_paths,
        key=lambda item: (
            0 if item.suffix.lower() in {".xlsx", ".xlsm"} else 1,
            0 if item.suffix.lower() == ".csv" else 1,
            item.name.lower(),
        ),
    )
    return ranked[0]


def ensure_versioned_copy(destination_dir: Path, source_path: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    candidate = destination_dir / source_path.name
    if not candidate.exists():
        shutil.copy2(source_path, candidate)
        return candidate

    stem = source_path.stem
    suffix = source_path.suffix
    index = 2
    while True:
        candidate = destination_dir / f"{stem}-v{index}{suffix}"
        if not candidate.exists():
            shutil.copy2(source_path, candidate)
            return candidate
        index += 1


def run_manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def run_status_path(run_dir: Path) -> Path:
    return run_dir / "status.json"


def run_checkpoint_path(run_dir: Path) -> Path:
    return run_dir / "checkpoint.json"


def scenario_dir(run_dir: Path, scenario_id: str) -> Path:
    return run_dir / "scenarios" / scenario_id


def scenario_manifest_path(run_dir: Path, scenario_id: str) -> Path:
    return scenario_dir(run_dir, scenario_id) / "scenario-manifest.json"


def scenario_status_path(run_dir: Path, scenario_id: str) -> Path:
    return scenario_dir(run_dir, scenario_id) / "scenario-status.json"


def load_run_manifest(run_dir: Path) -> dict[str, Any]:
    return read_json(run_manifest_path(run_dir), default={})


def load_run_status(run_dir: Path) -> dict[str, Any]:
    return read_json(run_status_path(run_dir), default={})


def load_scenario_manifest(run_dir: Path, scenario_id: str) -> dict[str, Any]:
    return read_json(scenario_manifest_path(run_dir, scenario_id), default={})


def load_scenario_status(run_dir: Path, scenario_id: str) -> dict[str, Any]:
    return read_json(scenario_status_path(run_dir, scenario_id), default={})


def touch_generated_artifact(run_dir: Path, artifact_path: Path) -> None:
    manifest = load_run_manifest(run_dir)
    generated = manifest.setdefault("generatedArtifactPaths", [])
    artifact_ref = relative_to_run(run_dir, artifact_path)
    if artifact_ref not in generated:
        generated.append(artifact_ref)
        generated.sort()
    write_json(run_manifest_path(run_dir), manifest)


def update_run_status(
    run_dir: Path,
    *,
    state: str,
    current_stage: str,
    next_action: str,
    latest_summary: str,
    active_scenario_id: str | None = None,
) -> None:
    status = load_run_status(run_dir)
    if active_scenario_id is not None:
        status["active_scenario_id"] = active_scenario_id
    status.update(
        {
            "state": state,
            "current_stage": current_stage,
            "next_action": next_action,
            "latest_summary": latest_summary,
        }
    )
    write_json(run_status_path(run_dir), status)


def update_checkpoint(
    run_dir: Path,
    *,
    state: str,
    current_stage: str,
    next_action: str,
    latest_summary: str,
    active_scenario_id: str,
    resume_hint: str,
) -> None:
    checkpoint = read_json(run_checkpoint_path(run_dir), default={})
    checkpoint.update(
        {
            "runId": load_run_manifest(run_dir).get("runId"),
            "activeScenarioId": active_scenario_id,
            "state": state,
            "currentStage": current_stage,
            "nextAction": next_action,
            "latestSummary": latest_summary,
            "resumeHint": resume_hint,
            "checkpointedAt": utc_now(),
        }
    )
    write_json(run_checkpoint_path(run_dir), checkpoint)


def update_scenario_status(
    run_dir: Path,
    scenario_id: str,
    *,
    state: str,
    current_stage: str,
    next_action: str,
    latest_summary: str,
    latest_clarification_request_path: str | None = None,
    latest_solve_request_path: str | None = None,
    latest_solve_response_path: str | None = None,
    latest_output_paths: dict[str, str] | None = None,
) -> None:
    status = load_scenario_status(run_dir, scenario_id)
    status.update(
        {
            "state": state,
            "scenarioId": scenario_id,
            "scenarioSlug": load_scenario_manifest(run_dir, scenario_id).get("scenarioSlug", scenario_id),
            "currentStage": current_stage,
            "nextAction": next_action,
            "latestSummary": latest_summary,
            "latestClarificationRequestPath": latest_clarification_request_path,
            "latestSolveRequestPath": latest_solve_request_path,
            "latestSolveResponsePath": latest_solve_response_path,
            "latestOutputPaths": latest_output_paths or {},
        }
    )
    write_json(scenario_status_path(run_dir, scenario_id), status)


def update_scenario_manifest(run_dir: Path, scenario_id: str, **changes: Any) -> None:
    manifest = load_scenario_manifest(run_dir, scenario_id)
    manifest.update(changes)
    write_json(scenario_manifest_path(run_dir, scenario_id), manifest)


def ensure_attractor_stage_artifacts(
    run_dir: Path,
    *,
    stage_id: str,
    command: str,
    inputs: dict[str, Any],
    summary: str,
    state: str,
    outputs: dict[str, Any] | None = None,
) -> None:
    attractor_root = run_dir / "attractor"
    stage_dir = attractor_root / stage_id
    attractor_root.mkdir(parents=True, exist_ok=True)
    (attractor_root / "context").mkdir(parents=True, exist_ok=True)

    run_manifest = read_json(attractor_root / "run-manifest.json", default={"stages": []})
    stages = set(run_manifest.get("stages", []))
    stages.add(stage_id)
    run_manifest["stages"] = sorted(stages)
    run_manifest["updatedAt"] = utc_now()
    write_json(attractor_root / "run-manifest.json", run_manifest)

    write_json(stage_dir / "active-tools.json", [{"command": command}])
    write_json(stage_dir / "context-inputs.json", inputs)
    write_text(stage_dir / "prompt.md", command)
    write_text(stage_dir / "response.md", summary)
    write_json(
        stage_dir / "status.json",
        {
            "stageId": stage_id,
            "state": state,
            "updatedAt": utc_now(),
            "summary": summary,
            "outputs": outputs or {},
        },
    )
    write_json(
        attractor_root / "context" / "latest.json",
        {
            "stageId": stage_id,
            "updatedAt": utc_now(),
            "inputs": inputs,
            "outputs": outputs or {},
        },
    )


def next_output_prefix(outputs_dir: Path, scenario_slug: str) -> str:
    existing = sorted(outputs_dir.glob(f"v*_{scenario_slug}-report.html"))
    if not existing:
        return "v1"
    highest = 0
    for item in existing:
        match = re.match(r"v(\d+)_", item.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"v{highest + 1}"


def parse_field_path(field_path: str) -> list[str]:
    if not field_path.startswith("schedule."):
        raise ValueError(f"Unsupported field path: {field_path}")
    path = field_path[len("schedule.") :]
    segments: list[str] = []
    buffer = ""
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            if buffer:
                segments.append(buffer)
                buffer = ""
            index += 1
            continue
        if char == "[":
            if buffer:
                segments.append(buffer)
                buffer = ""
            closing = path.index("]", index)
            segments.append(path[index + 1 : closing])
            index = closing + 1
            continue
        buffer += char
        index += 1
    if buffer:
        segments.append(buffer)
    return segments


def assign_field(payload: dict[str, Any], field_path: str, value: Any) -> None:
    cursor: Any = payload.setdefault("schedule", {})
    segments = parse_field_path(field_path)
    for segment in segments[:-1]:
        if segment not in cursor or cursor[segment] is None:
            cursor[segment] = {}
        cursor = cursor[segment]
    cursor[segments[-1]] = value


def preferred_planning_signals_path(normalized_dir: Path) -> Path:
    resolved_path = normalized_dir / "planning-signals-resolved.json"
    if resolved_path.exists():
        return resolved_path
    return normalized_dir / "planning-signals.json"


@dataclass
class EstimateProfile:
    key: str
    development_column: str | None
    qa_column: str | None
    description: str


ESTIMATE_PROFILES = {
    "regular": EstimateProfile(
        key="regular",
        development_column=None,
        qa_column=None,
        description="Regular delivery estimate profile",
    ),
    "ai": EstimateProfile(
        key="ai",
        development_column=None,
        qa_column=None,
        description="AI-assisted estimate profile",
    ),
}
