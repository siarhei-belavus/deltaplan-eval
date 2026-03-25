# DeltaPlan Planning Skill Pack

This repo ships the source for the DeltaPlan planning skill pack and installer.

## Productized install model

- `deltaplan init` installs a repo-local runtime under:
  - `.claude/skills/deltaplan/` (autonomous skill pack)
  - `.deltaplan/` (runtime metadata + managed state)
- Installed scripts run from:
  - `.claude/skills/deltaplan/scripts/...`
- Installed scripts use
  - `.deltaplan/.venv/bin/python`

## CLI lifecycle

- Install global CLI from a release manifest with signature verification:
  - `deltaplan init`
  - `deltaplan update`
  - `deltaplan remove`
  - `deltaplan doctor`
  - `deltaplan self-update`

## User-style install test (clean folder)

Release publishing is now workflow-driven:

- tag commit as `v<version>` (for example `v1.2.3`)
- push the tag
- GitHub Actions builds and publishes release assets automatically (requires `DELTAPLAN_RELEASE_PRIVATE_KEY` secret)

Then users install from that release:

```bash
# one-liner user path (install script from release)
curl -fsSL https://github.com/siarhei-belavus/deltaplan-eval/releases/latest/download/install.sh | sh
```

Then in any fresh git repo:

```bash
git init -q
DELTAPLAN_MANIFEST_URL="https://github.com/siarhei-belavus/deltaplan-eval/releases/latest/download/manifest.json" \
  deltaplan init
```

## Local one-command developer test

```bash
# builds a signed local release, installs CLI, and runs init/remove in a clean repo
sh scripts/release/e2e_local.sh
```

If Java 21 is not installed, init will stop at managed-Java install unless you add a local java21 asset in the release manifest.
## Quick start

From a repo with DeltaPlan installed:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/planning_workflow.py start \
  --workspace-root . \
  --input ./10\ digits.xlsx

.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/planning_workflow.py status \
```

## Runtime command surface in the shipped skill

Use repo-local paths only:

```bash
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/ingest_sources.py
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/extract_excel_artifacts.py
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/run_analysis_fanout.py
.deltaplan/.venv/bin/python .claude/skills/deltaplan/scripts/call_deltaplan_mcp.py
```

## Reference artifacts

- Prompt assets in source: `skills/delta-plan-roadmap-planning/resources/prompts/`

## Repository notes

- The source pack stores install-time dependencies in `skills/delta-plan-roadmap-planning/requirements.txt`.
- Source-only files like `skills/delta-plan-roadmap-planning/agents/openai.yaml` are excluded from shipped release payloads.
