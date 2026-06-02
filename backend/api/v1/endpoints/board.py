from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel

# Lazy import: db.repository is touched only inside handlers to keep
# import-time startup lightweight and resilient.
from db import repository as repo

router = APIRouter()

# Column configuration constants
STATUS_LABELS = {
    "backlog": "Backlog",
    "in_progress": "In Progress",
    "blocked": "Blocked",
    "human_review": "Human Review",
    "done": "Done",
}

STATUS_COLORS = {
    "backlog": "#6B7280",       # Gray
    "in_progress": "#3B82F6",   # Blue
    "blocked": "#EF4444",       # Red
    "human_review": "#F59E0B",  # Amber
    "done": "#10B981",          # Green
}

# Valid statuses in order
VALID_STATUSES = ["backlog", "in_progress", "blocked", "human_review", "done"]


class Issue(BaseModel):
    """Issue response matching frontend Issue type."""
    id: str
    key: str
    title: str
    description: str = ""
    status: str
    priority: str = "medium"
    profile: str = "general"
    labels: List[dict] = []
    assigneeId: Optional[str] = None
    assigneeName: Optional[str] = None
    assigneeAvatar: Optional[str] = None
    storyPoints: Optional[int] = None
    dependencies: List[str] = []
    prUrl: Optional[str] = None
    ciStatus: Optional[str] = None
    aiStatus: Optional[str] = None
    harnessType: Optional[str] = None
    eccJobId: Optional[str] = None
    eccJobStatus: Optional[str] = None
    eccJobMessage: Optional[str] = None
    eccJobUpdatedAt: Optional[str] = None
    activityLog: List[dict] = []
    eccLogs: List[dict] = []
    prDetails: Optional[dict] = None
    moveStatus: Optional[str] = None
    moveError: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class Column(BaseModel):
    """Column response matching frontend Column type."""
    id: str
    title: str
    color: str
    issues: List[Issue]


class BoardStateResponse(BaseModel):
    """Board state response compatible with frontend BoardState type."""
    columns: List[Column]


@router.get("/board", response_model=BoardStateResponse)
async def get_board():
    """
    Get board state with columns and issues.

    The board is built fresh from the repository on every request so a
    fresh process sees the persisted state immediately.
    """
    issues = await repo.list_issues()
    issues_by_status: dict[str, list[Issue]] = {s: [] for s in VALID_STATUSES}
    for issue_dict in issues:
        status = issue_dict.get("status", "backlog")
        if status not in issues_by_status:
            continue
        issues_by_status[status].append(Issue(
            id=issue_dict["id"],
            key=issue_dict["key"],
            title=issue_dict["title"],
            description=issue_dict.get("description", ""),
            status=issue_dict["status"],
            priority=issue_dict.get("priority", "medium"),
            profile=issue_dict.get("profile", "general"),
            created_at=issue_dict.get("created_at", ""),
            updated_at=issue_dict.get("updated_at", ""),
            createdAt=issue_dict.get("created_at"),
            updatedAt=issue_dict.get("updated_at"),
        ))

    columns = [
        Column(
            id=status,
            title=STATUS_LABELS[status],
            color=STATUS_COLORS[status],
            issues=issues_by_status[status],
        )
        for status in VALID_STATUSES
    ]

    return BoardStateResponse(columns=columns)
