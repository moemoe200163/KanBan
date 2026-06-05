"""API Model Executor — real LLM API execution for AgentRun.

When a run has a `provider` field set and execution_mode is `api-agent`,
this executor reads the provider config from the DB, makes a real HTTP
call to the LLM API, and streams the response back as logs.

Supported api_shapes:
- openai-chat (OpenAI, Xiaomi MiMo)
- anthropic-messages (Claude, MiniMax via Anthropic-compatible endpoint)
- openai-responses (OpenAI Responses API)

Falls back gracefully if provider config is missing or API call fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

import httpx

logger = logging.getLogger(__name__)

# Timeout for LLM API calls (seconds)
DEFAULT_TIMEOUT = 120.0
MAX_OUTPUT_TOKENS = 4096


@dataclass
class APIModelResult:
    """Result of an LLM API call."""
    success: bool
    output: str = ""
    error: Optional[str] = None
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class APIModelExecutor:
    """Executes a run by making a real LLM API call.

    Reads provider config from the DB, selects the right HTTP strategy
    based on api_shape, and streams the response back via on_log.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout

    async def execute(
        self,
        provider_id: str,
        model: str,
        prompt: str,
        on_log: Callable[[str], Coroutine[Any, Any, None]],
        system_prompt: Optional[str] = None,
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> APIModelResult:
        """Make a real LLM API call and return the result.

        Args:
            provider_id: Provider identifier (e.g. "minimax", "openai").
            model: Model name (e.g. "MiniMax-M3").
            prompt: User prompt to send.
            on_log: Async callback to emit log lines.
            system_prompt: Optional system prompt.
            max_tokens: Max output tokens.

        Returns:
            APIModelResult with the model's response.
        """
        from db.repository import get_llm_provider_config_with_key
        from core.llm.crypto import decrypt_api_key

        await on_log(f"Loading provider config for {provider_id}...")
        config = await get_llm_provider_config_with_key(provider_id)

        if not config:
            await on_log(f"ERROR: Provider config not found for {provider_id}")
            return APIModelResult(
                success=False,
                error=f"Provider config not found: {provider_id}",
                provider=provider_id,
                model=model,
            )

        if not config.get("enabled", True):
            await on_log(f"ERROR: Provider {provider_id} is disabled")
            return APIModelResult(
                success=False,
                error=f"Provider {provider_id} is disabled",
                provider=provider_id,
                model=model,
            )

        api_key_encrypted = config.get("api_key_encrypted", "")
        api_key = decrypt_api_key(api_key_encrypted) if api_key_encrypted else ""

        if not api_key:
            # Fallback to env var
            env_var = _env_var_for_provider(provider_id)
            api_key = os.getenv(env_var, "")

        if not api_key:
            await on_log(f"ERROR: No API key configured for {provider_id}")
            return APIModelResult(
                success=False,
                error=f"No API key for {provider_id}",
                provider=provider_id,
                model=model,
            )

        base_url = config.get("base_url", "")
        endpoint_path = config.get("endpoint_path", "/chat/completions")
        api_shape = config.get("api_shape", "openai-chat")
        auth_type = config.get("auth_type", "bearer")
        actual_model = model or config.get("model", "")

        await on_log(f"Provider: {provider_id} | Model: {actual_model} | Shape: {api_shape}")
        await on_log(f"Base URL: {base_url}")
        await on_log(f"API call started...")

        start = time.monotonic()

        try:
            if api_shape == "openai-chat":
                result = await self._call_openai_chat(
                    base_url=base_url,
                    endpoint_path=endpoint_path,
                    model=actual_model,
                    api_key=api_key,
                    auth_type=auth_type,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                )
            elif api_shape == "anthropic-messages":
                result = await self._call_anthropic_messages(
                    base_url=base_url,
                    endpoint_path=endpoint_path,
                    model=actual_model,
                    api_key=api_key,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                )
            elif api_shape == "openai-responses":
                result = await self._call_openai_responses(
                    base_url=base_url,
                    endpoint_path=endpoint_path,
                    model=actual_model,
                    api_key=api_key,
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
            else:
                await on_log(f"ERROR: Unknown api_shape: {api_shape}")
                return APIModelResult(
                    success=False,
                    error=f"Unknown api_shape: {api_shape}",
                    provider=provider_id,
                    model=actual_model,
                )

            latency_ms = int((time.monotonic() - start) * 1000)
            result.provider = provider_id
            result.model = actual_model
            result.latency_ms = latency_ms

            if result.success:
                await on_log(f"API call completed in {latency_ms}ms")
                await on_log(f"Tokens: prompt={result.prompt_tokens}, completion={result.completion_tokens}")
            else:
                await on_log(f"API call failed: {result.error}")

            return result

        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            await on_log(f"ERROR: API call timed out after {latency_ms}ms")
            return APIModelResult(
                success=False,
                error=f"Timed out after {latency_ms}ms",
                provider=provider_id,
                model=actual_model,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            await on_log(f"ERROR: {exc}")
            return APIModelResult(
                success=False,
                error=str(exc),
                provider=provider_id,
                model=actual_model,
                latency_ms=latency_ms,
            )

    async def _call_openai_chat(
        self,
        base_url: str,
        endpoint_path: str,
        model: str,
        api_key: str,
        auth_type: str,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
    ) -> APIModelResult:
        """Call an OpenAI-compatible chat completions endpoint."""
        url = f"{base_url.rstrip('/')}{endpoint_path}"
        headers = _build_auth_headers(auth_type, api_key)
        headers["Content-Type"] = "application/json"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=body)

            if resp.status_code == 200:
                data = resp.json()
                content = _extract_openai_chat_content(data)
                usage = data.get("usage", {})
                return APIModelResult(
                    success=True,
                    output=content,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )

            # Fallback: some providers reject max_tokens
            if resp.status_code == 400 and "max_tokens" in resp.text.lower():
                body["max_completion_tokens"] = max_tokens
                del body["max_tokens"]
                resp2 = await client.post(url, headers=headers, json=body)
                if resp2.status_code == 200:
                    data = resp2.json()
                    content = _extract_openai_chat_content(data)
                    usage = data.get("usage", {})
                    return APIModelResult(
                        success=True,
                        output=content,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )
                return APIModelResult(
                    success=False,
                    error=f"HTTP {resp2.status_code}: {resp2.text[:500]}",
                )

            return APIModelResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
            )

    async def _call_anthropic_messages(
        self,
        base_url: str,
        endpoint_path: str,
        model: str,
        api_key: str,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
    ) -> APIModelResult:
        """Call the Anthropic Messages API."""
        url = f"{base_url.rstrip('/')}{endpoint_path}"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=body)

            if resp.status_code == 200:
                data = resp.json()
                content = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        content += block.get("text", "")
                usage = data.get("usage", {})
                return APIModelResult(
                    success=True,
                    output=content,
                    prompt_tokens=usage.get("input_tokens", 0),
                    completion_tokens=usage.get("output_tokens", 0),
                )

            return APIModelResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
            )

    async def _call_openai_responses(
        self,
        base_url: str,
        endpoint_path: str,
        model: str,
        api_key: str,
        prompt: str,
        max_tokens: int,
    ) -> APIModelResult:
        """Call the OpenAI Responses API."""
        url = f"{base_url.rstrip('/')}{endpoint_path}"
        headers = _build_auth_headers("bearer", api_key)
        headers["Content-Type"] = "application/json"

        body = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "store": False,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=body)

            if resp.status_code == 200:
                data = resp.json()
                content = ""
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for block in item.get("content", []):
                            if block.get("type") == "output_text":
                                content += block.get("text", "")
                usage = data.get("usage", {})
                return APIModelResult(
                    success=True,
                    output=content,
                    prompt_tokens=usage.get("input_tokens", 0),
                    completion_tokens=usage.get("output_tokens", 0),
                )

            return APIModelResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_var_for_provider(provider_id: str) -> str:
    """Map provider ID to its env var name for API key fallback."""
    mapping = {
        "minimax": "MINIMAX_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "xiaomi": "XIAOMI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "codex": "CODEX_API_KEY",
    }
    return mapping.get(provider_id, f"{provider_id.upper()}_API_KEY")


def _build_auth_headers(auth_type: str, api_key: str) -> dict[str, str]:
    """Build auth headers based on auth_type."""
    if auth_type == "x-api-key":
        return {"x-api-key": api_key}
    if auth_type == "api-key":
        return {"api-key": api_key}
    # Default: bearer
    return {"Authorization": f"Bearer {api_key}"}


def _extract_openai_chat_content(data: dict) -> str:
    """Extract text content from OpenAI chat completions response."""
    choices = data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "")
