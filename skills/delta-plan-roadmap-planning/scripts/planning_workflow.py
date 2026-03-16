#!/usr/bin/env python3
"""
Convenience wrapper for starting and resuming the Attractor planning workflow.

AICODE-NOTE: This wrapper keeps the human-facing entrypoint short while the durable workflow state still lives entirely in the run workspace.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from planning_workspace_lib import RUNS_SUBDIR, slugify, utc_stamp


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "workflows" / "attractor" / "delta-plan-planning" / "pipeline.dot"
DEFAULT_MCP_JAR = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start or resume the DeltaPlan planning workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--workspace-root", required=True)
    start.add_argument("--input", required=True)
    start.add_argument("--scenario-id", default="baseline")
    start.add_argument("--mcp-jar", default=str(DEFAULT_MCP_JAR))

    resume = subparsers.add_parser("resume")
    resume.add_argument("--run-dir", required=True)
    resume.add_argument("--scenario-id", default="baseline")
    resume.add_argument("--mcp-jar", default=str(DEFAULT_MCP_JAR))

    status = subparsers.add_parser("status")
    status.add_argument("--run-dir", required=True)
    return parser.parse_args()


def run_attractor(run_dir: Path, *, scenario_id: str, input_path: Path | None, mcp_jar: Path, resume: bool) -> int:
    command = [
        "attractor",
        "run",
        str(PIPELINE),
        "--logs-dir",
        str(run_dir / "attractor"),
        "--set",
        f"run_dir={run_dir}",
        "--set",
        f"scenario_id={scenario_id}",
        "--set",
        f"skill_root={ROOT / 'skills' / 'delta-plan-roadmap-planning'}",
        "--set",
        f"mcp_jar={mcp_jar}",
        "--set",
        f"python_bin={ROOT / '.venv' / 'bin' / 'python'}",
    ]
    if input_path is not None:
        command.extend(["--set", f"input_path={input_path}"])
    if resume:
        command.extend(["--resume-from", str(run_dir / "attractor")])
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    args = parse_args()
    if args.command == "status":
        print((Path(args.run_dir).resolve() / "status.json").read_text())
        return 0

    if args.command == "start":
        input_path = Path(args.input).resolve()
        workspace_root = Path(args.workspace_root).resolve()
        run_dir = workspace_root / RUNS_SUBDIR / f"{utc_stamp()}-{slugify(input_path.stem)}"
        print(f"RUN_DIR={run_dir}")
        return run_attractor(
            run_dir,
            scenario_id=args.scenario_id,
            input_path=input_path,
            mcp_jar=Path(args.mcp_jar).resolve(),
            resume=False,
        )

    run_dir = Path(args.run_dir).resolve()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    primary_input = run_dir / manifest["primaryInputArtifact"]
    return run_attractor(
        run_dir,
        scenario_id=args.scenario_id,
        input_path=primary_input,
        mcp_jar=Path(args.mcp_jar).resolve(),
        resume=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
