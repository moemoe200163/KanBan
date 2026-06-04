"""Orchestrator — dispatches runs to workers via the DB queue.

The orchestrator is the central coordinator for the multi-agent runtime.
It does NOT start worker processes — it manages state transitions:

1. A dispatch request creates an AgentRun in "pending" status
2. An idle worker calls claim_next_run() to atomically pick up a run
3. The worker transitions the run through running → completed/failed

All state is persisted in the DB via repository methods. The orchestrator
is stateless — it reads and writes through the repository layer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


async def create_run_for_dispatch(
    *,
    board_id: str = "board-default",
    issue_id: str,
    issue_key: str,
    command: str,
    profile: str = "general",
    harness: str = "safe-runner",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    job_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Create a new run in 'pending' status for the orchestrator to dispatch.

    This is called by the ECC dispatch endpoint when execution_mode is
    api-agent or cli-agent. The run sits in the queue until a worker
    claims it.
    """
    from db import repository as repo

    run_id = f"run_{uuid4().hex[:12]}"
    run = await repo.create_run(
        id=run_id,
        board_id=board_id,
        issue_id=issue_id,
        issue_key=issue_key,
        job_id=job_id,
        command=command,
        profile=profile,
        harness=harness,
        provider=provider,
        model=model,
        extra_metadata=extra_metadata or {},
    )
    logger.info("Created run %s for issue %s (board=%s)", run_id, issue_key, board_id)
    return run


async def claim_next_run(
    worker_id: str,
    board_id: str = "board-default",
) -> Optional[dict]:
    """Find the oldest pending run for the board and claim it for this worker.

    Returns the updated run dict, or None if no pending runs exist.
    Uses status update to atomically claim (pending → claimed).
    """
    from db import repository as repo

    runs = await repo.list_runs_by_board(board_id=board_id, status="pending", limit=1, order="asc")
    if not runs:
        return None

    run = runs[0]  # oldest pending run
    now = datetime.now(timezone.utc)
    updated = await repo.update_run_status(
        run["id"],
        "claimed",
        worker_id=worker_id,
        started_at=now,
    )
    if updated:
        # Update worker state
        await repo.update_worker_status(
            worker_id,
            "claimed",
            active_run_id=run["id"],
            claimed_at=now,
        )
        # Append event
        await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run["id"],
            event_type="status_change",
            message=f"Run claimed by worker {worker_id}",
        )
        logger.info("Run %s claimed by worker %s", run["id"], worker_id)
    return updated


async def start_run(run_id: str, worker_id: str) -> Optional[dict]:
    """Transition a run from 'claimed' to 'running'."""
    from db import repository as repo

    now = datetime.now(timezone.utc)
    updated = await repo.update_run_status(
        run_id,
        "running",
        worker_id=worker_id,
        started_at=now,
    )
    if updated:
        await repo.update_worker_status(worker_id, "running", active_run_id=run_id)
        await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message=f"Run started by worker {worker_id}",
        )
        logger.info("Run %s started by worker %s", run_id, worker_id)
    return updated


async def complete_run(
    run_id: str,
    worker_id: str,
    result_summary: Optional[str] = None,
) -> Optional[dict]:
    """Transition a run from 'running' to 'completed'."""
    from db import repository as repo

    now = datetime.now(timezone.utc)
    updated = await repo.update_run_status(
        run_id,
        "completed",
        worker_id=worker_id,
        result_summary=result_summary,
        completed_at=now,
    )
    if updated:
        await repo.update_worker_status(worker_id, "idle", active_run_id=None)
        await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message=f"Run completed: {result_summary or 'success'}",
        )
        logger.info("Run %s completed by worker %s", run_id, worker_id)
    return updated


async def fail_run(
    run_id: str,
    worker_id: str,
    error_message: str = "Unknown error",
) -> Optional[dict]:
    """Transition a run from 'running' to 'failed'."""
    from db import repository as repo

    now = datetime.now(timezone.utc)
    updated = await repo.update_run_status(
        run_id,
        "failed",
        worker_id=worker_id,
        error_message=error_message,
        completed_at=now,
    )
    if updated:
        await repo.update_worker_status(
            worker_id, "idle", active_run_id=None, error_message=error_message,
        )
        await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="error",
            message=f"Run failed: {error_message}",
        )
        logger.warning("Run %s failed: %s", run_id, error_message)
    return updated


async def cancel_run(run_id: str, worker_id: Optional[str] = None) -> Optional[dict]:
    """Transition a run to 'cancelled'."""
    from db import repository as repo

    now = datetime.now(timezone.utc)
    updated = await repo.update_run_status(
        run_id,
        "cancelled",
        completed_at=now,
    )
    if updated:
        if worker_id:
            await repo.update_worker_status(worker_id, "idle", active_run_id=None)
        await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message="Run cancelled",
        )
        logger.info("Run %s cancelled", run_id)
    return updated


async def get_worker_stats(board_id: str = "board-default") -> dict:
    """Return worker counts by status for a board."""
    from db import repository as repo

    workers = await repo.list_workers_by_board(board_id)
    stats = {}
    for w in workers:
        status = w["status"]
        stats[status] = stats.get(status, 0) + 1
    return {
        "boardId": board_id,
        "total": len(workers),
        "byStatus": stats,
    }


async def get_run_stats(board_id: str = "board-default") -> dict:
    """Return run counts by status for a board."""
    from db import repository as repo

    # Get counts for each status
    stats = {}
    for status in ("pending", "claimed", "running", "completed", "failed", "cancelled"):
        runs = await repo.list_runs_by_board(board_id=board_id, status=status, limit=0)
        # limit=0 returns empty, so we need to count differently
        all_runs = await repo.list_runs_by_board(board_id=board_id)
        count = sum(1 for r in all_runs if r["status"] == status)
        if count > 0:
            stats[status] = count

    return {
        "boardId": board_id,
        "total": sum(stats.values()),
        "byStatus": stats,
    }
