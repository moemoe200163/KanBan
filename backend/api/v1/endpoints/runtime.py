"""Agent Runtime API endpoints.

Phase 1: read-only endpoints for workers, runs, and run events.
Phase 2: write endpoints for worker registration, heartbeat, run lifecycle.

All queries are filtered by board_id for board isolation.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth
from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID, assert_board_id_allowed

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class WorkerRegisterRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, description="Unique worker ID")
    board_id: str = Field(DEFAULT_BOARD_ID, description="Board this worker serves")
    worker_type: str = Field(..., min_length=1, description="Worker type (claude-code, codex, etc.)")
    harness: Optional[str] = Field(None, description="Harness identifier")
    capabilities: Optional[list] = Field(default_factory=list)
    max_concurrency: int = Field(1, ge=1, le=10)


class WorkerHeartbeatRequest(BaseModel):
    status: Optional[str] = Field(None, description="Optional status update")


class RunClaimRequest(BaseModel):
    board_id: str = Field(DEFAULT_BOARD_ID, description="Board to claim from")


class RunCompleteRequest(BaseModel):
    result_summary: Optional[str] = Field(None, description="Summary of the run result")


class RunFailRequest(BaseModel):
    error_message: str = Field(..., min_length=1, description="Error description")


class RunCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Cancellation reason")


# ---------------------------------------------------------------------------
# Agent Roles
# ---------------------------------------------------------------------------

@router.get("/runtime/roles")
async def list_agent_roles():
    """List available agent roles for role-based dispatch."""
    from core.runtime.orchestrator import AgentRole
    return {
        "roles": [
            {"id": role, "displayName": role.replace("-", " ").title()}
            for role in AgentRole.ALL
        ],
        "total": len(AgentRole.ALL),
    }


# ---------------------------------------------------------------------------
# Workers — Read
# ---------------------------------------------------------------------------

@router.get("/runtime/workers")
async def list_workers(
    board_id: str = Query(DEFAULT_BOARD_ID, description="Board to list workers for"),
):
    """List agent workers for a board."""
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from db import repository as repo
    workers = await repo.list_workers_by_board(board_id)
    return {"workers": workers, "total": len(workers)}


@router.get("/runtime/workers/{worker_id}")
async def get_worker(worker_id: str):
    """Get a single worker by ID."""
    from db import repository as repo
    worker = await repo.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found")
    return worker


# ---------------------------------------------------------------------------
# Workers — Write
# ---------------------------------------------------------------------------

@router.post("/runtime/workers")
async def register_worker(request: WorkerRegisterRequest, current_user: dict = Depends(require_auth)):
    """Register a new worker or update an existing one."""
    try:
        assert_board_id_allowed(request.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from db import repository as repo
    worker = await repo.upsert_worker(
        id=request.worker_id,
        board_id=request.board_id,
        worker_type=request.worker_type,
        harness=request.harness,
        capabilities=request.capabilities,
        max_concurrency=request.max_concurrency,
        status="idle",
    )
    return worker


@router.post("/runtime/workers/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: str, request: WorkerHeartbeatRequest, current_user: dict = Depends(require_auth)):
    """Update worker heartbeat timestamp and optional status."""
    from db import repository as repo
    worker = await repo.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found")

    result = await repo.update_worker_heartbeat(worker_id)
    if request.status:
        result = await repo.update_worker_status(worker_id, request.status)
    return result


# ---------------------------------------------------------------------------
# Runs — Read
# ---------------------------------------------------------------------------

@router.get("/runtime/runs")
async def list_runs(
    board_id: str = Query(DEFAULT_BOARD_ID, description="Board to list runs for"),
    issue_id: Optional[str] = Query(None, description="Filter by issue ID"),
    job_id: Optional[str] = Query(None, description="Filter by linked ECC job ID"),
    status: Optional[str] = Query(None, description="Filter by run status"),
    limit: int = Query(100, ge=1, le=500, description="Max runs to return"),
):
    """List execution runs for a board."""
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from db import repository as repo
    runs = await repo.list_runs_by_board(
        board_id=board_id,
        issue_id=issue_id,
        job_id=job_id,
        status=status,
        limit=limit,
    )
    return {"runs": runs, "total": len(runs)}


@router.get("/runtime/runs/{run_id}")
async def get_run(run_id: str):
    """Get a single run by ID."""
    from db import repository as repo
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


# ---------------------------------------------------------------------------
# Runs — Write (worker lifecycle)
# ---------------------------------------------------------------------------

@router.post("/runtime/runs/claim")
async def claim_run(request: RunClaimRequest, current_user: dict = Depends(require_auth)):
    """Claim the next pending run for a worker.

    The worker_id is passed via query parameter since this is called by
    the worker process. In Phase 2 this would be authenticated.
    """
    from core.runtime.orchestrator import claim_next_run
    from db import repository as repo

    # Find an idle worker to claim, or use the requesting worker
    # For now, list idle workers and claim for the first one
    workers = await repo.list_workers_by_board(request.board_id)
    idle_worker = next((w for w in workers if w["status"] == "idle"), None)
    if not idle_worker:
        return {"run": None, "message": "No idle workers available"}

    run = await claim_next_run(idle_worker["id"], request.board_id)
    if not run:
        return {"run": None, "message": "No pending runs to claim"}
    return {"run": run, "worker": idle_worker["id"]}


@router.post("/runtime/runs/{run_id}/start")
async def start_run_endpoint(run_id: str, current_user: dict = Depends(require_auth)):
    """Transition a claimed run to running."""
    from core.runtime.orchestrator import start_run
    from db import repository as repo

    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run["status"] != "claimed":
        raise HTTPException(status_code=409, detail=f"Run is in '{run['status']}' state, expected 'claimed'")

    worker_id = run.get("workerId")
    if not worker_id:
        raise HTTPException(status_code=409, detail="Run has no assigned worker")

    result = await start_run(run_id, worker_id)
    return result


@router.post("/runtime/runs/{run_id}/complete")
async def complete_run_endpoint(run_id: str, request: RunCompleteRequest, current_user: dict = Depends(require_auth)):
    """Transition a running run to completed."""
    from core.runtime.orchestrator import complete_run
    from db import repository as repo

    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run["status"] != "running":
        raise HTTPException(status_code=409, detail=f"Run is in '{run['status']}' state, expected 'running'")

    worker_id = run.get("workerId")
    result = await complete_run(run_id, worker_id, result_summary=request.result_summary)
    return result


@router.post("/runtime/runs/{run_id}/fail")
async def fail_run_endpoint(run_id: str, request: RunFailRequest, current_user: dict = Depends(require_auth)):
    """Transition a running run to failed."""
    from core.runtime.orchestrator import fail_run
    from db import repository as repo

    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run["status"] not in ("claimed", "running"):
        raise HTTPException(status_code=409, detail=f"Run is in '{run['status']}' state, expected 'claimed' or 'running'")

    worker_id = run.get("workerId")
    result = await fail_run(run_id, worker_id, error_message=request.error_message)
    return result


@router.post("/runtime/runs/{run_id}/cancel")
async def cancel_run_endpoint(
    run_id: str,
    request: RunCancelRequest = RunCancelRequest(),
    current_user: dict = Depends(require_auth),
):
    """Cancel a run in a non-terminal state (pending, claimed, running)."""
    from core.runtime.orchestrator import cancel_run
    from db import repository as repo

    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is in '{run['status']}' state, cannot cancel",
        )

    worker_id = run.get("workerId")
    result = await cancel_run(run_id, worker_id)
    return result


# ---------------------------------------------------------------------------
# Run Events
# ---------------------------------------------------------------------------

@router.get("/runtime/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    limit: int = Query(500, ge=1, le=2000, description="Max events to return"),
):
    """List events for a run, ordered by created_at ASC (oldest first)."""
    from db import repository as repo
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    events = await repo.list_run_events(run_id, limit=limit)
    return {"events": events, "total": len(events)}


# ---------------------------------------------------------------------------
# Log Sync — push + stream
# ---------------------------------------------------------------------------

class LogPushRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Log line content")
    level: str = Field("info", description="Log level: debug, info, warn, error")
    metadata: Optional[dict] = Field(default_factory=dict)


@router.post("/runtime/runs/{run_id}/log")
async def push_run_log(run_id: str, request: LogPushRequest, current_user: dict = Depends(require_auth)):
    """Push a log line from a worker. Persists to DB and broadcasts via WebSocket."""
    import uuid
    from db import repository as repo
    from uuid import uuid4

    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    event = await repo.append_run_event(
        id=f"log_{uuid4().hex[:12]}",
        run_id=run_id,
        event_type="log",
        message=request.message,
        extra_metadata={"level": request.level, **(request.metadata or {})},
    )

    # Broadcast via WebSocket (best effort — ignore if no subscribers)
    try:
        from .ws import broadcast_run_log
        await broadcast_run_log(run_id, event)
    except Exception:
        pass

    return event


@router.get("/runtime/runs/{run_id}/logs")
async def list_run_logs(
    run_id: str,
    limit: int = Query(500, ge=1, le=5000, description="Max log lines to return"),
):
    """List log events for a run, ordered by created_at ASC (oldest first).

    Convenience endpoint that filters to event_type=log only.
    """
    from db import repository as repo
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    all_events = await repo.list_run_events(run_id, limit=limit)
    # Filter to log events only (status_change events are separate)
    logs = [e for e in all_events if e.get("eventType") == "log"]
    return {"logs": logs, "total": len(logs)}
