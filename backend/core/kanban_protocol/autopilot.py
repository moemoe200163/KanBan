"""Autopilot Scheduler — background auto-dispatch for non-human lanes.

Polls for accepted handoffs in lanes where ``human_approval_required=False``
and dispatches them automatically.  Also enforces timeout-based retry for
long-running handoffs.

The scheduler runs as an asyncio background task started by FastAPI's
lifespan handler.  It can be toggled on/off at runtime via the
``/api/v1/autopilot/status`` endpoint.

Design principles:
- Only dispatches lanes where ``human_approval_required=False``.
- Respects the existing HandoffService state machine (accept -> dispatch).
- Uses the safe-runner path (no real LLM execution by default).
- Logs every action for audit trail.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Default polling interval in seconds.
DEFAULT_TICK_INTERVAL = 30

# Maximum number of handoffs to process per tick.
MAX_DISPATCH_PER_TICK = 5


class AutopilotScheduler:
    """Background scheduler that auto-dispatches handoffs."""

    def __init__(self, tick_interval: int = DEFAULT_TICK_INTERVAL):
        self.tick_interval = tick_interval
        self._enabled = False
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_tick_at: Optional[datetime] = None
        self._last_tick_result: Optional[dict] = None
        self._total_dispatched = 0
        self._total_timed_out = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "running": self._running,
            "tickInterval": self.tick_interval,
            "lastTickAt": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "lastTickResult": self._last_tick_result,
            "totalDispatched": self._total_dispatched,
            "totalTimedOut": self._total_timed_out,
        }

    def enable(self) -> dict:
        """Enable the autopilot scheduler."""
        self._enabled = True
        logger.info("Autopilot scheduler enabled")
        return self.status

    def disable(self) -> dict:
        """Disable the autopilot scheduler."""
        self._enabled = False
        logger.info("Autopilot scheduler disabled")
        return self.status

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._task and not self._task.done():
            return  # already running
        self._enabled = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Autopilot scheduler background task started")

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._enabled = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Autopilot scheduler stopped")

    async def _loop(self) -> None:
        """Background loop that calls tick() at the configured interval."""
        self._running = True
        try:
            while self._enabled:
                try:
                    await self.tick()
                except Exception as exc:
                    logger.error("Autopilot tick failed: %s %s", type(exc).__name__, exc)
                await asyncio.sleep(self.tick_interval)
        finally:
            self._running = False

    async def tick(self) -> dict:
        """Process one autopilot cycle.

        Returns a summary of actions taken.
        """
        self._last_tick_at = datetime.now(timezone.utc)
        dispatched = 0
        timed_out = 0
        skipped = 0
        errors = 0

        # --- Phase 1: Auto-dispatch accepted handoffs ---
        from db import repository as repo
        from core.kanban_protocol.lanes import get_lane
        from core.kanban_protocol.handoff import HandoffService

        accepted_handoffs = await repo.list_handoffs_by_status(
            status="accepted",
            limit=MAX_DISPATCH_PER_TICK,
        )

        svc = HandoffService()

        for h in accepted_handoffs:
            to_lane_key = h.get("toLane", "")
            try:
                lane = get_lane(to_lane_key)
            except KeyError:
                skipped += 1
                continue

            if lane.human_approval_required:
                skipped += 1
                continue

            # Auto-dispatch: the handoff is accepted and the lane allows it.
            try:
                issue = await repo.get_issue(h["issueId"])
                issue_key = issue["key"] if issue else h.get("issueId", "???")

                await svc.dispatch(
                    handoff_id=h["id"],
                    issue_key=issue_key,
                    profile=lane.allowed_profiles[0] if lane.allowed_profiles else "general",
                    actor="autopilot",
                )

                # Kick off the safe runner in the background.
                from api.v1.endpoints.ecc import (
                    _register_job_from_db,
                    _execute_safe_runner,
                )
                # The dispatch created a job; we need to find it.
                # The job is linked via handoff_id in the job's message.
                # For now, we look up the most recent job for this issue.
                jobs = await repo.list_jobs(issue_id=h["issueId"], limit=1)
                if jobs:
                    job_id = jobs[0]["id"]
                    await _register_job_from_db(job_id)
                    asyncio.create_task(_execute_safe_runner(job_id))

                dispatched += 1
                self._total_dispatched += 1
                logger.info(
                    "Autopilot dispatched handoff %s -> lane %s (issue %s)",
                    h["id"], to_lane_key, issue_key,
                )
            except Exception as exc:
                errors += 1
                logger.warning(
                    "Autopilot failed to dispatch handoff %s: %s %s",
                    h["id"], type(exc).__name__, exc,
                )

        # --- Phase 2: Timeout enforcement for in-progress handoffs ---
        in_progress = await repo.list_handoffs_by_status(
            status="in_progress",
            limit=MAX_DISPATCH_PER_TICK * 2,
        )

        now = datetime.now(timezone.utc)
        for h in in_progress:
            to_lane_key = h.get("toLane", "")
            try:
                lane = get_lane(to_lane_key)
            except KeyError:
                continue

            if lane.timeout_seconds <= 0:
                continue

            # Check if the handoff has exceeded the lane timeout.
            updated_at_str = h.get("updatedAt") or h.get("createdAt")
            if not updated_at_str:
                continue
            try:
                updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                # Ensure timezone-aware for comparison with now (UTC).
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

            elapsed = (now - updated_at).total_seconds()
            if elapsed > lane.timeout_seconds:
                # Apply retry policy.
                if lane.retry_policy == "none" or lane.retry_max <= 0:
                    # No retry — block the handoff.
                    try:
                        await svc.block(
                            handoff_id=h["id"],
                            actor="autopilot",
                            reason=f"Timed out after {int(elapsed)}s (limit: {lane.timeout_seconds}s)",
                        )
                        timed_out += 1
                        self._total_timed_out += 1
                        logger.info(
                            "Autopilot blocked timed-out handoff %s (lane %s, %.0fs)",
                            h["id"], to_lane_key, elapsed,
                        )
                    except Exception as exc:
                        errors += 1
                        logger.warning(
                            "Autopilot failed to block handoff %s: %s",
                            h["id"], exc,
                        )
                else:
                    # Retry: cancel current and create a new handoff to the same lane.
                    try:
                        await svc.cancel(handoff_id=h["id"], actor="autopilot")
                        await svc.create(
                            issue_id=h["issueId"],
                            board_id=h.get("boardId", "board-default"),
                            from_lane=h.get("fromLane"),
                            to_lane=to_lane_key,
                            payload={"retry_reason": f"Timed out after {int(elapsed)}s"},
                            created_by="autopilot",
                        )
                        timed_out += 1
                        self._total_timed_out += 1
                        logger.info(
                            "Autopilot retried timed-out handoff %s (lane %s, %.0fs)",
                            h["id"], to_lane_key, elapsed,
                        )
                    except Exception as exc:
                        errors += 1
                        logger.warning(
                            "Autopilot failed to retry handoff %s: %s",
                            h["id"], exc,
                        )

        result = {
            "dispatched": dispatched,
            "skipped": skipped,
            "timedOut": timed_out,
            "errors": errors,
            "acceptedScanned": len(accepted_handoffs),
            "inProgressScanned": len(in_progress),
        }
        self._last_tick_result = result
        return result


# Singleton instance — imported by the API endpoint and the startup handler.
scheduler = AutopilotScheduler()
