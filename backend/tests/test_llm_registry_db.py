"""Tests for core.llm.registry -- DB-first provider reads and fallback behavior."""

import os
import pytest
from unittest.mock import patch, AsyncMock

from core.llm import registry


# ---------------------------------------------------------------------------
# list_providers works when DB is unavailable (fallback to env)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_providers_works_when_db_unavailable():
    """list_providers_from_db falls back to env-based list when DB errors."""
    with patch(
        "db.repository.list_llm_provider_configs",
        new_callable=AsyncMock,
        side_effect=Exception("DB connection refused"),
    ):
        result = await registry.list_providers_from_db()
    # Should still return a list of providers (from static defs + env)
    assert isinstance(result, list)
    assert len(result) > 0
    # safe-runner is always configured
    safe = next(p for p in result if p["id"] == "safe-runner")
    assert safe["configured"] is True


def test_list_providers_returns_static_definitions_when_no_db_data():
    """Without DB configs, list_providers returns static defs with env status."""
    providers = registry.list_providers()
    assert isinstance(providers, list)
    # All static providers should be present
    ids = {p["id"] for p in providers}
    assert "openai" in ids
    assert "anthropic" in ids
    assert "minimax" in ids
    assert "xiaomi" in ids
    assert "safe-runner" in ids


def test_get_provider_returns_none_for_unknown():
    """get_provider returns None for a provider_id not in PROVIDER_MAP."""
    result = registry.get_provider("nonexistent-provider")
    assert result is None


# ---------------------------------------------------------------------------
# list_providers merges DB config on top of env
# ---------------------------------------------------------------------------

def test_list_providers_merges_db_config():
    """When db_configs is provided, DB values override env-var values."""
    db_configs = [
        {
            "providerId": "openai",
            "enabled": True,
            "baseUrl": "https://custom.openai.com/v1",
            "model": "gpt-4o-custom",
            "authType": "bearer",
            "apiKeyPrefix": "sk-proj-",
            "apiKeyLast4": "xyz1",
        },
    ]
    providers = registry.list_providers(db_configs=db_configs)
    openai = next(p for p in providers if p["id"] == "openai")

    # DB model overrides static default_model
    assert openai["defaultModel"] == "gpt-4o-custom"
    # DB maskedSecret uses prefix/last4
    assert openai["maskedSecret"] == "sk-proj-...xyz1"
    # DB baseUrl is surfaced
    assert openai["baseUrl"] == "https://custom.openai.com/v1"
    # configured is True because DB has key info
    assert openai["configured"] is True


def test_list_providers_db_enabled_override():
    """DB enabled=False overrides static enabled=True."""
    db_configs = [
        {
            "providerId": "openai",
            "enabled": False,
        },
    ]
    providers = registry.list_providers(db_configs=db_configs)
    openai = next(p for p in providers if p["id"] == "openai")
    assert openai["enabled"] is False


def test_list_providers_db_health_override():
    """DB health check results surface into the provider dict."""
    db_configs = [
        {
            "providerId": "anthropic",
            "lastTestStatus": "healthy",
            "lastTestAt": "2026-01-01T00:00:00Z",
            "lastErrorMessage": None,
        },
    ]
    providers = registry.list_providers(db_configs=db_configs)
    anthropic = next(p for p in providers if p["id"] == "anthropic")
    assert anthropic["healthStatus"] == "healthy"
    assert anthropic["lastChecked"] == "2026-01-01T00:00:00Z"


def test_list_providers_db_error_override():
    """DB error message surfaces into errorSummary."""
    db_configs = [
        {
            "providerId": "anthropic",
            "lastTestStatus": "unhealthy",
            "lastErrorMessage": "Invalid API key",
        },
    ]
    providers = registry.list_providers(db_configs=db_configs)
    anthropic = next(p for p in providers if p["id"] == "anthropic")
    assert anthropic["healthStatus"] == "unhealthy"
    assert anthropic["errorSummary"] == "Invalid API key"


# ---------------------------------------------------------------------------
# get_provider with db_configs
# ---------------------------------------------------------------------------

def test_get_provider_with_db_configs():
    """get_provider returns merged result when db_configs is provided."""
    db_configs = [
        {
            "providerId": "minimax",
            "model": "MiniMax-M3-256k",
            "apiKeyPrefix": "mx-",
            "apiKeyLast4": "a1b2",
        },
    ]
    result = registry.get_provider("minimax", db_configs=db_configs)
    assert result is not None
    assert result["defaultModel"] == "MiniMax-M3-256k"
    assert result["maskedSecret"] == "mx-...a1b2"


# ---------------------------------------------------------------------------
# Async DB-aware helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_providers_from_db_success():
    """list_providers_from_db returns merged list when DB is available."""
    mock_configs = [
        {
            "providerId": "openai",
            "model": "gpt-4o-db",
            "apiKeyPrefix": "sk-",
            "apiKeyLast4": "db99",
            "enabled": True,
        },
    ]
    with patch(
        "db.repository.list_llm_provider_configs",
        new_callable=AsyncMock,
        return_value=mock_configs,
    ):
        result = await registry.list_providers_from_db()

    assert isinstance(result, list)
    openai = next(p for p in result if p["id"] == "openai")
    assert openai["defaultModel"] == "gpt-4o-db"
    assert openai["maskedSecret"] == "sk-...db99"


@pytest.mark.asyncio
async def test_list_providers_from_db_fallback():
    """list_providers_from_db falls back when DB query raises."""
    with patch(
        "db.repository.list_llm_provider_configs",
        new_callable=AsyncMock,
        side_effect=RuntimeError("no event loop"),
    ):
        result = await registry.list_providers_from_db()

    # Should still return providers from static defs
    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_get_provider_from_db_success():
    """get_provider_from_db returns merged result when DB is available."""
    mock_configs = [
        {
            "providerId": "minimax",
            "model": "MiniMax-M3-v2",
            "apiKeyPrefix": "mm-",
            "apiKeyLast4": "99xx",
            "enabled": True,
        },
    ]
    with patch(
        "db.repository.list_llm_provider_configs",
        new_callable=AsyncMock,
        return_value=mock_configs,
    ):
        result = await registry.get_provider_from_db("minimax")

    assert result is not None
    assert result["defaultModel"] == "MiniMax-M3-v2"
    assert result["maskedSecret"] == "mm-...99xx"


@pytest.mark.asyncio
async def test_get_provider_from_db_fallback():
    """get_provider_from_db falls back when DB query raises."""
    with patch(
        "db.repository.list_llm_provider_configs",
        new_callable=AsyncMock,
        side_effect=Exception("DB down"),
    ):
        result = await registry.get_provider_from_db("openai")

    # Falls back to env-based lookup
    assert result is not None
    assert result["id"] == "openai"
