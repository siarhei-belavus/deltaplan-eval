---
name: delta-plan-roadmap-planning
description: Run DeltaPlan planning scenarios from workbook artifacts with chat-orchestrated clarification, durable domain artifacts, and DeltaPlan MCP solves.
---

# DeltaPlan Planning Workspace

Use this skill when the user wants to run, inspect, clarify, or branch a DeltaPlan planning scenario from workbook-style planning artifacts.

## Responsibilities

- Treat chat plus this skill as the only orchestrator.
- Maintain one current target run/scenario in chat memory.
- Read durable artifacts under `.codex-artifacts/delta-plan/runs/`.
- Support exactly four intents:
  - baseline request
  - clarification answer
  - what-if request
  - inspect request
- Ask only unanswered required questions from the latest open clarification request.
- Keep partial clarification answers in chat memory until the full required answer set is available.
- Write `response-*.json` only through `write_full_clarification_response.py`.
- Require a completed parent scenario before creating a what-if branch.

## Baseline Flow

1. Start a new run workspace:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/planning_workflow.py start \
  --workspace-root "$PWD" \
  --input "/absolute/path/to/source-artifact.xlsx"
```

2. Run the baseline stages in order:
   - `ingest_sources.py`
   - `extract_source_artifacts.py`
   - `build_source_inventory.py`
   - `run_analysis_fanout.py`
   - `merge_planning_signals.py`
   - `build_candidate_model.py`

3. If `build_candidate_model.py` emits `STATE=waiting_for_input`, ask only the latest required clarification questions in chat.
4. After the full answer set is available, write and merge the clarification response:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/write_full_clarification_response.py \
  --run-dir "/absolute/path/to/run" \
  --scenario-id "baseline" \
  --answers-file "/absolute/path/to/answers.json"

.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/merge_clarification_response.py \
  --run-dir "/absolute/path/to/run" \
  --scenario-id "baseline"
```

5. Continue with:
   - `build_solver_payload.py`
   - `call_deltaplan_mcp.py`
   - `save_and_render_schedule.py`
   - `finalize_run.py`

## What-If Flow

Create a what-if scenario only from a completed parent scenario:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/create_what_if_scenario.py \
  --run-dir "/absolute/path/to/run" \
  --source-scenario baseline \
  --scenario-id what-if-extra-devs \
  --scenario-label "Extra Developers" \
  --override-file "/absolute/path/to/override.json"
```

Then run `build_candidate_model.py` and the same downstream solve/render stages for the new scenario.

## Inspect Flow

Inspect only from manifests, clarification artifacts, solver artifacts, and rendered outputs:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/planning_workflow.py status \
  --run-dir "/absolute/path/to/run"
```

## Guardrails

- Do not invent planning horizon, capacity, or effort values.
- Do not persist partial clarification drafts.
- Do not branch what-if scenarios from incomplete parents.
- Preserve provenance back to workbook artifacts.
- Keep the solve boundary at the DeltaPlan MCP jar.
