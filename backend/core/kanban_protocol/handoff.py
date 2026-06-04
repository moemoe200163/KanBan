"""HandoffService — Kanban Protocol status machine.

Encapsulates the state transitions for an IssueHandoff. All methods are
idempotent on read; transitions raise ``ValueError`` on illegal moves.
"""
from typing import Optional

from pydantic import ValidationError

from db import repository as repo
from core.kanban_protocol.lanes import get_lane
from core.kanban_protocol.payloads import (
    LANE_PAYLOADS,
    PayloadValidationError,
)
from core.kanban_protocol.scope_guard import check_payload


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

        # Refuse out-of-scope payload keys (archived security work, etc.).
        check_payload(payload or {})

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
                f"Cannot complete handoff in status '{current['status']}'; "
                "only 'in_progress' or 'accepted' handoffs can be completed"
            )

        lane = get_lane(current["toLane"])
        existing = current.get("payload") or {}
        caller = payload or {}
        final_payload = {**existing, **caller}

        # Guardrail #1: scope guard runs FIRST so denied keys are not silently
        # dropped by Pydantic's `extra="forbid"`.
        check_payload(final_payload)

        payload_model = LANE_PAYLOADS[lane.key]
        try:
            validated = payload_model.model_validate(final_payload)
        except ValidationError as exc:
            raise PayloadValidationError(
                lane=lane.key,
                errors=[
                    {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                    for e in exc.errors()
                ],
            ) from exc

        merged_payload = validated.model_dump(mode="json")

        return await repo.update_issue_handoff(
            handoff_id,
            status="completed",
            payload=merged_payload,
            actor_field="completed_by",
            actor_value=actor,
            set_completed_at=True,
        )

    async def review(
        self,
        *,
        handoff_id: str,
        decision: str,
        actor: Optional[str],
        comment: Optional[str] = None,
    ) -> dict:
        """Reviewer decides on a completed handoff: approve, reject, or request_changes.

        Returns a dict with keys:
        - ``handoff``: the updated handoff record
        - ``routing``: a dict describing the routing action taken or suggested
          - ``action``: ``"none"`` | ``"rework"`` | ``"reject"``
          - ``next_handoff``: the newly created handoff (for rework/reject), or ``None``
          - ``next_lane``: the target lane for the routing action
        """
        if decision not in ("approve", "reject", "request_changes"):
            raise ValueError(
                f"Invalid decision '{decision}'; "
                "must be 'approve', 'reject', or 'request_changes'"
            )

        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        # Guard: reject re-review before status check so the message is clear
        # even after a first review moved the status away from "completed".
        if current.get("decision") is not None:
            raise ValueError(
                f"Handoff '{handoff_id}' already reviewed "
                f"with decision '{current['decision']}'"
            )
        if current["status"] != "completed":
            raise ValueError(
                f"Cannot review handoff in status '{current['status']}'; "
                "only 'completed' handoffs can be reviewed"
            )

        # Determine new status.
        if decision == "approve":
            new_status = "approved"
        else:
            new_status = "rejected" if decision == "reject" else "rework"

        updated = await repo.update_issue_handoff(
            handoff_id,
            status=new_status,
            decision=decision,
            review_comment=comment,
            reviewed_by=actor,
            set_reviewed_at=True,
        )

        # --- Decision routing ---
        from_lane = current.get("fromLane")
        issue_id = current["issueId"]
        board_id = current.get("boardId", "board-default")

        routing: dict = {"action": "none", "next_handoff": None, "next_lane": None}

        if decision == "request_changes":
            # Create a rework handoff back to the originating lane.
            target_lane = from_lane or "triage"
            rework_payload: dict = {
                "rework_reason": comment or "",
                "original_reviewer": actor,
                "rework_from_review": handoff_id,
            }
            next_h = await self.create(
                issue_id=issue_id,
                board_id=board_id,
                from_lane="review",
                to_lane=target_lane,
                payload=rework_payload,
                created_by=actor,
            )
            routing = {"action": "rework", "next_handoff": next_h, "next_lane": target_lane}

        elif decision == "reject":
            # Route to triage for re-evaluation.
            target_lane = "triage"
            reject_payload: dict = {
                "rejection_reason": comment or "",
                "original_reviewer": actor,
                "rejected_from_review": handoff_id,
                "rejected_from_lane": from_lane,
            }
            next_h = await self.create(
                issue_id=issue_id,
                board_id=board_id,
                from_lane="review",
                to_lane=target_lane,
                payload=reject_payload,
                created_by=actor,
            )
            routing = {"action": "reject", "next_handoff": next_h, "next_lane": target_lane}

        # approve: no auto-routing — human decides next step.

        return {"handoff": updated, "routing": routing}

    async def block(self, *, handoff_id: str, actor: Optional[str], reason: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("block_reason must be a non-empty string")
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] in ("completed", "cancelled"):
            raise ValueError(
                f"Cannot block handoff in terminal status '{current['status']}'"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="blocked",
            block_reason=reason,
        )

    async def unblock(self, *, handoff_id: str, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "blocked":
            raise ValueError(
                f"Cannot unblock handoff in status '{current['status']}'"
            )
        # MVP: return to the last non-blocked state. Without history
        # tracking, the safe assumption is that we came from 'pending'
        # or 'accepted'. We pick 'pending' so the human re-evaluates.
        return await repo.update_issue_handoff(
            handoff_id,
            status="pending",
            block_reason="",
        )

    async def cancel(self, *, handoff_id: str, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] in ("completed", "cancelled"):
            raise ValueError(
                f"Cannot cancel handoff in terminal status '{current['status']}'"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="cancelled",
            actor_field="cancelled_by",
            actor_value=actor,
        )

    async def comment(
        self,
        *,
        issue_id: str,
        handoff_id: str,
        body: str,
        author_id: Optional[str],
        author_name: Optional[str],
        comment_type: str,
    ) -> dict:
        """Add a comment to an issue associated with a handoff."""
        return await repo.create_issue_comment(
            issue_id=issue_id,
            body=body,
            author_id=author_id,
            author_name=author_name,
            comment_type=comment_type,
        )
