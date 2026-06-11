from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid

# Lazy import: db.repository is touched only inside handlers to keep
# import-time startup lightweight and resilient.
from db import repository as repo
from sqlalchemy.exc import IntegrityError
from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID, assert_board_id_allowed
from api.v1.auth_deps import require_auth, require_admin

# Parallel createIssue calls race on DEV-NNN key generation
# (next_issue_key reads max-then-increments). The unique constraint
# on Issue.key catches the collision; retry with a fresh key.
_MAX_KEY_RETRIES = 5

router = APIRouter()

# Valid status and priority values
VALID_STATUSES = ["backlog", "in_progress", "blocked", "human_review", "done"]
VALID_PRIORITIES = ["low", "medium", "high", "critical"]
VALID_PROFILES = ["frontend", "backend", "security", "refactor", "debug", "general"]


class IssueCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default="", max_length=5000)
    status: str = Field(default="backlog")
    priority: str = Field(default="medium")
    profile: str = Field(default="general")
    board_id: str = Field(default=DEFAULT_BOARD_ID, description="Board this issue belongs to")


class IssueResponse(BaseModel):
    id: str
    key: str
    title: str
    description: str
    status: str
    priority: str
    profile: str
    board_id: str = DEFAULT_BOARD_ID
    created_at: str
    updated_at: str


class IssueStatusUpdateRequest(BaseModel):
    status: str


@router.get("/issues")
async def list_issues(
    board_id: str = Query(DEFAULT_BOARD_ID, description="Board to list issues for"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    profile: Optional[str] = Query(None, description="Filter by assigned profile")
):
    """
    List all issues with optional filters.

    The repository is the source of truth; this endpoint just adds
    in-memory filtering and validation.
    """
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {VALID_STATUSES}",
        )
    if priority is not None and priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Valid values: {VALID_PRIORITIES}",
        )
    if profile is not None and profile not in VALID_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile. Valid values: {VALID_PROFILES}",
        )

    issues = await repo.list_issues(board_id=board_id)

    if status:
        issues = [i for i in issues if i["status"] == status]
    if priority:
        issues = [i for i in issues if i["priority"] == priority]
    if profile:
        issues = [i for i in issues if i["profile"] == profile]

    return {"issues": issues, "total": len(issues)}


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: str, current_user: dict = Depends(require_auth)):
    """Fetch a single issue by id.

    Used by the epic-tree page to load the epic header (its title,
    status, priority, creation time) so the page can render the
    breadcrumb without a board-wide fetch. We return the same shape
    as the list endpoint: a flat dict with the same fields the
    front-end Issue type expects.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return issue


@router.post("/issues")
async def create_issue(
    request: IssueCreateRequest,
    current_user: dict = Depends(require_auth),
):
    """
    Create a new issue.

    Persists through the repository. The repository generates the next
    DEV-NNN key based on existing rows.
    """
    import logging
    logging.getLogger(__name__).error(f"[create_issue] reached: status={request.status!r} priority={request.priority!r} profile={request.profile!r} user={current_user!r}")
    try:
        assert_board_id_allowed(request.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {VALID_STATUSES}",
        )
    if request.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Valid values: {VALID_PRIORITIES}",
        )
    if request.profile not in VALID_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile. Valid values: {VALID_PROFILES}",
        )

    new_id = str(uuid.uuid4())

    for _attempt in range(_MAX_KEY_RETRIES):
        new_key = await repo.next_issue_key()
        try:
            return await repo.upsert_issue({
                "id": new_id,
                "key": new_key,
                "title": request.title,
                "description": request.description or "",
                "status": request.status,
                "priority": request.priority,
                "profile": request.profile,
                "board_id": request.board_id,
            })
        except IntegrityError:
            # Another concurrent createIssue won this key. Re-read max and retry.
            continue

    raise HTTPException(
        status_code=503,
        detail="Could not allocate a unique issue key after retries",
    )


@router.put("/issues/{issue_id}/status")
async def update_issue_status(
    issue_id: str,
    request: Optional[IssueStatusUpdateRequest] = Body(default=None),
    status: Optional[str] = Query(default=None),
    current_user: dict = Depends(require_auth),
):
    """
    Update issue status.
    """
    next_status = request.status if request else status
    if next_status is None:
        raise HTTPException(status_code=422, detail="Missing status")

    if next_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {VALID_STATUSES}",
        )

    updated = await repo.update_issue_status(issue_id, next_status)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"Issue with id '{issue_id}' not found",
        )

    return updated


# ---------------------------------------------------------------------------
# Epic / parent linkage
# ---------------------------------------------------------------------------
# Reads below the cycle-reports endpoints added earlier. The
# frontend's /board/epic/{epic_id} page uses ``/issues/{id}/children``
# to list every issue whose ``parent_id`` points at the epic, and
# ``/issues/{id}/parent`` to follow the chain up to a root epic.
# Both endpoints are read-only and stay that way — mutation goes
# through the dedicated ``/parent`` PATCH in cycle_reports.py.

@router.get("/issues/{issue_id}/children")
async def list_issue_children(issue_id: str, current_user: dict = Depends(require_auth)):
    """All issues whose ``parent_id`` equals the given issue id.

    Used by the epic-tree page. The list is ordered by
    ``created_at`` so the page renders deterministically; we don't
    surface a ``status`` filter here because the page already groups
    children by status visually.
    """
    parent = await repo.get_issue(issue_id)
    if not parent:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    try:
        assert_board_id_allowed(parent["boardId"])
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    children = await repo.list_issue_children(issue_id)
    return {"children": children, "total": len(children)}


@router.get("/issues/{issue_id}/epic-chain")
async def get_epic_chain(issue_id: str, current_user: dict = Depends(require_auth)):
    """Walk parent_id up to a root epic, return the chain.

    Returns ``[root, ..., self]`` (root first) so the frontend can
    render a breadcrumb. The chain is bounded at 10 levels so a
    pathological self-cycle doesn't lock the request. If the issue
    is itself the root (no parent), the chain contains just the
    issue itself.
    """
    chain = await repo.get_epic_chain(issue_id, max_depth=10)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return {"chain": chain}


# ---------------------------------------------------------------------------
# Archive / unarchive / delete
# ---------------------------------------------------------------------------
# Soft-delete by default. The Mavis collab flow depends on
# cycle_reports, handoffs, and artifacts all staying around for
# audit; a hard DELETE would cascade and break the /reviews page
# plus the audit trail. ``is_archived`` hides the issue from the
# main board while keeping every downstream FK intact.
#
# The hard DELETE endpoint is admin-only and exists for the
# "this issue was created by accident, it never had any work
# logged against it" case. Any non-trivial issue with cycles,
# handoffs, or artifacts should be archived, not deleted.

@router.post("/issues/{issue_id}/archive")
async def archive_issue(issue_id: str, current_user: dict = Depends(require_auth)):
    """Mark an issue as archived. Idempotent."""
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    updated = await repo.archive_issue(issue_id)
    return updated


@router.post("/issues/{issue_id}/unarchive")
async def unarchive_issue(issue_id: str, current_user: dict = Depends(require_auth)):
    """Reverse archive. Idempotent."""
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    updated = await repo.unarchive_issue(issue_id)
    return updated


@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: str, current_user: dict = Depends(require_admin)):
    """Hard delete. Admin only. Cascades to all FKs.

    Reserved for the "this was created by accident, no work
    was ever logged" case. Regular operators should archive
    via the dedicated endpoint so the audit trail stays
    intact.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    await repo.delete_issue(issue_id)
    return {"id": issue_id, "deleted": True}
