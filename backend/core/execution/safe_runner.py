"""P0-safe execution runner.

Emits a deterministic sequence of events without invoking any real
AI/CLI adapter. This is the default execution path for the control
plane and the only path that runs without the ``ALLOW_REAL_LLM_EXECUTION``
gate. Real harnesses (Claude CLI, Codex, etc.) are added behind the
same interface by the adapter layer.

The runner is intentionally side-effect-free: it depends on injected
helpers for state transitions, persistence, and broadcast so it can be
unit-tested without touching the database or the WebSocket layer.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)


# Default deterministic log lines emitted during safe execution.
# Kept identical to the original inline implementation so the UI does
# not need to be updated.
DEFAULT_SAFE_EVENTS: List[str] = [
    "Analyzing issue {issue_key}",
    "Preparing execution context for {profile}",
    "Running safe quality check",
    "Ready for human review",
]


# Type aliases for the injected dependencies. These are intentionally
# loose to keep the module decoupled from the concrete pydantic job
# model used by the API layer.
TransitionFn = Callable[[Any, str, str], Any]
SaveFn = Callable[[Any], Awaitable[None]]
BroadcastFn = Callable[[str, Dict[str, Any]], Awaitable[None]]


@dataclass
class SafeRunnerDeps:
    """Bundle of dependencies required to run the safe loop.

    The dispatch endpoint and the adapter layer both construct one of
    these and pass it to :func:`run_safe_execution`. Keeping the
    dependencies explicit makes the runner trivial to mock in tests.
    """

    jobs: Dict[str, Any]
    transition_job: TransitionFn
    save_job_to_db: SaveFn
    broadcast_job_update: BroadcastFn
    sleep_seconds: float = 0.01
    events: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = list(DEFAULT_SAFE_EVENTS)


async def run_safe_execution(
    job_id: str,
    deps: SafeRunnerDeps,
) -> None:
    """Drive ``job_id`` through the deterministic safe lifecycle.

    Transitions: ``queued -> running -> review_required``.

    The function is a no-op if the job has been removed from the
    registry (e.g. by a concurrent cancel) and returns early if the
    job is cancelled mid-flight.
    """
    job = deps.jobs.get(job_id)
    if job is None:
        logger.warning("safe_runner: job %s not found in registry", job_id)
        return

    issue_key = getattr(job, "issue_key", "UNKNOWN")
    profile = getattr(job, "profile", "general")

    deps.transition_job(job, "running", "Safe execution started")
    await deps.save_job_to_db(job)
    await deps.broadcast_job_update(job_id, job.model_dump())

    for template in deps.events or DEFAULT_SAFE_EVENTS:
        await asyncio.sleep(deps.sleep_seconds)
        # Bail out if the job was cancelled while we were running.
        if getattr(job, "status", None) == "cancelled":
            return
        message = template.format(issue_key=issue_key, profile=profile)
        deps.transition_job(job, "running", message)
        await deps.save_job_to_db(job)
        await deps.broadcast_job_update(job_id, job.model_dump())

    if getattr(job, "status", None) == "cancelled":
        return

    deps.transition_job(
        job,
        "review_required",
        "Safe execution complete; human review required",
    )
    await deps.save_job_to_db(job)
    await deps.broadcast_job_update(job_id, job.model_dump())
