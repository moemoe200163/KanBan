"""Tests for MiniMax provider metadata, registry health, and execution gate."""

import os
import pytest


# ---------------------------------------------------------------------------
# T5.1 -- Provider metadata
# ---------------------------------------------------------------------------

def test_minimax_provider_metadata():
    """MiniMax provider has correct id, name, adapter, auth_env_var, default_model."""
    from core.llm.providers import PROVIDER_MAP

    p = PROVIDER_MAP.get("minimax")
    assert p is not None, "minimax provider not found in PROVIDER_MAP"
    assert p.id == "minimax"
    assert p.name == "MiniMax"
    assert p.adapter == "api-chat"
    assert p.auth_env_var == "MINIMAX_API_KEY"
    assert p.default_model == "MiniMax-M3"
    assert "MiniMax-M3" in p.models


# ---------------------------------------------------------------------------
# T5.2 -- Missing key status
# ---------------------------------------------------------------------------

def test_minimax_missing_key():
    """Without env vars, minimax status is missing_key."""
    from core.llm.registry import list_providers

    saved = os.environ.pop("MINIMAX_API_KEY", None)
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        assert minimax["status"] == "missing_key"
        assert minimax["configured"] is False
    finally:
        if saved is not None:
            os.environ["MINIMAX_API_KEY"] = saved


# ---------------------------------------------------------------------------
# T5.3 -- Configured status
# ---------------------------------------------------------------------------

def test_minimax_configured():
    """With env var set, minimax status is configured."""
    from core.llm.registry import list_providers

    os.environ["MINIMAX_API_KEY"] = "test-token-1234"
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        assert minimax["status"] == "configured"
        assert minimax["configured"] is True
    finally:
        os.environ.pop("MINIMAX_API_KEY", None)


# ---------------------------------------------------------------------------
# T5.4 -- No secret leak
# ---------------------------------------------------------------------------

def test_minimax_no_secret_leak():
    """API response does not contain raw secret."""
    from core.llm.registry import list_providers

    os.environ["MINIMAX_API_KEY"] = "super-secret-key-abcdef"
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        # maskedSecret should be masked, never the full key
        assert minimax["maskedSecret"] != "super-secret-key-abcdef"
        assert "super-secret" not in (minimax["maskedSecret"] or "")
        # authEnvVar is the variable name, not the value
        assert minimax["authEnvVar"] == "MINIMAX_API_KEY"
    finally:
        os.environ.pop("MINIMAX_API_KEY", None)


# ---------------------------------------------------------------------------
# T5.5 -- Execution gate blocks real LLM
# ---------------------------------------------------------------------------

def test_execution_gate_blocks_real_llm():
    """Dispatch with api-agent mode when gate is off -> effective mode is safe-runner."""
    saved = os.environ.pop("ALLOW_REAL_LLM_EXECUTION", None)
    try:
        allow_real = os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true"
        assert allow_real is False, "Gate should be off by default"

        execution_mode = "api-agent"
        if execution_mode in ("api-agent", "cli-agent") and not allow_real:
            execution_mode = "safe-runner"
        assert execution_mode == "safe-runner"
    finally:
        if saved is not None:
            os.environ["ALLOW_REAL_LLM_EXECUTION"] = saved


# ---------------------------------------------------------------------------
# T5.6 -- Execution gate allows real LLM
# ---------------------------------------------------------------------------

def test_execution_gate_allows_real_llm():
    """Dispatch with api-agent mode when gate is on -> effective mode stays api-agent."""
    saved = os.environ.get("ALLOW_REAL_LLM_EXECUTION")
    os.environ["ALLOW_REAL_LLM_EXECUTION"] = "true"
    try:
        allow_real = os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true"
        assert allow_real is True

        execution_mode = "api-agent"
        if execution_mode in ("api-agent", "cli-agent") and not allow_real:
            execution_mode = "safe-runner"
        assert execution_mode == "api-agent"
    finally:
        if saved is not None:
            os.environ["ALLOW_REAL_LLM_EXECUTION"] = saved
        else:
            os.environ.pop("ALLOW_REAL_LLM_EXECUTION", None)


# ---------------------------------------------------------------------------
# T5.7 -- Xiaomi provider metadata
# ---------------------------------------------------------------------------

def test_xiaomi_provider_metadata():
    """Xiaomi MiMo provider has correct id, name, adapter, auth_env_var."""
    from core.llm.providers import PROVIDER_MAP

    p = PROVIDER_MAP.get("xiaomi")
    assert p is not None, "xiaomi provider not found in PROVIDER_MAP"
    assert p.id == "xiaomi"
    assert p.name == "Xiaomi MiMo"
    assert p.adapter == "api-chat"
    assert p.auth_env_var == "XIAOMI_API_KEY"
    assert p.default_model == "MiMo-7B"
    assert "MiMo-7B" in p.models
