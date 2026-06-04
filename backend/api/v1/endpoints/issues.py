from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid

# Lazy import: db.repository is touched only inside handlers to keep
# import-time startup lightweight and resilient.
from db import repository as repo
from sqlalchemy.exc import IntegrityError
from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID, assert_board_id_allowed

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


@router.post("/issues")
async def create_issue(request: IssueCreateRequest):
    """
    Create a new issue.

    Persists through the repository. The repository generates the next
    DEV-NNN key based on existing rows.
    """
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
