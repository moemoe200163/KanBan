"""
Plan I (AI Studio) — 5 HTTP endpoints + 1 SSE stream.

Routes (mounted under ``/api/v1`` via ``backend/main.py``):

* ``POST   /ai-studio/conversations``               — create a new conversation
* ``GET    /ai-studio/conversations``               — list the caller's conversations
* ``GET    /ai-studio/conversations/{id}``          — load a conversation + its messages
* ``POST   /ai-studio/conversations/{id}/messages`` — send a user message, return SSE stream
* ``POST   /ai-studio/conversations/{id}/cancel``   — stop a streaming response (Phase 1: 200 OK no-op)
* ``DELETE /ai-studio/conversations/{id}``          — delete a conversation (cascades to messages)

The Plan I MVP is single-tenant, single-user per conversation. We
filter every list / read by ``current_user.user_id`` so user A can
never see user B's conversations. The ``admin`` / ``ops`` /
``super_admin`` roles retain the same per-user scope — they see
their own conversations only; cross-tenant impersonation is not
on the Phase 1 menu (it lands with the J-3 super_admin tooling).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from api.v1.auth_deps import require_auth
from api.v1.endpoints.auth import get_db_session
from core.execution.ai_studio_runner import (
    _default_provider_id,
    gen_id,
    stream_ai_studio_message,
)
from db.models import AIStudioConversation, AIStudioMessage, DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=256)
    provider_id: Optional[str] = Field(default=None, max_length=64)
    model: Optional[str] = Field(default=None, max_length=128)


class ConversationSummary(BaseModel):
    id: str
    title: str
    userId: str
    providerId: str
    model: Optional[str] = None
    createdAt: str
    updatedAt: str


class ConversationDetail(BaseModel):
    id: str
    title: str
    userId: str
    providerId: str
    model: Optional[str] = None
    createdAt: str
    updatedAt: str
    messages: List["MessageOut"] = []


class MessageOut(BaseModel):
    id: str
    conversationId: str
    type: str
    content: Optional[str] = None
    toolName: Optional[str] = None
    toolArgs: Optional[dict] = None
    toolResult: Optional[str] = None
    agentRole: Optional[str] = None
    timestamp: str


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=32_000)
    provider_id: Optional[str] = Field(default=None, max_length=64)


class CancelResponse(BaseModel):
    ok: bool
    conversationId: str
    detail: str = "cancel is a no-op in Phase 1; close the SSE stream on the client"


# Resolve the forward ref declared in ConversationDetail
ConversationDetail.model_rebuild()


# ---------------------------------------------------------------------------
# 5 endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/ai-studio/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    tags=["AI Studio"],
)
async def create_conversation(
    body: CreateConversationRequest,
    current_user: Annotated[dict, Depends(require_auth)],
    db_factory=Depends(get_db_session),
) -> ConversationSummary:
    """Create a new conversation owned by the caller."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    tenant_id = current_user.get("tenant_id") or DEFAULT_TENANT_ID
    provider_id = body.provider_id or _default_provider_id()
    now = datetime.now(timezone.utc)
    async with db_factory() as db:
        conv = AIStudioConversation(
            id=gen_id("aiconv"),
            title=body.title,
            user_id=user_id,
            tenant_id=tenant_id,
            provider_id=provider_id,
            model=body.model,
            created_at=now,
            updated_at=now,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return ConversationSummary(
        id=conv.id,
        title=conv.title,
        userId=conv.user_id,
        providerId=conv.provider_id,
        model=conv.model,
        createdAt=conv.created_at.isoformat() if conv.created_at else "",
        updatedAt=conv.updated_at.isoformat() if conv.updated_at else "",
    )


@router.get(
    "/ai-studio/conversations",
    response_model=List[ConversationSummary],
    tags=["AI Studio"],
)
async def list_conversations(
    current_user: Annotated[dict, Depends(require_auth)],
    db_factory=Depends(get_db_session),
) -> List[ConversationSummary]:
    """List the caller's conversations, most-recently-updated first."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    async with db_factory() as db:
        rows = (
            await db.execute(
                select(AIStudioConversation)
                .where(AIStudioConversation.user_id == user_id)
                .order_by(AIStudioConversation.updated_at.desc())
            )
        ).scalars().all()
    return [
        ConversationSummary(
            id=r.id,
            title=r.title,
            userId=r.user_id,
            providerId=r.provider_id,
            model=r.model,
            createdAt=r.created_at.isoformat() if r.created_at else "",
            updatedAt=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.get(
    "/ai-studio/conversations/{conversation_id}",
    response_model=ConversationDetail,
    tags=["AI Studio"],
)
async def get_conversation(
    conversation_id: str,
    current_user: Annotated[dict, Depends(require_auth)],
    db_factory=Depends(get_db_session),
) -> ConversationDetail:
    """Load a single conversation + its message history.

    The caller must own the conversation. We don't return 404 vs
    403 distinctly — both look the same to the client — so a
    malicious probe can't enumerate other users' ids.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    async with db_factory() as db:
        conv = (
            await db.execute(
                select(AIStudioConversation).where(
                    AIStudioConversation.id == conversation_id
                )
            )
        ).scalar_one_or_none()
        if conv is None or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = (
            await db.execute(
                select(AIStudioMessage)
                .where(AIStudioMessage.conversation_id == conversation_id)
                .order_by(AIStudioMessage.timestamp)
            )
        ).scalars().all()
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        userId=conv.user_id,
        providerId=conv.provider_id,
        model=conv.model,
        createdAt=conv.created_at.isoformat() if conv.created_at else "",
        updatedAt=conv.updated_at.isoformat() if conv.updated_at else "",
        messages=[
            MessageOut(
                id=m.id,
                conversationId=m.conversation_id,
                type=m.type,
                content=m.content,
                toolName=m.tool_name,
                toolArgs=m.tool_args,
                toolResult=m.tool_result,
                agentRole=m.agent_role,
                timestamp=m.timestamp.isoformat() if m.timestamp else "",
            )
            for m in messages
        ],
    )


