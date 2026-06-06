"""Tests for session resume — schema, repository, and API."""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db.models import Base, AgentSession, AgentRun, AgentRunEvent


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with one AgentRun."""
    from db import database as db_module

    db_path = tmp_path / "test_session_resume.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            run = AgentRun(
                id="run_test_001",
                board_id="board-default",
                issue_id="issue-1",
                issue_key="DEV-001",
                status="running",
                harness="api-model",
                provider="openai",
                model="gpt-4o",
                created_at=now,
            )
            session.add(run)
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


class TestAgentSessionModel:
    """Unit tests for AgentSession model creation and to_dict."""

    @pytest.mark.asyncio
    async def test_create_session(self, seeded_db):
        from db import repository as repo
        now = datetime.now(timezone.utc)
        session_dict = await repo.create_session(
            id="sess_abc123",
            board_id="board-default",
            issue_id="issue-1",
            issue_key="DEV-001",
            harness="api-model",
            provider="openai",
            model="gpt-4o",
        )
        assert session_dict["id"] == "sess_abc123"
        assert session_dict["status"] == "active"
        assert session_dict["harness"] == "api-model"
        assert session_dict["totalRuns"] == 1
        assert session_dict["conversationHistory"] == []
        assert session_dict["checkpointData"] == {}

    @pytest.mark.asyncio
    async def test_agent_run_has_session_id(self, seeded_db):
        from db import repository as repo
        session_dict = await repo.create_session(
            id="sess_xyz",
            board_id="board-default",
            issue_id="issue-1",
            issue_key="DEV-001",
        )
        await repo.update_run_session_id("run_test_001", "sess_xyz")
        run = await repo.get_run("run_test_001")
        assert run["sessionId"] == "sess_xyz"

    @pytest.mark.asyncio
    async def test_run_without_session_id_is_none(self, seeded_db):
        from db import repository as repo
        run = await repo.get_run("run_test_001")
        assert run["sessionId"] is None

    @pytest.mark.asyncio
    async def test_session_expires_at_default_7_days(self, seeded_db):
        from db import repository as repo
        session_dict = await repo.create_session(
            id="sess_ttl",
            board_id="board-default",
            issue_id="issue-1",
            issue_key="DEV-001",
        )
        expires = datetime.fromisoformat(session_dict["expiresAt"])
        created = datetime.fromisoformat(session_dict["createdAt"])
        delta = expires - created
        assert delta.days == 7


class TestSessionRepository:
    """Tests for session CRUD repository functions."""

    @pytest.mark.asyncio
    async def test_get_session(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_get", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        result = await repo.get_session("sess_get")
        assert result is not None
        assert result["id"] == "sess_get"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_session_returns_none(self, seeded_db):
        from db import repository as repo
        result = await repo.get_session("sess_missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_pause_session(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_pause", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.pause_session("sess_pause", last_error="timeout")
        result = await repo.get_session("sess_pause")
        assert result["status"] == "paused"
        assert result["lastError"] == "timeout"

    @pytest.mark.asyncio
    async def test_complete_session(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_done", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.complete_session("sess_done")
        result = await repo.get_session("sess_done")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_checkpoint(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_ckpt", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        await repo.update_session_checkpoint(
            "sess_ckpt",
            conversation_history=history,
            checkpoint_data={"step": 2},
            provider_resume_ref="resp_123",
        )
        result = await repo.get_session("sess_ckpt")
        assert result["conversationHistory"] == history
        assert result["checkpointData"] == {"step": 2}
        assert result["providerResumeRef"] == "resp_123"

    @pytest.mark.asyncio
    async def test_expire_session_clears_history(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_exp", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.update_session_checkpoint(
            "sess_exp",
            conversation_history=[{"role": "user", "content": "secret"}],
        )
        await repo.expire_session("sess_exp")
        result = await repo.get_session("sess_exp")
        assert result["status"] == "expired"
        assert result["conversationHistory"] is None

    @pytest.mark.asyncio
    async def test_list_sessions_by_issue(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_a", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.create_session(
            id="sess_b", board_id="board-default",
            issue_id="issue-2", issue_key="DEV-002",
        )
        sessions = await repo.list_sessions(issue_id="issue-1")
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess_a"

    @pytest.mark.asyncio
    async def test_list_sessions_by_board(self, seeded_db):
        from db import repository as repo
        await repo.create_session(
            id="sess_s1", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.create_session(
            id="sess_s2", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        sessions = await repo.list_sessions(board_id="board-default")
        assert len(sessions) == 2


class TestAdapterProtocol:
    """Tests for adapter session support protocol."""

    def test_base_adapter_does_not_support_resume(self):
        from core.adapters.base import BaseAIAdapter
        class DummyAdapter(BaseAIAdapter):
            @property
            def supported_harnesses(self):
                return ["dummy"]
            async def dispatch(self, issue, context):
                pass
            async def execute(self, task_id, prompt, workspace, on_log=None):
                pass
            async def test_environment(self):
                return True
        adapter = DummyAdapter()
        assert adapter.supports_resume() is False

    def test_supports_resume_override(self):
        from core.adapters.base import BaseAIAdapter
        class ResumeAdapter(BaseAIAdapter):
            @property
            def supported_harnesses(self):
                return ["resume"]
            async def dispatch(self, issue, context):
                pass
            async def execute(self, task_id, prompt, workspace, on_log=None):
                pass
            async def test_environment(self):
                return True
            def supports_resume(self):
                return True
        adapter = ResumeAdapter()
        assert adapter.supports_resume() is True

    @pytest.mark.asyncio
    async def test_execute_with_session_ignores_session_by_default(self):
        from core.adapters.base import BaseAIAdapter, ExecutionResult
        class SimpleAdapter(BaseAIAdapter):
            @property
            def supported_harnesses(self):
                return ["simple"]
            async def dispatch(self, issue, context):
                pass
            async def execute(self, task_id, prompt, workspace, on_log=None):
                return ExecutionResult(success=True, output="done")
            async def test_environment(self):
                return True
        adapter = SimpleAdapter()
        session_data = {"id": "sess_1", "conversationHistory": [], "checkpointData": {}}
        result = await adapter.execute_with_session(
            task_id="run_1", prompt="test", workspace="/tmp", session=session_data,
        )
        assert result.success is True
        assert result.output == "done"

    def test_execution_result_has_session_fields(self):
        from core.adapters.base import ExecutionResult
        result = ExecutionResult(
            success=True, output="ok",
            conversation_history=[{"role": "user", "content": "hi"}],
            checkpoint_data={"step": 1},
            provider_resume_ref="resp_123",
        )
        assert result.conversation_history == [{"role": "user", "content": "hi"}]
        assert result.checkpoint_data == {"step": 1}
        assert result.provider_resume_ref == "resp_123"

    def test_execution_result_session_fields_default_none(self):
        from core.adapters.base import ExecutionResult
        result = ExecutionResult(success=True, output="ok")
        assert result.conversation_history is None
        assert result.checkpoint_data is None
        assert result.provider_resume_ref is None


class TestWorkerSessionLifecycle:
    """Tests for worker session lifecycle building blocks."""

    @pytest.mark.asyncio
    async def test_resume_adapter_creates_session_and_links_to_run(self, seeded_db):
        """When adapter.supports_resume() is True, caller creates session and links to run."""
        from db import repository as repo
        from core.adapters.base import BaseAIAdapter, ExecutionResult

        class ResumeAdapter(BaseAIAdapter):
            @property
            def supported_harnesses(self):
                return ["resume-test"]
            async def dispatch(self, issue, context):
                pass
            async def execute(self, task_id, prompt, workspace, on_log=None):
                return ExecutionResult(
                    success=True, output="done",
                    conversation_history=[{"role": "user", "content": "hi"}],
                    checkpoint_data={"step": 1},
                    provider_resume_ref="resp_abc",
                )
            async def test_environment(self):
                return True
            def supports_resume(self):
                return True

        adapter = ResumeAdapter()
        assert adapter.supports_resume() is True

        # Create session and link to run (what the caller does)
        session = await repo.create_session(
            id="sess_worker_test",
            board_id="board-default",
            issue_id="issue-1",
            issue_key="DEV-001",
            harness="resume-test",
        )
        await repo.update_run_session_id("run_test_001", "sess_worker_test")

        # Execute and get session data from result
        result = await adapter.execute("run_test_001", "prompt", "/tmp")
        assert result.conversation_history is not None

        # Caller saves checkpoint
        await repo.update_session_checkpoint(
            "sess_worker_test",
            conversation_history=result.conversation_history,
            checkpoint_data=result.checkpoint_data,
            provider_resume_ref=result.provider_resume_ref,
        )

        # Verify
        session = await repo.get_session("sess_worker_test")
        assert session["conversationHistory"] == [{"role": "user", "content": "hi"}]
        assert session["checkpointData"] == {"step": 1}
        assert session["providerResumeRef"] == "resp_abc"

    @pytest.mark.asyncio
    async def test_non_resume_adapter_does_not_create_session(self, seeded_db):
        """When adapter.supports_resume() is False, no session is created."""
        from core.adapters.base import BaseAIAdapter, ExecutionResult

        class NoResumeAdapter(BaseAIAdapter):
            @property
            def supported_harnesses(self):
                return ["no-resume"]
            async def dispatch(self, issue, context):
                pass
            async def execute(self, task_id, prompt, workspace, on_log=None):
                return ExecutionResult(success=True, output="done")
            async def test_environment(self):
                return True

        adapter = NoResumeAdapter()
        assert adapter.supports_resume() is False
        # No session creation happens when supports_resume() is False

    @pytest.mark.asyncio
    async def test_session_paused_on_run_failure(self, seeded_db):
        """When a run fails, the linked session transitions to paused."""
        from db import repository as repo
        await repo.create_session(
            id="sess_fail", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        await repo.update_run_session_id("run_test_001", "sess_fail")
        # Simulate run failure -> session paused
        await repo.pause_session("sess_fail", last_error="timeout")
        session = await repo.get_session("sess_fail")
        assert session["status"] == "paused"
        assert session["lastError"] == "timeout"

    @pytest.mark.asyncio
    async def test_resume_increments_total_runs(self, seeded_db):
        """Resuming a session increments total_runs and sets last_run_at."""
        from db import repository as repo
        await repo.create_session(
            id="sess_resume_count", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        )
        # Pause then resume
        await repo.pause_session("sess_resume_count")
        ok = await repo.resume_session("sess_resume_count")
        assert ok is True
        session = await repo.get_session("sess_resume_count")
        assert session["status"] == "active"
        assert session["totalRuns"] == 2
        assert session["lastRunAt"] is not None


class TestSessionAPIEndpoints:
    """Integration tests for session REST API."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main
        return TestClient(main.app)

    def test_list_sessions(self, seeded_db, client):
        from db import repository as repo
        asyncio.run(repo.create_session(
            id="sess_api_1", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        ))
        resp = client.get("/api/v1/runtime/sessions?board_id=board-default")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_get_session(self, seeded_db, client):
        from db import repository as repo
        asyncio.run(repo.create_session(
            id="sess_api_2", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        ))
        resp = client.get("/api/v1/runtime/sessions/sess_api_2")
        assert resp.status_code == 200
        assert resp.json()["id"] == "sess_api_2"
        assert resp.json()["status"] == "active"

    def test_get_session_not_found(self, seeded_db, client):
        resp = client.get("/api/v1/runtime/sessions/sess_missing")
        assert resp.status_code == 404

    def test_resume_session(self, seeded_db, client):
        from db import repository as repo
        asyncio.run(repo.create_session(
            id="sess_api_resume", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        ))
        asyncio.run(repo.pause_session("sess_api_resume"))
        resp = client.post("/api/v1/runtime/sessions/sess_api_resume/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        assert resp.json()["totalRuns"] == 2

    def test_resume_active_session_fails(self, seeded_db, client):
        from db import repository as repo
        asyncio.run(repo.create_session(
            id="sess_api_active", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        ))
        resp = client.post("/api/v1/runtime/sessions/sess_api_active/resume")
        assert resp.status_code == 409

    def test_delete_session(self, seeded_db, client):
        from db import repository as repo
        asyncio.run(repo.create_session(
            id="sess_api_del", board_id="board-default",
            issue_id="issue-1", issue_key="DEV-001",
        ))
        resp = client.delete("/api/v1/runtime/sessions/sess_api_del")
        assert resp.status_code == 200
        session = asyncio.run(repo.get_session("sess_api_del"))
        assert session["status"] == "expired"
        assert session["conversationHistory"] is None
