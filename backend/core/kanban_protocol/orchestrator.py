"""Delivery Orchestrator — manual, rules-driven, no daemon.

Exposes ``create_job_for_handoff`` which the HandoffService calls during
dispatch. When ``ALLOW_REAL_LLM_EXECUTION=true``, creates an AgentRun
in the runtime queue for the worker to pick up. Otherwise falls back to
the safe-runner job path.
"""
import os
from typing import Optional


async def create_job_for_handoff(
    *,
    handoff_id: str,
    issue_id: str,
    issue_key: str,
    to_lane: str,
    profile: str,
    actor: Optional[str],
    board_id: str = "board-default",
    execution_mode: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Create a job or run for a handoff dispatch.

    When ``ALLOW_REAL_LLM_EXECUTION=true`` and ``execution_mode`` is not
    ``safe-runner``, an AgentRun is created in the runtime queue. The
    return dict includes ``"_run_id"`` so callers know the worker will
    handle execution (no background safe-runner task needed).

    Otherwise a safe-runner ECC job is created as before.
    """
    from db import repository as repo
    from core.kanban_protocol.lanes import get_lane_db

    # Build a command from the lane contract.
    lane = await get_lane_db(to_lane)
    command = lane.allowed_commands[0] if lane.allowed_commands else "/loop-start"

    # Check the real execution gate.
    allow_real = os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true"
    effective_mode = execution_mode or "safe-runner"
    if effective_mode in ("api-agent", "cli-agent") and not allow_real:
        effective_mode = "safe-runner"

    if effective_mode != "safe-runner":
        # Create an AgentRun for the worker to pick up.
        from core.runtime.orchestrator import create_run_for_dispatch
        run = await create_run_for_dispatch(
            board_id=board_id,
            issue_id=issue_id,
            issue_key=issue_key,
            command=command,
            profile=profile,
            harness=effective_mode,
            provider=provider,
            model=model,
            required_role=None,
            extra_metadata={"handoff_id": handoff_id, "actor": actor},
        )
        # Also create a placeholder ECC job so the UI can track it.
        job = await repo.create_ecc_job_safe_runner(
            issue_id=issue_id,
            issue_key=issue_key,
            command=command,
            profile=profile,
            harness="safe-runner",
            handoff_id=handoff_id,
            board_id=board_id,
        )
        return {"job": job, "_run_id": run["id"]}

    # Default: safe-runner job (no real execution).
    return await repo.create_ecc_job_safe_runner(
        issue_id=issue_id,
        issue_key=issue_key,
        command=command,
        profile=profile,
        harness="safe-runner",
        handoff_id=handoff_id,
        board_id=board_id,
    )
