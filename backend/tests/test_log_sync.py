"""Tests for Log Sync — push, stream, and WebSocket subscription.

Covers:
- POST /runtime/runs/{id}/log persists event and returns it
- GET /runtime/runs/{id}/logs returns full log history in ASC order
- Log event has correct metadata (level, timestamp)
- WebSocket broadcast_run_log sends to subscribers
- Log filtering (only log events, not status_change events)
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
    db_path = tmp_path / "test_log_sync.db"
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

    async def _init_db():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init_db())
    database._db_initialized = True

    yield new_engine

    loop.run_until_complete(new_engine.dispose())
    loop.close()


@pytest.fixture()
def api_client(fresh_db):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Log Push API
# ---------------------------------------------------------------------------

class TestLogPushAPI:
    def test_push_log(self, api_client):
        # Create a run first
        import asyncio
        loop = asyncio.new_event_loop()
        run = loop.run_until_complete(repo.create_run(
            id="log-run-1", board_id="board-default", issue_key="DEV-001",
        ))
        loop.close()

        resp = api_client.post("/api/v1/runtime/runs/log-run-1/log", json={
            "message": "Hello from worker",
            "level": "info",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Hello from worker"
        assert data["eventType"] == "log"
        assert data["metadata"]["level"] == "info"
        assert data["runId"] == "log-run-1"

    def test_push_log_not_found(self, api_client):
        resp = api_client.post("/api/v1/runtime/runs/nonexistent/log", json={
            "message": "test",
            "level": "info",
        })
        assert resp.status_code == 404

    def test_push_log_with_metadata(self, api_client):
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(repo.create_run(
            id="log-run-2", board_id="board-default",
        ))
        loop.close()

        resp = api_client.post("/api/v1/runtime/runs/log-run-2/log", json={
            "message": "Progress 50%",
            "level": "debug",
            "metadata": {"progress": 50},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["level"] == "debug"
        assert data["metadata"]["progress"] == 50


# ---------------------------------------------------------------------------
# Log Listing API
# ---------------------------------------------------------------------------

class TestLogListingAPI:
    def test_list_logs_empty(self, api_client):
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(repo.create_run(
            id="log-empty", board_id="board-default",
        ))
        loop.close()

        resp = api_client.get("/api/v1/runtime/runs/log-empty/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logs"] == []
        assert data["total"] == 0

    def test_list_logs_ordered_asc(self, api_client):
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(repo.create_run(
            id="log-ord", board_id="board-default",
        ))
        # Push multiple logs
        for i in range(3):
            api_client.post("/api/v1/runtime/runs/log-ord/log", json={
                "message": f"line {i}",
                "level": "info",
            })
        # Also add a status_change event
        loop.run_until_complete(repo.append_run_event(
            id="sc-1", run_id="log-ord", event_type="status_change", message="started",
        ))
        loop.close()

        resp = api_client.get("/api/v1/runtime/runs/log-ord/logs")
        assert resp.status_code == 200
        data = resp.json()
        # Only log events, not status_change
        assert data["total"] == 3
        assert data["logs"][0]["message"] == "line 0"
        assert data["logs"][2]["message"] == "line 2"

    def test_list_logs_not_found(self, api_client):
        resp = api_client.get("/api/v1/runtime/runs/nonexistent/logs")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket Broadcast
# ---------------------------------------------------------------------------

class TestWebSocketBroadcast:
    def test_broadcast_run_log_function(self):
        """Test that broadcast_run_log sends to the correct run."""
        import asyncio
        from api.v1.endpoints.ws import run_log_manager, broadcast_run_log

        loop = asyncio.new_event_loop()

        # Create a mock websocket
        class MockWS:
            def __init__(self):
                self.messages = []
                self._job = None
                self._run = None

            async def send_json(self, msg):
                self.messages.append(msg)

        mock = MockWS()

        # Manually add to run_connections
        run_log_manager._run_connections["test-run"] = {mock}
        run_log_manager._connection_run[mock] = "test-run"

        # Broadcast
        loop.run_until_complete(broadcast_run_log("test-run", {
            "id": "evt-1",
            "message": "hello",
            "eventType": "log",
        }))

        assert len(mock.messages) == 1
        assert mock.messages[0]["type"] == "run_log"
        assert mock.messages[0]["run_id"] == "test-run"
        assert mock.messages[0]["event"]["message"] == "hello"

        # Cleanup
        run_log_manager.disconnect(mock)
        loop.close()

    def test_broadcast_run_log_no_subscribers(self):
        """Broadcasting to a run with no subscribers should be a no-op."""
        import asyncio
        from api.v1.endpoints.ws import broadcast_run_log

        loop = asyncio.new_event_loop()
        # Should not raise
        loop.run_until_complete(broadcast_run_log("nonexistent-run", {"test": True}))
        loop.close()
