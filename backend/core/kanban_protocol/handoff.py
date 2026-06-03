"""HandoffService — Kanban Protocol status machine.

Encapsulates the state transitions for an IssueHandoff. All methods are
idempotent on read; transitions raise ``ValueError`` on illegal moves.
"""
from typing import Optional

from db import repository as repo
from core.kanban_protocol.lanes import get_lane


def _new_id() -> str:
    import uuid
    return f"h_{uuid.uuid4().hex[:16]}"


class HandoffService:
    """Pure status-machine layer. Persistence lives in ``db.repository``."""

    async def create(
        self,
        *,
        issue_id: str,
        board_id: str,
        from_lane: Optional[str],
        to_lane: str,
        payload: Optional[dict],
        created_by: Optional[str],
    ) -> dict:
        # Validate target lane up front so callers fail fast.
        try:
            get_lane(to_lane)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        return await repo.create_issue_handoff(
            id=_new_id(),
            board_id=board_id,
            issue_id=issue_id,
            from_lane=from_lane,
            to_lane=to_lane,
            payload=payload,
            created_by=created_by,
        )

    async def accept(self, handoff_id: str, *, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "pending":
            raise ValueError(
                f"Cannot accept handoff in status '{current['status']}'; "
                "only 'pending' handoffs can be accepted"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="accepted",
            actor_field="accepted_by",
            actor_value=actor,
        )
