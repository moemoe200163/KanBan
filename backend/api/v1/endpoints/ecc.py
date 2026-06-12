from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from uuid import uuid4
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID, assert_board_id_allowed
from api.v1.auth_deps import require_auth

# NOTE: backend.db imports are done lazily (inside functions that need them)
# to avoid import-time failures when running with PYTHONPATH=backend from
# within the backend/ package directory.

router = APIRouter()

VALID_COMMANDS = {
    "/loop-reset",
    "/loop-start",
    "/harness-pause",
    "/quality-gate --verify",
    "/release-ready --merge",
}
VALID_PROFILES = {"frontend", "backend", "security", "refactor", "debug", "general"}
VALID_HARNESSES = {"safe-runner", "claude-code", "codex", "cursor", "opencode", "gemini", "mavis"}
VALID_EXECUTION_MODES = {"safe-runner", "api-agent", "cli-agent", "shadow"}


class ECCDispatchRequest(BaseModel):
    issue_id: str = Field(..., min_length=1)
    issue_key: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    board_id: str = Field(default=DEFAULT_BOARD_ID, description="Board this dispatch belongs to")
    profile: str = Field(default="general")
    harness: str = Field(default="claude-code")
    # MVP 2: Provider/Model execution config
    provider: Optional[str] = Field(default=None, description="LLM provider id (e.g., openai, anthropic)")
    model: Optional[str] = Field(default=None, description="Model id (e.g., gpt-4o, claude-sonnet-4-20250514)")
    execution_mode: Optional[str] = Field(default=None, description="Execution mode: safe-runner, api-agent, cli-agent")
    required_role: Optional[str] = Field(default=None, description="Required agent role for role-based dispatch (e.g., backend-dev, frontend-dev)")


ECCJobStatus = Literal["queued", "running", "paused", "failed", "review_required", "completed", "cancelled"]


class ECCJobEvent(BaseModel):
    timestamp: str
    status: ECCJobStatus
    message: str


class ECCDispatchJob(BaseModel):
    id: str
    issue_id: str
    issue_key: str
    command: str
    profile: str
    harness: str
    status: ECCJobStatus
    created_at: str
    updated_at: str
    board_id: str = DEFAULT_BOARD_ID
    message: Optional[str] = None
    events: List[ECCJobEvent] = Field(default_factory=list)
    # MVP 2: Provider/Model execution config
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_mode: Optional[str] = None


class ECCJobStatusUpdate(BaseModel):
    status: ECCJobStatus
    message: Optional[str] = None


