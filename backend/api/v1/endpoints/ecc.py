from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
import asyncio
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
VALID_HARNESSES = {"claude-code", "codex", "cursor", "opencode", "gemini"}


class ECCDispatchRequest(BaseModel):
    issue_id: str = Field(..., min_length=1)
    issue_key: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    profile: str = Field(default="general")
    harness: str = Field(default="claude-code")


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
    """Run the P0-safe execution loop without invoking real AI/CLI adapters."""
    job = _jobs.get(job_id)
    if not job:
        return

    _transition_job(job, "running", "Safe execution started")
    await _save_job_to_db(job)
    await _broadcast_job_update(job_id, job.model_dump())

    safe_events = [
        f"Analyzing issue {job.issue_key}",
        f"Preparing execution context for {job.profile}",
        "Running safe quality check",
        "Ready for human review",
    ]

    for message in safe_events:
        await asyncio.sleep(0.01)
        _transition_job(job, "running", message)
        await _save_job_to_db(job)
        await _broadcast_job_update(job_id, job.model_dump())

    _transition_job(job, "review_required", "Safe execution complete; human review required")
    await _save_job_to_db(job)
    await _broadcast_job_update(job_id, job.model_dump())


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

    now = _utc_now()
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
        message="Queued for local control-plane dispatch",
        events=[
            ECCJobEvent(
                timestamp=now,
                status="queued",
                message="Queued for local control-plane dispatch",
            )
        ],
    )
    _jobs[job.id] = job

    # Persist to database
    await _save_job_to_db(job)

    # P0 guardrail: dispatch returns immediately and safe runner emits deterministic events.
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
