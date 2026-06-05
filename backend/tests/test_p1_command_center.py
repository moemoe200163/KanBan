import pytest
import asyncio
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select as sa_select

import main
from db import database as db_module
from db import repository as repo
from db.models import Base, User as UserModel

client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB for command center tests."""
    db_path = tmp_path / "test_cc.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)
    monkeypatch.delenv("E2E", raising=False)

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()

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
    new_engine.sync_engine.dispose()


def _dispatch(issue_id: str, issue_key: str, profile: str = "frontend", headers: dict = None) -> str:
    r = client.post(
        "/api/v1/ecc/dispatch",
        json={
            "issue_id": issue_id,
            "issue_key": issue_key,
            "command": f"/loop-start --profile={profile}",
            "profile": profile,
            "harness": "claude-code",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_jobs_filters_by_status(fresh_db):
    job_id = _dispatch("p1-filter", "DEV-P1-FILTER", headers=fresh_db)
    import time; time.sleep(1)
    r = client.get("/api/v1/ecc/jobs", params={"status": "review_required"})
    assert r.status_code == 200
    body = r.json()
    ids = [j["id"] for j in body["jobs"]]
    assert job_id in ids
    for job in body["jobs"]:
        assert job["status"] == "review_required"


def test_retry_creates_new_job_with_same_payload(fresh_db):
    original = _dispatch("p1-retry-ok", "DEV-P1-RETRY-OK", profile="backend", headers=fresh_db)
    # Move original to a retryable terminal state
    client.patch(
        f"/api/v1/ecc/jobs/{original}",
        json={"status": "failed", "message": "test seeded failure"},
        headers=fresh_db,
    )
    r = client.post(f"/api/v1/ecc/jobs/{original}/retry", headers=fresh_db)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] != original
    assert body["issue_id"] == "p1-retry-ok"
    assert body["issue_key"] == "DEV-P1-RETRY-OK"
    assert body["profile"] == "backend"
    assert body["status"] == "queued"
    assert any(e["status"] == "queued" for e in body["events"])


def test_retry_rejects_non_terminal_job(fresh_db):
    job_id = _dispatch("p1-retry-skip", "DEV-P1-RETRY-SKIP", headers=fresh_db)
    # The safe runner may have already advanced the job to "review_required"
    # (a retryable state). Force a deterministic non-retryable state so the
    # 409 branch is exercised reliably.
    client.patch(
        f"/api/v1/ecc/jobs/{job_id}",
        json={"status": "running", "message": "test forcing non-terminal state"},
        headers=fresh_db,
    )
    r = client.post(f"/api/v1/ecc/jobs/{job_id}/retry", headers=fresh_db)
    assert r.status_code == 409
    assert "retry" in r.json()["detail"].lower()


def test_retry_rejects_missing_job(fresh_db):
    r = client.post("/api/v1/ecc/jobs/ecc_does_not_exist/retry", headers=fresh_db)
    assert r.status_code == 404


def test_ws_anonymous_connect_in_dev_mode(fresh_db):
    # The test env should have ALLOW_ANONYMOUS_WS unset OR "true" by default.
    # We probe via the WS endpoint by reading the env gate and asserting the
    # 4001 close is NOT triggered for an unauthenticated connection.
    with client.websocket_connect("/ws/ecc/jobs?token=dev-anon") as ws:
        # If we got here, auth was bypassed.
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg["type"] == "pong"


@pytest.mark.asyncio
async def test_dispatch_broadcasts_job_update_via_ws(fresh_db):
    """Dispatching a job triggers _broadcast_job_update via _execute_safe_runner.

    TestClient's synchronous WS blocks the event loop so background tasks
    never fire inside ``websocket_connect``.  We work around this by:
      1. Dispatching via an async ASGI client (background task actually runs).
      2. Waiting for the runner to complete (job → review_required).
      3. Calling the broadcast bridge with a mock WS to verify the payload.
    """
    import httpx
    from unittest.mock import AsyncMock
    from api.v1.endpoints import ecc, ws

    # --- Step 1: dispatch via async client so the background task fires ---
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as ac:
        r = await ac.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "p1-ws-broadcast",
                "issue_key": "DEV-P1-WS-BROADCAST",
                "command": "/loop-start --profile=frontend",
                "profile": "frontend",
                "harness": "claude-code",
            },
            headers=fresh_db,
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]

    # --- Step 2: wait for the safe runner to finish ---
    await asyncio.sleep(0.5)

    job = ecc._jobs.get(job_id)
    assert job is not None, "job should exist in memory after dispatch"
    assert job.status == "review_required", (
        f"safe runner should have advanced to review_required, got {job.status}"
    )

    # --- Step 3: verify broadcast payload via mock WS ---
    mock_ws = AsyncMock()
    original_mgr = ws.job_manager
    try:
        ws.job_manager._job_connections[job_id] = {mock_ws}
        await ecc._broadcast_job_update(job_id, job.model_dump())
    finally:
        ws.job_manager._job_connections.pop(job_id, None)
        ws.job_manager = original_mgr

    mock_ws.send_json.assert_called_once()
    payload = mock_ws.send_json.call_args[0][0]
    assert payload["type"] == "job_update"
    assert payload["job"]["id"] == job_id
    assert payload["job"]["status"] == "review_required"
