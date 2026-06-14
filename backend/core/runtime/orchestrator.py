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
from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID

logger = logging.getLogger(__name__)


async def _broadcast_run_event(run_id: str, event: dict) -> None:
    """Push a run event to WebSocket subscribers (best-effort)."""
    try:
        from api.v1.endpoints.ws import broadcast_run_log
        await broadcast_run_log(run_id, event)
    except Exception:
        pass  # WS broadcast is best-effort


# ---------------------------------------------------------------------------
# Agent Roles — used for role-based dispatch
# ---------------------------------------------------------------------------

class AgentRole:
    """Predefined agent roles for capability-based dispatch.

    Workers register with a list of capabilities (role strings).
    Runs specify a ``required_role`` — only workers whose capabilities
    include that role can claim the run.

    A run with ``required_role=None`` can be claimed by any worker.
    """

    SAFE_RUNNER = "safe-runner"
    BACKEND_DEV = "backend-dev"
    FRONTEND_DEV = "frontend-dev"
    CODE_REVIEWER = "code-reviewer"
    FULL_STACK = "full-stack"
    QA = "qa"
    DEVOPS = "devops"

    # Convenience: all known roles (for validation / UI display)
    ALL = [
        SAFE_RUNNER,
        BACKEND_DEV,
        FRONTEND_DEV,
        CODE_REVIEWER,
        FULL_STACK,
        QA,
        DEVOPS,
    ]

    @classmethod
    def is_valid(cls, role: str) -> bool:
        """Return True if role is a known predefined role."""
        return role in cls.ALL


async def create_run_for_dispatch(
    *,
    board_id: str = DEFAULT_BOARD_ID,
    issue_id: str,
    issue_key: str,
    command: str,
    profile: str = "general",
    harness: str = "safe-runner",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    job_id: Optional[str] = None,
    required_role: Optional[str] = None,
    max_retries: int = 0,
    max_runtime_seconds: Optional[int] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Create a new run in 'pending' status for the orchestrator to dispatch.

    This is called by the ECC dispatch endpoint when execution_mode is
    api-agent or cli-agent. The run sits in the queue until a worker
    claims it.

    Args:
        required_role: If set, only workers with this role in their
            capabilities can claim the run. None means any worker can claim.
        max_retries: Maximum number of times a failed run can be retried.
        max_runtime_seconds: Maximum seconds a run can execute before timeout.
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
        required_role=required_role,
        max_retries=max_retries,
        max_runtime_seconds=max_runtime_seconds,
        extra_metadata=extra_metadata or {},
    )
    logger.info(
        "Created run %s for issue %s (board=%s, role=%s, retries=%d)",
        run_id, issue_key, board_id, required_role or "any", max_retries,
    )
    return run


async def claim_next_run(
    worker_id: str,
    board_id: str = DEFAULT_BOARD_ID,
) -> Optional[dict]:
    """Atomically find and claim the oldest matching pending run for this worker.

    Uses atomic_claim_run() to avoid the read-then-write race condition.
    Role-based matching: a run matches if its ``required_role`` is None
    (any worker can claim) or if ``required_role`` is in the worker's
    ``capabilities`` list.

    Returns the claimed run dict, or None if no matching runs exist.
    """
    from db import repository as repo

    # Fetch worker capabilities
    worker = await repo.get_worker(worker_id)
    worker_capabilities: list = worker.get("capabilities", []) if worker else []

    # Atomic claim — single UPDATE avoids race between multiple workers
    run = await repo.atomic_claim_run(
        worker_id=worker_id,
        board_id=board_id,
        capabilities=worker_capabilities,
    )

    if not run:
        return None

    now = datetime.now(timezone.utc)
    # Update worker state
    await repo.update_worker_status(
        worker_id,
        "claimed",
        active_run_id=run["id"],
        claimed_at=now,
    )
    # Append event
    event = await repo.append_run_event(
        id=f"evt_{uuid4().hex[:12]}",
        run_id=run["id"],
        event_type="status_change",
        message=f"Run claimed by worker {worker_id}",
    )
    await _broadcast_run_event(run["id"], event)
    logger.info("Run %s claimed by worker %s (atomic)", run["id"], worker_id)
    return run


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
        event = await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message=f"Run started by worker {worker_id}",
        )
        await _broadcast_run_event(run_id, event)
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
        event = await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message=f"Run completed: {result_summary or 'success'}",
        )
        await _broadcast_run_event(run_id, event)
        # Sync linked ECC job → review_required
        await _sync_job_for_run(run_id, "review_required", repo, result_summary=result_summary)
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
        event = await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="error",
            message=f"Run failed: {error_message}",
        )
        await _broadcast_run_event(run_id, event)
        # Sync linked ECC job → failed
        await _sync_job_for_run(run_id, "failed", repo, error_message=error_message)
        logger.warning("Run %s failed: %s", run_id, error_message)
    return updated


