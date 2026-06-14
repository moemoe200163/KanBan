"""
OpenAI Chat Completions streaming adapter.

OpenAI Chat Completions SSE format (one event per line, ``data:`` payload
only, ``[DONE]`` sentinel at the end):

    data: {"id":"chatcmpl-...","object":"chat.completion.chunk",
           "choices":[{"index":0,"delta":{"content":"Hello"},
           "finish_reason":null}]}

    data: {"id":"chatcmpl-...","object":"chat.completion.chunk",
           "choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

    data: [DONE]

We accumulate text from ``choices[0].delta.content`` and yield a
``content`` chunk for every non-empty delta. The final chunk may have
``finish_reason="stop"`` — we just yield it and let the driver stop.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from . import StreamChunk

logger = logging.getLogger(__name__)


class OpenAIStreamAdapter:
    """Stream tokens from an OpenAI /v1/chat/completions endpoint."""

    provider_id = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        endpoint_path: str = "/chat/completions",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.endpoint_path = endpoint_path

    async def stream(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **provider_kwargs,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.base_url.rstrip('/')}{self.endpoint_path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

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
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data: "):
                            continue
                        payload_str = line[6:].strip()
                        if not payload_str:
                            continue
                        if payload_str == "[DONE]":
                            return
                        try:
                            evt = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue
                        choices = evt.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield StreamChunk(
                                kind="content", content=text, raw=evt
                            )
        except httpx.HTTPError as exc:
            logger.warning("OpenAI stream HTTP error: %s", exc)
            yield StreamChunk(
                kind="error",
                content=f"openai http error: {exc}",
                raw={"error_type": type(exc).__name__},
            )
