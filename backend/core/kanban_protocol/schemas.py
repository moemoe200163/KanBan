"""Pydantic schemas for Kanban Protocol API requests and responses."""
from typing import List, Optional

from pydantic import BaseModel, Field


HandoffStatus = str  # one of: pending, accepted, in_progress, completed, blocked, cancelled


class HandoffCreateRequest(BaseModel):
    fromLane: Optional[str] = Field(default=None, max_length=32)
    toLane: str = Field(..., min_length=1, max_length=32)
    payload: Optional[dict] = Field(default_factory=dict)
    createdBy: Optional[str] = Field(default=None, max_length=128)


class HandoffActorRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)


class HandoffCompleteRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)
    payload: Optional[dict] = None  # if provided, merged into the existing payload


class HandoffDispatchRequest(BaseModel):
    issueKey: str = Field(..., min_length=1, max_length=32)
    profile: str = Field(..., min_length=1, max_length=32)
    actor: Optional[str] = Field(default=None, max_length=128)


class HandoffBlockRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)
    blockReason: str = Field(..., min_length=1, max_length=4000)


class HandoffCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)
    authorId: Optional[str] = Field(default=None, max_length=64)
    authorName: Optional[str] = Field(default=None, max_length=128)
    commentType: str = Field(default="handoff", max_length=32)


class HandoffPreviewResponse(BaseModel):
    handoffId: str
    toLane: str
    displayName: str
    defaultProvider: str
    defaultModel: str
    allowedCommands: List[str]
    requiredCompletionFields: List[str]
    presentFields: List[str]
    missingFields: List[str]
    nextLanes: List[str]
    humanApprovalRequired: bool
    hasApprover: bool
    timeoutSeconds: int
    retryPolicy: str
    retryMax: int
