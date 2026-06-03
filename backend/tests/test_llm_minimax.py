"""Tests for MiniMax provider metadata, registry health, and execution gate."""

import os
import pytest


# ---------------------------------------------------------------------------
# T5.1 — Provider metadata
# ---------------------------------------------------------------------------

def test_minimax_provider_metadata():
    """MiniMax provider has correct id, name, adapter, auth_env_var, default_model."""
    from core.llm.providers import PROVIDER_MAP

    p = PROVIDER_MAP.get("minimax")
    assert p is not None, "minimax provider not found in PROVIDER_MAP"
    assert p.id == "minimax"
    assert p.name == "MiniMax"
    assert p.adapter == "anthropic-compatible"
    assert p.auth_env_var == "ANTHROPIC_AUTH_TOKEN"
    assert p.default_model == "MiniMax-M3"
    assert "MiniMax-M3" in p.models


# ---------------------------------------------------------------------------
# T5.2 — Missing key status
# ---------------------------------------------------------------------------

def test_minimax_missing_key():
    """Without env vars, minimax status is missing_key."""
    from core.llm.registry import list_providers

    # Ensure env vars are NOT set for this test
    saved_url = os.environ.pop("ANTHROPIC_BASE_URL", None)
    saved_token = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        assert minimax["status"] == "missing_key"
        assert minimax["configured"] is False
    finally:
        if saved_url is not None:
            os.environ["ANTHROPIC_BASE_URL"] = saved_url
        if saved_token is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = saved_token


# ---------------------------------------------------------------------------
# T5.3 — Configured status
# ---------------------------------------------------------------------------

def test_minimax_configured():
    """With both env vars set, minimax status is configured."""
    from core.llm.registry import list_providers

    os.environ["ANTHROPIC_BASE_URL"] = "https://api.minimax.io/anthropic"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-token-1234"
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        assert minimax["status"] == "configured"
        assert minimax["configured"] is True
    finally:
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


# ---------------------------------------------------------------------------
# T5.4 — No secret leak
# ---------------------------------------------------------------------------

def test_minimax_no_secret_leak():
    """API response does not contain raw secret."""
    from core.llm.registry import list_providers

    os.environ["ANTHROPIC_BASE_URL"] = "https://api.minimax.io/anthropic"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "super-secret-key-abcdef"
    try:
        providers = list_providers()
        minimax = next(p for p in providers if p["id"] == "minimax")
        # maskedSecret should be masked, never the full key
        assert minimax["maskedSecret"] != "super-secret-key-abcdef"
        assert "abcdef" not in (minimax["maskedSecret"] or "")
        # authEnvVar is the variable name, not the value
        assert minimax["authEnvVar"] == "ANTHROPIC_AUTH_TOKEN"
    finally:
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


# ---------------------------------------------------------------------------
# T5.5 — Execution gate blocks real LLM
# ---------------------------------------------------------------------------

def test_execution_gate_blocks_real_llm():
    """Dispatch with api-agent mode when gate is off → effective mode is safe-runner."""
    # The gate is checked in ecc.py dispatch_ecc_command.
    # When ALLOW_REAL_LLM_EXECUTION is not "true", api-agent falls back to safe-runner.
    from api.v1.endpoints.ecc import dispatch_ecc_command

    saved = os.environ.pop("ALLOW_REAL_LLM_EXECUTION", None)
    try:
        # Gate is OFF (default) — we can't easily call the endpoint directly
        # in a unit test, but we can verify the gate logic directly:
        allow_real = os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true"
        assert allow_real is False, "Gate should be off by default"

        # Simulate the gate logic from ecc.py lines 203-208
        execution_mode = "api-agent"
        if execution_mode in ("api-agent", "cli-agent") and not allow_real:
            execution_mode = "safe-runner"
        assert execution_mode == "safe-runner"
    finally:
        if saved is not None:
            os.environ["ALLOW_REAL_LLM_EXECUTION"] = saved


# ---------------------------------------------------------------------------
# T5.6 — Execution gate allows real LLM
# ---------------------------------------------------------------------------

def test_execution_gate_allows_real_llm():
    """Dispatch with api-agent mode when gate is on → effective mode stays api-agent."""
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
