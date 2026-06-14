"""
MiniMax streaming adapter (Anthropic Messages API SSE).

IMPORTANT: MiniMax exposes the Anthropic Messages API shape, not the
OpenAI chat-completions shape. The seeded ``llm_provider_configs`` row
carries ``api_shape="anthropic-messages"`` (see
``db/repository.py:1906``). This adapter mirrors what the existing
``_call_anthropic_messages()`` in ``core/runtime/api_model_executor.py``
does for non-streaming calls, but yields :class:`StreamChunk` events
from the SSE response.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from . import StreamChunk

logger = logging.getLogger(__name__)


class MiniMaxStreamAdapter:
    """Stream tokens from a MiniMax endpoint that speaks Anthropic SSE."""

    provider_id = "minimax"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        endpoint_path: str = "/v1/messages",
        api_version: str = "2023-06-01",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.endpoint_path = endpoint_path
        self.api_version = api_version

    async def stream(
        self,
        messages: list[dict],
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **provider_kwargs,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.base_url.rstrip('/')}{self.endpoint_path}"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system:
            body["system"] = system

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=body
                ) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        yield StreamChunk(
                            kind="error",
                            content=text.decode("utf-8", errors="replace")[:2000],
                            raw={"status": resp.status_code},
                        )
                        return
                    event_type: Optional[str] = None
                    async for line in resp.aiter_lines():
                        if not line:
                            event_type = None
                            continue
                        if line.startswith("event: "):
                            event_type = line[7:].strip()
                            continue
                        if not line.startswith("data: "):
                            continue
                        payload_str = line[6:].strip()
                        if not payload_str or payload_str == "[DONE]":
                            continue
                        try:
                            evt = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue

                        if event_type == "content_block_delta":
                            delta = evt.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield StreamChunk(
                                    kind="content", content=text, raw=evt
                                )
                        elif event_type == "message_start":
                            yield StreamChunk(
                                kind="content", content="", raw=evt
                            )
                        elif event_type == "message_stop":
                            return
        except httpx.HTTPError as exc:
            logger.warning("MiniMax stream HTTP error: %s", exc)
            yield StreamChunk(
                kind="error",
                content=f"minimax http error: {exc}",
                raw={"error_type": type(exc).__name__},
            )
