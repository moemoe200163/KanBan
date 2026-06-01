import pytest
from core.adapters.base import BaseAIAdapter, ExecutionResult


def test_execution_result_dataclass():
    result = ExecutionResult(success=True, output="test output", duration_ms=100)
    assert result.success is True
    assert result.output == "test output"
    assert result.duration_ms == 100


def test_base_adapter_is_abc():
    with pytest.raises(TypeError):
        BaseAIAdapter()


def test_base_adapter_abstract_methods():
    class IncompleteAdapter(BaseAIAdapter):
        pass

    with pytest.raises(TypeError):
        IncompleteAdapter()