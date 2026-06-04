"""Tests for API Model Executor — real LLM API execution.

Covers:
- APIModelExecutor with mocked HTTP responses
- OpenAI chat completions flow
- Anthropic messages flow
- Provider config loading and error handling
- Missing API key handling
- Disabled provider handling
- HTTP error classification
- Worker routing to APIModelExecutor
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime.api_model_executor import (
    APIModelExecutor,
    APIModelResult,
    _env_var_for_provider,
    _build_auth_headers,
    _extract_openai_chat_content,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_env_var_for_minimax(self):
        assert _env_var_for_provider("minimax") == "MINIMAX_API_KEY"

    def test_env_var_for_openai(self):
        assert _env_var_for_provider("openai") == "OPENAI_API_KEY"

    def test_env_var_for_unknown(self):
        assert _env_var_for_provider("custom") == "CUSTOM_API_KEY"

    def test_bearer_auth(self):
        headers = _build_auth_headers("bearer", "sk-test")
        assert headers["Authorization"] == "Bearer sk-test"

    def test_x_api_key_auth(self):
        headers = _build_auth_headers("x-api-key", "sk-test")
        assert headers["x-api-key"] == "sk-test"

    def test_api_key_auth(self):
        headers = _build_auth_headers("api-key", "sk-test")
        assert headers["api-key"] == "sk-test"

    def test_extract_openai_content(self):
        data = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        assert _extract_openai_chat_content(data) == "Hello world"

    def test_extract_openai_empty(self):
        assert _extract_openai_chat_content({}) == ""


# ---------------------------------------------------------------------------
# APIModelExecutor — unit tests with mocked DB and HTTP
# ---------------------------------------------------------------------------

class TestAPIModelExecutor:
    def _mock_config(self, **overrides):
        """Build a fake provider config dict."""
        config = {
            "provider_id": "minimax",
            "display_name": "MiniMax",
            "enabled": True,
            "base_url": "https://api.minimax.io/v1",
            "endpoint_path": "/chat/completions",
            "api_shape": "openai-chat",
            "auth_type": "bearer",
            "model": "MiniMax-M3",
            "api_key_encrypted": "",
            "api_key_prefix": "sk-",
            "api_key_last4": "ABCD",
        }
        config.update(overrides)
        return config

    @pytest.mark.asyncio
    async def test_execute_missing_provider_config(self):
        """Returns error when provider config not found."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=None):
            result = await executor.execute(
                provider_id="nonexistent",
                model="test",
                prompt="hello",
                on_log=on_log,
            )

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_disabled_provider(self):
        """Returns error when provider is disabled."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(enabled=False)
        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config):
            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="hello",
                on_log=on_log,
            )

        assert result.success is False
        assert "disabled" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_api_key(self):
        """Returns error when no API key is configured."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(api_key_encrypted="")
        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config), \
             patch("os.getenv", return_value=""):
            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="hello",
                on_log=on_log,
            )

        assert result.success is False
        assert "No API key" in result.error

    @pytest.mark.asyncio
    async def test_execute_openai_chat_success(self):
        """Successful OpenAI chat completions call."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(api_key_encrypted="encrypted-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "GNN is a type of neural network..."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config), \
             patch("core.llm.crypto.decrypt_api_key", return_value="sk-test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="Explain GNN",
                on_log=on_log,
            )

        assert result.success is True
        assert "GNN" in result.output
        assert result.provider == "minimax"
        assert result.model == "MiniMax-M3"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert any("API call completed" in log for log in logs)

    @pytest.mark.asyncio
    async def test_execute_openai_chat_http_error(self):
        """Handles HTTP error from OpenAI chat endpoint."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(api_key_encrypted="encrypted-key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": "Unauthorized"}'

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config), \
             patch("core.llm.crypto.decrypt_api_key", return_value="sk-bad-key"), \
             patch("httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="test",
                on_log=on_log,
            )

        assert result.success is False
        assert "401" in result.error

    @pytest.mark.asyncio
    async def test_execute_anthropic_messages_success(self):
        """Successful Anthropic Messages API call."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(
            api_shape="anthropic-messages",
            base_url="https://api.anthropic.com/v1",
            endpoint_path="/messages",
            auth_type="x-api-key",
            api_key_encrypted="encrypted-ant-key",
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Claude response here"}],
            "usage": {"input_tokens": 5, "output_tokens": 15},
        }

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config), \
             patch("core.llm.crypto.decrypt_api_key", return_value="sk-ant-test"), \
             patch("httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await executor.execute(
                provider_id="anthropic",
                model="claude-sonnet-4-20250514",
                prompt="Explain GNN",
                on_log=on_log,
                system_prompt="You are helpful.",
            )

        assert result.success is True
        assert "Claude response" in result.output
        assert result.prompt_tokens == 5
        assert result.completion_tokens == 15

    @pytest.mark.asyncio
    async def test_execute_uses_env_var_fallback(self):
        """Falls back to env var when DB has no encrypted key."""
        executor = APIModelExecutor()
        logs = []

        async def on_log(msg):
            logs.append(msg)

        config = self._mock_config(api_key_encrypted="")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

        with patch("db.repository.get_llm_provider_config", new_callable=AsyncMock, return_value=config), \
             patch("core.llm.crypto.decrypt_api_key", return_value=""), \
             patch("os.getenv", return_value="sk-env-key"), \
             patch("httpx.AsyncClient") as MockClient:
            mock_client = MockClient.return_value.__aenter__.return_value
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="test",
                on_log=on_log,
            )

        assert result.success is True


# ---------------------------------------------------------------------------
# Worker routing — test that APIModelExecutor is used when provider is set
# ---------------------------------------------------------------------------

class TestWorkerRoutingToAPIModel:
    @pytest.mark.asyncio
    async def test_worker_uses_api_model_executor_for_provider_run(self):
        """Worker routes to APIModelExecutor when run has provider field."""
        from core.runtime.worker import AgentWorkerProcess
        from db import repository as repo

        worker = AgentWorkerProcess(
            worker_id="test-api-worker",
            poll_interval=0.01,
            heartbeat_interval=100,
        )

        fake_run = {
            "id": "run-api-1",
            "issueKey": "DEV-700",
            "command": "explain",
            "profile": "general",
            "harness": "safe-runner",
            "provider": "minimax",
            "model": "MiniMax-M3",
        }

        mock_upsert = AsyncMock(return_value={"id": "test-api-worker"})
        mock_heartbeat = AsyncMock()
        mock_start_run = AsyncMock(return_value=fake_run)
        mock_complete_run = AsyncMock(return_value={**fake_run, "status": "completed"})
        mock_fail_run = AsyncMock()
        mock_append_event = AsyncMock()

        claim_calls = 0
        async def claim_once(worker_id, board_id):
            nonlocal claim_calls
            claim_calls += 1
            if claim_calls == 1:
                return fake_run
            return None

        iteration = 0
        original_sleep = asyncio.sleep

        async def controlled_sleep(dt):
            nonlocal iteration
            iteration += 1
            if iteration > 10:
                worker.stop()
            await original_sleep(0)

        mock_api_result = MagicMock(
            success=True,
            output="GNN explanation from MiniMax",
            error=None,
            provider="minimax",
            model="MiniMax-M3",
            prompt_tokens=10,
            completion_tokens=50,
            latency_ms=1200,
        )

        with patch.object(repo, "upsert_worker", mock_upsert), \
             patch.object(repo, "update_worker_heartbeat", mock_heartbeat), \
             patch("core.runtime.orchestrator.claim_next_run", claim_once), \
             patch("core.runtime.orchestrator.start_run", mock_start_run), \
             patch("core.runtime.orchestrator.complete_run", mock_complete_run), \
             patch("core.runtime.orchestrator.fail_run", mock_fail_run), \
             patch("db.repository.append_run_event", mock_append_event), \
             patch("core.runtime.api_model_executor.APIModelExecutor.execute", new_callable=AsyncMock, return_value=mock_api_result), \
             patch("core.runtime.worker.POLL_INTERVAL", 0.01), \
             patch("asyncio.sleep", controlled_sleep):
            await worker.start()

        # Verify APIModelExecutor was used (via the mock)
        mock_complete_run.assert_called_once()
        # Result should contain the API output
        call_args = mock_complete_run.call_args
        assert "GNN explanation" in call_args[1]["result_summary"]