@router.post(
    "/ai-studio/conversations/{conversation_id}/messages",
    tags=["AI Studio"],
)
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    current_user: Annotated[dict, Depends(require_auth)],
    db_factory=Depends(get_db_session),
):
    """Send a user message and stream the assistant's reply as SSE.

    The endpoint returns a ``text/event-stream`` response. Events:

    - ``message_start`` — first event; carries the conversation id
    - ``content``       — one per text delta
    - ``error``         — surfaces unrecoverable failures
    - ``message_end``   — last event; carries the persisted
                          ``messageId`` of the assistant turn

    Phase 1 is single-model; the driver always uses the
    conversation's ``provider_id`` (or ``?provider=...`` if the
    body sets one) for the whole turn.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    async with db_factory() as db:
        conv = (
            await db.execute(
                select(AIStudioConversation).where(
                    AIStudioConversation.id == conversation_id
                )
            )
        ).scalar_one_or_none()
        if conv is None or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        provider_id = body.provider_id or conv.provider_id or _default_provider_id()

        async def event_iter():
            async with db_factory() as stream_db:
                async for event in stream_ai_studio_message(
                    conversation_id=conversation_id,
                    user_message=body.content,
                    provider_id=provider_id,
                    db=stream_db,
                ):
                    yield event

        return EventSourceResponse(event_iter())


@router.post(
    "/ai-studio/conversations/{conversation_id}/cancel",
    response_model=CancelResponse,
    tags=["AI Studio"],
)
async def cancel_message(
    conversation_id: str,
    current_user: Annotated[dict, Depends(require_auth)],
) -> CancelResponse:
    """Cancel an in-flight streaming response.

    Phase 1 is a no-op: we don't track stream handles server-side,
    and the client owns the connection so it can simply abort the
    ``fetch`` / ``EventSource`` to stop the response. The endpoint
    exists so the chat UI doesn't have to special-case the
    Phase 2 behaviour (which will track a per-conversation
    ``asyncio.Task`` and call ``.cancel()`` on it).
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return CancelResponse(ok=True, conversationId=conversation_id)


@router.delete(
    "/ai-studio/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["AI Studio"],
)
async def delete_conversation(
    conversation_id: str,
    current_user: Annotated[dict, Depends(require_auth)],
    db_factory=Depends(get_db_session),
) -> None:
    """Delete a conversation. Cascades to all of its messages."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    async with db_factory() as db:
        conv = (
            await db.execute(
                select(AIStudioConversation).where(
                    AIStudioConversation.id == conversation_id
                )
            )
        ).scalar_one_or_none()
        if conv is None or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        await db.delete(conv)
        await db.commit()
    return None
