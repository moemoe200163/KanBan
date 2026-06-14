import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


# ------------------------------------------------------------------
# SafeRunAdapter
# ------------------------------------------------------------------

class TestSafeRunAdapter:
    @pytest.mark.asyncio
    async def test_execute_emits_events(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter(config={"tick_delay": 0})
        logs = []

        async def on_log(msg):
            logs.append(msg)

        result = await adapter.execute(
            task_id="task-1",
            prompt="ignored",
            workspace="",
            on_log=on_log,
        )

        assert result.success is True
        assert result.output is not None
        assert "human review" in result.output
        assert len(logs) == 4  # DEFAULT_SAFE_EVENTS has 4 entries

    @pytest.mark.asyncio
    async def test_execute_custom_events(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter(config={
            "tick_delay": 0,
            "events": ["Step A {issue_key}", "Step B"],
        })
        logs = []

        async def on_log(msg):
            logs.append(msg)

        result = await adapter.execute(
            task_id="DEV-999",
            prompt="",
            workspace="",
            on_log=on_log,
        )

        assert result.success is True
        assert logs[0] == "Step A DEV-999"
        assert logs[1] == "Step B"

    @pytest.mark.asyncio
    async def test_execute_no_callback(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter(config={"tick_delay": 0})
        result = await adapter.execute(
            task_id="task-2", prompt="", workspace="", on_log=None,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_dispatch_builds_prompt(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter(config={"tick_delay": 0})
        issue = {"id": "iss-1", "key": "DEV-10", "title": "Fix bug"}
        result = await adapter.dispatch(issue, context={})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_test_environment_always_true(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter()
        assert await adapter.test_environment() is True

    def test_supported_harnesses(self):
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = SafeRunAdapter()
        assert adapter.supported_harnesses == ["safe-runner"]


# ------------------------------------------------------------------
# APIModelAdapter
# ------------------------------------------------------------------

class TestAPIModelAdapter:
    def test_config_defaults(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter()
        assert adapter.provider_id == ""
        assert adapter.model == ""
        assert adapter.timeout == 120.0
        assert adapter.system_prompt is None

    def test_config_custom(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={
            "provider_id": "openai",
            "model": "gpt-4",
            "timeout": 60,
            "system_prompt": "You are helpful.",
        })
        assert adapter.provider_id == "openai"
        assert adapter.model == "gpt-4"
        assert adapter.timeout == 60
        assert adapter.system_prompt == "You are helpful."

    def test_supported_harnesses(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter()
        assert adapter.supported_harnesses == ["api-model"]

    def test_build_prompt_basic(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter()
        issue = {"key": "DEV-1", "title": "Test issue"}
        context = {"command": "implement", "profile": "backend"}
        prompt = adapter._build_prompt(issue, context)

        assert "DEV-1" in prompt
        assert "Test issue" in prompt
        assert "implement" in prompt
        assert "backend" in prompt

    def test_build_prompt_with_description(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter()
        issue = {
            "key": "DEV-2",
            "title": "Fix login",
            "description": "Login form is broken",
        }
        prompt = adapter._build_prompt(issue, {})
        assert "Login form is broken" in prompt

    @pytest.mark.asyncio
    async def test_execute_delegates_to_api_model_executor(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "minimax", "model": "M3"})

        mock_api_result = MagicMock(
            success=True,
            output="LLM response",
            error=None,
            latency_ms=500,
        )

        with patch("core.runtime.api_model_executor.APIModelExecutor") as MockExec:
            mock_instance = MockExec.return_value
            mock_instance.execute = AsyncMock(return_value=mock_api_result)

            result = await adapter.execute(
                task_id="task-api",
                prompt="Hello",
                workspace="",
            )

        assert result.success is True
        assert result.output == "LLM response"
        assert result.duration_ms == 500

    @pytest.mark.asyncio
    async def test_execute_failure_maps_error(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "minimax"})

        mock_api_result = MagicMock(
            success=False,
            output=None,
            error="Auth failed",
            latency_ms=100,
        )

        with patch("core.runtime.api_model_executor.APIModelExecutor") as MockExec:
            mock_instance = MockExec.return_value
            mock_instance.execute = AsyncMock(return_value=mock_api_result)

            result = await adapter.execute(
                task_id="task-fail", prompt="Hello", workspace="",
            )

        assert result.success is False
        assert result.error == "Auth failed"
        assert result.output is None

    @pytest.mark.asyncio
    async def test_test_environment_no_provider(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter()
        assert await adapter.test_environment() is False

    @pytest.mark.asyncio
    async def test_test_environment_provider_enabled(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "openai"})

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"enabled": True, "provider": "openai"}
            assert await adapter.test_environment() is True

    @pytest.mark.asyncio
    async def test_test_environment_provider_disabled(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "openai"})

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"enabled": False}
            assert await adapter.test_environment() is False

    @pytest.mark.asyncio
    async def test_test_environment_db_error(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "openai"})

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("DB connection failed")
            assert await adapter.test_environment() is False

    @pytest.mark.asyncio
    async def test_dispatch_builds_and_executes(self):
        from core.adapters.api_model import APIModelAdapter

        adapter = APIModelAdapter(config={"provider_id": "openai"})

        mock_api_result = MagicMock(
            success=True, output="Response", error=None, latency_ms=200,
        )

        with patch("core.runtime.api_model_executor.APIModelExecutor") as MockExec:
            mock_instance = MockExec.return_value
            mock_instance.execute = AsyncMock(return_value=mock_api_result)

            issue = {"id": "iss-3", "key": "DEV-50", "title": "Deploy"}
            result = await adapter.dispatch(issue, context={"command": "deploy"})

        assert result.success is True
        assert result.output == "Response"