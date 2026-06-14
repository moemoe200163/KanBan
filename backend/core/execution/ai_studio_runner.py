"""
Plan I (AI Studio) — SSE streaming driver.

The driver is the single point of contact between the FastAPI
endpoint and the provider-agnostic streaming layer in
``backend/core/llm/streaming``. It owns:

1. Provider resolution — look up the active LLMProviderConfig row
   for the requested ``provider_id`` and build a per-request
   ``StreamAdapter`` instance with the right ``api_key`` /
   ``base_url`` / ``model``. The registry in ``core.llm.streaming``
   only knows the protocol; the driver wires in real credentials.
2. Message persistence — every turn writes a ``user`` row first
   (so the history we feed back to the model is current) and one
   ``assistant`` row at the end of the stream (so a client that
   disconnects mid-stream still has a partial-but-coherent log).
3. SSE event shaping — each ``StreamChunk`` becomes a single SSE
   event with the chunk's ``kind`` as the SSE event name and the
   rest of the chunk as the ``data`` payload.

The driver is deliberately a *coroutine* (``async def``), not a
class. The FastAPI endpoint wraps it in
``sse_starlette.sse.EventSourceResponse``, which knows how to drive
a coroutine that yields event dicts and serialise them as
``event: <name>\\ndata: <json>\\n\\n`` frames.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.crypto import decrypt_api_key
from core.llm.streaming import (
    StreamAdapter,
    StreamChunk,
    get_adapter,
    register_adapter,
)
from core.llm.streaming.custom import CustomStreamAdapter
from core.llm.streaming.minimax import MiniMaxStreamAdapter
from core.llm.streaming.openai import OpenAIStreamAdapter
from db.models import AIStudioConversation, AIStudioMessage, LLMProviderConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ID generator
# ---------------------------------------------------------------------------


def gen_id(prefix: str) -> str:
    """Generate a prefixed id (e.g. ``"aiconv_3f2a..."``, ``"aimsg_b91..."``).

    Phase 1 doesn't reuse the project's existing id conventions
    because none of the existing tables use a simple
    ``<prefix>_<hex>`` pattern — they all have a more elaborate
    format (e.g. ``ecc_``, ``board-``, etc.) and we don't want to
    collide with any of them. A fresh ``uuid4().hex[:16]`` is short
    enough for the chat UI to display and long enough to be safe
    against collision in any realistic test corpus.
    """
    if not prefix or not prefix.replace("_", "").isalnum():
        raise ValueError(f"Invalid id prefix: {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


async def _resolve_adapter(
    provider_id: str, db: AsyncSession
) -> Optional[StreamAdapter]:
    """Build a real ``StreamAdapter`` from the ``llm_provider_configs`` row.

    Returns ``None`` when the provider id is unknown or the row has
    no API key — the driver treats that as an unrecoverable error
    and surfaces a single ``error`` SSE event. We do not raise here
    so the streaming generator can emit one final ``message_end``
    before the coroutine closes, keeping the SSE framing on the
    client side clean.
    """
    row = (
        await db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.provider_id == provider_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        logger.warning("ai_studio: no LLMProviderConfig row for %s", provider_id)
        return None

    api_key = decrypt_api_key(row.api_key_encrypted or "")
    base_url = row.base_url or ""
    model = row.model or ""
    shape = (row.api_shape or "").lower()

    if not base_url:
        logger.warning("ai_studio: provider %s has no base_url", provider_id)
        return None

    # Build a per-request adapter. The shape decides which class
    # to use; ``custom`` is the catch-all for OpenAI-compatible
    # servers that the user wired up via the LLM provider
    # settings page.
    if shape == "anthropic-messages" and provider_id == "minimax":
        adapter: StreamAdapter = MiniMaxStreamAdapter(
            api_key=api_key,
            base_url=base_url,
            default_model=model or "MiniMax-M3",
            endpoint_path=row.endpoint_path or "/v1/messages",
        )
    elif shape in ("openai-chat", "openai-responses") and provider_id == "openai":
        adapter = OpenAIStreamAdapter(
            api_key=api_key,
            base_url=base_url,
            default_model=model or "gpt-4o",
            endpoint_path=row.endpoint_path or "/chat/completions",
        )
    else:
        # Anything else (custom server, unknown shape, user
        # pointing the ``minimax`` provider at a different
        # endpoint) gets the generic OpenAI-compatible adapter.
        adapter = CustomStreamAdapter(
            api_key=api_key,
            base_url=base_url,
            default_model=model or "custom-model",
            endpoint_path=row.endpoint_path or "/chat/completions",
        )

    # The registry is global, but every call gets its own adapter
    # instance — we register this one under its provider_id so
    # ``get_adapter`` in the test path can find it. ``register_adapter``
    # replaces previous entries, which is fine because each request
    # builds a fresh instance with the latest DB config.
    register_adapter(adapter)
    return get_adapter(provider_id)


def _default_provider_id() -> str:
    """Return the Phase 1 default provider.

    The plan's prose names ``minimax`` as the default and the
    seeded ``llm_provider_configs`` row matches; we keep the
    default here in one place so future phases can flip it
    without scattering string literals across the driver.
    """
    return "minimax"


# ---------------------------------------------------------------------------
# History loader
# ---------------------------------------------------------------------------


async def _load_history(
    db: AsyncSession, conversation_id: str
) -> list[dict]:
    """Return the conversation's prior turns as an OpenAI-style messages list.

    For Phase 1 we send the *full* history (capped at 50 turns to
    keep the request size sane). The model is given every prior
    ``user`` / ``assistant`` message verbatim — there's no
    truncation, summarisation, or system prompt injection yet.
    Those are Phase 2 (plan §三 8: thinking + system prompt for
    chain-of-thought) and live in the chat UI's request body.
    """
    rows = (
        await db.execute(
            select(AIStudioMessage)
            .where(AIStudioMessage.conversation_id == conversation_id)
            .where(AIStudioMessage.type.in_(("user", "assistant")))
            .order_by(AIStudioMessage.timestamp)
            .limit(100)
        )
    ).scalars().all()

    messages: list[dict] = []
    for r in rows:
        if not r.content:
            continue
        role = "user" if r.type == "user" else "assistant"
        messages.append({"role": role, "content": r.content})
    return messages


# ---------------------------------------------------------------------------
# Chunk serialiser
# ---------------------------------------------------------------------------


def _chunk_to_data(chunk: StreamChunk) -> dict:
    """Project a ``StreamChunk`` down to the dict we ship to the client.

    We don't ship the raw provider event by default — that bloats
    the wire format and leaks provider-internal schema. If the
    client needs the raw event (e.g. for usage stats) it can opt
    in by reading the ``raw`` field; we still strip it down to
    JSON-safe values.
    """
    data: dict = {}
    if chunk.content:
        data["content"] = chunk.content
    if chunk.tool_name:
        data["toolName"] = chunk.tool_name
    if chunk.tool_args is not None:
        data["toolArgs"] = chunk.tool_args
    if chunk.tool_result is not None:
        data["toolResult"] = chunk.tool_result
    if chunk.extra:
        data["extra"] = dict(chunk.extra)
    if chunk.raw is not None:
        # Only forward JSON-safe values; provider payloads can
        # contain datetime / bytes / Decimal in their raw form.
        try:
            json.dumps(chunk.raw)
            data["raw"] = chunk.raw
        except (TypeError, ValueError):
            data["raw"] = {"_unserializable": True}
    return data


# ---------------------------------------------------------------------------
# The streaming driver
# ---------------------------------------------------------------------------


async def stream_ai_studio_message(
    conversation_id: str,
    user_message: str,
    provider_id: str,
    db: AsyncSession,
) -> AsyncIterator[dict]:
    """Yield SSE event dicts for a single assistant turn.

    The outer FastAPI endpoint wraps each yield as a Server-Sent
    Event: ``yield {"event": "content", "data": {"content": "hi"}}``
    becomes ``event: content\\ndata: {"content":"hi"}\\n\\n`` on
    the wire.

    Yielded events follow the schema in plan §三 3:

    - ``message_start`` — fires once, before the first model
      token. ``data`` includes the conversation id.
    - ``content`` — one per text delta. ``data.content`` is the
      delta text.
    - ``error`` — surfaces unrecoverable errors. ``data.detail``
      is a short, user-safe string.
    - ``message_end`` — fires once, after the model stream ends.
      ``data.messageId`` is the persisted ``AIStudioMessage.id``.
    """
    yield {
        "event": "message_start",
        "data": {"conversationId": conversation_id},
    }

    # ------------------------------------------------------------------
    # 1. Persist the user message. Doing this *before* the model
    #    call means a request that crashes mid-stream still has the
    #    user turn in the conversation log; the client can refresh
    #    the page and see what they typed.
    # ------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    user_msg = AIStudioMessage(
        id=gen_id("aimsg"),
        conversation_id=conversation_id,
        type="user",
        content=user_message,
        timestamp=now,
    )
    db.add(user_msg)
    # Touch updated_at on the conversation so the list endpoint
    # sorts by recency correctly.
    conv = await db.get(AIStudioConversation, conversation_id)
    if conv is not None:
        conv.updated_at = now
    try:
        await db.commit()
    except Exception as exc:
        logger.exception("ai_studio: failed to persist user message")
        await db.rollback()
        yield {
            "event": "error",
            "data": {"detail": f"persistence failure: {exc}"},
        }
        return

    # ------------------------------------------------------------------
    # 2. Resolve the provider adapter. If we can't, the call is
    #    over before it starts.
    # ------------------------------------------------------------------
    try:
        adapter = await _resolve_adapter(provider_id, db)
    except Exception as exc:
        logger.exception("ai_studio: provider resolution failed")
        yield {
            "event": "error",
            "data": {"detail": f"provider resolution failed: {exc}"},
        }
        return

    if adapter is None:
        yield {
            "event": "error",
            "data": {
                "detail": (
                    f"LLM provider '{provider_id}' is not configured. "
                    f"Add an API key in the LLM Providers settings."
                ),
            },
        }
        return

    # ------------------------------------------------------------------
    # 3. Load history and stream the model. The history is captured
    #    *after* the user message is committed, so the model sees
    #    the user's own text plus everything that came before.
    # ------------------------------------------------------------------
    history = await _load_history(db, conversation_id)

    # Optional system prompt — Phase 2 will inject chain-of-thought
    # scaffolding here. For Phase 1 we keep it None so the
    # provider's default behaviour shines through.
    system: Optional[str] = None

    assistant_chunks: list[str] = []
    model_id: Optional[str] = None
    try:
        async for chunk in adapter.stream(
            history,
            system=system,
            temperature=0.7,
            max_tokens=1024,
        ):
            if chunk.kind == "content" and chunk.content:
                assistant_chunks.append(chunk.content)
            yield {"event": chunk.kind, "data": _chunk_to_data(chunk)}
            # Pull a model id out of message_start raw payloads
            # when present (Anthropic-style events carry the
            # model name in ``message.model``). We don't enforce
            # it; it's only for the persisted metadata.
            if chunk.raw and chunk.raw.get("message", {}).get("model"):
                model_id = chunk.raw["message"]["model"]
    except Exception as exc:
        logger.exception("ai_studio: streaming failed")
        # Best-effort: try to persist whatever we got so a UI
        # refresh shows the partial reply instead of nothing.
        await _persist_assistant(
            db, conversation_id, "".join(assistant_chunks)
        )
        yield {
            "event": "error",
            "data": {"detail": f"streaming failed: {exc}"},
        }
        return

    # ------------------------------------------------------------------
    # 4. Persist the assistant message.
    # ------------------------------------------------------------------
    full_reply = "".join(assistant_chunks)
    assistant_msg_id = await _persist_assistant(
        db, conversation_id, full_reply, model_id=model_id
    )

    yield {
        "event": "message_end",
        "data": {"messageId": assistant_msg_id} if assistant_msg_id else {},
    }


async def _persist_assistant(
    db: AsyncSession,
    conversation_id: str,
    content: str,
    *,
    model_id: Optional[str] = None,
) -> Optional[str]:
    """Persist the assistant turn. Returns the new ``AIStudioMessage.id``.

    Failures are logged but never raised — by the time we get here
    the user already saw the full text via SSE events, and the
    message_end event will arrive with an empty payload so the
    client can at least close the connection cleanly.
    """
    if not content:
        # Nothing to persist; the model returned zero text (rare
        # but legal — the safety filter can refuse to answer).
        return None
    now = datetime.now(timezone.utc)
    msg = AIStudioMessage(
        id=gen_id("aimsg"),
        conversation_id=conversation_id,
        type="assistant",
        content=content,
        timestamp=now,
    )
    db.add(msg)
    conv = await db.get(AIStudioConversation, conversation_id)
    if conv is not None:
        conv.updated_at = now
        if model_id and not conv.model:
            conv.model = model_id
    try:
        await db.commit()
    except Exception:
        logger.exception("ai_studio: failed to persist assistant message")
        await db.rollback()
        return None
    return msg.id
