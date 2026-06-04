"""Read-only API endpoints for the Agent Runtime.

Phase 1 exposes only GET endpoints for workers, runs, and run events.
All queries are filtered by board_id for board isolation.
No write endpoints — the runtime does not start workers yet.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

@router.get("/runtime/workers")
async def list_workers(
    board_id: str = Query("board-default", description="Board to list workers for"),
):
    """List agent workers for a board."""
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
# Runs
# ---------------------------------------------------------------------------

@router.get("/runtime/runs")
async def list_runs(
    board_id: str = Query("board-default", description="Board to list runs for"),
    issue_id: Optional[str] = Query(None, description="Filter by issue ID"),
    status: Optional[str] = Query(None, description="Filter by run status"),
    limit: int = Query(100, ge=1, le=500, description="Max runs to return"),
):
    """List execution runs for a board."""
    from db import repository as repo
    runs = await repo.list_runs_by_board(
        board_id=board_id,
        issue_id=issue_id,
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
# Run Events
# ---------------------------------------------------------------------------

@router.get("/runtime/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    limit: int = Query(500, ge=1, le=2000, description="Max events to return"),
):
    """List events for a run, ordered by created_at ASC (oldest first)."""
    from db import repository as repo
    # Verify run exists
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    events = await repo.list_run_events(run_id, limit=limit)
    return {"events": events, "total": len(events)}
