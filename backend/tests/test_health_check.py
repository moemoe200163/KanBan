"""Tests for LLM Provider Health Check Engine."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.llm.health_check import (
    HealthStatus,
    _classify_exception,
    _classify_http_status,
    _test_anthropic_messages,
    _test_ollama,
    _test_openai_chat,
    _test_openai_responses,
    run_health_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    """Create a mock httpx.Response with the given status code and text."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {"error": text} if text else {}
    return resp


def _mock_client(responses: list) -> MagicMock:
    """
    Create a mock httpx.AsyncClient that returns responses in order.

    The client supports being used as an async context manager.
    Each call to post/get returns the next response in the list.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    # Set up methods to return responses in sequence
    call_index = {"post": 0, "get": 0}

    async def mock_post(*args, **kwargs):
        idx = call_index["post"]
        call_index["post"] += 1
        if idx < len(responses["post"]):
            return responses["post"][idx]
        return _mock_response(200)

    async def mock_get(*args, **kwargs):
        idx = call_index["get"]
        call_index["get"] += 1
        if idx < len(responses["get"]):
            return responses["get"][idx]
        return _mock_response(200)

    client.post = AsyncMock(side_effect=mock_post)
    client.get = AsyncMock(side_effect=mock_get)
    return client


# ---------------------------------------------------------------------------
# Tests: NOT_CONFIGURED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_configured_bearer_auth_returns_not_configured():
    """api_key is None with bearer auth should return not_configured."""
    result = await run_health_check(
        api_shape="openai-chat",
        base_url="https://api.openai.com/v1",
        endpoint_path="/chat/completions",
        model="gpt-4o",
        api_key=None,
        auth_type="bearer",
    )
    assert result["status"] == HealthStatus.NOT_CONFIGURED.value
    assert result["ok"] is False
    assert result["latencyMs"] == 0


@pytest.mark.asyncio
async def test_not_configured_empty_api_key():
    """Empty api_key string with x-api-key auth should return not_configured."""
    result = await run_health_check(
        api_shape="anthropic-messages",
        base_url="https://api.anthropic.com/v1",
        endpoint_path="/messages",
        model="claude-sonnet-4-20250514",
        api_key="",
        auth_type="x-api-key",
    )
    assert result["status"] == HealthStatus.NOT_CONFIGURED.value
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Tests: healthy responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthy_openai_chat():
    """Mock successful 200 response on openai-chat should return healthy."""
    mock_resp = _mock_response(200, '{"choices": [{"message": {"content": "ok"}}]}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.HEALTHY.value
    assert result["ok"] is True
    assert result["latencyMs"] >= 0


@pytest.mark.asyncio
async def test_healthy_anthropic_messages():
    """Mock successful 200 response on anthropic-messages should return healthy."""
    mock_resp = _mock_response(200, '{"content": [{"text": "ok"}]}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="anthropic-messages",
            base_url="https://api.anthropic.com/v1",
            endpoint_path="/messages",
            model="claude-sonnet-4-20250514",
            api_key="sk-ant-test-key",
            auth_type="x-api-key",
        )

    assert result["status"] == HealthStatus.HEALTHY.value
    assert result["ok"] is True
    assert result["latencyMs"] >= 0


@pytest.mark.asyncio
async def test_healthy_openai_responses():
    """Mock successful 200 response on openai-responses should return healthy."""
    mock_resp = _mock_response(200, '{"output": [{"content": "ok"}]}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-responses",
            base_url="https://api.openai.com/v1",
            endpoint_path="/responses",
            model="codex-mini-latest",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.HEALTHY.value
    assert result["ok"] is True
    assert result["latencyMs"] >= 0


@pytest.mark.asyncio
async def test_healthy_ollama():
    """Mock /api/tags 200 + /api/chat 200 should return healthy."""
    tags_resp = _mock_response(200, '{"models": [{"name": "llama3"}]}')
    chat_resp = _mock_response(200, '{"message": {"content": "ok"}}')
    client = _mock_client({"post": [chat_resp], "get": [tags_resp]})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="ollama",
            base_url="http://localhost:11434",
            endpoint_path="",
            model="llama3",
            api_key=None,
            auth_type="none",
        )

    assert result["status"] == HealthStatus.HEALTHY.value
    assert result["ok"] is True
    assert result["latencyMs"] >= 0


# ---------------------------------------------------------------------------
# Tests: Error classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error():
    """Mock 401 response should return auth_error."""
    mock_resp = _mock_response(401, '{"error": "unauthorized"}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-bad-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.AUTH_ERROR.value
    assert result["ok"] is False
    assert result["safeError"] == "HTTP 401"


@pytest.mark.asyncio
async def test_billing_error():
    """Mock 402 response should return billing_error."""
    mock_resp = _mock_response(402, '{"error": "payment required"}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.BILLING_ERROR.value
    assert result["ok"] is False
    assert result["safeError"] == "HTTP 402"


@pytest.mark.asyncio
async def test_model_error():
    """Mock 404 response should return model_error."""
    mock_resp = _mock_response(404, '{"error": "model not found"}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="anthropic-messages",
            base_url="https://api.anthropic.com/v1",
            endpoint_path="/messages",
            model="claude-nonexistent",
            api_key="sk-ant-test-key",
            auth_type="x-api-key",
        )

    assert result["status"] == HealthStatus.MODEL_ERROR.value
    assert result["ok"] is False
    assert result["safeError"] == "HTTP 404"


@pytest.mark.asyncio
async def test_rate_limited():
    """Mock 429 response should return rate_limited."""
    mock_resp = _mock_response(429, '{"error": "rate limit exceeded"}')
    client = _mock_client({"post": [mock_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.RATE_LIMITED.value
    assert result["ok"] is False
    assert result["safeError"] == "HTTP 429"


@pytest.mark.asyncio
async def test_timeout():
    """Mock timeout exception should return timeout."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.TIMEOUT.value
    assert result["ok"] is False
    assert result["safeError"] == HealthStatus.TIMEOUT.value


