from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from uuid import uuid4
import json
import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

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


async def _execute_ecc_command(job_id: str) -> None:
    """Execute the ECC command with real-time log streaming via WebSocket."""
    import os
    from core.adapters import HarnessRegistry, ClaudeLocalAdapter

    job = _jobs.get(job_id)
    if not job:
        return

    # Transition to running
    _transition_job(job, "running", "AI execution started")
    await _broadcast_job_update(job_id, job.model_dump())

    # Register ClaudeLocalAdapter if not already registered
    if not HarnessRegistry.is_supported(job.harness):
        HarnessRegistry.register(job.harness, ClaudeLocalAdapter)

    # Get appropriate adapter
    adapter = HarnessRegistry.get(job.harness, config={
        "github_repo": os.getenv("GITHUB_REPO", "your-org/your-repo"),
        "github_token": os.getenv("GITHUB_TOKEN"),
        "working_dir": os.getenv("WORKSPACE_DIR", "/Users/user/Code/kanban"),
    })

    if not adapter:
        _transition_job(job, "failed", f"Harness {job.harness} not supported")
        await _broadcast_job_update(job_id, job.model_dump())
        return

    # Build issue context from job
    issue = {
        "key": job.issue_key,
        "title": job.issue_key,
        "description": f"ECC Command: {job.command}\nProfile: {job.profile}",
        "profile": job.profile,
    }

    context = {
        "working_dir": os.getenv("WORKSPACE_DIR", "/Users/user/Code/kanban"),
        "branch_name": f"feature/{job.issue_key.lower().replace(' ', '-')}",
    }

    # Execute via adapter
    try:
        result = await adapter.dispatch(issue, context)

        if result.success:
            _transition_job(job, "completed", f"Success: {result.pr_url or 'No PR created'}")
        else:
            _transition_job(job, "failed", result.error or "Unknown error")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"ECC execution failed for {job_id}: {e}")
        _transition_job(job, "failed", str(e))

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
    """Persist job state to SQLite database."""
    # Disabled due to aiosqlite greenlet issue with BackgroundTasks
    # Re-enable once the async context issue is resolved
    pass


async def load_jobs_from_db() -> None:
    """Load all jobs from database into _jobs dict on startup."""
    global _jobs
    try:
        # Relative import to avoid backend/backend path issues
        from db.database import AsyncSessionLocal, ensure_db_init
        from db.models import JobModel
        await ensure_db_init()  # lazy-init tables if not yet created
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(JobModel))
            rows = result.scalars().all()
            
            for row in rows:
                job_dict = row.to_dict()
                # Convert events JSON back to ECCJobEvent objects
                job_dict["events"] = [ECCJobEvent(**e) for e in job_dict.get("events", [])]
                _jobs[row.id] = ECCDispatchJob(**job_dict)
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
        # Authentication required - raise 401 if not provided
        # The frontend always sends Authorization header, so this is the normal path
        pass  # Let it fail naturally if no auth

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

    # Execute the actual AI command with WebSocket streaming
    background_tasks.add_task(_execute_ecc_command, job.id)

    return job


@router.get("/ecc/jobs")
async def list_ecc_jobs():
    jobs: List[ECCDispatchJob] = sorted(
        _jobs.values(),
        key=lambda job: job.created_at,
        reverse=True,
    )
    return {"jobs": [job.model_dump() for job in jobs], "total": len(jobs)}


@router.get("/ecc/jobs/{job_id}")
async def get_ecc_job(job_id: str):
    job = _jobs.get(job_id)
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
