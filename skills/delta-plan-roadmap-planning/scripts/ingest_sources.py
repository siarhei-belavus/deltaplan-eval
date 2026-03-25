#!/usr/bin/env python3
"""Classify copied source artifacts and record parser routing."""

from __future__ import annotations

import argparse
from pathlib import Path

from planning_workspace_lib import (
    classify_input,
    generic_next_action,
    generic_resume_hint,
    load_run_manifest,
    parser_name_for_kind,
    relative_to_run,
    source_manifest_path,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_status,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify source artifacts and parser routes.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="ingest_sources")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    run_manifest = load_run_manifest(run_dir)
    source_files = run_manifest.get("sourceFiles", [])
    if not source_files:
        raise SystemExit("No source files recorded in manifest.json")

    records = []
    primary_kind = run_manifest.get("sourceKind")
    for source_file in source_files:
        kind = source_file.get("kind") or classify_input(Path(source_file["copiedPath"]))
        parser_name = parser_name_for_kind(kind)
        route = f"extract_{parser_name}_artifacts" if parser_name != "unknown" else "unsupported_source"
        records.append(
            {
                "sourceId": source_file.get("sourceId"),
                "copiedPath": source_file["copiedPath"],
                "kind": kind,
                "parser": parser_name,
                "route": route,
                "supported": parser_name != "unknown",
                "isPrimary": bool(source_file.get("isPrimary")),
            }
        )
        if source_file.get("isPrimary"):
            primary_kind = kind

    manifest_path = source_manifest_path(run_dir)
    write_json(
        manifest_path,
        {
            "primarySourceId": run_manifest.get("primarySourceId"),
            "primaryInputArtifact": run_manifest.get("primaryInputArtifact"),
            "sourceKind": primary_kind,
            "sources": records,
            "segmentArtifacts": {},
        },
    )
    touch_generated_artifact(run_dir, manifest_path)

    next_action = generic_next_action(primary_kind or "unknown")
    resume_hint = generic_resume_hint(primary_kind or "unknown")
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Input sources classified and routed to parser stages.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Input sources classified and routed to parser stages.",
        active_scenario_id=args.scenario_id,
        resume_hint=resume_hint,
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action=next_action,
        latest_summary="Input sources were classified successfully.",
    )
    print(f"SOURCE_MANIFEST={relative_to_run(run_dir, manifest_path)}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
