#!/usr/bin/env python3
"""
Classify source artifacts and record the deterministic ingest contract.

AICODE-NOTE: Ingest stays explicit even for a single workbook so the run workspace records which parser path each source followed before deeper extraction starts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from planning_workspace_lib import (
    classify_input,
    ensure_attractor_stage_artifacts,
    load_run_manifest,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_status,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify input sources for the planning workspace.")
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
    for source_file in source_files:
        kind = source_file.get("kind") or classify_input(Path(source_file["copiedPath"]))
        route = "workbook_extraction" if kind == "excel_workbook" else f"{kind}_parser"
        records.append(
            {
                "copiedPath": source_file["copiedPath"],
                "kind": kind,
                "route": route,
                "supported": kind in {"excel_workbook", "csv", "markdown", "text"},
            }
        )

    ingest_path = run_dir / "intake" / "source-ingest.json"
    write_json(
        ingest_path,
        {
            "primaryInputArtifact": run_manifest.get("primaryInputArtifact"),
            "sources": records,
        },
    )
    touch_generated_artifact(run_dir, ingest_path)
    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Extract workbook intake artifacts",
        latest_summary="Input sources classified and routed to parser stages.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Extract workbook intake artifacts",
        latest_summary="Input sources classified and routed to parser stages.",
        active_scenario_id=args.scenario_id,
        resume_hint="Run extract_workbook next.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action="Extract workbook intake artifacts",
        latest_summary="Input sources were classified successfully.",
    )
    ensure_attractor_stage_artifacts(
        run_dir,
        stage_id=args.stage_id,
        command="ingest_sources.py",
        inputs={"runDir": str(run_dir), "sourceCount": len(source_files)},
        summary="Classified source artifacts and recorded parser routing decisions.",
        state="success",
        outputs={"sourceIngestPath": relative_to_run(run_dir, ingest_path)},
    )
    print(f"SOURCE_INGEST={ingest_path}")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
