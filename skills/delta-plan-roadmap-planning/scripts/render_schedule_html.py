#!/usr/bin/env python3
"""
Render lightweight HTML artifacts for DeltaPlan solve outputs.

AICODE-NOTE: The evaluation bundle keeps the renderer dependency-light and file-based so reviewers can open timeline and heatmap outputs directly from the run workspace.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


PHASE_COLORS = [
    "#1f6feb",
    "#2da44e",
    "#d29922",
    "#cf222e",
    "#8957e5",
    "#0969da",
]
STATUS_COLORS = {
    "CRIT": "#8b0000",
    "HIGH": "#d73a49",
    "WARN": "#fb8500",
    "AT": "#2da44e",
    "GOOD": "#7ee787",
    "LOW": "#d8f3dc",
    "IDLE": "#f3f4f6",
}


def week_index(week: dict[str, int] | None) -> int | None:
    if not week:
        return None
    return (week["month"] - 1) * 4 + week["week"]


def week_label(week: dict[str, int] | None) -> str:
    if not week:
        return "-"
    return f"M{week['month']} W{week['week']}"


def phase_colors(phases: list[dict[str, Any]] | None) -> dict[str, str]:
    mapping = {}
    for index, phase in enumerate(phases or []):
        mapping[phase["id"]] = PHASE_COLORS[index % len(PHASE_COLORS)]
    return mapping


def build_timeline_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for feature in payload["features"]:
        rows.append(
            {
                "id": feature["id"],
                "title": feature.get("title") or feature["id"],
                "phaseId": feature.get("phaseId") or "UNASSIGNED",
                "start": week_index(feature.get("startWeek")),
                "finish": week_index(feature.get("completionWeek")),
                "dependsOn": feature.get("dependencies") or [],
            }
        )
    return rows


def aggregate_monthly_heatmap(payload: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for week in payload["weeklyHeatmap"]:
        month = week["week"]["month"]
        for role in week["roleUtilization"]:
            grouped[(role["role"], month)].append(role)

    results = []
    for (role_name, month), items in sorted(grouped.items()):
        avg_util = round(sum(item["utilizationPercent"] for item in items) / len(items), 1)
        peak_excess = round(max(item["fteExcess"] for item in items), 2)
        if peak_excess >= 2.0:
            status = "CRIT"
        elif peak_excess >= 1.0:
            status = "HIGH"
        elif peak_excess >= 0.1:
            status = "WARN"
        elif avg_util >= 76:
            status = "AT"
        elif avg_util >= 26:
            status = "GOOD"
        elif avg_util >= 1:
            status = "LOW"
        else:
            status = "IDLE"
        results.append(
            {
                "role": role_name,
                "month": month,
                "avgUtil": avg_util,
                "peakExcess": peak_excess,
                "status": status,
            }
        )
    return results


def render_html_report(
    *,
    payload: dict[str, Any],
    title: str,
    estimate_profile: str,
    output_path: Path,
) -> None:
    timeline_rows = build_timeline_rows(payload)
    max_week = max(
        [week_index(feature.get("completionWeek")) or 0 for feature in payload["features"]]
        + [week_index(phase.get("completionWeek")) or 0 for phase in (payload.get("phases") or [])]
        + [1]
    )
    phase_color_map = phase_colors(payload.get("phases"))
    week_headers = [f"M{((index - 1) // 4) + 1}W{((index - 1) % 4) + 1}" for index in range(1, max_week + 1)]

    timeline_html = []
    for row in timeline_rows:
        cells = []
        for index in range(1, max_week + 1):
            active = row["start"] is not None and row["finish"] is not None and row["start"] <= index <= row["finish"]
            color = phase_color_map.get(row["phaseId"], "#c9d1d9")
            style = f"background:{color};" if active else "background:#ffffff;"
            cells.append(f"<td style='{style} width:24px; height:22px;'></td>")
        timeline_html.append(
            "<tr>"
            f"<th>{row['id']}</th><td>{row['title']}</td><td>{row['phaseId']}</td>"
            + "".join(cells)
            + "</tr>"
        )

    weekly_rows = defaultdict(dict)
    for week in payload["weeklyHeatmap"]:
        week_key = f"M{week['week']['month']}W{week['week']['week']}"
        for role in week["roleUtilization"]:
            weekly_rows[role["role"]][week_key] = role

    heatmap_html = []
    for role_name in sorted(weekly_rows):
        cells = []
        for week_key in week_headers:
            role = weekly_rows[role_name].get(week_key)
            if role:
                intensity = role["heatmapColor"]
                label = f"{role['utilizationPercent']:.0f}%"
                tooltip = f"{role['scheduledRawFte']:.2f}/{role['availableRawFte']:.2f} FTE"
            else:
                intensity = "#f3f4f6"
                label = "-"
                tooltip = "No data"
            cells.append(f"<td title='{tooltip}' style='background:{intensity}; text-align:center;'>{label}</td>")
        heatmap_html.append(f"<tr><th>{role_name}</th>{''.join(cells)}</tr>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111827; background: #f8fafc; }}
    .card {{ background: white; border-radius: 16px; padding: 20px; margin-bottom: 20px; box-shadow: 0 8px 24px rgba(15,23,42,0.08); }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .meta {{ color: #4b5563; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p class="meta">Estimate profile: {estimate_profile}. Features: {len(payload['features'])}. Phases: {len(payload.get('phases') or [])}.</p>
  </div>
  <div class="card">
    <h2>Timeline</h2>
    <table>
      <thead>
        <tr><th>ID</th><th>Feature</th><th>Phase</th>{''.join(f'<th>{header}</th>' for header in week_headers)}</tr>
      </thead>
      <tbody>
        {''.join(timeline_html)}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Weekly Heatmap</h2>
    <table>
      <thead>
        <tr><th>Role</th>{''.join(f'<th>{header}</th>' for header in week_headers)}</tr>
      </thead>
      <tbody>
        {''.join(heatmap_html)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    output_path.write_text(html)