# In-memory dict for backwards-compatible read operations
_jobs: Dict[str, ECCDispatchJob] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _broadcast_job_update(job_id: str, job_data: dict) -> None:
    """Broadcast job update via WebSocket if available."""
    try:
        # Import here to avoid circular imports and path issues
        from .ws import job_manager
        await job_manager.broadcast_to_job(job_id, {
            "type": "job_update",
            "job": job_data
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to broadcast job update: {e}")


async def _execute_safe_runner(job_id: str) -> None:
    """Run the P0-safe execution loop without invoking real AI/CLI adapters.

    Thin wrapper around the shared :mod:`core.execution.safe_runner`
    so the dispatch endpoint and the adapter layer both use the same
    proven path.
    """
    from core.execution.safe_runner import SafeRunnerDeps, run_safe_execution

    await run_safe_execution(
        job_id,
        SafeRunnerDeps(
            jobs=_jobs,
            transition_job=_transition_job,
            save_job_to_db=_save_job_to_db,
            broadcast_job_update=_broadcast_job_update,
        ),
    )


def _complete_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if not job:
        return

    _transition_job(job, "running", "Dispatch accepted by local control plane")


def _transition_job(job: ECCDispatchJob, status: ECCJobStatus, message: str) -> ECCDispatchJob:
    now = _utc_now()
    job.status = status
    job.updated_at = now
    job.message = message
    job.events.append(ECCJobEvent(timestamp=now, status=status, message=message))
    return job


# Map of ECC terminal status -> next issue status. Failure / cancel
# intentionally has no entry: the issue stays where it is so a human can
# decide whether to retry, block, or re-prioritise.
_ECC_ISSUE_PROMOTION: dict[str, str] = {
    "review_required": "human_review",
    "completed": "done",
}


async def _auto_promote_issue(job) -> None:
    """Push the issue linked to a finished job to the next lane.

    - `review_required` -> `human_review`  (PR / output ready for inspection)
    - `completed`       -> `done`          (agent finished and self-validated)
    - `failed` / `cancelled` / `running` / `paused` / `queued` -> no-op

    The issue update is best-effort: if it fails (e.g. issue was deleted)
    we log and move on so the job update itself isn't blocked.
    """
    next_status = _ECC_ISSUE_PROMOTION.get(job.status)
    if not next_status:
        return

    issue_id = getattr(job, "issue_id", None)
    if not issue_id:
        return

    try:
        from db import repository as repo
        updated = await repo.update_issue_status(issue_id, next_status)
        if not updated:
            import logging
            logging.getLogger(__name__).warning(
                "[ECC] auto-promote: issue %s not found for job %s",
                issue_id, job.id,
            )
            return
        import logging
        logging.getLogger(__name__).info(
            "[ECC] auto-promote: job %s -> %s; issue %s -> %s",
            job.id, job.status, issue_id, next_status,
        )

        # Write a Mavis-style cycle report alongside the auto-promote so
        # the leader has the plan / progress log / deliverable on the
        # review surface. Only fire once per job — for ``completed`` we
        # get the full event list, for ``review_required`` we record
        # the partial result and let the leader decide.
        try:
            await _write_auto_cycle_report(job, next_status)
        except Exception as cr_exc:
            logging.getLogger(__name__).warning(
                "[ECC] auto-cycle-report failed for job %s: %s", job.id, cr_exc,
            )

        # Broadcast the change so the front-end can move the card live.
        try:
            from main import manager
            await manager.broadcast({
                "type": "issue_updated",
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "payload": {
                    "issueId": issue_id,
                    "changes": {
                        "status": next_status,
                    },
                },
            })
        except Exception as broadcast_exc:
            import logging
            logging.getLogger(__name__).warning(
                "[ECC] auto-promote broadcast failed: %s", broadcast_exc,
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception(
            "[ECC] auto-promote failed for job %s issue %s: %s",
            job.id, issue_id, exc,
        )


async def _write_auto_cycle_report(job, next_status: str) -> None:
    """Emit a Mavis-style cycle report when ECC auto-promotes a job.

    Called from :func:`_auto_promote_issue` on every terminal-success
    transition. The plan is a templated one-liner that names the
    command + profile; the progress log mirrors the ECC job's event
    list so a leader reviewing the report can see exactly what the
    runner did. The verdict is ``auto_passed`` for ``completed`` and
    ``pending`` for ``review_required`` (the leader is expected to
    flip it to ``pass`` or ``fail`` after looking at the report).
    """
    import logging
    import uuid as _uuid

    issue_id = getattr(job, "issue_id", None)
    if not issue_id:
        return

    verdict = "auto_passed" if next_status == "done" else "pending"
    events = [
        {"ts": e.timestamp, "status": e.status, "message": e.message}
        for e in getattr(job, "events", [])
    ]
    last_message = getattr(job, "message", "") or ""
    plan = (
        f"Auto-run via {getattr(job, 'harness', 'safe-runner')}: "
        f"`{getattr(job, 'command', '?')}` (profile={getattr(job, 'profile', '?')}). "
        f"Linked issue {getattr(job, 'issue_key', '?')} on lane progression."
    )
    report = {
        "id": f"cr_{_uuid.uuid4().hex[:16]}",
        "issue_id": issue_id,
        "job_id": job.id,
        "author_id": None,
        "author_name": "auto-promote",
        "plan": plan,
        "progress_log": events,
        "deliverable_summary": last_message or None,
        "verdict": verdict,
        "verdict_reason": (
            "auto-promoted from ECC job; awaiting leader review"
            if verdict == "pending"
            else "auto-promoted; safe-runner reported completed"
        ),
        "board_id": getattr(job, "board_id", "board-default"),
    }
    from db import repository as repo
    await repo.upsert_cycle_report(report)
    logging.getLogger(__name__).info(
        "[ECC] auto cycle-report: job %s -> report %s verdict=%s",
        job.id, report["id"], verdict,
    )


async def _transition_and_persist(
    job: ECCDispatchJob,
    status: ECCJobStatus,
    message: str,
) -> ECCDispatchJob:
    """Transition a job, persist, and trigger auto-promote of the linked issue.

    The safe runner and other internal callers used to mutate job state
    via ``_transition_job`` (sync) and only the public ``PATCH`` endpoint
    persisted. We consolidate that here so any transition — internal
    or external — fans out to the DB, the linked issue, and the
    WebSocket broadcast. The original sync ``_transition_job`` is kept
    as a primitive for callers that explicitly want to defer persistence
    (e.g. tests).
    """
    updated = _transition_job(job, status, message)
    await _save_job_to_db(updated)
    return updated


async def _save_job_to_db(job: ECCDispatchJob) -> None:
    """Persist job state through the repository.

    Errors are logged and swallowed so a DB failure never breaks the
    in-memory job flow. After a successful persist we also auto-promote
    the linked issue when the new status is a terminal success state
    (see :func:`_auto_promote_issue`).
    """
    from db import repository as repo

    await repo.upsert_job({
        "id": job.id,
        "board_id": job.board_id,
        "issue_id": job.issue_id,
        "issue_key": job.issue_key,
        "command": job.command,
        "profile": job.profile,
        "harness": job.harness,
        "status": job.status,
        "message": job.message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "events": [e.model_dump() for e in job.events],
    })

    # Side effect: when the safe runner (or any internal caller) writes
    # a terminal success status, push the linked issue forward in the
    # Kanban flow. Failure / cancel leave the issue in place.
    await _auto_promote_issue(job)


async def load_jobs_from_db() -> None:
    """Load all jobs from database into _jobs dict on startup."""
    global _jobs
    try:
        from db import repository as repo
        rows = await repo.load_all_jobs_into_memory()
        _jobs = {}
        for row in rows:
            row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
            _jobs[row["id"]] = ECCDispatchJob(**row)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to load jobs from DB: {e}")
        _jobs = {}


async def _register_job_from_db(job_id: str) -> None:
    """Load a single job from DB into the in-memory _jobs registry.

    Called by the handoff dispatch path so that a job created via
    ``create_job_for_handoff`` is visible to the safe-runner before
    the background task starts.
    """
    if job_id in _jobs:
        return  # already registered
    try:
        from db import repository as repo
        row = await repo.get_job(job_id)
        if row:
            row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
            _jobs[row["id"]] = ECCDispatchJob(**row)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to register job {job_id}: {e}")


@router.post("/ecc/dispatch")
async def dispatch_ecc_command(
    request: ECCDispatchRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_auth),
):
    """
    Dispatch an ECC command to the control plane.

    Requires JWT authentication (via Authorization header or ?token= query param).
    """
    import os

    # Validate board_id
    try:
        assert_board_id_allowed(request.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    command_name = request.command.split(" --profile=", 1)[0]
    if command_name not in VALID_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Invalid ECC command: {request.command}")

    if request.profile not in VALID_PROFILES:
        raise HTTPException(status_code=400, detail=f"Invalid profile: {request.profile}")

    if request.harness not in VALID_HARNESSES:
        raise HTTPException(status_code=400, detail=f"Invalid harness: {request.harness}")

    # MVP 2: Validate execution_mode if provided
    if request.execution_mode and request.execution_mode not in VALID_EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid execution_mode: {request.execution_mode}")

    # MVP 2: Determine effective execution mode
    # Check ALLOW_REAL_LLM_EXECUTION gate
    allow_real_llm = os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true"
    effective_execution_mode = request.execution_mode or "safe-runner"

    # If real LLM execution is not allowed, force safe-runner
    if effective_execution_mode in ("api-agent", "cli-agent") and not allow_real_llm:
        effective_execution_mode = "safe-runner"

    # Plan C: shadow mode is a Mavis-specific execution path. Mavis is
    # event-driven (the CLI pushes events into the ecc_jobs.events
    # stream), so we do NOT spawn a background task or push the job
    # into the orchestrator queue. The job sits in ``queued`` until
    # the Mavis CLI writes its first event via
    # ``POST /api/v1/ecc/jobs/{job_id}/events``. The harness check
    # makes sure only harness=mavis jobs are allowed to take this
    # path — anything else is treated as a misconfigured dispatch.
    if effective_execution_mode == "shadow" and request.harness != "mavis":
        raise HTTPException(
            status_code=400,
            detail=(
                f"execution_mode=shadow requires harness=mavis, got "
                f"harness={request.harness}"
            ),
        )

    now = _utc_now()

    # Build initial message based on execution mode
    if effective_execution_mode == "safe-runner":
        initial_message = "Queued for safe runner execution"
    elif effective_execution_mode == "api-agent":
        initial_message = f"Queued for API agent execution (provider={request.provider or 'default'}, model={request.model or 'default'})"
    elif effective_execution_mode == "shadow":
        initial_message = (
            f"Queued for Mavis shadow execution — waiting for CLI to push events"
        )
    else:
        initial_message = f"Queued for CLI agent execution (harness={request.harness})"

    job = ECCDispatchJob(
        id=f"ecc_{uuid4().hex[:12]}",
        issue_id=request.issue_id,
        issue_key=request.issue_key,
        command=request.command,
        profile=request.profile,
        harness=request.harness,
        status="queued",
        created_at=now,
        updated_at=now,
        board_id=request.board_id,
        message=initial_message,
        events=[
            ECCJobEvent(
                timestamp=now,
                status="queued",
                message=initial_message,
            )
        ],
        # MVP 2: Provider/Model execution config
        provider=request.provider,
        model=request.model,
        execution_mode=effective_execution_mode,
    )
    _jobs[job.id] = job

    # Persist to database
    await _save_job_to_db(job)

    # MVP 2: Add event if real execution was blocked
    if request.execution_mode and request.execution_mode != effective_execution_mode:
        _transition_job(job, "queued", f"Real execution disabled; using safe runner instead")
        await _save_job_to_db(job)

    # P0 guardrail: dispatch returns immediately and safe runner emits deterministic events.
    # MVP 2: Use effective execution mode
    if effective_execution_mode == "safe-runner":
        background_tasks.add_task(_execute_safe_runner, job.id)
    elif effective_execution_mode == "shadow":
        # Plan C: Mavis shadow mode is purely event-driven. The CLI is
        # responsible for pushing events via the dedicated endpoint
        # below. We deliberately do not spawn a background task or
        # push the job into the orchestrator queue — both would
        # create a phantom "worker" competing with the real Mavis
        # process (which is the user's terminal session, not a
        # long-running daemon). The job sits in ``queued`` with the
        # initial message set above until the CLI writes its first
        # event.
        pass
    else:
        # Create an AgentRun in the runtime queue for the orchestrator.
        # The run sits in "pending" until a worker claims it.
        try:
            from core.runtime.orchestrator import create_run_for_dispatch
            run = await create_run_for_dispatch(
                board_id=request.board_id,
                issue_id=request.issue_id,
                issue_key=request.issue_key,
                command=request.command,
                profile=request.profile,
                harness=request.harness,
                provider=request.provider,
                model=request.model,
                job_id=job.id,
                required_role=request.required_role,
            )
            _transition_job(job, "queued", f"Run {run['id']} created in runtime queue")
            await _save_job_to_db(job)
        except Exception as e:
            _transition_job(job, "failed", f"Failed to create runtime run: {e}")
            await _save_job_to_db(job)

    return job


@router.get("/ecc/jobs")
async def list_ecc_jobs(
    board_id: Optional[str] = Query(
        DEFAULT_BOARD_ID,
        description="Filter jobs by board. Defaults to the default board.",
    ),
    issue_id: Optional[str] = Query(
        None,
        description="Filter jobs to a single issue id. Returns all jobs when omitted.",
    ),
    status: Optional[str] = Query(
        None,
        description="Filter jobs by ECC status (queued, running, paused, failed, review_required, completed, cancelled).",
    ),
    limit: Optional[int] = Query(
        None,
        description="Maximum number of jobs to return. Defaults to all.",
        ge=1,
        le=500,
    ),
):
    """List ECC jobs, optionally filtered to a single issue or a single status."""
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        from db import repository as repo
        rows = await repo.list_jobs(issue_id=issue_id, status=status, board_id=board_id, limit=limit)
        jobs = []
        for row in rows:
            row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
            job = ECCDispatchJob(**row)
            _jobs[job.id] = job
            jobs.append(job)
    except Exception:
        filtered = list(_jobs.values())
        if board_id:
            filtered = [j for j in filtered if j.board_id == board_id]
        if issue_id:
            filtered = [j for j in filtered if j.issue_id == issue_id]
        if status:
            filtered = [j for j in filtered if j.status == status]
        jobs = filtered

    jobs = sorted(jobs, key=lambda job: job.created_at, reverse=True)
    if limit:
        jobs = jobs[:limit]
    return {"jobs": [job.model_dump() for job in jobs], "total": len(jobs)}


@router.get("/ecc/jobs/{job_id}")
async def get_ecc_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        try:
            from db import repository as repo
            row = await repo.get_job(job_id)
            if row:
                row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
                job = ECCDispatchJob(**row)
                _jobs[job.id] = job
        except Exception:
            job = None
    if not job:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")
    try:
        assert_board_id_allowed(job.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return job


@router.patch("/ecc/jobs/{job_id}")
async def update_ecc_job(job_id: str, request: ECCJobStatusUpdate, current_user: dict = Depends(require_auth)):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    message = request.message or f"Job marked {request.status}"
    updated_job = await _transition_and_persist(job, request.status, message)

    return updated_job


@router.post("/ecc/jobs/{job_id}/cancel")
async def cancel_ecc_job(job_id: str, current_user: dict = Depends(require_auth)):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in '{job.status}' state")

    updated_job = _transition_job(job, "cancelled", "Job cancelled by control plane")

    # Persist to database
    await _save_job_to_db(updated_job)

    # If this job has linked AgentRuns (real execution path), cancel them too.
    try:
        from db.repository import find_active_runs_for_job_id
        from core.runtime.orchestrator import cancel_run as orch_cancel_run
        active_runs = await find_active_runs_for_job_id(job_id)
        for run in active_runs:
            await orch_cancel_run(run["id"])
            import logging
            logging.getLogger(__name__).info(
                "Cancelled AgentRun %s linked to ECC job %s", run["id"], job_id,
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to cancel linked runs for job %s: %s", job_id, exc,
        )

    return updated_job


# Plan C: Mavis shadow-worker event push endpoint.
# ---------------------------------------------------------------------------
# The Mavis CLI (running in the user's terminal session) is responsible
# for telling the board what it's doing. Instead of opening a websocket
# or polling, the CLI calls this endpoint to append an event to the
# job's events stream and (optionally) transition the job's status.
#
# Auth model: a shared secret in the ``X-Mavis-Token`` header. The
# secret is read from the ``MAVIS_DISPATCH_TOKEN`` environment variable
# on the backend. The CLI is configured with the same value. We also
# require that the job's harness is ``mavis`` — even with a valid
# shared secret, this endpoint refuses to write to a job owned by a
# different harness (defence in depth: the secret alone is not enough).
# ---------------------------------------------------------------------------


class MavisEventRequest(BaseModel):
    status: ECCJobStatus = Field(
        ...,
        description="New job status after this event is applied",
    )
    message: str = Field(..., min_length=1, max_length=512)
    metadata: Optional[dict] = Field(
        default=None,
        description="Optional structured metadata for the Worker tab UI",
    )


@router.post("/ecc/jobs/{job_id}/events")
async def push_mavis_event(
    job_id: str,
    body: MavisEventRequest,
    request: Request,
):
    """Plan C: Mavis CLI pushes a progress event into the ecc_jobs
    events stream and transitions the job's status.

    Authenticated by ``X-Mavis-Token`` matching the ``MAVIS_DISPATCH_TOKEN``
    environment variable. The job's harness must be ``mavis``.
    """
    # Read the auth header from the raw Request — FastAPI's automatic
    # parameter-to-header binding via ``x_mavis_token: Optional[str] = None``
    # is unreliable for dashes/underscores in the header name. Reading
    # directly from request.headers sidesteps the whole binding layer.
    x_mavis_token = request.headers.get("x-mavis-token") or request.headers.get("X-Mavis-Token")

    expected_token = os.getenv("MAVIS_DISPATCH_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "MAVIS_DISPATCH_TOKEN not configured on the backend; "
                "shadow-worker event push is disabled"
            ),
        )
    if not x_mavis_token or x_mavis_token != expected_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-Mavis-Token",
        )

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404, detail=f"ECC job '{job_id}' not found"
        )

    if job.harness != "mavis":
        raise HTTPException(
            status_code=403,
            detail=(
                f"Refusing to write to non-mavis job: harness={job.harness}. "
                f"This endpoint is for harness=mavis jobs only."
            ),
        )

    if job.status in {"completed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot push events to job in '{job.status}' state"
            ),
        )

    # Append the event. We do this BEFORE _transition_job so the
    # transition message is also captured as a structured event
    # (the transition itself emits one — see _transition_job).
    if body.metadata is not None:
        # We don't persist arbitrary metadata yet (the events column
        # is just timestamp/status/message). Stash a marker so the
        # Worker tab UI can render the payload later.
        event_message = f"{body.message} [+meta keys={','.join(body.metadata.keys())}]"
    else:
        event_message = body.message

    updated = await _transition_and_persist(job, body.status, event_message)

    # Plan F: notify live-board subscribers. The per-job WS channel
    # already covers clients tracking this specific job; the
    # per-issue channel is what the IssueDetail panel listens on
    # so it can refetch events / artifacts / cycle-reports in one
    # place. Best-effort — a broken WS doesn't fail the push.
    try:
        from api.v1.endpoints.ws import broadcast_issue_updated
        await broadcast_issue_updated(job.issue_id, "event")
    except Exception as ws_exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Plan F: mavis event broadcast failed for %s: %s",
            job.issue_id, ws_exc,
        )
    return updated


