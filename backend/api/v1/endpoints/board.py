from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel

# Lazy import: db.repository is touched only inside handlers to keep
# import-time startup lightweight and resilient.
from db import repository as repo
from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID, assert_board_id_allowed
from api.v1.auth_deps import require_auth, require_role as _require_role
require_role_ops = _require_role("ops", "admin")

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
    # Mavis collaboration fields — exposed so the front-end can
    # render the epic-subtask marker on the card and the structured
    # acceptance-criteria checklist in the detail drawer.
    parentId: Optional[str] = None
    acceptanceCriteria: List[dict] = []
    isArchived: bool = False
    archivedAt: Optional[str] = None
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


class BoardSummary(BaseModel):
    """One entry in the ``GET /api/v1/boards`` response.

    Boards are derived from the issues table (no dedicated registry),
    so the id, display name, and live issue count are the only fields
    the UI needs to render the sidebar selector.
    """
    id: str
    name: str
    issueCount: int


@router.get("/board", response_model=BoardStateResponse)
async def get_board(
    board_id: str = Query(DEFAULT_BOARD_ID, description="Board to retrieve"),
    include_archived: bool = Query(default=False, description="When true, include archived issues (operator opt-in via the sidebar toggle)"),
):
    """
    Get board state with columns and issues.

    The board is built fresh from the repository on every request so a
    fresh process sees the persisted state immediately. Archived
    issues are filtered out by default; pass ``include_archived=1``
    to surface them so the operator can review and unarchive.
    """
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    issues = await repo.list_issues(board_id=board_id, include_archived=include_archived)
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
            prUrl=issue_dict.get("prUrl"),
            ciStatus=issue_dict.get("ciStatus"),
            parentId=issue_dict.get("parentId"),
            acceptanceCriteria=issue_dict.get("acceptanceCriteria") or [],
            isArchived=bool(issue_dict.get("isArchived", False)),
            archivedAt=issue_dict.get("archivedAt"),
            created_at=issue_dict.get("createdAt", ""),
            updated_at=issue_dict.get("updatedAt", ""),
            createdAt=issue_dict.get("createdAt"),
            updatedAt=issue_dict.get("updatedAt"),
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


@router.get("/boards", response_model=List[BoardSummary])
async def list_boards(
    current_user: dict = Depends(require_auth),
) -> List[BoardSummary]:
    """List every board the operator can switch to.

    Boards are inferred from ``Issue.distinct(board_id)`` — see
    :func:`db.repository.list_boards` — so any board that has at least
    one issue shows up. ``DEFAULT_BOARD_ID`` is always included even
    on a fresh database so the selector has something to render.

    Requires authentication: a future multi-tenant deployment will
    need to filter this list per-user, so we lock it down now and
    avoid an unannounced behaviour change later.
    """
    rows = await repo.list_boards()
    return [BoardSummary(**row) for row in rows]


# ---------------------------------------------------------------------------
# Plan J-3 stub: POST /board — create a new board
# ---------------------------------------------------------------------------
# Plan J-3 prompt §九 #15: this endpoint is reserved under the
# require_ops gate. The codebase's boards are derived from the
# issues table (no dedicated registry), so the "create" semantics
# here are: validate the board_id, then add a 0-issue board to
# the sidebar by writing a sentinel issue. We don't do that here;
# the placeholder returns 501 so the gate is testable without
# committing to a side-effect. A future iteration can land the
# sentinel-issue logic alongside the multi-tenant board_id work.
from typing import Annotated


@router.post("/board", tags=["Board"], status_code=201)
async def create_board(
    body: dict,
    _ops: Annotated[dict, Depends(require_role_ops)],
):
    """Plan J-3 stub: ops/admin can register a new board.

    The handler is intentionally a placeholder; the real
    implementation lands when the multi-tenant board_id
    refactor ships (out of J-3 scope).
    """
    raise HTTPException(
        status_code=501,
        detail="POST /board is a J-3 reserved route; create_board "
               "semantics land with the multi-tenant board_id refactor.",
    )
