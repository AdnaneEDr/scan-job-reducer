"""Replay scan job events deterministically, without running real scans."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import typing


def reduce_jobs(payload: dict[str, typing.Any], arguments: argparse.Namespace) -> dict[str, typing.Any]:
    """Return new job states and an audit without modifying the input."""
    # bool is a subclass of int in Python, but is not an integer here.
    def integer(value: typing.Any) -> bool:
        return type(value) is int

    def identifier(value: typing.Any) -> bool:
        return isinstance(value, str) and len(value) > 0

    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    maximum = policy.get("max_attempts")
    backoff = policy.get("backoff_seconds")
    if not integer(maximum) or maximum <= 0:
        raise ValueError("policy.max_attempts must be a positive integer")
    if not integer(backoff) or backoff < 0:
        raise ValueError("policy.backoff_seconds must be a nonnegative integer")
    definitions = payload.get("jobs")
    events = payload.get("events")
    if not isinstance(definitions, list) or not isinstance(events, list):
        raise ValueError("jobs and events must be arrays")

    jobs = {}
    for row, definition in enumerate(definitions, 1):
        if not isinstance(definition, dict) or not identifier(definition.get("job_id")):
            raise ValueError(f"jobs row {row}: job_id must be a nonempty string")
        job_id = definition["job_id"]
        if job_id in jobs:
            raise ValueError(f"jobs row {row}: duplicate job_id {job_id!r}")
        jobs[job_id] = dict(job_id=job_id, state="queued", attempts=0, next_start_at=0)

    audit = []
    seen = set()
    watermark = 0
    terminal = {"succeeded", "failed", "cancelled"}
    for row, event in enumerate(events, 1):
        reasons = []
        event = event if isinstance(event, dict) else {}
        event_id = event.get("event_id")
        job_id = event.get("job_id")
        kind = event.get("type")
        at = event.get("at")

        # Reserve IDs and update time independently of all other validation.
        if not identifier(event_id):
            reasons.append("event_id must be a nonempty string")
        elif event_id in seen:
            reasons.append("duplicate event_id")
        else:
            seen.add(event_id)
        if not integer(at) or at < 0:
            reasons.append("at must be a nonnegative integer")
        if integer(at):
            if at < watermark:
                reasons.append("time is below the global watermark")
            else:
                watermark = at

        job = None
        if not identifier(job_id):
            reasons.append("job_id must be a nonempty string")
        else:
            job = jobs.get(job_id)
            if job is None:
                reasons.append("unknown job_id")
        if not isinstance(kind, str) or kind not in {"start", "success", "fail", "cancel"}:
            reasons.append("invalid event type")

        if not reasons:
            state = job["state"]
            if state in terminal:
                reasons.append("job is terminal")
            elif kind == "start":
                if state not in {"queued", "retry_wait"}:
                    reasons.append("start requires queued or retry_wait")
                elif at < job["next_start_at"]:
                    reasons.append("retry is too early")
                else:
                    job.update(state="running", attempts=job["attempts"] + 1, next_start_at=None)
            elif kind == "cancel":
                job.update(state="cancelled", next_start_at=None)
            elif state != "running":
                reasons.append(f"{kind} requires running")
            elif kind == "success":
                job.update(state="succeeded", next_start_at=None)
            elif job["attempts"] < maximum:
                job.update(state="retry_wait", next_start_at=at + backoff)
            else:
                job.update(state="failed", next_start_at=None)

        entry = dict(row=row, event_id=event_id, accepted=not reasons,
                     reason="; ".join(reasons) if reasons else "accepted")
        if job is not None:
            entry["job"] = job.copy()
        audit.append(entry)

    accepted = sum(entry["accepted"] for entry in audit)
    return {
        "jobs": [jobs[key].copy() for key in sorted(jobs)],
        "audit": audit,
        "summary": {"accepted_events": accepted, "rejected_events": len(audit) - accepted},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay job events without running scans or sleeping.")
    parser.add_argument("--input", default="inputs/primary.json", help="UTF-8 fixture JSON")
    arguments = parser.parse_args()
    try:
        payload = json.loads(pathlib.Path(arguments.input).read_text(encoding="utf-8"))
        if isinstance(payload, dict) is False:
            raise ValueError("input must be a JSON object")
        result = reduce_jobs(payload, arguments)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
