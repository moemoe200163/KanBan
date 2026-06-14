"""Tests for P5 Real LLM Pipeline — API model adapter flow.

Covers:
- Dispatch with execution_mode=api-agent creates AgentRun when gate is open
- Dispatch with execution_mode=api-agent falls back to safe-runner when gate is closed
- HarnessRegistry resolves provider to APIModelAdapter
- APIModelExecutor handles provider config lookup, API key resolution, HTTP call
- APIModelAdapter correctly delegates to APIModelExecutor
"""

import asyncio
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select as sa_select

import main
from db import database as db_module
from db import repository as repo
from db.models import Base, User as UserModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def _init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB with auth headers."""
    db_path = tmp_path / "test_p5.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True

        from api.v1.endpoints.auth import hash_password, create_jwt_token
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            result = await session.execute(
                sa_select(UserModel).where(UserModel.username == "testuser")
            )
            if not result.scalar_one_or_none():
                pwd_hash, _ = hash_password("testpass123")
                session.add(UserModel(
                    id="user_test_1",
                    username="testuser",
                    email="test@example.com",
                    password_hash=pwd_hash,
                    role="admin",
                    created_at=now,
                    updated_at=now,
                ))
                await session.commit()
        token, _ = create_jwt_token("user_test_1", "testuser")
        return {"Authorization": f"Bearer {token}"}

    headers = asyncio.run(_setup())
    yield headers
    asyncio.run(new_engine.dispose())


@pytest.fixture()
def api_client(fresh_db):
    from fastapi.testclient import TestClient
    return TestClient(main.app), fresh_db


@pytest.fixture(autouse=True)
def _register_registry_adapters():
    """Ensure HarnessRegistry has the adapters registered for tests."""
    from core.adapters.registry import HarnessRegistry
    from core.adapters.safe_runner import SafeRunAdapter
    from core.adapters.api_model import APIModelAdapter

    HarnessRegistry.clear()
    HarnessRegistry.register("safe-runner", SafeRunAdapter)
    HarnessRegistry.register_provider("minimax", APIModelAdapter)
    HarnessRegistry.register_provider("openai", APIModelAdapter)
    HarnessRegistry.register_provider("anthropic", APIModelAdapter)
    yield
    HarnessRegistry.clear()


# ---------------------------------------------------------------------------
# Dispatch Gate — execution_mode routing
# ---------------------------------------------------------------------------

class TestDispatchExecutionModeGate:

    def test_api_agent_forced_to_safe_runner_when_gate_closed(self, api_client):
        client, headers = api_client
        resp = client.post("/api/v1/ecc/dispatch", json={
            "issue_id": "iss-1",
            "issue_key": "DEV-001",
            "command": "/loop-start",
            "execution_mode": "api-agent",
            "provider": "minimax",
        }, headers=headers)
        assert resp.status_code == 200
        job = resp.json()
        # Gate is closed: execution_mode forced to safe-runner
        assert job["execution_mode"] == "safe-runner"
        # Provider is preserved in the job record even when gate is closed
        assert job["provider"] == "minimax"

    def test_api_agent_allowed_when_gate_open(self, api_client, monkeypatch):
        client, headers = api_client
        monkeypatch.setenv("ALLOW_REAL_LLM_EXECUTION", "true")
        resp = client.post("/api/v1/ecc/dispatch", json={
            "issue_id": "iss-2",
            "issue_key": "DEV-002",
            "command": "/loop-start",
            "execution_mode": "api-agent",
            "provider": "minimax",
            "model": "MiniMax-M3",
        }, headers=headers)
        assert resp.status_code == 200
        job = resp.json()
        assert job["execution_mode"] == "api-agent"
        assert job["provider"] == "minimax"
        assert job["model"] == "MiniMax-M3"


# ---------------------------------------------------------------------------
# HarnessRegistry — provider resolution
# ---------------------------------------------------------------------------

class TestHarnessRegistryProviderResolution:

    def test_resolve_minimax_provider(self):
        from core.adapters.registry import HarnessRegistry
        from core.adapters.api_model import APIModelAdapter

        adapter = HarnessRegistry.resolve_for_run({
            "provider": "minimax",
            "harness": "safe-runner",
            "board_id": "board-default",
        })
        assert isinstance(adapter, APIModelAdapter)

    def test_resolve_openai_provider(self):
        from core.adapters.registry import HarnessRegistry
        from core.adapters.api_model import APIModelAdapter

        adapter = HarnessRegistry.resolve_for_run({
            "provider": "openai",
            "harness": "safe-runner",
            "board_id": "board-default",
        })
        assert isinstance(adapter, APIModelAdapter)

    def test_fallback_to_safe_runner_when_no_provider(self):
        from core.adapters.registry import HarnessRegistry
        from core.adapters.safe_runner import SafeRunAdapter

        adapter = HarnessRegistry.resolve_for_run({
            "provider": None,
            "harness": "safe-runner",
            "board_id": "board-default",
        })
        assert isinstance(adapter, SafeRunAdapter)


# ---------------------------------------------------------------------------
# APIModelExecutor — mocked HTTP flow
# ---------------------------------------------------------------------------

class TestAPIModelExecutorFlow:

    @pytest.mark.asyncio
    async def test_execute_with_provider_config(self, fresh_db):
        from core.runtime.api_model_executor import APIModelExecutor

        await repo.upsert_llm_provider_config(
            provider_id="minimax",
            display_name="MiniMax",
            base_url="https://api.minimax.io/v1",
            endpoint_path="/chat/completions",
            api_shape="openai-chat",
            auth_type="bearer",
            model="MiniMax-M3",
            api_key_encrypted="encrypted-key-123",
        )

        logs = []
        async def on_log(msg):
            logs.append(msg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        executor = APIModelExecutor(timeout=30)
        with patch("core.runtime.api_model_executor.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            # decrypt_api_key is lazily imported inside execute() from core.llm.crypto
            # Both patches must be active when execute() runs
            with patch("core.llm.crypto.decrypt_api_key", return_value="sk-test-key"):
                result = await executor.execute(
                    provider_id="minimax",
                    model="MiniMax-M3",
                    prompt="Reply with only: ok",
                    on_log=on_log,
                )

                assert result.success is True
        assert result.output == "ok"
        assert result.provider == "minimax"
        assert result.model == "MiniMax-M3"

    @pytest.mark.asyncio
    async def test_execute_missing_provider_config(self, fresh_db):
        from core.runtime.api_model_executor import APIModelExecutor

        logs = []
        async def on_log(msg):
            logs.append(msg)

        executor = APIModelExecutor(timeout=30)
        result = await executor.execute(
            provider_id="nonexistent",
            model="test-model",
            prompt="test",
            on_log=on_log,
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_missing_api_key(self, fresh_db):
        from core.runtime.api_model_executor import APIModelExecutor

        await repo.upsert_llm_provider_config(
            provider_id="minimax",
            display_name="MiniMax",
            base_url="https://api.minimax.io/v1",
            api_shape="openai-chat",
        )

        logs = []
        async def on_log(msg):
            logs.append(msg)

        executor = APIModelExecutor(timeout=30)
        # decrypt_api_key is lazily imported inside execute() from core.llm.crypto
        with patch("core.llm.crypto.decrypt_api_key", return_value=""):
            result = await executor.execute(
                provider_id="minimax",
                model="MiniMax-M3",
                prompt="test",
                on_log=on_log,
            )

        assert result.success is False
        assert "No API key" in result.error


# ---------------------------------------------------------------------------
# APIModelAdapter — delegates to executor
# ---------------------------------------------------------------------------

class TestAPIModelAdapter:

    @pytest.mark.asyncio
    async def test_adapter_execute_delegates_to_executor(self, fresh_db):
        from core.adapters.api_model import APIModelAdapter

        await repo.upsert_llm_provider_config(
            provider_id="minimax",
            display_name="MiniMax",
            base_url="https://api.minimax.io/v1",
            endpoint_path="/chat/completions",
            api_shape="openai-chat",
            auth_type="bearer",
            model="MiniMax-M3",
            api_key_encrypted="encrypted-key",
        )

        adapter = APIModelAdapter(config={
            "provider_id": "minimax",
            "model": "MiniMax-M3",
        })

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Hello from MiniMax"
        mock_result.error = None
        mock_result.latency_ms = 500

        with patch("core.runtime.api_model_executor.APIModelExecutor") as MockExecutor:
            mock_instance = AsyncMock()
            mock_instance.execute = AsyncMock(return_value=mock_result)
            MockExecutor.return_value = mock_instance

            logs = []
            async def on_log(msg):
                logs.append(msg)

            result = await adapter.execute(
                task_id="test-run-1",
                prompt="Say hello",
                workspace="/tmp",
                on_log=on_log,
            )

        assert result.success is True
        assert result.output == "Hello from MiniMax"
        mock_instance.execute.assert_called_once()
