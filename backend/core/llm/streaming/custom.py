"""
Generic OpenAI-compatible streaming adapter.

The escape hatch for any self-hosted server that speaks the OpenAI
Chat Completions wire format — LM Studio, Ollama (with
``OPENAI_COMPATIBILITY=1``), Xiaomi MiMo, private proxies, etc. It
behaves exactly like :class:`OpenAIStreamAdapter` but takes the
endpoint path from the user-supplied provider config (the MiniMax /
OpenAI adapters use fixed paths).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import httpx

from . import StreamChunk
from .openai import OpenAIStreamAdapter

logger = logging.getLogger(__name__)


class CustomStreamAdapter(OpenAIStreamAdapter):
    """Generic OpenAI-compatible adapter.

    The protocol is identical to :class:`OpenAIStreamAdapter` — we
    subclass it so the only difference is the more permissive default
    endpoint (``/v1/chat/completions``) and the ``provider_id`` string.
    """

    provider_id = "custom"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        endpoint_path: str = "/chat/completions",
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            endpoint_path=endpoint_path,
        )
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
        async for chunk in super().stream(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **provider_kwargs,
        ):
            yield chunk
