"""
Plan J-3 stub — ai_studio conversations endpoints.

Plan J-3 prompt §九 #18-19: GET/POST /ai-studio/conversations under
the ``require_auth`` gate. The AI Studio feature ships in Plan I; this
file reserves the routes so the J-3 contract (signature + gate) is
in place. Handler bodies return 501 with a clear J-3 marker.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth


router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ConversationSummary(BaseModel):
    id: str
    title: str
    owner_id: str
    created_at: str
    updated_at: str


class PostConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    body: str = Field(..., min_length=1)


class PostConversationResponse(BaseModel):
    id: str
    title: str
    owner_id: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get(
    "/ai-studio/conversations",
    response_model=List[ConversationSummary],
    tags=["AI Studio"],
)
async def list_conversations(
    current_user: Annotated[dict, Depends(require_auth)],
) -> List[ConversationSummary]:
    """List the caller's conversations.

    Plan J-3 stub: returns an empty list. The real implementation
    lands in Plan I alongside the conversation persistence layer.
    """
    return []


@router.post(
    "/ai-studio/conversations",
    response_model=PostConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["AI Studio"],
)
async def post_conversation(
    body: PostConversationRequest,
    current_user: Annotated[dict, Depends(require_auth)],
) -> PostConversationResponse:
    """Create a new conversation owned by the caller.

    Plan J-3 stub: echoes a synthetic id. Plan I replaces the body
    with the real insert into the conversations table.
    """
    conv_id = f"conv_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    return PostConversationResponse(
        id=conv_id,
        title=body.title,
        owner_id=current_user.get("user_id", "anonymous"),
        created_at=now,
    )
