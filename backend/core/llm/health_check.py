"""
LLM Provider Health Check Engine + Chat Helper

Makes real API calls to test provider connectivity and classify errors.
Each provider shape (openai-chat, openai-responses, anthropic-messages,
ollama) has its own test strategy with minimal token usage.

Also exports ``chat_complete`` for non-health-check use: it makes the
same shape of HTTP call but actually returns the model's text
content instead of classifying the response. Used by features that
need real LLM output (e.g. AC suggestion for issues).
"""

import asyncio
import json
import logging
import time
from enum import Enum
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Minimal token budget for health checks
_MAX_TOKENS = 8
_HEALTH_PROMPT = "Reply with only: ok"

# Timeout per strategy (seconds)
_TIMEOUT_OPENAI_CHAT = 10.0
_TIMEOUT_OPENAI_RESPONSES = 10.0
_TIMEOUT_ANTHROPIC_MESSAGES = 10.0
_TIMEOUT_OLLAMA = 15.0
_TIMEOUT_OLLAMA_TAGS = 10.0


class HealthStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    HEALTHY = "healthy"
    AUTH_ERROR = "auth_error"
    BILLING_ERROR = "billing_error"
    PERMISSION_ERROR = "permission_error"
    MODEL_ERROR = "model_error"
    RATE_LIMITED = "rate_limited"
    ENDPOINT_ERROR = "endpoint_error"
    TIMEOUT = "timeout"
    UNKNOWN_ERROR = "unknown_error"


def _classify_http_status(status_code: int) -> HealthStatus:
    """Map an HTTP status code to a HealthStatus."""
    mapping = {
        401: HealthStatus.AUTH_ERROR,
        402: HealthStatus.BILLING_ERROR,
        403: HealthStatus.PERMISSION_ERROR,
        404: HealthStatus.MODEL_ERROR,
        429: HealthStatus.RATE_LIMITED,
    }
    return mapping.get(status_code, HealthStatus.UNKNOWN_ERROR)


def _classify_exception(exc: Exception) -> HealthStatus:
    """Map an exception to a HealthStatus."""
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return HealthStatus.TIMEOUT
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return HealthStatus.ENDPOINT_ERROR
    return HealthStatus.UNKNOWN_ERROR


def _build_result(
    status: HealthStatus,
    latency_ms: int,
    message: str = "",
    safe_error: Optional[str] = None,
) -> dict:
    """Build the standard health check result dict."""
    return {
        "status": status.value,
        "ok": status == HealthStatus.HEALTHY,
        "latencyMs": latency_ms,
        "message": message,
        "safeError": safe_error,
    }


