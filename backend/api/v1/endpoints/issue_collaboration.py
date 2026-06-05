"""
P2: Issue Collaboration Records API

Endpoints for issue events, comments, and artifacts.
All endpoints require an issue_id path parameter and operate within
the scope of that issue.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List

from db import repository as repo
from api.v1.auth_deps import require_auth

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)
    authorId: Optional[str] = Field(default=None, max_length=64)
    authorName: Optional[str] = Field(default=None, max_length=128)
    commentType: str = Field(default="comment", max_length=32)
    metadata: Optional[dict] = None


class ArtifactCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    artifactType: str = Field(..., max_length=64)
    jobId: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default=None, max_length=128)
    pathOrUrl: Optional[str] = Field(default=None, max_length=1024)
    sensitivity: str = Field(default="public", max_length=32)
    summary: Optional[str] = Field(default=None, max_length=5000)
    metadata: Optional[dict] = None
    createdById: Optional[str] = Field(default=None, max_length=64)
    createdByName: Optional[str] = Field(default=None, max_length=128)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/issues/{issue_id}/events")
async def list_issue_events(
    issue_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    List events for an issue, newest first.

    Returns the collaboration timeline: status changes, handoffs,
    decisions, command runs, etc.
    """
    # Verify issue exists
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{issue_id}' not found",
        )

    events = await repo.list_issue_events(issue_id, limit=limit)
    return {"events": events, "total": len(events)}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.get("/issues/{issue_id}/comments")
async def list_issue_comments(
    issue_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    List comments for an issue, oldest first.

    Returns human/agent notes and discussion threads.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{issue_id}' not found",
        )

    comments = await repo.list_issue_comments(issue_id, limit=limit)
    return {"comments": comments, "total": len(comments)}


@router.post("/issues/{issue_id}/comments", status_code=201)
async def create_issue_comment(
    issue_id: str,
    request: CommentCreateRequest,
    current_user: dict = Depends(require_auth),
):
    """
    Create a comment on an issue.

    Also creates an event on the issue timeline.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{issue_id}' not found",
        )

    comment = await repo.create_issue_comment(
        issue_id=issue_id,
        body=request.body,
        author_id=request.authorId,
        author_name=request.authorName,
        comment_type=request.commentType,
        metadata=request.metadata,
    )

    # Also create an event for the timeline
    await repo.create_issue_event(
        issue_id=issue_id,
        event_type="comment",
        summary=f"Comment added by {request.authorName or 'anonymous'}",
        actor_id=request.authorId,
        actor_name=request.authorName,
        details={"commentId": comment["id"], "commentType": request.commentType},
    )

    return comment


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

@router.get("/issues/{issue_id}/artifacts")
async def list_issue_artifacts(
    issue_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    List artifacts for an issue, newest first.

    Returns metadata about files, outputs, and evidence linked to the issue.
    v1 is metadata-only — no binary storage.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{issue_id}' not found",
        )

    artifacts = await repo.list_issue_artifacts(issue_id, limit=limit)
    return {"artifacts": artifacts, "total": len(artifacts)}


@router.post("/issues/{issue_id}/artifacts", status_code=201)
async def create_issue_artifact(
    issue_id: str,
    request: ArtifactCreateRequest,
    current_user: dict = Depends(require_auth),
):
    """
    Create artifact metadata for an issue.

    v1 is metadata-only — stores path/URL reference, not the actual file.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{issue_id}' not found",
        )

    artifact = await repo.create_issue_artifact(
        issue_id=issue_id,
        title=request.title,
        artifact_type=request.artifactType,
        job_id=request.jobId,
        source=request.source,
        path_or_url=request.pathOrUrl,
        sensitivity=request.sensitivity,
        summary=request.summary,
        metadata=request.metadata,
        created_by_id=request.createdById,
        created_by_name=request.createdByName,
    )

    # Also create an event for the timeline
    await repo.create_issue_event(
        issue_id=issue_id,
        event_type="artifact_added",
        summary=f"Artifact '{request.title}' added",
        actor_id=request.createdById,
        actor_name=request.createdByName,
        details={"artifactId": artifact["id"], "artifactType": request.artifactType},
    )

    return artifact
