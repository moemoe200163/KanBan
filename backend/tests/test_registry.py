import pytest
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


@pytest.fixture(autouse=True)
def reset_registry():
    HarnessRegistry.clear()
    yield
    HarnessRegistry.clear()


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