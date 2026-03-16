#!/usr/bin/env python3
"""
Render durable scenario outputs from a DeltaPlan solve response.

AICODE-NOTE: Output rendering writes versioned per-scenario artifacts so reviewers can compare reruns without losing previous solve results.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from planning_workspace_lib import next_output_prefix, relative_to_run, touch_generated_artifact, write_json
from render_schedule_html import aggregate_monthly_heatmap, render_html_report, week_label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render scenario report artifacts from a solve response.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--estimate-profile", required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def render_payload_from_solver_artifacts(solve_response: dict[str, Any], solve_request: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(solve_response)
    request_features = {
        item.get("id"): item
        for item in solve_request.get("schedule", {}).get("features", [])
        if item.get("id")
    }
    enriched_features = []
    for feature in payload.get("features", []):
        request_feature = request_features.get(feature.get("id"), {})
        enriched_feature = dict(feature)
        if not enriched_feature.get("dependencies") and request_feature.get("dependencies"):
            enriched_feature["dependencies"] = request_feature["dependencies"]
        if not enriched_feature.get("title") and request_feature.get("title"):
            enriched_feature["title"] = request_feature["title"]
        if not enriched_feature.get("phaseId") and request_feature.get("phaseId"):
            enriched_feature["phaseId"] = request_feature["phaseId"]
        enriched_features.append(enriched_feature)
    payload["features"] = enriched_features
    return payload


def roadmap_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Roadmap", "", "## Phases", "", "| Phase | Start | Finish |", "| --- | --- | --- |"]
    for phase in payload.get("phases") or []:
        lines.append(f"| {phase['name']} | {week_label(phase.get('startWeek'))} | {week_label(phase.get('completionWeek'))} |")
    lines.extend(["", "## Features", "", "| Feature | Phase | Start | Finish | Dependencies |", "| --- | --- | --- | --- | --- |"])
    for feature in payload["features"]:
        deps = ", ".join(feature.get("dependencies") or []) or "none"
        lines.append(
            f"| {feature['id']} {feature.get('title') or ''} | {feature.get('phaseId') or '-'} | "
            f"{week_label(feature.get('startWeek'))} | {week_label(feature.get('completionWeek'))} | {deps} |"
        )
    return "\n".join(lines)


def monthly_heatmap_markdown(payload: dict[str, Any]) -> str:
    monthly_rows = aggregate_monthly_heatmap(payload)
    months = sorted({row["month"] for row in monthly_rows})
    roles = sorted({row["role"] for row in monthly_rows})
    lookup = {(row["role"], row["month"]): row for row in monthly_rows}
    lines = ["# Monthly Capacity Heatmap", "", "| Role \\\\ Month | " + " | ".join(f"M{month}" for month in months) + " |"]
    lines.append("| --- | " + " | ".join("---" for _ in months) + " |")
    for role in roles:
        cells = []
        for month in months:
            item = lookup.get((role, month))
            if item:
                cells.append(f"{item['status']} {item['avgUtil']}% | +{item['peakExcess']}")
            else:
                cells.append("-")
        lines.append(f"| {role} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def summary_text(payload: dict[str, Any], estimate_profile: str) -> tuple[str, str]:
    monthly_rows = aggregate_monthly_heatmap(payload)
    top_warning = max(monthly_rows, key=lambda item: (item["peakExcess"], item["avgUtil"]), default=None)
    summary_lines = [
        f"Estimate profile: {estimate_profile}",
        f"Features: {len(payload['features'])}",
        f"Phases: {len(payload.get('phases') or [])}",
    ]
    if top_warning:
        summary_lines.append(
            f"Biggest capacity signal: {top_warning['role']} in M{top_warning['month']} -> "
            f"{top_warning['status']} {top_warning['avgUtil']}% | +{top_warning['peakExcess']} FTE"
        )
    summary_lines.append("Outputs include roadmap markdown, monthly heatmap markdown, and an HTML report.")
    text_summary = "\n".join(summary_lines)
    markdown_summary = "# Scenario Summary\n\n" + "\n".join(f"- {line}" for line in summary_lines)
    return text_summary, markdown_summary


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    outputs_dir = scenario_dir / "outputs"
    solver_dir = scenario_dir / "solver"
    scenario_manifest = load_json(scenario_dir / "scenario-manifest.json")
    solve_response = load_json(solver_dir / "solve-response.json")
    solve_request = load_json(solver_dir / "solve-request.json")
    render_payload = render_payload_from_solver_artifacts(solve_response, solve_request)
    scenario_slug = scenario_manifest.get("scenarioSlug", args.scenario_id)
    version_prefix = next_output_prefix(outputs_dir, scenario_slug)
    base_name = f"{version_prefix}_{scenario_slug}"

    html_path = outputs_dir / f"{base_name}-report.html"
    text_path = outputs_dir / f"{base_name}-summary.txt"
    md_path = outputs_dir / f"{base_name}-summary.md"
    roadmap_path = outputs_dir / f"{base_name}-roadmap.md"
    heatmap_path = outputs_dir / f"{base_name}-heatmap-monthly.md"

    render_html_report(
        payload=render_payload,
        title=f"DeltaPlan Scenario Report: {scenario_manifest.get('scenarioLabel', args.scenario_id)}",
        estimate_profile=args.estimate_profile,
        output_path=html_path,
    )
    text_summary, markdown_summary = summary_text(render_payload, args.estimate_profile)
    text_path.write_text(text_summary + "\n")
    md_path.write_text(markdown_summary + "\n")
    roadmap_path.write_text(roadmap_markdown(render_payload) + "\n")
    heatmap_path.write_text(monthly_heatmap_markdown(render_payload) + "\n")

    for artifact in [html_path, text_path, md_path, roadmap_path, heatmap_path]:
        touch_generated_artifact(run_dir, artifact)

    print(f"HTML_REPORT={html_path}")
    print(f"SUMMARY_TEXT={text_path}")
    print(f"SUMMARY_MD={md_path}")
    print(f"ROADMAP_MD={roadmap_path}")
    print(f"HEATMAP_MD={heatmap_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
