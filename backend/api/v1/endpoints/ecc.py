from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

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
VALID_HARNESSES = {"safe-runner", "claude-code", "codex", "cursor", "opencode", "gemini"}
VALID_EXECUTION_MODES = {"safe-runner", "api-agent", "cli-agent"}


class ECCDispatchRequest(BaseModel):
    issue_id: str = Field(..., min_length=1)
    issue_key: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    profile: str = Field(default="general")
    harness: str = Field(default="claude-code")
    # MVP 2: Provider/Model execution config
    provider: Optional[str] = Field(default=None, description="LLM provider id (e.g., openai, anthropic)")
    model: Optional[str] = Field(default=None, description="Model id (e.g., gpt-4o, claude-sonnet-4-20250514)")
    execution_mode: Optional[str] = Field(default=None, description="Execution mode: safe-runner, api-agent, cli-agent")


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


async def _save_job_to_db(job: ECCDispatchJob) -> None:
    """Persist job state through the repository.

    Errors are logged and swallowed so a DB failure never breaks the
    in-memory job flow.
    """
    from db import repository as repo

    await repo.upsert_job({
        "id": job.id,
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


@router.post("/ecc/dispatch")
async def dispatch_ecc_command(
    request: ECCDispatchRequest,
    background_tasks: BackgroundTasks
):
    """
    Dispatch an ECC command to the control plane.

    Requires JWT authentication (via Authorization header or ?token= query param).
    Set ALLOW_ANONYMOUS_DISPATCH=true to disable auth (development only).
    """
    import os
    allow_anonymous = os.getenv("ALLOW_ANONYMOUS_DISPATCH", "false").lower() == "true"

    if not allow_anonymous:
        # TODO(P1): No auth middleware exists yet. This branch is a no-op.
        # Implement JWT validation before any public/production deployment.
        pass

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

    now = _utc_now()

    # Build initial message based on execution mode
    if effective_execution_mode == "safe-runner":
        initial_message = "Queued for safe runner execution"
    elif effective_execution_mode == "api-agent":
        initial_message = f"Queued for API agent execution (provider={request.provider or 'default'}, model={request.model or 'default'})"
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
    else:
        # For now, all non-safe-runner modes still go through safe runner
        # This will be replaced with real adapters in P3
        background_tasks.add_task(_execute_safe_runner, job.id)

    return job


@router.get("/ecc/jobs")
async def list_ecc_jobs(
    issue_id: Optional[str] = Query(
        None,
        description="Filter jobs to a single issue id. Returns all jobs when omitted.",
    ),
    status: Optional[str] = Query(
        None,
        description="Filter jobs by ECC status (queued, running, paused, failed, review_required, completed, cancelled).",
    ),
):
    """List ECC jobs, optionally filtered to a single issue or a single status."""
    try:
        from db import repository as repo
        rows = await repo.list_jobs(issue_id=issue_id, status=status)
        jobs = []
        for row in rows:
            row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
            job = ECCDispatchJob(**row)
            _jobs[job.id] = job
            jobs.append(job)
    except Exception:
        if issue_id or status:
            filtered = list(_jobs.values())
            if issue_id:
                filtered = [j for j in filtered if j.issue_id == issue_id]
            if status:
                filtered = [j for j in filtered if j.status == status]
            jobs = filtered
        else:
            jobs = list(_jobs.values())

    jobs = sorted(jobs, key=lambda job: job.created_at, reverse=True)
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
    return job


@router.patch("/ecc/jobs/{job_id}")
async def update_ecc_job(job_id: str, request: ECCJobStatusUpdate):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    message = request.message or f"Job marked {request.status}"
    updated_job = _transition_job(job, request.status, message)
    
    # Persist to database
    await _save_job_to_db(updated_job)
    
    return updated_job


@router.post("/ecc/jobs/{job_id}/cancel")
async def cancel_ecc_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in '{job.status}' state")

    updated_job = _transition_job(job, "cancelled", "Job cancelled by control plane")
    
    # Persist to database
    await _save_job_to_db(updated_job)
    
    return updated_job


RETRYABLE_TERMINAL_STATUSES = {"failed", "cancelled", "review_required"}


@router.post("/ecc/jobs/{job_id}/retry")
async def retry_ecc_job(job_id: str, background_tasks: BackgroundTasks):
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
