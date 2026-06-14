#!/usr/bin/env python3
"""
mavis_worker.py — Plan C/D: Mavis CLI dispatcher.

Pushes events into the Kanban board's ecc_jobs.events stream for
``harness=mavis`` jobs, and (Plan D) registers deliverable artifacts
on the issue once a build output is ready. The script is the only
writer outside the backend itself: a normal ``harness=claude-code``
job is driven by the safe-runner inside the container, but a
Mavis job is driven by THIS script running in the user's terminal
session.

Three modes:

1. Non-interactive (preferred for batch / scripted use):
       echo '{"job_id":"ecc_abc","status":"running","message":"…"}' \\
            | python3 scripts/mavis_worker.py

2. Interactive (when the user just wants to log a quick update):
       python3 scripts/mavis_worker.py --job-id ecc_abc

3. Publish a deliverable (Plan D):
       python3 scripts/mavis_worker.py --publish \\
              --issue-id <uuid> --title "Snake game" \\
              --artifact-type build_output \\
              --file ./deliveries/snake-DEV-XXX.html \\
              --url-base http://127.0.0.1

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


def publish_artifact(
    api_base: str,
    token: str,
    issue_id: str,
    artifact_type: str,
    title: str,
    file_path: str | None,
    public_url: str | None,
    summary: str | None = None,
    source: str = "mavis",
    extra_data: dict | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Plan D: register a build output as an issue_artifacts row.

    ``file_path`` is the path on disk Mavis just wrote (relative to
    the kanban repo's ``deliveries/`` directory in the typical case
    — the devflow-nginx bind mount makes those files visible at
    ``/deliveries/<filename>``). ``public_url`` overrides the
    derived URL when Mavis knows the host should be different (e.g.
    the user opened the board via ``localhost`` rather than
    ``127.0.0.1``).
    """
    import json
    import os.path

    path_or_url: str | None = public_url
    if path_or_url is None and file_path:
        # Default: assume the kanban repo's deliveries/ directory is
        # bind-mounted to /var/www/devflow-deliveries/ inside nginx,
        # and the public URL is /deliveries/<basename>.
        path_or_url = f"http://127.0.0.1/deliveries/{os.path.basename(file_path)}"

    body: dict[str, Any] = {
        "artifactType": artifact_type,
        "title": title,
        "pathOrUrl": path_or_url,
        "source": source,
        "summary": summary or title,
    }
    if extra_data is not None:
        body["extraData"] = extra_data
    if job_id is not None:
        body["jobId"] = job_id

    url = f"{api_base.rstrip('/')}/api/v1/issues/{issue_id}/artifacts"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Plan D writes go through the regular user-auth path,
            # not the mavis event-push token. The dev bypass is on
            # by default, but if it's not, fall back to MAVIS_DISPATCH_TOKEN.
            "X-Mavis-Token": token,
            "Authorization": f"Bearer {token}",
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


def _publish_mode(args: argparse.Namespace) -> int:
    """Plan D: register a deliverable artifact on an issue."""
    api_base = args.api_base or _resolve_api_base()
    token = args.token or _resolve_token()

    if not args.issue_id:
        print("error: --issue-id is required in --publish mode", file=sys.stderr)
        return 2
    if not args.title:
        print("error: --title is required in --publish mode", file=sys.stderr)
        return 2
    if not args.file_path and not args.public_url:
        print(
            "error: at least one of --file / --public-url is required",
            file=sys.stderr,
        )
        return 2

    import os
    extra_data: dict[str, Any] = {}
    if args.file_path:
        try:
            extra_data["sizeBytes"] = os.path.getsize(args.file_path)
        except OSError:
            pass

    result = publish_artifact(
        api_base,
        token,
        issue_id=args.issue_id,
        artifact_type=args.artifact_type,
        title=args.title,
        file_path=args.file_path,
        public_url=args.public_url,
        summary=args.message,
        extra_data=extra_data or None,
        job_id=args.job_id,
    )
    print(
        f"OK artifact={result.get('id')} type={result.get('artifactType')} url={result.get('pathOrUrl')}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan C/D Mavis worker — push a single ECC job event or register a deliverable."
    )
    parser.add_argument("--job-id", help="ECC job id (e.g. ecc_abc123)")
    parser.add_argument(
        "--status",
        choices=sorted(VALID_STATUSES),
        help="New job status after this event",
    )
    parser.add_argument("--message", help="Event message (what Mavis is doing)")

    # Plan D: --publish mode flips the script from "push event" to
    # "register deliverable on issue". The two modes are mutually
    # exclusive in practice, but we don't enforce that — if both
    # are set, --publish wins.
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish a deliverable artifact instead of pushing a job event (Plan D)",
    )
    parser.add_argument(
        "--issue-id",
        help="Issue id (for --publish mode, where to attach the artifact)",
    )
    parser.add_argument(
        "--title",
        help="Artifact title (for --publish mode)",
    )
    parser.add_argument(
        "--artifact-type",
        default="build_output",
        help="Artifact type (default: build_output)",
    )
    parser.add_argument(
        "--file",
        dest="file_path",
        help="Path to the deliverable file on disk (for --publish mode)",
    )
    parser.add_argument(
        "--public-url",
        dest="public_url",
        help="Override the public URL of the deliverable (for --publish mode)",
    )
    parser.add_argument(
        "--api-base",
        help="Backend base URL (default: $MAVIS_API_BASE or http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--token",
        help="X-Mavis-Token (default: $MAVIS_DISPATCH_TOKEN or dev fallback)",
    )
    args = parser.parse_args(argv)

    if args.publish:
        return _publish_mode(args)

    # Heuristic: if anything is on stdin, use stdin mode. Otherwise
    # fall back to interactive prompts (or pure flag-driven mode).
    if not sys.stdin.isatty():
        return _stdin_mode(args)
    return _interactive(args)


if __name__ == "__main__":
    sys.exit(main())
