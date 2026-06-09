"""Tests for the Tool Runtime Bridge — agentic tool-use loop."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.runtime.tool_bridge import (
    ToolCall,
    parse_anthropic_tool_use,
    parse_openai_tool_calls,
    kanban_tools_as_openai_functions,
    kanban_tools_as_anthropic_tools,
    run_tool_loop,
    BridgeResult,
)
from api.v1.endpoints.kanban_tools import TOOL_SCHEMAS
from db.models import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB for bridge loop tests."""
    from db import database as db_module
    db_path = tmp_path / "test_bridge.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield new_engine, new_sessionmaker


class TestToolSchemaConversion:
    """Test converting TOOL_SCHEMAS to API-specific formats."""

    def test_openai_functions_format(self):
        functions = kanban_tools_as_openai_functions(TOOL_SCHEMAS)
        assert len(functions) == len(TOOL_SCHEMAS)
        for fn in functions:
            assert fn["type"] == "function"
            assert "function" in fn
            assert "name" in fn["function"]
            assert "parameters" in fn["function"]
            assert fn["function"]["parameters"]["type"] == "object"

    def test_anthropic_tools_format(self):
        tools = kanban_tools_as_anthropic_tools(TOOL_SCHEMAS)
        assert len(tools) == len(TOOL_SCHEMAS)
        for tool in tools:
            assert "name" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_all_kanban_tools_present(self):
        functions = kanban_tools_as_openai_functions(TOOL_SCHEMAS)
        names = {fn["function"]["name"] for fn in functions}
        expected = {
            "kanban_list", "kanban_show", "kanban_create", "kanban_comment",
            "kanban_block", "kanban_unblock", "kanban_complete",
            "kanban_heartbeat", "kanban_link",
        }
        assert names == expected


class TestAnthropicToolUseParsing:
    """Test parsing tool_use blocks from Anthropic responses."""

    def test_parse_single_tool_use(self):
        content = [
            {"type": "text", "text": "I'll check the issue."},
            {"type": "tool_use", "id": "tu_001", "name": "kanban_show", "input": {"issue_key": "DEV-1"}},
        ]
        calls = parse_anthropic_tool_use(content)
        assert len(calls) == 1
        assert calls[0].id == "tu_001"
        assert calls[0].name == "kanban_show"
        assert calls[0].input["issue_key"] == "DEV-1"

    def test_parse_multiple_tool_use(self):
        content = [
            {"type": "tool_use", "id": "tu_001", "name": "kanban_show", "input": {}},
            {"type": "tool_use", "id": "tu_002", "name": "kanban_comment", "input": {"body": "test"}},
        ]
        calls = parse_anthropic_tool_use(content)
        assert len(calls) == 2

    def test_parse_no_tool_use(self):
        content = [{"type": "text", "text": "Just a normal response."}]
        calls = parse_anthropic_tool_use(content)
        assert len(calls) == 0


class TestOpenAIToolCallsParsing:
    """Test parsing tool_calls from OpenAI responses."""

    def test_parse_tool_calls(self):
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_001",
                    "type": "function",
                    "function": {
                        "name": "kanban_show",
                        "arguments": '{"issue_key": "DEV-1"}',
                    },
                }
            ],
        }
        calls = parse_openai_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "kanban_show"
        assert calls[0].input["issue_key"] == "DEV-1"

    def test_parse_function_call_legacy(self):
        message = {
            "role": "assistant",
            "content": None,
            "function_call": {
                "name": "kanban_show",
                "arguments": '{"issue_key": "DEV-1"}',
            },
        }
        calls = parse_openai_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "kanban_show"

    def test_parse_no_tool_calls(self):
        message = {"role": "assistant", "content": "Normal response."}
        calls = parse_openai_tool_calls(message)
        assert len(calls) == 0


