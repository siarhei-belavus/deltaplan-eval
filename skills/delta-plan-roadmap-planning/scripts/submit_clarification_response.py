#!/usr/bin/env python3
"""
Write a structured clarification response for the latest open request.

AICODE-NOTE: The skill writes answers through this helper so resume stays file-backed and the workflow never has to scrape chat text for planning facts.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from planning_workspace_lib import load_scenario_status, utc_now, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write clarification answers into response-*.json.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", default="baseline")
    parser.add_argument("--answers-file", required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return __import__("json").loads(path.read_text())


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    scenario_dir = run_dir / "scenarios" / args.scenario_id
    scenario_status = load_scenario_status(run_dir, args.scenario_id)
    latest_request_ref = scenario_status.get("latestClarificationRequestPath")
    if not latest_request_ref:
        raise SystemExit("No open clarification request is recorded in scenario-status.json")

    request_path = run_dir / latest_request_ref
    request_payload = load_json(request_path)
    answers_payload = load_json(Path(args.answers_file).resolve())

    if isinstance(answers_payload, dict) and "answers" in answers_payload:
        answers = answers_payload["answers"]
    elif isinstance(answers_payload, dict):
        by_field_path = answers_payload
        answers = []
        for question in request_payload["questions"]:
            if question["fieldPath"] in by_field_path:
                answers.append(
                    {
                        "questionId": question["questionId"],
                        "status": "answered",
                        "value": by_field_path[question["fieldPath"]],
                        "source": "user",
                        "note": None,
                    }
                )
    else:
        raise SystemExit("answers-file must contain either {'answers': [...]} or a fieldPath->value object.")

    response_path = scenario_dir / "clarifications" / f"{request_payload['requestId'].replace('request', 'response')}.json"
    response_payload = {
        "requestId": request_payload["requestId"],
        "scenarioId": args.scenario_id,
        "status": "submitted",
        "submittedAt": utc_now(),
        "answers": answers,
    }
    write_json(response_path, response_payload)
    print(f"CLARIFICATION_RESPONSE={response_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
