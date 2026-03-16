---
name: delta-plan-roadmap-planning
description: Run DeltaPlan planning-workspace scenarios from messy planning inputs with durable run artifacts, clarification checkpoints, Attractor orchestration, and DeltaPlan MCP solves.
---

<!-- AICODE-NOTE: This evaluation-bundle skill is the handoff artifact for the planning workspace initiative. It keeps the human-facing flow thin and pushes durable state into the run workspace on disk. -->

# DeltaPlan Planning Workspace

Use this skill when the user wants to start, inspect, resume, or branch a DeltaPlan planning run from one or more planning artifacts, especially Excel workbooks.

## Responsibilities

- Detect whether the user wants a new run, a resume, or a what-if branch.
- Read the run workspace under `.codex-artifacts/delta-plan/runs/`.
- Ask only the latest unresolved clarification questions from `scenarios/<scenario-id>/clarifications/request-*.json`.
- Write structured clarification responses before resuming.
- Run the Attractor workflow that owns the stage ordering.
- Summarize the latest successful outputs and point to the saved artifacts.

## New Run Flow

1. Pick the primary input artifact and a short scenario slug.
2. Start the workflow:

```bash
python3 skills/delta-plan-roadmap-planning/scripts/planning_workflow.py start \
  --workspace-root "$PWD" \
  --input "/absolute/path/to/workbook.xlsx"
```

3. Read `.codex-artifacts/delta-plan/runs/<run-id>/status.json`.
4. If the run is waiting, ask only the questions from the latest clarification request.

## Resume Flow

1. Read `status.json` and the active scenario’s `scenario-status.json`.
2. If the run is waiting for input, write a structured clarification response:

```bash
python3 skills/delta-plan-roadmap-planning/scripts/submit_clarification_response.py \
  --run-dir "/absolute/path/to/run" \
  --answers-file "/absolute/path/to/answers.json"
```

3. Resume the workflow:

```bash
python3 skills/delta-plan-roadmap-planning/scripts/planning_workflow.py resume \
  --run-dir "/absolute/path/to/run"
```

## What-If Flow

Create a sibling scenario after a completed baseline or completed prior scenario:

```bash
python3 skills/delta-plan-roadmap-planning/scripts/create_what_if_scenario.py \
  --run-dir "/absolute/path/to/run" \
  --source-scenario baseline \
  --scenario-id what-if-ai \
  --scenario-label "AI Estimate Profile" \
  --override-file "/absolute/path/to/override.json"
```

Then build, solve, and render that scenario by resuming the workflow with the new active scenario.

## Artifact Contract

Treat the run workspace as the source of truth, not chat memory:

- `.codex-artifacts/delta-plan/runs/<run-id>/manifest.json`
- `.codex-artifacts/delta-plan/runs/<run-id>/checkpoint.json`
- `.codex-artifacts/delta-plan/runs/<run-id>/status.json`
- `.codex-artifacts/delta-plan/runs/<run-id>/scenarios/<scenario-id>/...`

## Guardrails

- Do not invent planning horizon, capacity, or critical effort values.
- Record defaults explicitly before solve.
- Preserve provenance back to workbook sheet, row, and column.
- Keep the solve boundary at the DeltaPlan MCP jar.
