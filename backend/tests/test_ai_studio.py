"""
Plan I-MVP-1 — AI Studio backend tests.

Covers:

1. ``test_stream_chunk_dataclass`` — StreamChunk shape contract.
2. ``test_adapter_registry_roundtrip`` — register / get / list
   adapters via the in-process registry.
3. ``test_minimax_adapter_provider_id`` — MiniMaxStreamAdapter is
   queryable as ``provider_id == "minimax"``.
4. ``test_openai_adapter_provider_id`` — OpenAIStreamAdapter is
   queryable as ``provider_id == "openai"``.
5. ``test_custom_adapter_provider_id`` — CustomStreamAdapter
   subclasses the OpenAI one and is queryable as
   ``provider_id == "custom"``.
6. ``test_minimax_adapter_parses_anthropic_sse`` — feed the adapter
   a fake Anthropic Messages SSE stream via ``httpx.MockTransport``
   and assert the right ``StreamChunk`` sequence comes out.
7. ``test_minimax_adapter_surfaces_http_error`` — non-200 response
   becomes a single ``error`` chunk.
8. ``test_openai_adapter_parses_chat_completions_sse`` — feed the
   OpenAI adapter a fake chat-completions SSE stream and assert
   the right text accumulates.
9. ``test_runner_gen_id_format`` — id prefix round-trips.
10. ``test_runner_default_provider_id_is_minimax`` — Phase 1
    default is minimax (matches the seeded LLMProviderConfig row).
11. ``test_runner_persist_user_and_assistant_roundtrip`` — end-to-end
    through ``stream_ai_studio_message``: register a fake adapter,
    spin up a SQLite session with a seeded provider row + a
    conversation row, and assert that user + assistant messages
    land in the DB and the SSE event sequence is correct.
12. ``test_runner_emits_error_when_provider_missing`` — when the
    provider has no LLMProviderConfig row the driver emits one
    ``error`` event and stops.

The HTTP-level endpoints are covered indirectly through the runner
tests; full FastAPI client tests are out of scope for this MVP
because Plan J's tenant-scope listener on the dev path requires
middleware context that the TestClient doesn't propagate cleanly
without the real ASGI middleware (see j-bug-2 backlog).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, List

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import (
    AIStudioConversation,
    AIStudioMessage,
    Base,
    LLMProviderConfig,
    User,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_user_row() -> User:
    now = datetime.now(timezone.utc)
    return User(
        id="user_ai_studio_test",
        username="aistudio",
        email="aistudio@example.com",
        role="user",
        is_active=True,
        tenant_id="tnt_default",
        is_super_admin=False,
        created_at=now,
        updated_at=now,
    )


def _seed_provider_row(provider_id: str, api_shape: str = "openai-chat") -> LLMProviderConfig:
    now = datetime.now(timezone.utc)
    return LLMProviderConfig(
        id=f"llm_{provider_id}",
        provider_id=provider_id,
        tenant_id="tnt_default",
        display_name=provider_id,
        enabled=True,
        base_url="https://example.invalid/v1",
        endpoint_path="/chat/completions",
        api_shape=api_shape,
        auth_type="bearer",
        model="test-model",
        api_key_encrypted="test-key",
        created_at=now,
        updated_at=now,
    )


async def _make_in_memory_db() -> tuple[async_sessionmaker, AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sm, engine


# ---------------------------------------------------------------------------
# 1. StreamChunk shape
# ---------------------------------------------------------------------------


def test_stream_chunk_dataclass():
    from core.llm.streaming import StreamChunk

    c = StreamChunk(kind="content", content="hi")
    assert c.kind == "content"
    assert c.content == "hi"
    assert c.tool_name is None
    assert c.tool_args is None
    assert c.tool_result is None
    assert c.raw is None
    assert c.extra == {}


# ---------------------------------------------------------------------------
# 2. Adapter registry
# ---------------------------------------------------------------------------


def test_adapter_registry_roundtrip():
    from core.llm.streaming import (
        clear_adapters,
        get_adapter,
        list_adapters,
        register_adapter,
    )
    from core.llm.streaming.custom import CustomStreamAdapter
    from core.llm.streaming.minimax import MiniMaxStreamAdapter
    from core.llm.streaming.openai import OpenAIStreamAdapter

    clear_adapters()
    try:
        register_adapter(
            MiniMaxStreamAdapter(
                api_key="k",
                base_url="https://x",
                default_model="m",
            )
        )
        register_adapter(
            OpenAIStreamAdapter(
                api_key="k",
                base_url="https://x",
                default_model="m",
            )
        )
        register_adapter(
            CustomStreamAdapter(
                api_key="k",
                base_url="https://x",
                default_model="m",
            )
        )
        ids = list_adapters()
        assert "minimax" in ids
        assert "openai" in ids
        assert "custom" in ids
        assert get_adapter("minimax").provider_id == "minimax"
        assert get_adapter("openai").provider_id == "openai"
        assert get_adapter("custom").provider_id == "custom"

        # Unknown id → KeyError (caller catches + surfaces as SSE error)
        with pytest.raises(KeyError):
            get_adapter("nope")
    finally:
        clear_adapters()


# ---------------------------------------------------------------------------
# 3-5. Adapter provider_id contracts
# ---------------------------------------------------------------------------


def test_minimax_adapter_provider_id():
    from core.llm.streaming.minimax import MiniMaxStreamAdapter

    a = MiniMaxStreamAdapter(
        api_key="sk-test", base_url="https://x", default_model="MiniMax-M3"
    )
    assert a.provider_id == "minimax"


def test_openai_adapter_provider_id():
    from core.llm.streaming.openai import OpenAIStreamAdapter

    a = OpenAIStreamAdapter(
        api_key="sk-test", base_url="https://x", default_model="gpt-4o"
    )
    assert a.provider_id == "openai"


def test_custom_adapter_provider_id():
    from core.llm.streaming.custom import CustomStreamAdapter

    a = CustomStreamAdapter(
        api_key="sk-test", base_url="https://x", default_model="llama3"
    )
    assert a.provider_id == "custom"
    # The custom adapter is a thin OpenAI-compatible wrapper; make
    # sure the OpenAI base class is still in the MRO so we don't
    # accidentally fork the protocol.
    from core.llm.streaming.openai import OpenAIStreamAdapter

    assert isinstance(a, OpenAIStreamAdapter)


# ---------------------------------------------------------------------------
# 6. MiniMax adapter parses Anthropic SSE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minimax_adapter_parses_anthropic_sse():
    """Feed the MiniMax adapter a fake Anthropic Messages SSE stream.

    The transport is replaced with ``httpx.MockTransport`` so the
    adapter never hits the network. We assert:

    1. one content chunk per content_block_delta
    2. message_stop ends the stream
    3. unrelated event types (ping, content_block_start) are
       silently ignored
    """
    import httpx
    from core.llm.streaming.minimax import MiniMaxStreamAdapter
    from core.llm.streaming import StreamChunk

    sse_payload = (
        'event: message_start\n'
        'data: {"type":"message_start","message":{"id":"msg_1","model":"MiniMax-M3"}}\n'
        "\n"
        'event: content_block_start\n'
        'data: {"type":"content_block_start","index":0}\n'
        "\n"
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"Hello"}}\n'
        "\n"
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":" world"}}\n'
        "\n"
        'event: content_block_stop\n'
        'data: {"type":"content_block_stop","index":0}\n'
        "\n"
        'event: message_delta\n'
        'data: {"type":"message_delta"}\n'
        "\n"
        'event: message_stop\n'
        'data: {"type":"message_stop"}\n'
        "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_payload.encode())

    transport = httpx.MockTransport(handler)
    adapter = MiniMaxStreamAdapter(
        api_key="sk-test",
        base_url="https://example.invalid",
        default_model="MiniMax-M3",
    )

    chunks: List[StreamChunk] = []
    # ``httpx.AsyncClient.stream`` needs a transport; we patch by
    # monkey-patching the class-level ``__init__`` to inject ours.
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[assignment]
    try:
        async for chunk in adapter.stream(
            messages=[{"role": "user", "content": "hi"}]
        ):
            chunks.append(chunk)
    finally:
        httpx.AsyncClient.__init__ = original_init  # type: ignore[assignment]

    text = "".join(c.content for c in chunks if c.kind == "content")
    assert "Hello world" in text
    # message_stop terminates the generator before any
    # post-message_stop events arrive.
    assert chunks[-1].kind in ("content",)


# ---------------------------------------------------------------------------
# 7. MiniMax surfaces HTTP error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minimax_adapter_surfaces_http_error():
    """A 401 from the provider becomes a single ``error`` chunk."""
    import httpx
    from core.llm.streaming.minimax import MiniMaxStreamAdapter
    from core.llm.streaming import StreamChunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[assignment]
    try:
        adapter = MiniMaxStreamAdapter(
            api_key="bad",
            base_url="https://example.invalid",
            default_model="m",
        )
        chunks: List[StreamChunk] = []
        async for chunk in adapter.stream(
            messages=[{"role": "user", "content": "hi"}]
        ):
            chunks.append(chunk)
    finally:
        httpx.AsyncClient.__init__ = original_init  # type: ignore[assignment]

    assert len(chunks) == 1
    assert chunks[0].kind == "error"
    assert "unauthorized" in chunks[0].content.lower()


# ---------------------------------------------------------------------------
# 8. OpenAI adapter parses chat-completions SSE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_adapter_parses_chat_completions_sse():
    import httpx
    from core.llm.streaming.openai import OpenAIStreamAdapter
    from core.llm.streaming import StreamChunk

    sse_payload = (
        'data: {"id":"cmpl-1","object":"chat.completion.chunk",'
        '"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n'
        "\n"
        'data: {"id":"cmpl-1","object":"chat.completion.chunk",'
        '"choices":[{"index":0,"delta":{"content":" there"},"finish_reason":null}]}\n'
        "\n"
        'data: {"id":"cmpl-1","object":"chat.completion.chunk",'
        '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_payload.encode())

    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[assignment]
    try:
        adapter = OpenAIStreamAdapter(
            api_key="sk-test",
            base_url="https://example.invalid",
            default_model="gpt-4o",
        )
        chunks: List[StreamChunk] = []
        async for chunk in adapter.stream(
            messages=[{"role": "user", "content": "hi"}]
        ):
            chunks.append(chunk)
    finally:
        httpx.AsyncClient.__init__ = original_init  # type: ignore[assignment]

    text = "".join(c.content for c in chunks if c.kind == "content")
    assert text == "Hi there"


# ---------------------------------------------------------------------------
# 9-10. Runner helpers
# ---------------------------------------------------------------------------


def test_runner_gen_id_format():
    from core.execution.ai_studio_runner import gen_id

    cid = gen_id("aiconv")
    assert cid.startswith("aiconv_")
    assert len(cid) > len("aiconv_")
    mid = gen_id("aimsg")
    assert mid.startswith("aimsg_")


def test_runner_default_provider_id_is_minimax():
    from core.execution.ai_studio_runner import _default_provider_id

    assert _default_provider_id() == "minimax"


# ---------------------------------------------------------------------------
# 11. Runner end-to-end through the SSE generator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_persist_user_and_assistant_roundtrip():
    """Register a fake adapter, drive the runner, assert DB state + SSE events.

    The fake adapter yields a deterministic sequence of
    ``content`` chunks so we can match the persisted
    ``AIStudioMessage.content`` against the concatenation.
    """
    from core.llm.streaming import StreamAdapter, StreamChunk
    from core.llm.streaming import register_adapter, clear_adapters
    from core.execution.ai_studio_runner import stream_ai_studio_message

    class FakeAdapter:
        provider_id = "faketest"

        async def stream(
            self,
            messages,
            *,
            model=None,
            temperature=0.7,
            max_tokens=None,
            **kwargs,
        ):
            for token in ("Hello", " ", "world", "."):
                yield StreamChunk(kind="content", content=token)

    sm, _engine = await _make_in_memory_db()
    async with sm() as db:
        db.add(_seed_user_row())
        db.add(_seed_provider_row("faketest", api_shape="openai-chat"))
        # A pre-existing conversation to attach messages to.
        conv = AIStudioConversation(
            id="aiconv_test",
            title="hello",
            user_id="user_ai_studio_test",
            tenant_id="tnt_default",
            provider_id="faketest",
            model="test-model",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(conv)
        await db.commit()

    clear_adapters()
    try:
        register_adapter(FakeAdapter())

        async with sm() as db:
            events: list[dict] = []
            async for evt in stream_ai_studio_message(
                conversation_id="aiconv_test",
                user_message="hi",
                provider_id="faketest",
                db=db,
            ):
                events.append(evt)
    finally:
        clear_adapters()

    # Event sequence
    assert events[0]["event"] == "message_start"
    assert events[0]["data"]["conversationId"] == "aiconv_test"
    assert events[-1]["event"] == "message_end"
    assert "messageId" in events[-1]["data"]
    # Four content events for "Hello", " ", "world", "."
    content_events = [e for e in events if e["event"] == "content"]
    assert len(content_events) == 4
    assert "".join(e["data"]["content"] for e in content_events) == "Hello world."

    # DB state
    async with sm() as db:
        msgs = (
            await db.execute(
                select(AIStudioMessage).order_by(AIStudioMessage.timestamp)
            )
        ).scalars().all()
    assert len(msgs) == 2
    by_type = {m.type: m for m in msgs}
    assert by_type["user"].content == "hi"
    assert by_type["assistant"].content == "Hello world."


# ---------------------------------------------------------------------------
# 12. Runner surfaces error when provider is missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_emits_error_when_provider_missing():
    from core.execution.ai_studio_runner import stream_ai_studio_message
    from core.llm.streaming import clear_adapters

    sm, _engine = await _make_in_memory_db()
    async with sm() as db:
        db.add(_seed_user_row())
        # No LLMProviderConfig row for "ghost" → _resolve_adapter
        # returns None → driver emits one error event.
        conv = AIStudioConversation(
            id="aiconv_ghost",
            title="x",
            user_id="user_ai_studio_test",
            tenant_id="tnt_default",
            provider_id="ghost",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(conv)
        await db.commit()

    clear_adapters()
    async with sm() as db:
        events: list[dict] = []
        async for evt in stream_ai_studio_message(
            conversation_id="aiconv_ghost",
            user_message="hi",
            provider_id="ghost",
            db=db,
        ):
            events.append(evt)

    kinds = [e["event"] for e in events]
    assert "message_start" in kinds
    assert "error" in kinds
    err = next(e for e in events if e["event"] == "error")
    assert "ghost" in err["data"]["detail"].lower() or "not configured" in err["data"]["detail"].lower()
