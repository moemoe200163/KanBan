"""Kanban Protocol — Handoff API."""
from typing import Optional

from fastapi import APIRouter, HTTPException

from core.kanban_protocol.board_scope import assert_board_id_allowed
from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.schemas import HandoffCreateRequest
from core.kanban_protocol.scope_guard import ScopeDeniedError
from db import repository as repo

router = APIRouter()
_svc = HandoffService()


def _check_board(board_id: str) -> None:
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/boards/{board_id}/issues/{issue_id}/handoffs", status_code=201)
async def create_handoff(
    board_id: str,
    issue_id: str,
    body: HandoffCreateRequest,
):
    _check_board(board_id)
    # Confirm the issue exists; otherwise we'd create orphan handoffs.
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    try:
        return await _svc.create(
            issue_id=issue_id,
            board_id=board_id,
            from_lane=body.fromLane,
            to_lane=body.toLane,
            payload=body.payload,
            created_by=body.createdBy,
        )
    except (ValueError, ScopeDeniedError) as exc:
        # Service-layer validation (unknown lane, scope-denied payload)
        # is a client error, not a server error.
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/boards/{board_id}/issues/{issue_id}/handoffs")
async def list_handoffs(board_id: str, issue_id: str):
    _check_board(board_id)
    handoffs = await repo.list_issue_handoffs(
        issue_id=issue_id, board_id=board_id
    )
    return {"handoffs": handoffs, "total": len(handoffs)}


@router.get("/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}")
async def get_handoff(board_id: str, issue_id: str, handoff_id: str):
    _check_board(board_id)
    handoff = await repo.get_issue_handoff(handoff_id)
    if (
        not handoff
        or handoff["boardId"] != board_id
        or handoff["issueId"] != issue_id
    ):
        raise HTTPException(
            status_code=404, detail=f"Handoff '{handoff_id}' not found"
        )
    return handoff
