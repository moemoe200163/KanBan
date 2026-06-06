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