async def _sync_job_for_run(
    run_id: str,
    job_status: str,
    repo,
    result_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Sync the linked ECC job status when a run completes or fails.

    Looks up the run's job_id, then upserts the ECC job with the new status
    and appends a status_change event.
    """
    try:
        run = await repo.get_run(run_id)
        if not run:
            return
        job_id = run.get("jobId") or run.get("job_id")
        if not job_id:
            return

        job = await repo.get_job(job_id)
        if not job:
            return

        now = datetime.now(timezone.utc).isoformat()
        message = result_summary or error_message or job_status
        events = list(job.get("events") or [])
        events.append({
            "timestamp": now,
            "status": job_status,
            "message": f"Run {run_id}: {message}",
        })

        await repo.upsert_job({
            "id": job_id,
            "issue_id": job["issue_id"],
            "issue_key": job["issue_key"],
            "command": job.get("command", ""),
            "profile": job.get("profile", ""),
            "harness": job.get("harness", ""),
            "board_id": job.get("board_id", "board-default"),
            "status": job_status,
            "created_at": job.get("created_at", now),
            "updated_at": now,
            "message": message[:512] if message else None,
            "events": events,
        })
        logger.info("Synced job %s → %s (from run %s)", job_id, job_status, run_id)

        # --- Close job→handoff loop ---
        # When job reaches review_required, auto-complete the linked handoff
        # so it transitions from in_progress to completed (ready for review).
        if job_status == "review_required":
            handoff_id = _extract_handoff_id(job)
            if handoff_id:
                try:
                    from core.kanban_protocol.handoff import HandoffService
                    svc = HandoffService()
                    await svc.system_complete(
                        handoff_id=handoff_id,
                        result_summary=result_summary,
                    )
                    logger.info("Auto-completed handoff %s for job %s", handoff_id, job_id)
                except Exception as exc:
                    logger.warning("Failed to auto-complete handoff %s: %s", handoff_id, exc)

    except Exception as exc:
        logger.warning("Failed to sync job for run %s: %s", run_id, exc)


def _extract_handoff_id(job: dict) -> Optional[str]:
    """Extract handoff_id from the job's message field.

    The message format is: "Created by Kanban Protocol handoff {handoff_id}"
    """
    import re
    message = job.get("message", "")
    match = re.search(r"handoff\s+(h_\w+)", message)
    return match.group(1) if match else None


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
        event = await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message="Run cancelled",
        )
        await _broadcast_run_event(run_id, event)
        # Sync linked ECC job → cancelled
        await _sync_job_for_run(run_id, "cancelled", repo)
        logger.info("Run %s cancelled", run_id)
    return updated


async def get_worker_stats(board_id: str = DEFAULT_BOARD_ID) -> dict:
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


async def get_run_stats(board_id: str = DEFAULT_BOARD_ID) -> dict:
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


# ---------------------------------------------------------------------------
# Stale Run Reclaim — detect crashed workers and requeue/kill stale runs
# ---------------------------------------------------------------------------

async def reclaim_stale_runs(
    board_id: str = DEFAULT_BOARD_ID,
    stale_threshold_seconds: int = 300,
) -> list:
    """Detect stale runs and either requeue or fail them.

    Called periodically by the worker or on startup. Runs that have been
    in 'claimed' or 'running' state longer than stale_threshold_seconds
    without a heartbeat are reclaimed:
    - If retry_count < max_retries: requeue to 'pending' with backoff
    - If retry_count >= max_retries: mark as 'failed'
    """
    from db import repository as repo

    reclaimed = await repo.reclaim_stale_runs(
        stale_threshold_seconds=stale_threshold_seconds,
        board_id=board_id,
    )

    for run in reclaimed:
        status = run.get("status", "unknown")
        run_id = run.get("id", "?")
        if status == "pending":
            logger.info("Reclaimed stale run %s → requeued (retry %s)", run_id, run.get("retryCount"))
        else:
            logger.warning("Stale run %s → failed (max retries exhausted)", run_id)
        # Append event
        event = await repo.append_run_event(
            id=f"evt_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="status_change",
            message=f"Stale reclaim: {status}",
            extra_metadata={"reclaimed_status": status},
        )
        await _broadcast_run_event(run_id, event)
        # Sync linked ECC job
        await _sync_job_for_run(run_id, status, repo)

    return reclaimed
