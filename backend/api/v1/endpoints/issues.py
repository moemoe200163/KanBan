from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid

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


class IssueResponse(BaseModel):
    id: str
    key: str
    title: str
    description: str
    status: str
    priority: str
    profile: str
    created_at: str
    updated_at: str


# In-memory issue storage (in production, use database)
_issues_db: List[IssueResponse] = []
_issue_counter = 0


def _seed_initial_issues() -> None:
    """Seed the in-memory database with initial issues for demo purposes."""
    global _issues_db, _issue_counter
    if _issues_db:  # Already seeded
        return

    now = datetime.now(timezone.utc).isoformat()

    seed_data = [
        {"title": "Implement user authentication flow", "status": "done", "priority": "high", "profile": "backend"},
        {"title": "Build Kanban board drag-and-drop", "status": "in_progress", "priority": "high", "profile": "frontend"},
        {"title": "Set up CI/CD pipeline", "status": "in_progress", "priority": "medium", "profile": "backend"},
        {"title": "Design system documentation", "status": "backlog", "priority": "medium", "profile": "frontend"},
        {"title": "API rate limiting implementation", "status": "backlog", "priority": "high", "profile": "backend"},
        {"title": "Mobile responsive fixes", "status": "blocked", "priority": "medium", "profile": "frontend"},
        {"title": "Security audit for auth module", "status": "human_review", "priority": "critical", "profile": "security"},
        {"title": "Database migration script", "status": "done", "priority": "medium", "profile": "backend"},
    ]

    for i, data in enumerate(seed_data, start=1):
        _issue_counter = i
        issue = IssueResponse(
            id=f"seed-{i}",
            key=f"DEV-{i:03d}",
            title=data["title"],
            description="",
            status=data["status"],
            priority=data["priority"],
            profile=data["profile"],
            created_at=now,
            updated_at=now,
        )
        _issues_db.append(issue)


# Seed on module load
_seed_initial_issues()


def _generate_issue_key() -> str:
    """Generate the next issue key (e.g., DEV-001, DEV-002)."""
    global _issue_counter
    _issue_counter += 1
    return f"DEV-{_issue_counter:03d}"


@router.get("/issues")
async def list_issues(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    profile: Optional[str] = Query(None, description="Filter by assigned profile")
):
    """
    List all issues with optional filters.

    Supports filtering by:
    - status: Filter by issue status (backlog, in_progress, blocked, human_review, done)
    - priority: Filter by priority (low, medium, high, critical)
    - profile: Filter by assigned agent profile

    Args:
        status: Optional status filter
        priority: Optional priority filter
        profile: Optional profile filter

    Returns:
        Dictionary with issues array and total count
    """
    filtered_issues = _issues_db

    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Valid values: {VALID_STATUSES}"
            )
        filtered_issues = [i for i in filtered_issues if i.status == status]

    if priority:
        if priority not in VALID_PRIORITIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority. Valid values: {VALID_PRIORITIES}"
            )
        filtered_issues = [i for i in filtered_issues if i.priority == priority]

    if profile:
        if profile not in VALID_PROFILES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid profile. Valid values: {VALID_PROFILES}"
            )
        filtered_issues = [i for i in filtered_issues if i.profile == profile]

    return {
        "issues": [i.model_dump() for i in filtered_issues],
        "total": len(filtered_issues)
    }


@router.post("/issues")
async def create_issue(request: IssueCreateRequest):
    """
    Create a new issue.

    Creates a new issue with the provided details. The issue is assigned
    a unique ID and key (e.g., DEV-001).

    Args:
        request: Issue creation payload

    Returns:
        Created issue with id, key, and all fields

    Raises:
        HTTPException 400: If validation fails
    """
    # Validate status
    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {VALID_STATUSES}"
        )

    # Validate priority
    if request.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Valid values: {VALID_PRIORITIES}"
        )

    # Validate profile
    if request.profile not in VALID_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile. Valid values: {VALID_PROFILES}"
        )

    now = datetime.now(timezone.utc).isoformat()
    issue = IssueResponse(
        id=str(uuid.uuid4()),
        key=_generate_issue_key(),
        title=request.title,
        description=request.description,
        status=request.status,
        priority=request.priority,
        profile=request.profile,
        created_at=now,
        updated_at=now
    )

    _issues_db.append(issue)

    # TODO: Integrate with database (PostgreSQL via SQLAlchemy)
    # TODO: Publish event to message queue for agent notification

    return issue


@router.put("/issues/{issue_id}/status")
async def update_issue_status(issue_id: str, status: str):
    """
    Update issue status.

    Transitions an issue to a new status. This may trigger
    webhook notifications for downstream systems.

    Args:
        issue_id: The issue ID to update
        status: The new status

    Returns:
        Updated issue with new status

    Raises:
        HTTPException 404: If issue not found
        HTTPException 400: If status is invalid
    """
    # Validate status
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {VALID_STATUSES}"
        )

    # Find the issue
    issue = next((i for i in _issues_db if i.id == issue_id), None)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue with id '{issue_id}' not found"
        )

    old_status = issue.status
    issue.status = status
    issue.updated_at = datetime.now(timezone.utc).isoformat()

    # TODO: Trigger webhook for status change
    # This would typically enqueue a webhook task via Redis

    return issue.model_dump()


# Test cases for list_issues
# - Should return all issues when no filters provided
# - Should return empty array when no issues exist
# - Should filter by status correctly
# - Should filter by priority correctly
# - Should filter by profile correctly
# - Should return 400 for invalid status filter
# - Should return 400 for invalid priority filter
# - Should return 400 for invalid profile filter
# - Should combine multiple filters with AND logic

# Test cases for create_issue
# - Should create issue with generated id and key
# - Should use default values when optional fields not provided
# - Should return 400 for invalid status
# - Should return 400 for invalid priority
# - Should return 400 for invalid profile
# - Should return 400 when title is empty
# - Should return 400 when title exceeds 200 characters

# Test cases for update_issue_status
# - Should update status when issue exists
# - Should return 404 when issue not found
# - Should return 400 for invalid status value
# - Should update the updated_at timestamp