class TestToolBridgeLoop:
    """Test the agentic tool-use bridge loop with mocked LLM API."""

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, fresh_db):
        """Bridge returns text directly when LLM doesn't call tools."""
        mock_on_log = AsyncMock()

        with patch("db.repository.get_llm_provider_config_with_key") as mock_config:
            mock_config.return_value = {
                "api_key_encrypted": "",
                "base_url": "https://api.example.com",
                "endpoint_path": "/chat/completions",
                "api_shape": "openai-chat",
                "auth_type": "bearer",
                "enabled": True,
                "model": "test-model",
            }

            with patch("core.runtime.api_model_executor._env_var_for_provider", return_value="TEST_API_KEY"):
                with patch("os.getenv", return_value="test-key-123"):
                    with patch("core.runtime.tool_bridge.httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()
                        mock_response = MagicMock()
                        mock_response.status_code = 200
                        mock_response.json.return_value = {
                            "choices": [{
                                "message": {
                                    "role": "assistant",
                                    "content": "All tests pass.",
                                }
                            }],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                        }
                        mock_client.post.return_value = mock_response
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client_cls.return_value = mock_client

                        result = await run_tool_loop(
                            provider_id="test-provider",
                            model="test-model",
                            system_prompt="You are a test agent.",
                            user_prompt="Run tests",
                            tool_schemas=TOOL_SCHEMAS,
                            on_log=mock_on_log,
                            max_iterations=3,
                        )

        assert result.success
        assert result.output == "All tests pass."
        assert result.tool_calls_made == 1  # 1 iteration, no tool calls

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self, fresh_db):
        """Bridge executes one tool call then returns text response."""
        from db import repository as repo

        # Create an issue for kanban_show to find
        issue = await repo.upsert_issue({
            "id": "i-bridge", "key": "DEV-BRIDGE", "board_id": "board-default",
            "title": "Bridge Test", "status": "backlog", "priority": "medium",
        })

        mock_on_log = AsyncMock()

        with patch("db.repository.get_llm_provider_config_with_key") as mock_config:
            mock_config.return_value = {
                "api_key_encrypted": "",
                "base_url": "https://api.example.com",
                "endpoint_path": "/chat/completions",
                "api_shape": "openai-chat",
                "auth_type": "bearer",
                "enabled": True,
                "model": "test-model",
            }

            with patch("core.runtime.api_model_executor._env_var_for_provider", return_value="TEST_API_KEY"):
                with patch("os.getenv", return_value="test-key-123"):
                    with patch("core.runtime.tool_bridge.httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()

                        # First call: tool_call
                        tool_response = MagicMock()
                        tool_response.status_code = 200
                        tool_response.json.return_value = {
                            "choices": [{
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [{
                                        "id": "call_001",
                                        "type": "function",
                                        "function": {
                                            "name": "kanban_show",
                                            "arguments": json.dumps({"issue_key": "DEV-BRIDGE"}),
                                        },
                                    }],
                                }
                            }],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                        }

                        # Second call: text response
                        text_response = MagicMock()
                        text_response.status_code = 200
                        text_response.json.return_value = {
                            "choices": [{
                                "message": {
                                    "role": "assistant",
                                    "content": "The issue is in backlog status.",
                                }
                            }],
                            "usage": {"prompt_tokens": 200, "completion_tokens": 15},
                        }

                        mock_client.post.side_effect = [tool_response, text_response]
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client_cls.return_value = mock_client

                        result = await run_tool_loop(
                            provider_id="test-provider",
                            model="test-model",
                            system_prompt="You are a test agent.",
                            user_prompt="What's the status of DEV-BRIDGE?",
                            tool_schemas=TOOL_SCHEMAS,
                            board_id="board-default",
                            issue_key="DEV-BRIDGE",
                            on_log=mock_on_log,
                            max_iterations=3,
                        )

        assert result.success
        assert "backlog" in result.output.lower()
        assert result.tool_calls_made == 2  # 2 iterations

    @pytest.mark.asyncio
    async def test_max_iterations_limit(self, fresh_db):
        """Bridge stops at max_iterations."""
        mock_on_log = AsyncMock()

        with patch("db.repository.get_llm_provider_config_with_key") as mock_config:
            mock_config.return_value = {
                "api_key_encrypted": "",
                "base_url": "https://api.example.com",
                "endpoint_path": "/chat/completions",
                "api_shape": "openai-chat",
                "auth_type": "bearer",
                "enabled": True,
                "model": "test-model",
            }

            with patch("core.runtime.api_model_executor._env_var_for_provider", return_value="TEST_API_KEY"):
                with patch("os.getenv", return_value="test-key-123"):
                    with patch("core.runtime.tool_bridge.httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()
                        # Always return tool_call to exhaust iterations
                        tool_response = MagicMock()
                        tool_response.status_code = 200
                        tool_response.json.return_value = {
                            "choices": [{
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [{
                                        "id": "call_loop",
                                        "type": "function",
                                        "function": {
                                            "name": "kanban_show",
                                            "arguments": '{"issue_key": "DEV-1"}',
                                        },
                                    }],
                                }
                            }],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                        }
                        mock_client.post.return_value = tool_response
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client_cls.return_value = mock_client

                        result = await run_tool_loop(
                            provider_id="test-provider",
                            model="test-model",
                            system_prompt="test",
                            user_prompt="test",
                            tool_schemas=TOOL_SCHEMAS,
                            on_log=mock_on_log,
                            max_iterations=2,
                        )

        assert result.success
        assert result.tool_calls_made == 2
        assert "Max tool iterations" in result.output

    @pytest.mark.asyncio
    async def test_missing_provider_returns_error(self, fresh_db):
        """Bridge returns error when provider config is missing."""
        with patch("db.repository.get_llm_provider_config_with_key", return_value=None):
            result = await run_tool_loop(
                provider_id="nonexistent",
                model="test-model",
                system_prompt="test",
                user_prompt="test",
                tool_schemas=TOOL_SCHEMAS,
                on_log=AsyncMock(),
            )

        assert not result.success
        assert "not found" in result.error.lower()
