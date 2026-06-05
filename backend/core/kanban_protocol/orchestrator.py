"""Delivery Orchestrator — manual, rules-driven, no daemon.

Exposes ``create_job_for_handoff`` which the HandoffService calls during
dispatch. The implementation delegates to the existing P0 safe-runner
dispatch path so real Claude/Codex execution is never triggered by
default.
"""
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
) -> dict:
    """Create a JobModel row using the existing P0 dispatch path."""
    # Lazy import to avoid pulling the existing dispatch path during
    # unit tests that only exercise the status machine.
    from db import repository as repo
    from core.kanban_protocol.lanes import get_lane

    # Build a command from the lane contract. The command name is the
    # lane's first allowed command; this is purely advisory for the safe
    # runner, which never actually executes user-provided commands.
    lane = get_lane(to_lane)
    command = lane.allowed_commands[0] if lane.allowed_commands else "/loop-start"

    # Re-use the safe-runner default; real adapter execution is opt-in
    # via env flag, unchanged.
    return await repo.create_ecc_job_safe_runner(
        issue_id=issue_id,
        issue_key=issue_key,
        command=command,
        profile=profile,
        harness="safe-runner",
        handoff_id=handoff_id,
        board_id=board_id,
    )
