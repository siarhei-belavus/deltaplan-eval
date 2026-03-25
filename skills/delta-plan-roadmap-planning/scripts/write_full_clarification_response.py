#!/usr/bin/env python3
"""
Write one complete clarification response for the latest open request.

AICODE-NOTE: Clarification durability begins only after the full required answer
set is available; this helper validates completeness before writing any response
artifact.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from planning_workspace_lib import touch_generated_artifact, utc_now, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a complete clarification response artifact.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--answers-file", required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def request_number(path: Path) -> int:
    match = re.match(r"request-(\d+)\.json", path.name)
    return int(match.group(1)) if match else -1


def latest_open_request(clarifications_dir: Path) -> Path:
    candidates = []
    for path in clarifications_dir.glob("request-*.json"):
        payload = load_json(path)
        if payload.get("status") == "open":
            candidates.append(path)
    if not candidates:
        raise SystemExit("No open clarification request exists for this scenario.")
    return sorted(candidates, key=request_number)[-1]


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    clarifications_dir = run_dir / "scenarios" / args.scenario_id / "clarifications"
    request_path = latest_open_request(clarifications_dir)
    request_payload = load_json(request_path)
    answers_payload = load_json(Path(args.answers_file).resolve())

    if answers_payload.get("requestId") != request_payload.get("requestId"):
        raise SystemExit("answers-file requestId does not match the latest open clarification request.")
    if answers_payload.get("scenarioId") != args.scenario_id:
        raise SystemExit("answers-file scenarioId does not match --scenario-id.")

    request_questions = {question["questionId"]: question for question in request_payload.get("questions", [])}
    answers_by_id: dict[str, dict[str, Any]] = {}
    for item in answers_payload.get("answers", []):
        question_id = item.get("questionId")
        if question_id in answers_by_id:
            raise SystemExit(f"Duplicate answer supplied for {question_id}.")
        if question_id not in request_questions:
            raise SystemExit(f"Unknown questionId in answers-file: {question_id}")
        answers_by_id[question_id] = item

    missing_required = [
        question_id
        for question_id, question in request_questions.items()
        if question.get("required", True) and question_id not in answers_by_id
    ]
    if missing_required:
        raise SystemExit(f"Missing required clarification answers: {', '.join(missing_required)}")

    response_path = clarifications_dir / f"{request_payload['requestId'].replace('request', 'response')}.json"
    response_payload = {
        "requestId": request_payload["requestId"],
        "scenarioId": args.scenario_id,
        "status": "submitted",
        "submittedAt": utc_now(),
        "answers": [
            {
                "questionId": question_id,
                "status": "answered",
                "value": answers_by_id[question_id]["value"],
                "source": "user",
                "note": answers_by_id[question_id].get("note"),
            }
            for question_id in request_questions
            if question_id in answers_by_id
        ],
    }
    write_json(response_path, response_payload)
    touch_generated_artifact(run_dir, response_path)

    request_payload["status"] = "answered"
    write_json(request_path, request_payload)

    print(f"CLARIFICATION_RESPONSE={response_path}")
    print("STATE=answered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