RETRYABLE_TERMINAL_STATUSES = {"failed", "cancelled", "review_required"}


@router.post("/ecc/jobs/{job_id}/retry")
async def retry_ecc_job(job_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(require_auth)):
    """Create a new job that re-runs the same payload as `job_id`.

    The source job must be in a retryable terminal state. The new job
    starts at `queued` and runs through the same safe runner.
    """
    source = _jobs.get(job_id)
    if not source:
        try:
            from db import repository as repo
            row = await repo.get_job(job_id)
            if row:
                row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
                source = ECCDispatchJob(**row)
                _jobs[source.id] = source
        except Exception:
            source = None
    if not source:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    try:
        assert_board_id_allowed(source.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if source.status not in RETRYABLE_TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot retry job in '{source.status}' state. "
                f"Retryable states: {sorted(RETRYABLE_TERMINAL_STATUSES)}"
            ),
        )

    now = _utc_now()
    new_job = ECCDispatchJob(
        id=f"ecc_{uuid4().hex[:12]}",
        issue_id=source.issue_id,
        issue_key=source.issue_key,
        command=source.command,
        profile=source.profile,
        harness=source.harness,
        board_id=source.board_id,
        status="queued",
        created_at=now,
        updated_at=now,
        message=f"Retried from job {source.id}",
        events=[
            ECCJobEvent(
                timestamp=now,
                status="queued",
                message=f"Retried from job {source.id}",
            )
        ],
    )
    _jobs[new_job.id] = new_job
    await _save_job_to_db(new_job)

    background_tasks.add_task(_execute_safe_runner, new_job.id)

    return new_job
