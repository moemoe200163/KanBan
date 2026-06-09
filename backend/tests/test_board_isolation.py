"""Tests for Board Isolation — board_id propagation across repo and API.

Covers:
- _job_model_to_dict includes board_id
- create_issue_event/comment/artifact set board_id on model
- create_job_for_handoff passes board_id to repo
- Cross-board issue isolation (list_issues, find_issue_by_key)
- Cross-board run isolation (reclaim_stale_runs)
- Cross-board job isolation (list_jobs)
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID
from db import database as _db_module
from db import repository as repo
from db.models import Base


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file and reset tables."""
    db_path = tmp_path / "test_board_isolation.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(_db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(_db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(_db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(_db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _db_module._db_initialized = True
    asyncio.run(_setup())

    yield repo


async def _noop():
    pass


# ---------------------------------------------------------------------------
# _job_model_to_dict includes board_id
# ---------------------------------------------------------------------------

class TestJobModelToDict:
    def test_includes_board_id(self):
        from db.repository import _job_model_to_dict

        class FakeJob:
            id = "j1"
            issue_id = "i1"
            issue_key = "DEV-001"
            command = "/loop-start"
            profile = "general"
            harness = "safe-runner"
            status = "queued"
            created_at = "2026-01-01T00:00:00Z"
            updated_at = "2026-01-01T00:00:00Z"
            board_id = "board-default"
            message = "test"
            events = []

        d = _job_model_to_dict(FakeJob())
        assert "board_id" in d
        assert d["board_id"] == "board-default"

    def test_includes_custom_board_id(self):
        from db.repository import _job_model_to_dict

        class FakeJob:
            id = "j1"
            issue_id = "i1"
            issue_key = "DEV-001"
            command = "/loop-start"
            profile = "general"
            harness = "safe-runner"
            status = "queued"
            created_at = "2026-01-01T00:00:00Z"
            updated_at = "2026-01-01T00:00:00Z"
            board_id = "board-alpha"
            message = "test"
            events = []

        d = _job_model_to_dict(FakeJob())
        assert d["board_id"] == "board-alpha"