async def _test_openai_chat(
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: str,
) -> dict:
    """
    Test an OpenAI-compatible chat completions endpoint.

    Uses POST {baseUrl}{endpointPath} with a minimal prompt.
    Falls back from max_completion_tokens to max_tokens if the provider
    rejects the parameter.
    """
    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _HEALTH_PROMPT}],
        "max_completion_tokens": _MAX_TOKENS,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_OPENAI_CHAT) as client:
            resp = await client.post(url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                return _build_result(
                    HealthStatus.HEALTHY, latency_ms,
                    message="Chat completions endpoint responding",
                )

            # Fallback: some providers reject max_completion_tokens
            body_text = resp.text.lower()
            if resp.status_code == 400 and (
                "max_completion_tokens" in body_text or "invalid" in body_text
            ):
                body["max_tokens"] = _MAX_TOKENS
                del body["max_completion_tokens"]
                resp2 = await client.post(url, headers=headers, json=body)
                latency_ms = int((time.monotonic() - start) * 1000)
                if resp2.status_code == 200:
                    return _build_result(
                        HealthStatus.HEALTHY, latency_ms,
                        message="Chat completions endpoint responding (fallback max_tokens)",
                    )
                status = _classify_http_status(resp2.status_code)
                return _build_result(
                    status, latency_ms,
                    message=f"HTTP {resp2.status_code} on retry",
                    safe_error=f"HTTP {resp2.status_code}",
                )

            status = _classify_http_status(resp.status_code)
            return _build_result(
                status, latency_ms,
                message=f"HTTP {resp.status_code}",
                safe_error=f"HTTP {resp.status_code}",
            )

    except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        status = _classify_exception(exc)
        return _build_result(
            status, latency_ms,
            message=str(exc),
            safe_error=status.value,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return _build_result(
            HealthStatus.UNKNOWN_ERROR, latency_ms,
            message=str(exc),
            safe_error=HealthStatus.UNKNOWN_ERROR.value,
        )


async def _test_openai_responses(
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: str,
) -> dict:
    """
    Test the OpenAI Responses API endpoint.

    Uses POST {baseUrl}{endpointPath} with a minimal prompt.
    """
    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "input": _HEALTH_PROMPT,
        "max_output_tokens": _MAX_TOKENS,
        "store": False,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_OPENAI_RESPONSES) as client:
            resp = await client.post(url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                return _build_result(
                    HealthStatus.HEALTHY, latency_ms,
                    message="Responses API endpoint responding",
                )

            status = _classify_http_status(resp.status_code)
            return _build_result(
                status, latency_ms,
                message=f"HTTP {resp.status_code}",
                safe_error=f"HTTP {resp.status_code}",
            )

    except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        status = _classify_exception(exc)
        return _build_result(
            status, latency_ms,
            message=str(exc),
            safe_error=status.value,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return _build_result(
            HealthStatus.UNKNOWN_ERROR, latency_ms,
            message=str(exc),
            safe_error=HealthStatus.UNKNOWN_ERROR.value,
        )


async def _test_anthropic_messages(
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: str,
) -> dict:
    """
    Test the Anthropic Messages API endpoint.

    Uses POST {baseUrl}{endpointPath} with anthropic-version header.
    """
    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": _HEALTH_PROMPT}],
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_ANTHROPIC_MESSAGES) as client:
            resp = await client.post(url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                return _build_result(
                    HealthStatus.HEALTHY, latency_ms,
                    message="Anthropic Messages API responding",
                )

            status = _classify_http_status(resp.status_code)
            return _build_result(
                status, latency_ms,
                message=f"HTTP {resp.status_code}",
                safe_error=f"HTTP {resp.status_code}",
            )

    except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        status = _classify_exception(exc)
        return _build_result(
            status, latency_ms,
            message=str(exc),
            safe_error=status.value,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return _build_result(
            HealthStatus.UNKNOWN_ERROR, latency_ms,
            message=str(exc),
            safe_error=HealthStatus.UNKNOWN_ERROR.value,
        )


async def _test_ollama(
    base_url: str,
    endpoint_path: str,
    model: str,
) -> dict:
    """
    Test an Ollama instance.

    First checks /api/tags to verify Ollama is running, then sends
    a minimal chat request.
    """
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _HEALTH_PROMPT}],
        "stream": False,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_OLLAMA) as client:
            # Step 1: Check if Ollama is reachable via /api/tags
            tags_resp = await client.get(tags_url, headers=headers, timeout=_TIMEOUT_OLLAMA_TAGS)
            if tags_resp.status_code != 200:
                latency_ms = int((time.monotonic() - start) * 1000)
                return _build_result(
                    HealthStatus.ENDPOINT_ERROR, latency_ms,
                    message=f"Ollama /api/tags returned HTTP {tags_resp.status_code}",
                    safe_error=f"HTTP {tags_resp.status_code}",
                )

            # Step 2: Send a minimal chat request
            chat_resp = await client.post(chat_url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - start) * 1000)

            if chat_resp.status_code == 200:
                return _build_result(
                    HealthStatus.HEALTHY, latency_ms,
                    message="Ollama responding",
                )

            status = _classify_http_status(chat_resp.status_code)
            return _build_result(
                status, latency_ms,
                message=f"HTTP {chat_resp.status_code}",
                safe_error=f"HTTP {chat_resp.status_code}",
            )

    except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        status = _classify_exception(exc)
        return _build_result(
            status, latency_ms,
            message=str(exc),
            safe_error=status.value,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return _build_result(
            HealthStatus.UNKNOWN_ERROR, latency_ms,
            message=str(exc),
            safe_error=HealthStatus.UNKNOWN_ERROR.value,
        )


async def run_health_check(
    api_shape: str,
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: Optional[str],
    auth_type: str,
) -> dict:
    """
    Run a real API health check for the given provider config.

    Dispatches to the appropriate test strategy based on api_shape:
    - openai-chat: Chat completions API (MiniMax, Xiaomi MiMo, etc.)
    - openai-responses: OpenAI Responses API
    - anthropic-messages: Anthropic Messages API (Claude)
    - ollama: Local Ollama instance

    Args:
        api_shape: One of "openai-chat", "openai-responses", "anthropic-messages", "ollama"
        base_url: Provider base URL (e.g., "https://api.openai.com/v1")
        endpoint_path: Endpoint path (e.g., "/chat/completions")
        model: Model identifier to test
        api_key: API key (may be None for unauthenticated providers)
        auth_type: Auth type ("bearer", "x-api-key", "none", etc.)

    Returns:
        {
            "status": HealthStatus value,
            "ok": bool,
            "latencyMs": int,
            "message": str,
            "safeError": Optional[str],
        }
    """
    # Early return if no API key for authenticated providers
    if auth_type != "none" and (not api_key or not api_key.strip()):
        return _build_result(
            HealthStatus.NOT_CONFIGURED, 0,
            message="API key not configured",
            safe_error=HealthStatus.NOT_CONFIGURED.value,
        )

    logger.info(f"Running health check for api_shape={api_shape}, model={model}")

    if api_shape == "openai-chat":
        return await _test_openai_chat(base_url, endpoint_path, model, api_key or "")
    elif api_shape == "openai-responses":
        return await _test_openai_responses(base_url, endpoint_path, model, api_key or "")
    elif api_shape == "anthropic-messages":
        return await _test_anthropic_messages(base_url, endpoint_path, model, api_key or "")
    elif api_shape == "ollama":
        return await _test_ollama(base_url, endpoint_path, model)
    else:
        return _build_result(
            HealthStatus.UNKNOWN_ERROR, 0,
            message=f"Unknown api_shape: {api_shape}",
            safe_error=HealthStatus.UNKNOWN_ERROR.value,
        )


# ---------------------------------------------------------------------------
# chat_complete — actually returns the model's text, not just health.
#
# Used by features that need a real LLM response (e.g. AC suggestion).
# Mirrors the shape dispatch in ``run_health_check`` but extracts the
# text content from the provider's response object. The parsing rules
# are intentionally simple: each provider returns content at a
# different path, and we trust the first non-empty string we find.
# ---------------------------------------------------------------------------

_CHAT_MAX_TOKENS = 1024
_CHAT_TIMEOUT = 30.0


class ChatError(Exception):
    """Raised when a chat call fails. ``code`` is one of:
    not_configured, network, http_<status>, parse_error.
    """


async def chat_complete(
    api_shape: str,
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: Optional[str],
    messages: list[dict],
    *,
    max_tokens: int = _CHAT_MAX_TOKENS,
    temperature: float = 0.3,
) -> str:
    """Call the configured provider and return the model's text reply.

    ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts,
    OpenAI-style. Anthropic and Ollama take the same shape and we map
    it provider-side.

    Returns the model's text reply as a string. Raises ``ChatError``
    on any failure so the caller can decide whether to fall back to a
    heuristic or surface an error to the user.
    """
    if not base_url:
        raise ChatError("not_configured: base URL is empty")
    if not model:
        raise ChatError("not_configured: model is empty")

    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if api_shape == "anthropic-messages":
        headers["anthropic-version"] = "2023-06-01"
        headers["x-api-key"] = api_key or ""
        # Anthropic separates the system prompt from the conversation
        # turn. Pull the system out so callers can pass it via the
        # standard messages list.
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        conv = [m for m in messages if m.get("role") != "system"]
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
    elif api_shape == "ollama":
        # Ollama's chat endpoint expects a flat list of messages.
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
    else:  # openai-chat and openai-responses
        body = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=body)
    except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise ChatError(f"network: {exc}") from exc
    except Exception as exc:
        raise ChatError(f"network: {exc}") from exc

    if resp.status_code != 200:
        raise ChatError(f"http_{resp.status_code}: {resp.text[:200]}")

    try:
        data: Any = resp.json()
    except json.JSONDecodeError as exc:
        raise ChatError(f"parse_error: {exc}") from exc

    text = _extract_text(api_shape, data)
    if not text:
        raise ChatError("parse_error: no text content in response")
    logger.info(
        "chat_complete shape=%s model=%s ms=%d chars=%d",
        api_shape, model, int((time.monotonic() - start) * 1000), len(text),
    )
    return text


def _extract_text(api_shape: str, data: Any) -> str:
    """Pull the model's text from a provider response.

    Each shape puts the assistant content at a different path:

    - openai-chat: ``choices[0].message.content``
    - openai-responses: ``output[].content[].text`` (newer Responses API)
    - anthropic-messages: ``content[].text``
    - ollama: ``message.content``

    Returns an empty string if no text is found; the caller raises
    ChatError("parse_error: ...") in that case.
    """
    try:
        if api_shape in ("openai-chat",):
            return data["choices"][0]["message"]["content"] or ""
        if api_shape == "openai-responses":
            for block in data.get("output", []):
                for c in block.get("content", []):
                    if c.get("type") in ("output_text", "text"):
                        return c.get("text", "") or ""
            return ""
        if api_shape == "anthropic-messages":
            for c in data.get("content", []):
                if c.get("type") == "text":
                    return c.get("text", "") or ""
            return ""
        if api_shape == "ollama":
            return (data.get("message") or {}).get("content", "") or ""
    except (KeyError, TypeError, IndexError):
        return ""
    return ""
