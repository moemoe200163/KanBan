#!/usr/bin/env python3
"""
mavis_worker.py — Plan C: Mavis CLI dispatcher.

Pushes events into the Kanban board's ecc_jobs.events stream for
``harness=mavis`` jobs. The script is the only writer outside the
backend itself: a normal ``harness=claude-code`` job is driven by
the safe-runner inside the container, but a Mavis job is driven
by THIS script running in the user's terminal session.

Two modes:

1. Non-interactive (preferred for batch / scripted use):
       echo '{"job_id":"ecc_abc","status":"running","message":"…"}' \\
            | python3 scripts/mavis_worker.py

2. Interactive (when the user just wants to log a quick update):
       python3 scripts/mavis_worker.py --job-id ecc_abc

Auth model:
  - X-Mavis-Token header. Reads MAVIS_DISPATCH_TOKEN env var,
    falling back to the dev default baked into docker-compose.yml.
  - API base defaults to http://127.0.0.1:8000 (the dev backend),
    override with MAVIS_API_BASE.

Limitations:
  - One event per invocation. Call the script multiple times to
    push multiple events; that mirrors how the safe-runner emits
    events one at a time and keeps each call's input simple.
  - No retries. If the network blip, re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_TOKEN = "mavis-dev-token-2026-06-12"

VALID_STATUSES = {
    "queued",
    "running",
    "paused",
    "failed",
    "review_required",
    "completed",
    "cancelled",
}


def _resolve_token() -> str:
    return os.getenv("MAVIS_DISPATCH_TOKEN") or DEFAULT_TOKEN


def _resolve_api_base() -> str:
    return os.getenv("MAVIS_API_BASE") or DEFAULT_API_BASE


def push_event(
    api_base: str,
    token: str,
    job_id: str,
    status: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a single event. Raises on transport / non-2xx errors."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Must be one of: "
            f"{sorted(VALID_STATUSES)}"
        )
    url = f"{api_base.rstrip('/')}/api/v1/ecc/jobs/{job_id}/events"
    body: dict[str, Any] = {"status": status, "message": message}
    if metadata is not None:
        body["metadata"] = metadata

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Mavis-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {e.code} from {url}: {detail}"
        ) from e


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    sys.stdout.write(f"{label}{suffix}: ")
    sys.stdout.flush()
    line = sys.stdin.readline().rstrip("\n")
    return line or default


def _interactive(args: argparse.Namespace) -> int:
    api_base = args.api_base or _resolve_api_base()
    token = args.token or _resolve_token()
    job_id = args.job_id or _prompt("Job ID", "")
    if not job_id:
        print("error: job_id is required", file=sys.stderr)
        return 2
    status = (
        args.status
        or _prompt("Status (queued/running/paused/failed/review_required/completed/cancelled)", "running")
    )
    if status not in VALID_STATUSES:
        print(
            f"error: invalid status {status!r}. Must be one of: {sorted(VALID_STATUSES)}",
            file=sys.stderr,
        )
        return 2
    message = args.message or _prompt("Message", "")

    result = push_event(api_base, token, job_id, status, message)
    print(
        f"OK job={result.get('id')} status={result.get('status')} events={len(result.get('events', []))}"
    )
    return 0


def _stdin_mode(args: argparse.Namespace) -> int:
    """Read a single JSON object from stdin and push it."""
    api_base = args.api_base or _resolve_api_base()
    token = args.token or _resolve_token()

    raw = sys.stdin.read()
    if not raw.strip():
        print("error: stdin empty; expected a JSON object", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2

    job_id = payload.get("job_id") or args.job_id
    if not job_id:
        print("error: job_id missing (pass via stdin or --job-id)", file=sys.stderr)
        return 2

    result = push_event(
        api_base,
        token,
        job_id,
        payload["status"],
        payload["message"],
        metadata=payload.get("metadata"),
    )
    print(
        f"OK job={result.get('id')} status={result.get('status')} events={len(result.get('events', []))}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan C Mavis worker — push a single ECC job event."
    )
    parser.add_argument("--job-id", help="ECC job id (e.g. ecc_abc123)")
    parser.add_argument(
        "--status",
        choices=sorted(VALID_STATUSES),
        help="New job status after this event",
    )
    parser.add_argument("--message", help="Event message (what Mavis is doing)")
    parser.add_argument(
        "--api-base",
        help="Backend base URL (default: $MAVIS_API_BASE or http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--token",
        help="X-Mavis-Token (default: $MAVIS_DISPATCH_TOKEN or dev fallback)",
    )
    args = parser.parse_args(argv)

    # Heuristic: if anything is on stdin, use stdin mode. Otherwise
    # fall back to interactive prompts (or pure flag-driven mode).
    if not sys.stdin.isatty():
        return _stdin_mode(args)
    return _interactive(args)


if __name__ == "__main__":
    sys.exit(main())
