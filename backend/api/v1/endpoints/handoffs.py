"""Kanban Protocol — Handoff API."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.kanban_protocol.board_scope import assert_board_id_allowed
from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.lanes import get_lane
from core.kanban_protocol.schemas import (
    HandoffActorRequest,
    HandoffBlockRequest,
    HandoffCommentRequest,
    HandoffCompleteRequest,
    HandoffCreateRequest,
    HandoffDispatchRequest,
    HandoffPreviewResponse,
)
from core.kanban_protocol.payloads import PayloadValidationError
from core.kanban_protocol.scope_guard import ScopeDeniedError
from db import repository as repo

router = APIRouter()
_svc = HandoffService()


def _check_board(board_id: str) -> None:
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


async def _resolve_handoff(board_id: str, issue_id: str, handoff_id: str) -> dict:
    """Validate board, issue, and handoff ownership. Returns handoff dict or raises 404."""
    _check_board(board_id)
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
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
    return await _resolve_handoff(board_id, issue_id, handoff_id)


@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/accept"
)
async def accept_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        return await _svc.accept(handoff_id, actor=body.actor)
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/dispatch"
)
async def dispatch_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffDispatchRequest,
    background_tasks: BackgroundTasks,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        issue = await repo.get_issue(issue_id)
        result = await _svc.dispatch(
            handoff_id=handoff_id,
            issue_key=issue["key"],  # authoritative, not body.issueKey
            profile=body.profile,
            actor=body.actor,
        )

        # Auto-start safe runner for the created job.
        # _svc.dispatch creates a DB row via create_job_for_handoff;
        # we now also register it in the in-memory ecc._jobs registry
        # and kick off the safe-runner background task.
        job_data = result.get("job")
        if job_data and job_data.get("id"):
            from api.v1.endpoints.ecc import (
                _execute_safe_runner,
                _register_job_from_db,
            )
            await _register_job_from_db(job_data["id"])
            background_tasks.add_task(_execute_safe_runner, job_data["id"])

        return result
    except (ValueError, ScopeDeniedError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/complete"
)
async def complete_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffCompleteRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        result = await _svc.complete(
            handoff_id=handoff_id,
            actor=body.actor,
            payload=body.payload,
        )

        # Auto-create artifacts from typed payload fields.
        payload = body.payload or {}

        for shot in (payload.get("screenshots") or []):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title=shot,
                artifact_type="screenshot",
                job_id=None,
                source="handoff_complete",
                path_or_url=shot,
                summary=f"Screenshot from handoff {handoff_id}",
            )

        if payload.get("diff_summary"):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title="Diff Summary",
                artifact_type="diff_summary",
                job_id=None,
                source="handoff_complete",
                path_or_url=None,
                summary=payload["diff_summary"],
            )

        if payload.get("test_results"):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title="Test Results",
                artifact_type="test_log",
                job_id=None,
                source="handoff_complete",
                path_or_url=None,
                summary=payload["test_results"],
            )

        return result
    except PayloadValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Validation failed for lane '{exc.lane}'",
                "lane": exc.lane,
                "errors": exc.errors,
            },
        )
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Block endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/block"
)
async def block_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffBlockRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        return await _svc.block(
            handoff_id=handoff_id,
            actor=body.actor,
            reason=body.blockReason,
        )
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Unblock endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/unblock"
)
async def unblock_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        return await _svc.unblock(
            handoff_id=handoff_id,
            actor=body.actor,
        )
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/cancel"
)
async def cancel_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        return await _svc.cancel(
            handoff_id=handoff_id,
            actor=body.actor,
        )
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Comment endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/comment",
    status_code=201,
)
async def comment_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffCommentRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    return await _svc.comment(
        issue_id=issue_id,
        handoff_id=handoff_id,
        body=body.body,
        author_id=body.authorId,
        author_name=body.authorName,
        comment_type=body.commentType,
    )


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/preview"
)
async def preview_handoff(board_id: str, issue_id: str, handoff_id: str):
    handoff = await _resolve_handoff(board_id, issue_id, handoff_id)
    lane = get_lane(handoff["toLane"])
    payload = handoff.get("payload") or {}
    required = lane.required_completion_fields
    present_fields = [f for f in required if f in payload]
    missing_fields = [f for f in required if f not in payload]
    return HandoffPreviewResponse(
        handoffId=handoff["id"],
        toLane=lane.key,
        displayName=lane.display_name,
        defaultProvider=lane.default_provider,
        defaultModel=lane.default_model,
        allowedCommands=lane.allowed_commands,
        requiredCompletionFields=required,
        presentFields=present_fields,
        missingFields=missing_fields,
        nextLanes=lane.next_lanes,
        humanApprovalRequired=lane.human_approval_required,
        hasApprover=bool("approver" in payload),
        timeoutSeconds=lane.timeout_seconds,
        retryPolicy=lane.retry_policy,
        retryMax=lane.retry_max,
    )
