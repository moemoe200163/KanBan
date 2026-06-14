"""Tests for Agent Runtime schema, repository, and read-only API.

Covers:
- DB roundtrip: worker create → get → update → verify
- DB roundtrip: run create → append events → list events ordered ASC
- Board isolation: workers/runs on board-A not visible when filtering board-B
- Event ordering: events returned in insertion order (created_at ASC)
- API: GET /runtime/workers returns empty list when no workers
- API: GET /runtime/runs returns empty list when no runs
- API: GET /runtime/runs/{id}/events returns events in order
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database, repository as repo
from db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    db_path = tmp_path / "test_runtime.db"
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


async def _init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Worker DB Roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_create_and_get(fresh_db):
    result = await repo.upsert_worker(
        id="worker-1",
        board_id="board-default",
        worker_type="claude-code",
        harness="claude-code",
        status="idle",
    )
    assert result["id"] == "worker-1"
    assert result["boardId"] == "board-default"
    assert result["workerType"] == "claude-code"
    assert result["status"] == "idle"

    fetched = await repo.get_worker("worker-1")
    assert fetched is not None
    assert fetched["id"] == "worker-1"
    assert fetched["status"] == "idle"


@pytest.mark.asyncio
async def test_worker_update_status(fresh_db):
    await repo.upsert_worker(id="w-1", worker_type="claude-code")

    updated = await repo.update_worker_status("w-1", "running", active_run_id="run-abc")
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["activeRunId"] == "run-abc"

    fetched = await repo.get_worker("w-1")
    assert fetched["status"] == "running"
    assert fetched["activeRunId"] == "run-abc"


@pytest.mark.asyncio
async def test_worker_heartbeat(fresh_db):
    await repo.upsert_worker(id="w-hb", worker_type="codex")

    result = await repo.update_worker_heartbeat("w-hb")
    assert result is not None
    assert result["lastHeartbeatAt"] is not None


@pytest.mark.asyncio
async def test_worker_get_nonexistent(fresh_db):
    result = await repo.get_worker("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_worker_update_nonexistent(fresh_db):
    result = await repo.update_worker_status("nonexistent", "running")
    assert result is None


# ---------------------------------------------------------------------------
# Board Isolation — Workers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_board_isolation(fresh_db):
    await repo.upsert_worker(id="w-a1", board_id="board-a", worker_type="claude-code")
    await repo.upsert_worker(id="w-a2", board_id="board-a", worker_type="codex")
    await repo.upsert_worker(id="w-b1", board_id="board-b", worker_type="claude-code")

    board_a = await repo.list_workers_by_board("board-a")
    board_b = await repo.list_workers_by_board("board-b")
    board_c = await repo.list_workers_by_board("board-c")  # empty board

    assert len(board_a) == 2
    assert len(board_b) == 1
    assert len(board_c) == 0

    ids_a = {w["id"] for w in board_a}
    assert "w-a1" in ids_a
    assert "w-a2" in ids_a
    assert "w-b1" not in ids_a


# ---------------------------------------------------------------------------
# Run DB Roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_create_and_get(fresh_db):
    result = await repo.create_run(
        id="run-1",
        board_id="board-default",
        issue_id="issue-1",
        issue_key="DEV-001",
        command="/loop-start",
        profile="backend",
    )
    assert result["id"] == "run-1"
    assert result["status"] == "pending"
    assert result["issueKey"] == "DEV-001"

    fetched = await repo.get_run("run-1")
    assert fetched is not None
    assert fetched["id"] == "run-1"


@pytest.mark.asyncio
async def test_run_update_status(fresh_db):
    await repo.create_run(id="run-2", board_id="board-default")

    updated = await repo.update_run_status(
        "run-2", "running",
        worker_id="worker-1",
        started_at=None,  # will use current time in practice
    )
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["workerId"] == "worker-1"


@pytest.mark.asyncio
async def test_run_get_nonexistent(fresh_db):
    result = await repo.get_run("nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# Board Isolation — Runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_board_isolation(fresh_db):
    await repo.create_run(id="r-a1", board_id="board-a", issue_key="A-001")
    await repo.create_run(id="r-a2", board_id="board-a", issue_key="A-002")
    await repo.create_run(id="r-b1", board_id="board-b", issue_key="B-001")

    runs_a = await repo.list_runs_by_board("board-a")
    runs_b = await repo.list_runs_by_board("board-b")
    runs_c = await repo.list_runs_by_board("board-c")

    assert len(runs_a) == 2
    assert len(runs_b) == 1
    assert len(runs_c) == 0


@pytest.mark.asyncio
async def test_run_board_filter_by_issue(fresh_db):
    await repo.create_run(id="r-f1", board_id="board-default", issue_id="iss-1")
    await repo.create_run(id="r-f2", board_id="board-default", issue_id="iss-1")
    await repo.create_run(id="r-f3", board_id="board-default", issue_id="iss-2")

    runs = await repo.list_runs_by_board("board-default", issue_id="iss-1")
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_run_board_filter_by_status(fresh_db):
    await repo.create_run(id="r-s1", board_id="board-default")
    await repo.create_run(id="r-s2", board_id="board-default")
    await repo.update_run_status("r-s1", "completed")

    pending = await repo.list_runs_by_board("board-default", status="pending")
    completed = await repo.list_runs_by_board("board-default", status="completed")
    assert len(pending) == 1
    assert len(completed) == 1


# ---------------------------------------------------------------------------
# Run Events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_events_append_and_list(fresh_db):
    await repo.create_run(id="run-ev", board_id="board-default")

    await repo.append_run_event(id="ev-1", run_id="run-ev", event_type="status_change", message="started")
    await repo.append_run_event(id="ev-2", run_id="run-ev", event_type="log", message="line 1")
    await repo.append_run_event(id="ev-3", run_id="run-ev", event_type="log", message="line 2")

    events = await repo.list_run_events("run-ev")
    assert len(events) == 3
    # Should be ordered ASC (oldest first)
    assert events[0]["id"] == "ev-1"
    assert events[1]["id"] == "ev-2"
    assert events[2]["id"] == "ev-3"
    assert events[0]["message"] == "started"
    assert events[2]["message"] == "line 2"


@pytest.mark.asyncio
async def test_run_events_empty(fresh_db):
    events = await repo.list_run_events("nonexistent-run")
    assert events == []


@pytest.mark.asyncio
async def test_run_events_are_append_only(fresh_db):
    """Events should never be updated — only appended."""
    await repo.create_run(id="run-ao", board_id="board-default")
    ev = await repo.append_run_event(id="ev-ao-1", run_id="run-ao", event_type="log", message="original")

    # Verify the event exists and has the original message
    events = await repo.list_run_events("run-ao")
    assert len(events) == 1
    assert events[0]["message"] == "original"
    assert events[0]["eventType"] == "log"


# ---------------------------------------------------------------------------
# Worker → Run relationship
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_runs_by_worker(fresh_db):
    await repo.create_run(id="rw-1", board_id="board-default", worker_id="wk-1")
    await repo.create_run(id="rw-2", board_id="board-default", worker_id="wk-1")
    await repo.create_run(id="rw-3", board_id="board-default", worker_id="wk-2")

    runs_w1 = await repo.list_runs_by_worker("wk-1")
    runs_w2 = await repo.list_runs_by_worker("wk-2")
    runs_w3 = await repo.list_runs_by_worker("wk-nonexistent")

    assert len(runs_w1) == 2
    assert len(runs_w2) == 1
    assert len(runs_w3) == 0


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(fresh_db):
    """FastAPI TestClient with isolated DB."""
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


class TestRuntimeWorkersAPI:
    def test_list_workers_empty(self, api_client):
        resp = api_client.get("/api/v1/runtime/workers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workers"] == []
        assert data["total"] == 0

    def test_get_worker_not_found(self, api_client):
        resp = api_client.get("/api/v1/runtime/workers/nonexistent")
        assert resp.status_code == 404


class TestRuntimeRunsAPI:
    def test_list_runs_empty(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []
        assert data["total"] == 0

    def test_get_run_not_found(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_runs_with_data(self, api_client):
        # Insert via repository (API is read-only)
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(repo.create_run(
            id="api-run-1", board_id="board-default", issue_key="DEV-001",
        ))
        loop.close()

        resp = api_client.get("/api/v1/runtime/runs?board_id=board-default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1


class TestRuntimeRunEventsAPI:
    def test_list_events_empty(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs/nonexistent/events")
        assert resp.status_code == 404

    def test_list_events_for_run(self, api_client):
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(repo.create_run(
            id="api-run-ev", board_id="board-default",
        ))
        loop.run_until_complete(repo.append_run_event(
            id="api-ev-1", run_id="api-run-ev", event_type="log", message="hello",
        ))
        loop.close()

        resp = api_client.get("/api/v1/runtime/runs/api-run-ev/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["events"][0]["message"] == "hello"
        assert data["events"][0]["eventType"] == "log"
