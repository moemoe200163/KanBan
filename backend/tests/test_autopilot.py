"""Tests for the Autopilot scheduler."""
import pytest
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel, IssueHandoff, User as UserModel


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with an issue and handoffs."""
    db_path = tmp_path / "test_autopilot.db"
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

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            # Create a test issue
            session.add(IssueModel(
                id="issue-ap-1",
                key="DEV-700",
                title="autopilot test issue",
                description="",
                status="in_progress",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            # Handoff in "accepted" status to a non-human lane (frontend)
            session.add(IssueHandoff(
                id="h_ap_accepted",
                board_id="board-default",
                issue_id="issue-ap-1",
                from_lane="triage",
                to_lane="frontend",
                status="accepted",
                payload={},
                created_by="human",
                created_at=now,
                updated_at=now,
            ))
            # Handoff in "accepted" status to a human-required lane (product)
            session.add(IssueHandoff(
                id="h_ap_human",
                board_id="board-default",
                issue_id="issue-ap-1",
                from_lane="triage",
                to_lane="product",
                status="accepted",
                payload={},
                created_by="human",
                created_at=now,
                updated_at=now,
            ))
            # Handoff in "in_progress" that has timed out
            session.add(IssueHandoff(
                id="h_ap_timeout",
                board_id="board-default",
                issue_id="issue-ap-1",
                from_lane="triage",
                to_lane="frontend",
                status="in_progress",
                payload={},
                created_by="human",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ))
            # Create an admin user for auth-gated endpoints
            from api.v1.endpoints.auth import hash_password
            pwd_hash, _ = hash_password("admin_pass_123")
            session.add(UserModel(
                id="user_ap_admin",
                username="ap_admin_test",
                password_hash=pwd_hash,
                role="admin",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


def _get_admin_token() -> str:
    resp = client.post("/api/v1/auth/token", json={
        "username": "ap_admin_test",
        "password": "admin_pass_123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Autopilot tick — auto-dispatch
# ---------------------------------------------------------------------------

def test_tick_dispatches_accepted_non_human_lane(fresh_db):
    """Accepted handoff to frontend (no human approval) should be dispatched."""
    from core.kanban_protocol.autopilot import scheduler

    result = asyncio_run(scheduler.tick())
    assert result["dispatched"] >= 1
    assert result["errors"] == 0

    # Verify the handoff was dispatched (status changed to in_progress)
    import asyncio
    from db import repository as repo
    h = asyncio.run(repo.get_issue_handoff("h_ap_accepted"))
    assert h["status"] == "in_progress"
    assert h["dispatchedBy"] == "autopilot"


def test_tick_skips_human_required_lane(fresh_db):
    """Accepted handoff to product (human approval required) should be skipped."""
    from core.kanban_protocol.autopilot import scheduler

    result = asyncio_run(scheduler.tick())
    assert result["skipped"] >= 1

    # Verify the handoff was NOT dispatched
    import asyncio
    from db import repository as repo
    h = asyncio.run(repo.get_issue_handoff("h_ap_human"))
    assert h["status"] == "accepted"  # unchanged


# ---------------------------------------------------------------------------
# Autopilot tick — timeout enforcement
# ---------------------------------------------------------------------------

def test_tick_retries_timed_out_handoff(fresh_db):
    """In_progress handoff exceeding lane timeout should be retried (frontend has retry_policy='fixed')."""
    from core.kanban_protocol.autopilot import scheduler

    # The h_ap_timeout handoff is 2 hours old; frontend lane timeout is 1800s (30min).
    result = asyncio_run(scheduler.tick())
    assert result["timedOut"] >= 1

    import asyncio
    from db import repository as repo
    # The original handoff should be cancelled (retry path).
    h = asyncio.run(repo.get_issue_handoff("h_ap_timeout"))
    assert h["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

def test_status_endpoint(fresh_db):
    resp = client.get("/api/v1/autopilot/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "enabled" in body
    assert "running" in body
    assert "tickInterval" in body
    assert "totalDispatched" in body


def test_enable_disable_via_status(fresh_db):
    token = _get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    # Disable
    resp = client.post("/api/v1/autopilot/status", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Enable
    resp = client.post("/api/v1/autopilot/status", json={"enabled": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


# ---------------------------------------------------------------------------
# Tick endpoint
# ---------------------------------------------------------------------------

def test_tick_endpoint(fresh_db):
    token = _get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/autopilot/tick", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "result" in body
    assert "dispatched" in body["result"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import asyncio


def asyncio_run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
