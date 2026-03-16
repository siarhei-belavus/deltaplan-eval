# DeltaPlan Planning Workspace Evaluation


## Bundle


## Real Workbook Fixture


## Smoke Evidence

### Attractor-driven baseline run


### What-if scenario evidence


## Rerun Commands

Create the local Python environment:

```bash
```

Start a new Attractor run:

```bash
```

Resume a paused run:

```bash
```

## Upstream fixes exercised during implementation

- DeltaPlan MCP module now includes a batch MCP solve helper for the evaluation workflow:
- Attractor resume now re-enters a paused `wait.human` checkpoint instead of treating it as terminal failure:
