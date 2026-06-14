import pytest
from unittest.mock import AsyncMock, MagicMock
from core.adapters.registry import HarnessRegistry
from core.adapters.base import BaseAIAdapter, ExecutionResult


class DummyAdapter(BaseAIAdapter):
    def __init__(self, config=None):
        self._config = config

    @property
    def supported_harnesses(self):
        return ["dummy"]

    async def dispatch(self, issue, context):
        return ExecutionResult(success=True)

    async def execute(self, task_id, prompt, workspace, on_log=None):
        return ExecutionResult(success=True)

    async def test_environment(self):
        return True


class AnotherAdapter(BaseAIAdapter):
    def __init__(self, config=None):
        self._config = config

    @property
    def supported_harnesses(self):
        return ["another"]

    async def dispatch(self, issue, context):
        return ExecutionResult(success=True)

    async def execute(self, task_id, prompt, workspace, on_log=None):
        return ExecutionResult(success=True, output="another output")

    async def test_environment(self):
        return True


@pytest.fixture(autouse=True)
def reset_registry():
    HarnessRegistry.clear()
    yield
    HarnessRegistry.clear()


# ------------------------------------------------------------------
# Basic registration
# ------------------------------------------------------------------

def test_register_adapter_class():
    HarnessRegistry.register("dummy", DummyAdapter)
    assert "dummy" in HarnessRegistry.list_supported()


def test_get_adapter_instance():
    HarnessRegistry.register("dummy", DummyAdapter)
    adapter = HarnessRegistry.get("dummy")
    assert adapter is not None
    assert isinstance(adapter, DummyAdapter)


def test_get_cached_instance():
    HarnessRegistry.register("dummy", DummyAdapter)
    adapter1 = HarnessRegistry.get("dummy")
    adapter2 = HarnessRegistry.get("dummy")
    assert adapter1 is adapter2


def test_unsupported_harness_returns_none():
    HarnessRegistry.clear()
    adapter = HarnessRegistry.get("nonexistent")
    assert adapter is None


def test_is_supported():
    HarnessRegistry.register("dummy", DummyAdapter)
    assert HarnessRegistry.is_supported("dummy") is True
    assert HarnessRegistry.is_supported("nonexistent") is False


# ------------------------------------------------------------------
# Provider registration
# ------------------------------------------------------------------

def test_register_provider():
    HarnessRegistry.register_provider("openai", DummyAdapter)
    assert "openai" in HarnessRegistry.list_providers()


def test_get_for_provider():
    HarnessRegistry.register_provider("openai", DummyAdapter)
    adapter = HarnessRegistry.get_for_provider("openai", config={"model": "gpt-4"})
    assert adapter is not None
    assert isinstance(adapter, DummyAdapter)
    assert adapter._config["model"] == "gpt-4"
    assert adapter._config["provider_id"] == "openai"


def test_get_for_provider_caches():
    HarnessRegistry.register_provider("openai", DummyAdapter)
    a1 = HarnessRegistry.get_for_provider("openai")
    a2 = HarnessRegistry.get_for_provider("openai")
    assert a1 is a2


def test_unsupported_provider_returns_none():
    adapter = HarnessRegistry.get_for_provider("nonexistent")
    assert adapter is None


def test_is_provider_supported():
    HarnessRegistry.register_provider("openai", DummyAdapter)
    assert HarnessRegistry.is_provider_supported("openai") is True
    assert HarnessRegistry.is_provider_supported("anthropic") is False


def test_list_providers():
    HarnessRegistry.register_provider("openai", DummyAdapter)
    HarnessRegistry.register_provider("anthropic", AnotherAdapter)
    providers = HarnessRegistry.list_providers()
    assert "openai" in providers
    assert "anthropic" in providers


# ------------------------------------------------------------------
# resolve_for_run — provider path
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_for_run_provider_path():
    """When run has provider set, resolve_for_run returns a fresh provider adapter."""
    HarnessRegistry.register_provider("minimax", DummyAdapter)

    run = {
        "id": "run-1",
        "provider": "minimax",
        "model": "MiniMax-M3",
        "harness": "safe-runner",
    }
    adapter = HarnessRegistry.resolve_for_run(run)
    assert adapter is not None
    assert isinstance(adapter, DummyAdapter)


@pytest.mark.asyncio
async def test_resolve_for_run_provider_takes_precedence():
    """Provider-specific adapter wins over harness adapter."""
    HarnessRegistry.register("safe-runner", AnotherAdapter)
    HarnessRegistry.register_provider("minimax", DummyAdapter)

    run = {
        "id": "run-2",
        "provider": "minimax",
        "harness": "safe-runner",
    }
    adapter = HarnessRegistry.resolve_for_run(run)
    # Should be DummyAdapter (provider), not AnotherAdapter (harness)
    assert isinstance(adapter, DummyAdapter)


# ------------------------------------------------------------------
# resolve_for_run — harness path
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_for_run_harness_path():
    """When no provider, resolve_for_run uses harness type."""
    HarnessRegistry.register("claude-code", AnotherAdapter)

    run = {
        "id": "run-3",
        "harness": "claude-code",
    }
    adapter = HarnessRegistry.resolve_for_run(run)
    assert adapter is not None
    assert isinstance(adapter, AnotherAdapter)


# ------------------------------------------------------------------
# resolve_for_run — safe-runner fallback
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_for_run_fallback_to_safe_runner():
    """When no provider or harness match, falls back to safe-runner."""
    HarnessRegistry.register("safe-runner", DummyAdapter)

    run = {
        "id": "run-4",
        "harness": "unknown-harness",
    }
    adapter = HarnessRegistry.resolve_for_run(run)
    assert adapter is not None
    assert isinstance(adapter, DummyAdapter)


@pytest.mark.asyncio
async def test_resolve_for_run_nothing_registered():
    """When nothing is registered, returns None."""
    run = {"id": "run-5", "harness": "safe-runner"}
    adapter = HarnessRegistry.resolve_for_run(run)
    assert adapter is None


@pytest.mark.asyncio
async def test_resolve_for_run_creates_fresh_instances():
    """resolve_for_run creates a new instance each call (no caching)."""
    HarnessRegistry.register("safe-runner", DummyAdapter)

    run = {"id": "run-6", "harness": "safe-runner"}
    a1 = HarnessRegistry.resolve_for_run(run)
    a2 = HarnessRegistry.resolve_for_run(run)
    assert a1 is not a2


# ------------------------------------------------------------------
# Clear
# ------------------------------------------------------------------

def test_clear():
    HarnessRegistry.register("dummy", DummyAdapter)
    HarnessRegistry.register_provider("openai", DummyAdapter)
    HarnessRegistry.clear()
    assert HarnessRegistry.list_supported() == []
    assert HarnessRegistry.list_providers() == []