@pytest.mark.asyncio
async def test_endpoint_error():
    """Mock connection error should return endpoint_error."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="ollama",
            base_url="http://localhost:11434",
            endpoint_path="",
            model="llama3",
            api_key=None,
            auth_type="none",
        )

    assert result["status"] == HealthStatus.ENDPOINT_ERROR.value
    assert result["ok"] is False
    assert result["safeError"] == HealthStatus.ENDPOINT_ERROR.value


# ---------------------------------------------------------------------------
# Tests: max_completion_tokens fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_completion_tokens_fallback():
    """
    Mock 400 on first call (max_completion_tokens rejected),
    then 200 on retry with max_tokens should return healthy.
    """
    bad_resp = _mock_response(400, '{"error": {"message": "max_completion_tokens is not valid"}}')
    good_resp = _mock_response(200, '{"choices": [{"message": {"content": "ok"}}]}')
    client = _mock_client({"post": [bad_resp, good_resp], "get": []})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="openai-chat",
            base_url="https://api.example.com/v1",
            endpoint_path="/chat/completions",
            model="test-model",
            api_key="sk-test-key",
            auth_type="bearer",
        )

    assert result["status"] == HealthStatus.HEALTHY.value
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Tests: Ollama unreachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_unreachable():
    """Mock /api/tags connection error should return endpoint_error."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="ollama",
            base_url="http://localhost:11434",
            endpoint_path="",
            model="llama3",
            api_key=None,
            auth_type="none",
        )

    assert result["status"] == HealthStatus.ENDPOINT_ERROR.value
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Tests: Unknown api_shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_api_shape():
    """Unknown api_shape should return unknown_error."""
    result = await run_health_check(
        api_shape="unsupported-provider",
        base_url="https://example.com",
        endpoint_path="/test",
        model="test",
        api_key="sk-test",
        auth_type="bearer",
    )
    assert result["status"] == HealthStatus.UNKNOWN_ERROR.value
    assert result["ok"] is False
    assert "Unknown api_shape" in result["message"]


# ---------------------------------------------------------------------------
# Tests: Utility functions
# ---------------------------------------------------------------------------


def test_classify_http_status_codes():
    """Verify all mapped HTTP status codes produce the correct HealthStatus."""
    assert _classify_http_status(401) == HealthStatus.AUTH_ERROR
    assert _classify_http_status(402) == HealthStatus.BILLING_ERROR
    assert _classify_http_status(403) == HealthStatus.PERMISSION_ERROR
    assert _classify_http_status(404) == HealthStatus.MODEL_ERROR
    assert _classify_http_status(429) == HealthStatus.RATE_LIMITED
    # Unmapped codes return UNKNOWN_ERROR
    assert _classify_http_status(500) == HealthStatus.UNKNOWN_ERROR
    assert _classify_http_status(200) == HealthStatus.UNKNOWN_ERROR


def test_classify_exception_types():
    """Verify exception classification for timeout and connection errors."""
    assert _classify_exception(asyncio.TimeoutError()) == HealthStatus.TIMEOUT
    assert _classify_exception(httpx.TimeoutException("timeout")) == HealthStatus.TIMEOUT
    assert _classify_exception(httpx.ConnectError("refused")) == HealthStatus.ENDPOINT_ERROR
    # ConnectTimeout is a subclass of TimeoutException, so it maps to TIMEOUT
    assert _classify_exception(httpx.ConnectTimeout("timeout")) == HealthStatus.TIMEOUT
    assert _classify_exception(ValueError("something")) == HealthStatus.UNKNOWN_ERROR


# ---------------------------------------------------------------------------
# Tests: health_type "none" bypasses key check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_with_none_auth_skips_key_check():
    """Ollama (auth_type=none) should not return NOT_CONFIGURED when api_key is None."""
    tags_resp = _mock_response(200, '{"models": []}')
    chat_resp = _mock_response(200, '{"message": {"content": "ok"}}')
    client = _mock_client({"post": [chat_resp], "get": [tags_resp]})

    with patch("core.llm.health_check.httpx.AsyncClient", return_value=client):
        result = await run_health_check(
            api_shape="ollama",
            base_url="http://localhost:11434",
            endpoint_path="",
            model="llama3",
            api_key=None,
            auth_type="none",
        )

    assert result["status"] != HealthStatus.NOT_CONFIGURED.value
    assert result["status"] == HealthStatus.HEALTHY.value
