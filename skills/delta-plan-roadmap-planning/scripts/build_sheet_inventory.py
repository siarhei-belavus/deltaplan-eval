#!/usr/bin/env python3
"""
Build a sheet-agnostic workbook inventory and region candidates.

AICODE-NOTE: The inventory stage stays deterministic so semantic analysis can reason over a stable workbook profile instead of workbook-specific sheet names.
"""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from planning_workspace_lib import (
    ensure_attractor_stage_artifacts,
    load_run_manifest,
    read_json,
    relative_to_run,
    touch_generated_artifact,
    update_checkpoint,
    update_run_status,
    update_scenario_status,
    write_json,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build workbook inventory and region candidates.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--stage-id", default="build_sheet_inventory")
    return parser.parse_args()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def column_letter(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def load_sheet_payloads(intake_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = []
    for sheet_name in manifest.get("sheetOrder", []):
        artifact = manifest.get("sheetArtifacts", {}).get(sheet_name, {})
        slug = artifact.get("slug")
        if not slug:
            continue
        payload = read_json(intake_root / "sheets" / f"{slug}.json", default={})
        if payload:
            payloads.append(payload)
    return payloads


def sheet_rows(sheet_payload: dict[str, Any]) -> dict[int, dict[int, dict[str, Any]]]:
    rows: dict[int, dict[int, dict[str, Any]]] = {}
    for cell in sheet_payload.get("cells", []):
        value = cell.get("displayValue")
        if value in (None, ""):
            continue
        rows.setdefault(int(cell["row"]), {})[int(cell["column"])] = cell
    return rows


def contiguous_blocks(row_numbers: list[int], gap: int = 1) -> list[tuple[int, int]]:
    if not row_numbers:
        return []
    blocks: list[tuple[int, int]] = []
    start = row_numbers[0]
    previous = row_numbers[0]
    for row_number in row_numbers[1:]:
        if row_number - previous > gap:
            blocks.append((start, previous))
            start = row_number
        previous = row_number
    blocks.append((start, previous))
    return blocks


def row_values(row_cells: dict[int, dict[str, Any]], min_column: int, max_column: int) -> list[str]:
    return [normalize_text(row_cells.get(column_index, {}).get("displayValue")) for column_index in range(min_column, max_column + 1)]


def choose_sample_row_numbers(data_row_numbers: list[int]) -> list[int]:
    row_count = len(data_row_numbers)
    if row_count <= 60:
        return data_row_numbers
    sample_budget = min(row_count, max(24, math.isqrt(row_count) * 4))
    head_count = max(8, sample_budget // 3)
    tail_count = max(6, sample_budget // 4)
    middle_budget = max(0, sample_budget - head_count - tail_count)
    head = data_row_numbers[:head_count]
    tail = data_row_numbers[-tail_count:]
    middle = data_row_numbers[head_count:-tail_count]
    if not middle:
        return sorted(set(head + tail))
    stride = max(1, math.ceil(len(middle) / max(1, middle_budget)))
    sampled_middle = middle[::stride][:middle_budget]
    return sorted(set(head + sampled_middle + tail))


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


def header_score(cells: dict[int, dict[str, Any]]) -> float:
    if not cells:
        return 0.0
    texts = [normalize_text(cell.get("displayValue")) for cell in cells.values()]
    non_empty = [text for text in texts if text]
    if not non_empty:
        return 0.0
    text_like = sum(1 for text in non_empty if not re.fullmatch(r"[-+]?\d+(\.\d+)?", text))
    unique = len(set(non_empty))
    blanks = max(0, len(cells) - len(non_empty))
    keyword_bonus = sum(
        1
        for text in non_empty
        if re.search(r"(req|requirement|feature|milestone|dependency|assumption|capacity|month|week|role|priority|risk|status|deadline|qa|dev)", text, re.IGNORECASE)
    )
    return text_like * 1.5 + unique + keyword_bonus - blanks * 0.2


def region_kind_hints(headers: list[str], sample_rows: list[list[str]], stats: dict[str, Any]) -> list[str]:
    joined_headers = " | ".join(item.lower() for item in headers if item)
    flattened = "\n".join(" | ".join(row).lower() for row in sample_rows if any(row))
    hints: list[str] = []
    if re.search(r"(req id|requirement|feature|backlog|story|task|epic)", joined_headers) or stats["referenceTokenCount"] > 0:
        hints.append("feature_table")
    if re.search(r"(milestone|acceptance|month|week|w1|w2)", joined_headers) or stats["dateLikeDensity"] > 0.2:
        hints.append("timeline_table")
    if re.search(r"(capacity|fte|allocation|role)", joined_headers):
        hints.append("capacity_table")
    if re.search(r"(assumption|note|risk|blocker|dependency)", joined_headers):
        hints.append("constraints_or_notes")
    if stats["textDensity"] > 0.6 and stats["columnCount"] <= 3 and any(re.fullmatch(r"#|\d+", item) for item in headers if item):
        hints.append("list_like")
    if not hints:
        hints.append("unknown")
    return hints


def classify_row(values: list[str]) -> str:
    joined = " | ".join(value.lower() for value in values if value)
    if not joined:
        return "blank"
    if re.search(r"\b(total|subtotal|sum|rollup|summary|overall)\b", joined):
        return "rollup"
    if re.search(r"\b(note|notes|comment|comments|assumption|assumptions|risk|blocker)\b", joined):
        return "note"
    if re.search(r"\b(sprint|iteration|week|month|deadline|milestone)\b", joined):
        return "timeline"
    return "data"


def header_similarity(left: list[str], right: list[str]) -> float:
    left_set = {value.strip().lower() for value in left if value.strip()}
    right_set = {value.strip().lower() for value in right if value.strip()}
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / max(len(left_set), len(right_set))


def build_region_rows(
    block_rows: dict[int, dict[int, dict[str, Any]]],
    min_column: int,
    max_column: int,
) -> list[dict[str, Any]]:
    rows_payload: list[dict[str, Any]] = []
    for row_number in sorted(block_rows):
        cells = []
        for column_index in range(min_column, max_column + 1):
            cell = block_rows[row_number].get(column_index)
            cells.append(
                {
                    "column": column_index,
                    "columnLetter": column_letter(column_index),
                    "coordinate": f"{column_letter(column_index)}{row_number}",
                    "displayValue": normalize_text(cell.get("displayValue")) if cell else "",
                    "rawValue": cell.get("rawValue") if cell else None,
                    "formula": cell.get("formula") if cell else None,
                    "inferredType": cell.get("inferredType") if cell else "blank",
                }
            )
        values = [cell["displayValue"] for cell in cells]
        rows_payload.append(
            {
                "rowNumber": row_number,
                "values": values,
                "rowKind": classify_row(values),
                "cells": cells,
            }
        )
    return rows_payload


def build_region(
    sheet_payload: dict[str, Any],
    rows: dict[int, dict[int, dict[str, Any]]],
    start_row: int,
    end_row: int,
    region_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    block_rows = {row_number: rows[row_number] for row_number in range(start_row, end_row + 1) if row_number in rows}
    non_empty_columns = sorted({column for row in block_rows.values() for column in row})
    min_column = min(non_empty_columns)
    max_column = max(non_empty_columns)
    candidate_rows = [row_number for row_number in range(start_row, min(end_row, start_row + 3) + 1) if row_number in block_rows]
    header_row = max(candidate_rows, key=lambda row_number: header_score(block_rows[row_number]))
    headers = row_values(block_rows[header_row], min_column, max_column)
    data_row_numbers = [row_number for row_number in range(header_row + 1, end_row + 1) if row_number in block_rows]
    sample_rows_payload = [
        {
            "rowNumber": row_number,
            "values": row_values(block_rows[row_number], min_column, max_column),
        }
        for row_number in choose_sample_row_numbers(data_row_numbers)
    ]
    values = [normalize_text(cell.get("displayValue")) for row in block_rows.values() for cell in row.values()]
    non_empty_values = [value for value in values if value]
    text_values = [value for value in non_empty_values if not re.fullmatch(r"[-+]?\d+(\.\d+)?", value)]
    date_like = sum(1 for value in non_empty_values if re.match(r"\d{4}-\d{2}-\d{2}T", value))
    formula_count = sum(1 for row in block_rows.values() for cell in row.values() if cell.get("formula"))
    reference_tokens = extract_reference_tokens("\n".join(non_empty_values))
    stats = {
        "rowCount": end_row - start_row + 1,
        "columnCount": max_column - min_column + 1,
        "textDensity": round(len(text_values) / max(1, len(non_empty_values)), 3),
        "dateLikeDensity": round(date_like / max(1, len(non_empty_values)), 3),
        "formulaCount": formula_count,
        "referenceTokenCount": len(reference_tokens),
    }
    region_id = f"{sheet_payload['sheetSlug']}--r{region_index:02d}"
    region_summary = {
        "regionId": region_id,
        "sheetName": sheet_payload["sheetName"],
        "sheetSlug": sheet_payload["sheetSlug"],
        "rowStart": start_row,
        "rowEnd": end_row,
        "columnStart": min_column,
        "columnEnd": max_column,
        "range": f"{column_letter(min_column)}{start_row}:{column_letter(max_column)}{end_row}",
        "headerRow": header_row,
        "headers": headers,
        "sampleRows": sample_rows_payload,
        "kindHints": region_kind_hints(headers, [item["values"] for item in sample_rows_payload], stats),
        "evidence": {
            "referenceTokens": reference_tokens,
            "mergedRanges": [item for item in sheet_payload.get("mergedRanges", []) if intersects_range(item, start_row, end_row)],
        },
        "stats": stats,
        "provenance": {
            "sheet": sheet_payload["sheetName"],
            "range": f"{column_letter(min_column)}{start_row}:{column_letter(max_column)}{end_row}",
            "headerEvidence": [item for item in headers if item][:8],
        },
    }
    region_artifact = {
        "regionId": region_id,
        "sheetName": sheet_payload["sheetName"],
        "sheetSlug": sheet_payload["sheetSlug"],
        "range": region_summary["range"],
        "headerRow": header_row,
        "headers": headers,
        "kindHints": list(region_summary["kindHints"]),
        "rowBounds": {"start": start_row, "end": end_row},
        "columnBounds": {"start": min_column, "end": max_column},
        "rows": build_region_rows(block_rows, min_column, max_column),
        "sampleRows": sample_rows_payload,
        "stats": stats,
        "provenance": dict(region_summary["provenance"]),
    }
    return region_summary, region_artifact


def intersects_range(range_ref: str, start_row: int, end_row: int) -> bool:
    numbers = [int(item) for item in re.findall(r"\d+", range_ref)]
    if not numbers:
        return False
    return not (max(numbers) < start_row or min(numbers) > end_row)


def sheet_summary(sheet_payload: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    rows = sheet_rows(sheet_payload)
    non_empty_rows = sorted(rows)
    non_empty_columns = sorted({column for row in rows.values() for column in row})
    type_counter = Counter(
        cell.get("inferredType", "unknown")
        for cell in sheet_payload.get("cells", [])
        if cell.get("displayValue") not in (None, "")
    )
    return {
        "sheetName": sheet_payload["sheetName"],
        "sheetSlug": sheet_payload["sheetSlug"],
        "hidden": sheet_payload.get("hidden", False),
        "rowBounds": sheet_payload.get("rowBounds", {}),
        "columnBounds": sheet_payload.get("columnBounds", {}),
        "nonEmptyRowCount": len(non_empty_rows),
        "nonEmptyColumnCount": len(non_empty_columns),
        "formulaPresence": manifest.get("formulaPresence", {}).get(sheet_payload["sheetName"], False),
        "dateLikeCellCount": len(manifest.get("dateLikeCells", {}).get(sheet_payload["sheetName"], [])),
        "detectedTableRanges": manifest.get("detectedTableRanges", {}).get(sheet_payload["sheetName"], []),
        "mergedRanges": sheet_payload.get("mergedRanges", []),
        "topInferredTypes": dict(type_counter.most_common(4)),
        "rowSegments": contiguous_blocks(non_empty_rows),
    }


def cross_sheet_reference_hints(regions: list[dict[str, Any]]) -> dict[str, list[str]]:
    token_to_sheets: dict[str, set[str]] = {}
    for region in regions:
        for token in region.get("evidence", {}).get("referenceTokens", []):
            token_to_sheets.setdefault(token, set()).add(region["sheetName"])
    hints: dict[str, list[str]] = {}
    for region in regions:
        hints[region["regionId"]] = sorted(
            token
            for token in region.get("evidence", {}).get("referenceTokens", [])
            if len(token_to_sheets.get(token, set())) > 1
        )
    return hints


def build_inventory_refs(
    run_dir: Path,
    scenario_id: str,
    workbook_manifest: dict[str, Any],
    workbook_profile: dict[str, Any],
    region_artifacts: dict[str, str],
) -> dict[str, Any]:
    run_manifest = load_run_manifest(run_dir)
    sheet_regions: dict[str, list[dict[str, Any]]] = {}
    for region in workbook_profile["regions"]:
        sheet_regions.setdefault(region["sheetName"], []).append(region)
    for regions in sheet_regions.values():
        regions.sort(key=lambda item: item["rowStart"])

    cross_sheet_hints = cross_sheet_reference_hints(workbook_profile["regions"])
    unexplained_areas: list[dict[str, Any]] = []
    sheet_refs: list[dict[str, Any]] = []
    region_refs: list[dict[str, Any]] = []

    for sheet in workbook_profile["sheets"]:
        artifact = workbook_manifest.get("sheetArtifacts", {}).get(sheet["sheetName"], {})
        regions = sheet_regions.get(sheet["sheetName"], [])
        suspicious_segments: list[list[int]] = []
        for index, region in enumerate(regions):
            previous_region = regions[index - 1] if index > 0 else None
            next_region = regions[index + 1] if index + 1 < len(regions) else None
            adjacent_region_ids = [candidate["regionId"] for candidate in [previous_region, next_region] if candidate]
            neighbor_segments = [
                [candidate["rowStart"], candidate["rowEnd"]]
                for candidate in [previous_region, next_region]
                if candidate
            ]
            suspicion_flags: list[str] = []
            row_kinds = [sample.get("values", []) for sample in region.get("sampleRows", [])]
            if any(classify_row(values) in {"rollup", "timeline", "note"} for values in row_kinds):
                suspicion_flags.append("mixed_semantic_rows_in_samples")
            if region["stats"]["formulaCount"] > 0 and "feature_table" in region["kindHints"]:
                suspicion_flags.append("formula_presence_inside_feature_like_region")
            if region["evidence"]["mergedRanges"]:
                suspicion_flags.append("merged_ranges_present")
            if previous_region and header_similarity(region["headers"], previous_region["headers"]) >= 0.5:
                suspicion_flags.append("similar_headers_to_adjacent_region")
            if next_region and header_similarity(region["headers"], next_region["headers"]) >= 0.5:
                suspicion_flags.append("similar_headers_to_adjacent_region")
            if cross_sheet_hints.get(region["regionId"]):
                suspicion_flags.append("cross_sheet_reference_tokens_detected")

            if suspicion_flags or region["kindHints"] == ["unknown"]:
                suspicious_segments.append([region["rowStart"], region["rowEnd"]])
                unexplained_areas.append(
                    {
                        "sheetName": region["sheetName"],
                        "range": region["range"],
                        "reason": "; ".join(suspicion_flags) if suspicion_flags else "Region remains weakly classified by deterministic inventory",
                    }
                )

            region_refs.append(
                {
                    "regionId": region["regionId"],
                    "sheetName": region["sheetName"],
                    "sheetSlug": region["sheetSlug"],
                    "range": region["range"],
                    "headerRow": region["headerRow"],
                    "headers": region["headers"],
                    "kindHints": region["kindHints"],
                    "fullRegionPath": region_artifacts[region["regionId"]],
                    "adjacentRegionIds": adjacent_region_ids,
                    "neighborRowSegments": neighbor_segments,
                    "crossSheetReferenceHints": cross_sheet_hints.get(region["regionId"], []),
                    "suspicionFlags": suspicion_flags,
                    "provenance": dict(region["provenance"]),
                }
            )

        sheet_refs.append(
            {
                "sheetName": sheet["sheetName"],
                "sheetSlug": sheet["sheetSlug"],
                "sheetJsonPath": artifact.get("jsonPath"),
                "sheetCsvPath": artifact.get("csvPath"),
                "sheetMarkdownPath": artifact.get("markdownPath"),
                "hidden": sheet["hidden"],
                "rowSegments": [list(segment) for segment in sheet.get("rowSegments", [])],
                "suspiciousSegments": suspicious_segments,
                "notes": [],
            }
        )

    return {
        "scenarioId": scenario_id,
        "sourceWorkbook": {
            "primaryInputArtifact": run_manifest.get("primaryInputArtifact", workbook_manifest.get("workbookFilename")),
            "workbookManifestPath": "intake/workbook-manifest.json",
        },
        "sheetRefs": sheet_refs,
        "regionRefs": region_refs,
        "unexplainedAreas": unexplained_areas,
    }


def inventory_markdown(workbook_profile: dict[str, Any]) -> str:
    lines = ["# Workbook Inventory", ""]
    for sheet in workbook_profile["sheets"]:
        lines.append(f"## {sheet['sheetName']}")
        lines.append(f"- Hidden: {sheet['hidden']}")
        lines.append(f"- Non-empty rows: {sheet['nonEmptyRowCount']}")
        lines.append(f"- Non-empty columns: {sheet['nonEmptyColumnCount']}")
        lines.append(f"- Formula presence: {sheet['formulaPresence']}")
        lines.append(f"- Date-like cells: {sheet['dateLikeCellCount']}")
        lines.append("")
    lines.append("## Regions")
    lines.append("")
    for region in workbook_profile["regions"]:
        lines.append(f"### {region['regionId']}")
        lines.append(f"- Sheet: {region['sheetName']}")
        lines.append(f"- Range: {region['range']}")
        lines.append(f"- Kind hints: {', '.join(region['kindHints'])}")
        lines.append(f"- Headers: {', '.join(item for item in region['headers'] if item) or '<none>'}")
        for sample in region["sampleRows"]:
            preview = " | ".join(item for item in sample["values"] if item) or "<empty>"
            lines.append(f"- Sample row {sample['rowNumber']}: {preview}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def inventory_refs_markdown(inventory_refs: dict[str, Any]) -> str:
    lines = ["# Inventory Refs", ""]
    lines.append("## Sheets")
    lines.append("")
    for sheet in inventory_refs["sheetRefs"]:
        lines.append(f"### {sheet['sheetName']}")
        lines.append(f"- JSON: {sheet['sheetJsonPath']}")
        lines.append(f"- CSV: {sheet['sheetCsvPath']}")
        lines.append(f"- Markdown: {sheet['sheetMarkdownPath']}")
        lines.append(f"- Row segments: {sheet['rowSegments']}")
        lines.append(f"- Suspicious segments: {sheet['suspiciousSegments']}")
        lines.append("")
    lines.append("## Regions")
    lines.append("")
    for region in inventory_refs["regionRefs"]:
        lines.append(f"### {region['regionId']}")
        lines.append(f"- Sheet: {region['sheetName']}")
        lines.append(f"- Range: {region['range']}")
        lines.append(f"- Artifact: {region['fullRegionPath']}")
        lines.append(f"- Kind hints: {', '.join(region['kindHints'])}")
        lines.append(f"- Adjacent regions: {', '.join(region['adjacentRegionIds']) or '<none>'}")
        lines.append(f"- Cross-sheet refs: {', '.join(region['crossSheetReferenceHints']) or '<none>'}")
        lines.append(f"- Suspicion flags: {', '.join(region['suspicionFlags']) or '<none>'}")
        lines.append("")
    if inventory_refs["unexplainedAreas"]:
        lines.append("## Unexplained Areas")
        lines.append("")
        for item in inventory_refs["unexplainedAreas"]:
            lines.append(f"- {item['sheetName']} {item['range']}: {item['reason']}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    intake_root = run_dir / "intake"
    manifest_path = intake_root / "workbook-manifest.json"
    workbook_manifest = read_json(manifest_path, default={})
    sheet_payloads = load_sheet_payloads(intake_root, workbook_manifest)
    sheets = [sheet_summary(sheet_payload, workbook_manifest) for sheet_payload in sheet_payloads]

    regions: list[dict[str, Any]] = []
    region_artifacts: dict[str, str] = {}
    scenario_dir = run_dir / "scenarios" / args.scenario_id / "normalized"
    regions_dir = scenario_dir / "regions"
    for sheet_payload in sheet_payloads:
        rows = sheet_rows(sheet_payload)
        row_blocks = contiguous_blocks(sorted(rows))
        for region_index, (start_row, end_row) in enumerate(row_blocks, start=1):
            if end_row - start_row < 1:
                continue
            region, region_artifact = build_region(sheet_payload, rows, start_row, end_row, region_index)
            region_path = regions_dir / f"{region['regionId']}.json"
            write_json(region_path, region_artifact)
            touch_generated_artifact(run_dir, region_path)
            regions.append(region)
            region_artifacts[region["regionId"]] = relative_to_run(run_dir, region_path)

    date_values = []
    for region in regions:
        for sample in region["sampleRows"]:
            for value in sample["values"]:
                if re.match(r"\d{4}-\d{2}-\d{2}T", value):
                    date_values.append(value)

    workbook_profile = {
        "sheets": sheets,
        "regions": regions,
        "detectedDateRange": {
            "start": min(date_values) if date_values else None,
            "end": max(date_values) if date_values else None,
        },
        "unsupportedFeatures": workbook_manifest.get("unsupportedFeatures", {}),
    }

    json_path = scenario_dir / "workbook-profile.json"
    md_path = scenario_dir / "workbook-profile.md"
    inventory_refs_path = scenario_dir / "inventory-refs.json"
    inventory_refs_md_path = scenario_dir / "inventory-refs.md"
    inventory_refs = build_inventory_refs(run_dir, args.scenario_id, workbook_manifest, workbook_profile, region_artifacts)
    write_json(json_path, workbook_profile)
    write_text(md_path, inventory_markdown(workbook_profile))
    write_json(inventory_refs_path, inventory_refs)
    write_text(inventory_refs_md_path, inventory_refs_markdown(inventory_refs))
    touch_generated_artifact(run_dir, json_path)
    touch_generated_artifact(run_dir, md_path)
    touch_generated_artifact(run_dir, inventory_refs_path)
    touch_generated_artifact(run_dir, inventory_refs_md_path)

    update_run_status(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Run focused workbook analysis agents",
        latest_summary="Workbook inventory and region candidates are ready for semantic analysis.",
        active_scenario_id=args.scenario_id,
    )
    update_checkpoint(
        run_dir,
        state="running",
        current_stage=args.stage_id,
        next_action="Run focused workbook analysis agents",
        latest_summary="Workbook inventory and region candidates are ready for semantic analysis.",
        active_scenario_id=args.scenario_id,
        resume_hint="Run the focused analysis agents next.",
    )
    update_scenario_status(
        run_dir,
        args.scenario_id,
        state="running",
        current_stage=args.stage_id,
        next_action="Run focused workbook analysis agents",
        latest_summary="Workbook inventory built for semantic planning analysis.",
    )
    ensure_attractor_stage_artifacts(
        run_dir,
        stage_id=args.stage_id,
        command="build_sheet_inventory.py",
        inputs={"runDir": str(run_dir), "scenarioId": args.scenario_id},
        summary="Workbook inventory and region candidates generated.",
        state="success",
        outputs={
            "workbookProfilePath": relative_to_run(run_dir, json_path),
            "inventoryMarkdownPath": relative_to_run(run_dir, md_path),
            "inventoryRefsPath": relative_to_run(run_dir, inventory_refs_path),
        },
    )

    print(f"WORKBOOK_PROFILE={json_path}")
    print(f"WORKBOOK_PROFILE_MD={md_path}")
    print(f"INVENTORY_REFS={inventory_refs_path}")
    print(f"INVENTORY_REFS_MD={inventory_refs_md_path}")
    print("WORKBOOK_PROFILE_SUMMARY_BEGIN")
    print(inventory_markdown(workbook_profile).rstrip())
    print("WORKBOOK_PROFILE_SUMMARY_END")
    print("INVENTORY_REFS_SUMMARY_BEGIN")
    print(inventory_refs_markdown(inventory_refs).rstrip())
    print("INVENTORY_REFS_SUMMARY_END")
    print("STATE=running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
