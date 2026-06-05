"""Tests for auth rollout — verifying auth is enforced on write endpoints."""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, User as UserModel


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with a test user."""
    db_path = tmp_path / "test_auth.db"
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
            from api.v1.endpoints.auth import hash_password
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
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


def _get_token() -> str:
    """Login and return a JWT token."""
    resp = client.post("/api/v1/auth/token", json={
        "username": "testuser",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Write endpoints require auth
# ---------------------------------------------------------------------------

def test_create_issue_requires_auth(fresh_db):
    """POST /issues without token → 401."""
    resp = client.post("/api/v1/issues", json={
        "title": "Test issue",
        "status": "backlog",
        "priority": "medium",
        "profile": "general",
    })
    assert resp.status_code == 401


def test_create_issue_with_auth(fresh_db):
    """POST /issues with valid token → 200."""
    token = _get_token()
    resp = client.post("/api/v1/issues", json={
        "title": "Test issue",
        "status": "backlog",
        "priority": "medium",
        "profile": "general",
    }, headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test issue"


def test_update_issue_status_requires_auth(fresh_db):
    """PUT /issues/{id}/status without token → 401."""
    # First create an issue (via direct DB insert to avoid auth)
    import asyncio
    from db import repository as repo
    asyncio.run(repo.upsert_issue({
        "id": "issue_auth_1",
        "key": "DEV-900",
        "title": "Auth test issue",
        "status": "backlog",
        "priority": "medium",
        "board_id": "board-default",
    }))

    resp = client.put("/api/v1/issues/issue_auth_1/status", json={
        "status": "in_progress",
    })
    assert resp.status_code == 401


def test_update_issue_status_with_auth(fresh_db):
    """PUT /issues/{id}/status with valid token → 200."""
    import asyncio
    from db import repository as repo
    asyncio.run(repo.upsert_issue({
        "id": "issue_auth_2",
        "key": "DEV-901",
        "title": "Auth test issue 2",
        "status": "backlog",
        "priority": "medium",
        "board_id": "board-default",
    }))

    token = _get_token()
    resp = client.put("/api/v1/issues/issue_auth_2/status", json={
        "status": "in_progress",
    }, headers=_auth_header(token))
    assert resp.status_code == 200


def test_ecc_dispatch_requires_auth(fresh_db):
    """POST /ecc/dispatch without token → 401."""
    resp = client.post("/api/v1/ecc/dispatch", json={
        "issue_id": "issue_1",
        "issue_key": "DEV-001",
        "command": "/loop-reset",
        "profile": "general",
        "harness": "safe-runner",
    })
    assert resp.status_code == 401


def test_ecc_dispatch_with_auth(fresh_db):
    """POST /ecc/dispatch with valid token → 200 or 404 (issue not found)."""
    token = _get_token()
    resp = client.post("/api/v1/ecc/dispatch", json={
        "issue_id": "issue_1",
        "issue_key": "DEV-001",
        "command": "/loop-reset",
        "profile": "general",
        "harness": "safe-runner",
    }, headers=_auth_header(token))
    # Will be 422 or similar because issue doesn't exist, but NOT 401
    assert resp.status_code != 401


def test_cancel_job_requires_auth(fresh_db):
    """POST /ecc/jobs/{id}/cancel without token → 401."""
    resp = client.post("/api/v1/ecc/jobs/fake_job_id/cancel")
    assert resp.status_code == 401


def test_retry_job_requires_auth(fresh_db):
    """POST /ecc/jobs/{id}/retry without token → 401."""
    resp = client.post("/api/v1/ecc/jobs/fake_job_id/retry")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Read endpoints remain accessible without auth
# ---------------------------------------------------------------------------

def test_board_accessible_without_auth(fresh_db):
    """GET /board without token → 200 (public read)."""
    resp = client.get("/api/v1/board")
    assert resp.status_code == 200


def test_list_issues_accessible_without_auth(fresh_db):
    """GET /issues without token → 200 (public read)."""
    resp = client.get("/api/v1/issues")
    assert resp.status_code == 200


def test_ecc_jobs_accessible_without_auth(fresh_db):
    """GET /ecc/jobs without token → 200 (public read)."""
    resp = client.get("/api/v1/ecc/jobs")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth endpoints themselves don't require auth
# ---------------------------------------------------------------------------

def test_register_works_without_auth(fresh_db):
    """POST /auth/register doesn't require existing auth."""
    resp = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "newpass1234",
    })
    assert resp.status_code == 201


def test_login_works_without_auth(fresh_db):
    """POST /auth/token doesn't require existing auth."""
    resp = client.post("/api/v1/auth/token", json={
        "username": "testuser",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_health_works_without_auth(fresh_db):
    """GET /health doesn't require auth."""
    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Invalid token
# ---------------------------------------------------------------------------

def test_invalid_token_rejected(fresh_db):
    """Write endpoint with invalid token → 401."""
    resp = client.post("/api/v1/issues", json={
        "title": "Should fail",
    }, headers={"Authorization": "Bearer invalid-token-here"})
    assert resp.status_code == 401
