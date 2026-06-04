"""Agent Worker Process — polls for pending runs and executes them.

P0 implementation uses a deterministic safe runner (no real AI/CLI invocation).
The worker runs as a background asyncio task within the FastAPI process,
calling orchestrator functions directly (no HTTP round-trips).

Lifecycle:
    1. Register as an AgentWorker via repository
    2. Poll for pending runs via claim_next_run()
    3. Execute the run (safe runner for P0)
    4. Report completion/failure
    5. Send periodic heartbeats
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default deterministic log lines for safe execution (matches safe_runner.py)
DEFAULT_SAFE_EVENTS: List[str] = [
    "Analyzing issue {issue_key}",
    "Preparing execution context for {profile}",
    "Running safe quality check",
    "Ready for human review",
]

# Worker polling / heartbeat config (override via env)
POLL_INTERVAL: float = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))
HEARTBEAT_INTERVAL: float = float(os.getenv("WORKER_HEARTBEAT_INTERVAL", "15.0"))
EXECUTION_TICK_DELAY: float = float(os.getenv("WORKER_TICK_DELAY", "0.05"))


# ---------------------------------------------------------------------------
# ExecutionContext — bridges AgentRun DB record to the execution layer
# ---------------------------------------------------------------------------

@dataclass
class ExecutionContext:
    """Minimal context passed to an executor for a single run.

    This is the P0 version — just enough to drive the safe runner.
    Future phases add workspace_path, env, timeout, etc.
    """

    run_id: str
    issue_key: str
    command: str
    profile: str = "general"
    harness: str = "safe-runner"
    board_id: str = "board-default"
    extra_metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SafeRunExecutor — deterministic execution for AgentRun
# ---------------------------------------------------------------------------

class SafeRunExecutor:
    """Executes a run using the deterministic safe-event sequence.

    Unlike the original SafeRunnerDeps which operates on in-memory
    ECCDispatchJob objects, this executor works directly with the
    orchestrator + repository layer for AgentRun records.
    """

    def __init__(
        self,
        events: Optional[List[str]] = None,
        tick_delay: float = EXECUTION_TICK_DELAY,
    ):
        self.events = events or list(DEFAULT_SAFE_EVENTS)
        self.tick_delay = tick_delay

    async def execute(
        self,
        ctx: ExecutionContext,
        on_log: Callable[[str], Coroutine[Any, Any, None]],
    ) -> str:
        """Run the safe-event sequence and return a result summary.

        Args:
            ctx: The execution context for this run.
            on_log: Async callback to emit a log line.

        Returns:
            A result summary string ("success" or an error message).
        """
        issue_key = ctx.issue_key
        profile = ctx.profile

        for template in self.events:
            await asyncio.sleep(self.tick_delay)
            message = template.format(issue_key=issue_key, profile=profile)
            await on_log(message)

        return "Safe execution complete; human review required"


# ---------------------------------------------------------------------------
# AgentWorkerProcess — the main worker loop
# ---------------------------------------------------------------------------

class AgentWorkerProcess:
    """Background worker that polls for pending runs and executes them.

    The worker is designed to run as an asyncio task within the FastAPI
    process (P0). It uses the orchestrator and repository layers directly
    — no HTTP round-trips.

    Args:
        worker_id: Unique identifier for this worker instance.
        board_id: Board to claim runs from.
        worker_type: Worker type string (e.g. "safe-runner", "claude-code").
        harness: Harness identifier.
        poll_interval: Seconds between claim polls.
        heartbeat_interval: Seconds between heartbeats.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        board_id: str = "board-default",
        worker_type: str = "safe-runner",
        harness: str = "safe-runner",
        poll_interval: float = POLL_INTERVAL,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
    ):
        self.worker_id = worker_id or f"worker_{uuid4().hex[:8]}"
        self.board_id = board_id
        self.worker_type = worker_type
        self.harness = harness
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self._running = False
        self._executor = SafeRunExecutor()

    async def start(self) -> None:
        """Start the worker loop. Runs until stop() is called."""
        from db import repository as repo
        from core.runtime.orchestrator import (
            claim_next_run,
            start_run,
            complete_run,
            fail_run,
        )

        # Register this worker
        await repo.upsert_worker(
            id=self.worker_id,
            board_id=self.board_id,
            worker_type=self.worker_type,
            harness=self.harness,
            status="idle",
        )
        logger.info("Worker %s registered (board=%s)", self.worker_id, self.board_id)

        self._running = True
        last_heartbeat = asyncio.get_event_loop().time()

        while self._running:
            # Send heartbeat if due
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= self.heartbeat_interval:
                try:
                    await repo.update_worker_heartbeat(self.worker_id)
                    last_heartbeat = now
                except Exception as exc:
                    logger.warning("Heartbeat failed: %s", exc)

            # Try to claim a run
            try:
                run = await claim_next_run(self.worker_id, self.board_id)
            except Exception as exc:
                logger.error("Claim failed: %s", exc)
                await asyncio.sleep(self.poll_interval)
                continue

            if run is None:
                await asyncio.sleep(self.poll_interval)
                continue

            # Execute the claimed run
            run_id = run["id"]
            logger.info("Worker %s executing run %s", self.worker_id, run_id)

            try:
                # Transition to running
                await start_run(run_id, self.worker_id)

                # Build execution context from run record
                ctx = ExecutionContext(
                    run_id=run_id,
                    issue_key=run.get("issueKey", "UNKNOWN"),
                    command=run.get("command", ""),
                    profile=run.get("profile", "general"),
                    harness=run.get("harness", self.harness),
                    board_id=self.board_id,
                )

                # Log callback — pushes to DB + WebSocket via repo
                async def _on_log(message: str) -> None:
                    from db.repository import append_run_event
                    await append_run_event(
                        id=f"log_{uuid4().hex[:12]}",
                        run_id=run_id,
                        event_type="log",
                        message=message,
                        extra_metadata={"level": "info"},
                    )

                # Execute
                result = await self._executor.execute(ctx, _on_log)

                # Complete
                await complete_run(run_id, self.worker_id, result_summary=result)
                logger.info("Worker %s completed run %s", self.worker_id, run_id)

            except Exception as exc:
                logger.error("Run %s failed: %s", run_id, exc)
                try:
                    await fail_run(
                        run_id, self.worker_id, error_message=str(exc)
                    )
                except Exception:
                    logger.error("Failed to report failure for run %s", run_id)

        # Worker stopped — update status
        try:
            await repo.update_worker_status(self.worker_id, "stopped")
        except Exception:
            pass
        logger.info("Worker %s stopped", self.worker_id)

    def stop(self) -> None:
        """Signal the worker to stop after the current iteration."""
        self._running = False
        logger.info("Worker %s stop requested", self.worker_id)


# ---------------------------------------------------------------------------
# Module-level singleton for the background worker
# ---------------------------------------------------------------------------

_background_worker: Optional[AgentWorkerProcess] = None


async def start_background_worker(**kwargs) -> AgentWorkerProcess:
    """Create and start the background worker as an asyncio task.

    Called from main.py lifespan. Returns the worker instance so the
    lifespan can store it on app.state for cleanup.
    """
    global _background_worker
    _background_worker = AgentWorkerProcess(**kwargs)
    # Don't await — start as a fire-and-forget task
    asyncio.create_task(_background_worker.start())
    return _background_worker


def stop_background_worker() -> None:
    """Signal the background worker to stop."""
    global _background_worker
    if _background_worker is not None:
        _background_worker.stop()
        _background_worker = None