# ---------------------------------------------------------------------------
# create_issue_event sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueEventBoardId:
    @pytest.mark.asyncio
    async def test_event_board_id_forwarded(self):
        """Verify create_issue_event passes board_id to the IssueEvent model."""
        from db.repository import create_issue_event

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_event(
                issue_id="i1",
                event_type="test",
                summary="test event",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"

    @pytest.mark.asyncio
    async def test_event_defaults_board_id(self):
        from db.repository import create_issue_event

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_event(
                issue_id="i1",
                event_type="test",
                summary="test event",
            )
            assert captured["board_id"] == DEFAULT_BOARD_ID


# ---------------------------------------------------------------------------
# create_issue_comment sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueCommentBoardId:
    @pytest.mark.asyncio
    async def test_comment_board_id_forwarded(self):
        from db.repository import create_issue_comment

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_comment(
                issue_id="i1",
                body="hello",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"


# ---------------------------------------------------------------------------
# create_issue_artifact sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueArtifactBoardId:
    @pytest.mark.asyncio
    async def test_artifact_board_id_forwarded(self):
        from db.repository import create_issue_artifact

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_artifact(
                issue_id="i1",
                title="test.txt",
                artifact_type="file",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"


# ---------------------------------------------------------------------------
# create_job_for_handoff passes board_id
# ---------------------------------------------------------------------------

class TestCreateJobForHandoffBoardId:
    @pytest.mark.asyncio
    async def test_passes_board_id_to_repo(self):
        mock_create = AsyncMock(return_value={"id": "ecc_test", "board_id": "custom-board"})

        with patch("db.repository.create_ecc_job_safe_runner", mock_create), \
             patch("core.kanban_protocol.lanes.get_lane") as mock_get_lane:
            mock_get_lane.return_value = type("Lane", (), {"allowed_commands": ["/loop-start"]})()

            from core.kanban_protocol.orchestrator import create_job_for_handoff
            await create_job_for_handoff(
                handoff_id="h1",
                issue_id="i1",
                issue_key="DEV-001",
                to_lane="review",
                profile="general",
                actor="test",
                board_id="custom-board",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["board_id"] == "custom-board"

    @pytest.mark.asyncio
    async def test_defaults_to_board_default(self):
        mock_create = AsyncMock(return_value={"id": "ecc_test", "board_id": "board-default"})

        with patch("db.repository.create_ecc_job_safe_runner", mock_create), \
             patch("core.kanban_protocol.lanes.get_lane") as mock_get_lane:
            mock_get_lane.return_value = type("Lane", (), {"allowed_commands": ["/loop-start"]})()

            from core.kanban_protocol.orchestrator import create_job_for_handoff
            await create_job_for_handoff(
                handoff_id="h1",
                issue_id="i1",
                issue_key="DEV-001",
                to_lane="review",
                profile="general",
                actor="test",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["board_id"] == "board-default"


# ---------------------------------------------------------------------------
# kanban_show forwards board_id to list_issue_artifacts
# ---------------------------------------------------------------------------

class TestKanbanShowArtifactBoardScope:
    @pytest.mark.asyncio
    async def test_kanban_show_passes_board_id_to_artifacts(self):
        """kanban_show must forward ctx.board_id when listing artifacts."""
        from core.kanban_protocol.tools import kanban_show, KanbanToolContext

        fake_issue = {"id": "i1", "key": "DEV-100", "board_id": "scope-board"}

        mock_list_issues = AsyncMock(return_value=[fake_issue])
        mock_list_handoffs = AsyncMock(return_value=[])
        mock_list_artifacts = AsyncMock(return_value=[])

        with patch("db.repository.list_issues", mock_list_issues), \
             patch("db.repository.list_issue_handoffs", mock_list_handoffs), \
             patch("db.repository.list_issue_artifacts", mock_list_artifacts):
            ctx = KanbanToolContext(
                board_id="scope-board",
                issue_key="DEV-100",
            )
            result = await kanban_show(ctx)

        assert result.ok is True
        mock_list_artifacts.assert_called_once_with(
            issue_id="i1", board_id="scope-board"
        )


# ---------------------------------------------------------------------------
# Cross-board isolation: issues
# ---------------------------------------------------------------------------

class TestCrossBoardIssueIsolation:
    @pytest.mark.asyncio
    async def test_list_issues_scoped_to_board(self, fresh_db):
        """list_issues with board_id only returns issues from that board."""
        await repo.upsert_issue({
            "id": "i-a1", "key": "A-001", "board_id": "board-a",
            "title": "Board A Issue", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i-b1", "key": "B-001", "board_id": "board-b",
            "title": "Board B Issue", "status": "backlog", "priority": "medium",
        })

        a_issues = await repo.list_issues(board_id="board-a")
        b_issues = await repo.list_issues(board_id="board-b")

        assert len(a_issues) == 1
        assert a_issues[0]["key"] == "A-001"
        assert len(b_issues) == 1
        assert b_issues[0]["key"] == "B-001"

    @pytest.mark.asyncio
    async def test_find_issue_by_key_scoped_to_board(self, fresh_db):
        """find_issue_by_key with board_id only finds issues from that board."""
        await repo.upsert_issue({
            "id": "i-a2", "key": "A-KEY-001", "board_id": "board-a",
            "title": "On A", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i-b2", "key": "B-KEY-001", "board_id": "board-b",
            "title": "On B", "status": "backlog", "priority": "medium",
        })

        # Found on the correct board
        found_a = await repo.find_issue_by_key("A-KEY-001", board_id="board-a")
        found_b = await repo.find_issue_by_key("B-KEY-001", board_id="board-b")

        # Wrong board returns None
        found_wrong_board = await repo.find_issue_by_key("A-KEY-001", board_id="board-b")
        # Non-existent board returns None
        found_none = await repo.find_issue_by_key("A-KEY-001", board_id="board-c")

        assert found_a is not None
        assert found_a["title"] == "On A"
        assert found_b is not None
        assert found_b["title"] == "On B"
        assert found_wrong_board is None
        assert found_none is None


# ---------------------------------------------------------------------------
# Cross-board isolation: runs
# ---------------------------------------------------------------------------

class TestCrossBoardRunIsolation:
    @pytest.mark.asyncio
    async def test_reclaim_stale_runs_scoped_to_board(self, fresh_db):
        """reclaim_stale_runs with board_id only reclaims runs from that board."""
        from datetime import datetime, timezone, timedelta
        from db.models import AgentRun

        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=1)

        # Create stale runs on both boards
        await repo.create_run(
            id="run-a-stale", board_id="board-a",
            issue_id="i1", issue_key="A-001", command="/test",
        )
        await repo.create_run(
            id="run-b-stale", board_id="board-b",
            issue_id="i2", issue_key="B-001", command="/test",
        )

        # Set both to claimed status with old heartbeat
        for run_id in ["run-a-stale", "run-b-stale"]:
            async with repo._get_sessionmaker()() as session:
                run = await session.get(AgentRun, run_id)
                run.status = "claimed"
                run.started_at = old
                run.last_heartbeat_at = old
                await session.commit()

        # Reclaim only board-a
        reclaimed = await repo.reclaim_stale_runs(board_id="board-a")
        reclaimed_ids = [r["id"] for r in reclaimed]

        assert "run-a-stale" in reclaimed_ids
        assert "run-b-stale" not in reclaimed_ids

        # Verify board-b run is still claimed
        run_b = await repo.get_run("run-b-stale")
        assert run_b["status"] == "claimed"


# ---------------------------------------------------------------------------
# Cross-board isolation: ECC jobs
# ---------------------------------------------------------------------------

class TestCrossBoardJobIsolation:
    @pytest.mark.asyncio
    async def test_list_jobs_scoped_to_board(self, fresh_db):
        """list_jobs with board_id only returns jobs from that board."""
        # Create jobs on different boards (create_ecc_job_safe_runner
        # generates its own job_id internally, so we capture the return)
        job_a = await repo.create_ecc_job_safe_runner(
            issue_id="i1", issue_key="A-001",
            board_id="board-a", command="/test",
            profile="general", harness="safe-runner",
        )
        job_b = await repo.create_ecc_job_safe_runner(
            issue_id="i2", issue_key="B-001",
            board_id="board-b", command="/test",
            profile="general", harness="safe-runner",
        )

        a_jobs = await repo.list_jobs(board_id="board-a")
        b_jobs = await repo.list_jobs(board_id="board-b")

        assert len(a_jobs) == 1
        assert a_jobs[0]["id"] == job_a["id"]
        assert len(b_jobs) == 1
        assert b_jobs[0]["id"] == job_b["id"]
