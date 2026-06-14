"""
Plan I (AI Studio) — provider-agnostic streaming interface.

Defines the protocol that the SSE driver in
``backend/core/execution/ai_studio_runner.py`` talks to, plus a tiny
registry for resolving a provider id (e.g. ``"minimax"``,
``"openai"``, ``"custom"``) to a concrete adapter instance.

Each adapter in this package implements the same ``stream()``
shape, but parses the provider's own SSE event format and yields
a stream of :class:`StreamChunk` so the driver never has to know
whether it's talking to Anthropic Messages SSE, OpenAI
chat-completions SSE, or a generic ``/v1/chat/completions`` clone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """A single token / event from a streaming LLM call.

    ``kind`` is a coarse event type the SSE driver maps 1:1 to an SSE
    event name. Supported values:

    - ``"content"`` — a text delta from the model
    - ``"thinking"`` — a chain-of-thought / reasoning delta
    - ``"tool_call"`` — a structured tool call
    - ``"tool_result"`` — a tool result (echoed back through the stream)
    - ``"error"`` — a non-fatal stream-level error event
    - ``"message_start"`` / ``"message_end"`` — sentinels bracketing
      a single assistant turn
    """

    kind: str
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None
    # Provider-specific extras (e.g. usage stats, finish reason)
    # are stuffed here and forwarded to the SSE client if the schema
    # supports it.
    raw: Optional[dict] = None
    extra: Dict[str, str] = field(default_factory=dict)


@runtime_checkable
class StreamAdapter(Protocol):
    """Provider-agnostic streaming interface.

    Each provider (minimax, openai, custom) gets its own adapter that
    implements this. The SSE driver calls ``stream(messages, ...)``
    and yields StreamChunks without knowing which provider is behind
    it. Adapters must yield at least one ``content`` chunk (or end
    the stream early) and must not raise mid-stream — non-fatal
    errors are surfaced as ``StreamChunk(kind="error", ...)``.
    """

    provider_id: str

    async def stream(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **provider_kwargs,
    ) -> AsyncIterator[StreamChunk]:
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTERS: Dict[str, StreamAdapter] = {}


def register_adapter(adapter: StreamAdapter) -> None:
    """Register a :class:`StreamAdapter` instance under its ``provider_id``.

    Re-registering the same id replaces the previous instance — useful
    for tests that want to inject a fake adapter without touching
    module-level state.
    """
    if not adapter.provider_id:
        raise ValueError("StreamAdapter.provider_id must be a non-empty string")
    _ADAPTERS[adapter.provider_id] = adapter
    logger.debug(f"registered streaming adapter: {adapter.provider_id}")


def unregister_adapter(provider_id: str) -> None:
    """Remove a registered adapter. Test-only helper."""
    _ADAPTERS.pop(provider_id, None)


def get_adapter(provider_id: str) -> StreamAdapter:
    """Resolve a provider id to its registered adapter.

    Raises ``KeyError`` if the id is unknown — the SSE driver catches
    this and surfaces it as an ``error`` event so the chat UI can show
    a useful message instead of a 500.
    """
    if provider_id not in _ADAPTERS:
        raise KeyError(f"Unknown LLM provider: {provider_id}")
    return _ADAPTERS[provider_id]


def list_adapters() -> list[str]:
    """Return the registered provider ids (mostly for tests + /docs)."""
    return sorted(_ADAPTERS.keys())


def clear_adapters() -> None:
    """Drop every registered adapter. Test-only helper."""
    _ADAPTERS.clear()


def register_default_adapters() -> None:
    """Register the three Phase 1 adapters with placeholder credentials.

    These are *placeholder* instances. The SSE driver does NOT resolve
    a provider from this registry directly — the real credentials
    live in ``llm_provider_configs`` and the driver constructs a
    per-request adapter instance with the right ``api_key`` /
    ``base_url`` from the DB row (see
    ``backend/core/execution/ai_studio_runner._resolve_adapter``).
    """
    from .custom import CustomStreamAdapter
    from .minimax import MiniMaxStreamAdapter
    from .openai import OpenAIStreamAdapter

    try:
        register_adapter(
            MiniMaxStreamAdapter(
                api_key="",
                base_url="https://api.minimax.io/anthropic",
                default_model="MiniMax-M3",
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.debug(f"minimax placeholder register failed: {exc}")

    try:
        register_adapter(
            OpenAIStreamAdapter(
                api_key="",
                base_url="https://api.openai.com/v1",
                default_model="gpt-4o",
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.debug(f"openai placeholder register failed: {exc}")

    try:
        register_adapter(
            CustomStreamAdapter(
                api_key="",
                base_url="http://localhost:11434/v1",
                default_model="llama3",
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.debug(f"custom placeholder register failed: {exc}")


__all__ = [
    "StreamChunk",
    "StreamAdapter",
    "register_adapter",
    "unregister_adapter",
    "get_adapter",
    "list_adapters",
    "clear_adapters",
    "register_default_adapters",
]
