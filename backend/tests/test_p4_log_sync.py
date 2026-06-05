"""Tests for P4 Log Sync — job_id filter on runs, runtime endpoint job_id param.

Covers:
- list_runs_by_board with job_id filter
- GET /api/v1/runtime/runs?job_id= returns linked runs
- orchestrator broadcast helper is callable
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database, repository as repo
from db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def _init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    db_path = tmp_path / "test_p4.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(database, "engine", new_engine, raising=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(database, "_db_initialized", False, raising=False)
    monkeypatch.setattr(database, "DATABASE_URL", new_url, raising=False)

    async def _init():
        pass
    monkeypatch.setattr(database, "ensure_db_init", _init, raising=False)

    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init_db(new_engine))
    database._db_initialized = True

    yield new_engine

    loop.run_until_complete(new_engine.dispose())
    loop.close()


@pytest.fixture()
def api_client(fresh_db):
    """FastAPI TestClient with isolated DB."""
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# list_runs_by_board — job_id filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_filter_by_job_id(fresh_db):
    """Runs linked to a job are returned when filtering by job_id."""
    await repo.create_run(id="r-j1", board_id="board-default", job_id="job-abc", issue_key="X-001")
    await repo.create_run(id="r-j2", board_id="board-default", job_id="job-abc", issue_key="X-002")
    await repo.create_run(id="r-j3", board_id="board-default", job_id="job-xyz", issue_key="X-003")
    await repo.create_run(id="r-j4", board_id="board-default", issue_key="X-004")

    runs = await repo.list_runs_by_board("board-default", job_id="job-abc")
    assert len(runs) == 2
    run_ids = {r["id"] for r in runs}
    assert run_ids == {"r-j1", "r-j2"}


@pytest.mark.asyncio
async def test_run_filter_by_job_id_no_match(fresh_db):
    """Filtering by a non-existent job_id returns empty list."""
    await repo.create_run(id="r-n1", board_id="board-default", job_id="job-abc")

    runs = await repo.list_runs_by_board("board-default", job_id="job-nonexistent")
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_run_filter_by_job_id_and_status(fresh_db):
    """Combining job_id and status filters works correctly."""
    await repo.create_run(id="r-c1", board_id="board-default", job_id="job-1")
    await repo.create_run(id="r-c2", board_id="board-default", job_id="job-1")
    await repo.update_run_status("r-c1", "completed")

    pending = await repo.list_runs_by_board("board-default", job_id="job-1", status="pending")
    completed = await repo.list_runs_by_board("board-default", job_id="job-1", status="completed")
    assert len(pending) == 1
    assert len(completed) == 1
    assert pending[0]["id"] == "r-c2"
    assert completed[0]["id"] == "r-c1"


# ---------------------------------------------------------------------------
# Runtime API — job_id query param
# ---------------------------------------------------------------------------

class TestRuntimeEndpointJobIdFilter:
    """Test the runtime runs endpoint accepts job_id query param."""

    def test_list_runs_with_job_id(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs?board_id=board-default&job_id=job-abc")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_list_runs_default_params(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data


# ---------------------------------------------------------------------------
# Orchestrator broadcast helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_run_event_is_callable():
    """_broadcast_run_event exists and is an async function."""
    from core.runtime.orchestrator import _broadcast_run_event
    import asyncio
    assert asyncio.iscoroutinefunction(_broadcast_run_event)


@pytest.mark.asyncio
async def test_broadcast_run_event_swallows_errors():
    """_broadcast_run_event does not raise on import/broadcast failure."""
    from core.runtime.orchestrator import _broadcast_run_event
    # Should not raise — best-effort broadcast
    await _broadcast_run_event("run_test", {"test": True})
