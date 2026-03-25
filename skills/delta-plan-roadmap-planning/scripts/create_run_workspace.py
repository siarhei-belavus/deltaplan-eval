#!/usr/bin/env python3
"""Create or initialize a DeltaPlan planning run workspace."""

from __future__ import annotations

import argparse
from pathlib import Path

from planning_workspace_lib import (
    RUNS_SUBDIR,
    WORKSPACE_VERSION,
    choose_primary_input,
    classify_input,
    ensure_versioned_copy,
    generic_next_action,
    generic_resume_hint,
    parser_name_for_kind,
    relative_to_run,
    run_manifest_path,
    scenario_dir,
    scenario_manifest_path,
    scenario_status_path,
    slugify,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_manifest,
    update_scenario_status,
    utc_now,
    utc_stamp,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a DeltaPlan planning run workspace.")
    parser.add_argument("--workspace-root", help="Workspace root used for default run placement.")
    parser.add_argument("--run-dir", help="Explicit run directory.")
    parser.add_argument("--input", action="append", required=True, help="Input artifact path. Repeatable.")
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--scenario-label", default="Baseline")
    parser.add_argument("--stage-id", default="start_run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_paths = [Path(item).resolve() for item in args.input]
    missing = [str(item) for item in source_paths if not item.exists()]
    if missing:
        raise SystemExit(f"Missing input artifact(s): {', '.join(missing)}")

    primary_input = choose_primary_input(source_paths)
    primary_kind = classify_input(primary_input)
    scenario_slug = args.scenario_id
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
    else:
        workspace_root = Path(args.workspace_root or Path.cwd()).resolve()
        run_dir = workspace_root / RUNS_SUBDIR / f"{utc_stamp()}-{slugify(primary_input.stem)}"

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    (run_dir / "intake").mkdir(exist_ok=True)
    (run_dir / "debug").mkdir(exist_ok=True)
    scenario_root = scenario_dir(run_dir, args.scenario_id)
    for subdir in ["normalized", "analysis", "clarifications", "solver", "outputs"]:
        (scenario_root / subdir).mkdir(parents=True, exist_ok=True)

    copied_sources = []
    for index, source_path in enumerate(source_paths, start=1):
        copied = ensure_versioned_copy(run_dir / "inputs", source_path)
        source_kind = classify_input(source_path)
        copied_sources.append(
            {
                "sourceId": f"source-{index}",
                "originalPath": str(source_path),
                "copiedPath": relative_to_run(run_dir, copied),
                "kind": source_kind,
                "parser": parser_name_for_kind(source_kind),
                "isPrimary": source_path == primary_input,
            }
        )
        touch_generated_artifact(run_dir, copied)

    primary_source = next(item for item in copied_sources if item["isPrimary"])
    run_manifest = {
        "runId": run_dir.name,
        "workspaceVersion": WORKSPACE_VERSION,
        "createdAt": utc_now(),
        "activeScenarioId": args.scenario_id,
        "primarySourceId": primary_source["sourceId"],
        "primaryInputArtifact": primary_source["copiedPath"],
        "sourceKind": primary_kind,
        "sourceFiles": copied_sources,
        "generatedArtifactPaths": sorted(
            relative_to_run(run_dir, path)
            for path in [run_dir / "manifest.json", run_dir / "checkpoint.json", run_dir / "status.json"]
        ),
        "scenarioChildren": [],
    }
    write_json(run_manifest_path(run_dir), run_manifest)

    next_action = generic_next_action(primary_kind)
    resume_hint = generic_resume_hint(primary_kind)
    write_json(
        scenario_manifest_path(run_dir, args.scenario_id),
        {
            "scenarioId": args.scenario_id,
            "scenarioSlug": scenario_slug,
            "scenarioLabel": args.scenario_label,
            "scenarioType": "baseline",
            "parentScenarioId": None,
            "createdAt": utc_now(),
            "defaultsApplied": [],
            "validationSummary": None,
            "latestSolveRequestPath": None,
            "latestSolveResponsePath": None,
            "latestOutputVersion": None,
            "latestOutputPaths": {},
        },
    )
    write_json(
        scenario_status_path(run_dir, args.scenario_id),
        {
            "state": "running",
            "scenarioId": args.scenario_id,
            "scenarioSlug": scenario_slug,
            "currentStage": args.stage_id,
            "nextAction": next_action,
            "latestSummary": "Run workspace initialized.",
            "latestClarificationRequestPath": None,
            "latestSolveRequestPath": None,
            "latestSolveResponsePath": None,
            "latestOutputPaths": {},
        },
    )
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Run workspace initialized.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Run workspace initialized.",
        active_scenario_id=args.scenario_id,
        resume_hint=resume_hint,
    )
    update_scenario_manifest(
        run_dir,
        args.scenario_id,
        latestSolveRequestPath=None,
        latestSolveResponsePath=None,
        latestOutputVersion=None,
        latestOutputPaths={},
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Run workspace initialized and source artifacts copied.",
    )

    print(f"RUN_DIR={run_dir}")
    print(f"ACTIVE_SCENARIO={args.scenario_id}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
