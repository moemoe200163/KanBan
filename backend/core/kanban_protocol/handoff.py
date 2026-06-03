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

    async def dispatch(
        self,
        *,
        handoff_id: str,
        issue_key: str,
        profile: str,
        actor: Optional[str],
    ) -> dict:
        from core.kanban_protocol.orchestrator import create_job_for_handoff

        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "accepted":
            raise ValueError(
                f"Cannot dispatch handoff in status '{current['status']}'; "
                "only 'accepted' handoffs can be dispatched"
            )

        lane = get_lane(current["toLane"])
        payload = current.get("payload") or {}

        if lane.human_approval_required and not payload.get("approver"):
            raise PermissionError(
                f"Lane '{lane.key}' requires human approval; "
                "payload must include an 'approver' field before dispatch"
            )

        job = await create_job_for_handoff(
            handoff_id=handoff_id,
            issue_id=current["issueId"],
            issue_key=issue_key,
            to_lane=lane.key,
            profile=profile,
            actor=actor,
        )

        updated = await repo.update_issue_handoff(
            handoff_id,
            status="in_progress",
            actor_field="dispatched_by",
            actor_value=actor,
        )
        return {"handoff": updated, "job": job}

    async def complete(
        self,
        *,
        handoff_id: str,
        actor: Optional[str],
        payload: Optional[dict],
    ) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] not in ("in_progress", "accepted"):
            raise ValueError(
                f"Cannot complete handoff in status '{current['status']}'"
            )

        lane = get_lane(current["toLane"])
        merged_payload = dict(current.get("payload") or {})
        if payload:
            merged_payload.update(payload)
        missing = [
            field for field in lane.required_completion_fields
            if field not in merged_payload
        ]
        if missing:
            raise ValueError(
                f"Cannot complete handoff: missing required fields {missing}"
            )

        return await repo.update_issue_handoff(
            handoff_id,
            status="completed",
            payload=merged_payload,
            actor_field="completed_by",
            actor_value=actor,
            set_completed_at=True,
        )
