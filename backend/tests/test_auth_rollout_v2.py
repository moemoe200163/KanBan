"""Tests for full auth rollout — verify write endpoints require auth."""
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
    """Fresh SQLite DB with a test user (default member role)."""
    db_path = tmp_path / "test_auth_rollout_v2.db"
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
            pwd_hash, _ = hash_password("test_pass_123")
            session.add(UserModel(
                id="user_rollout_v2_1",
                username="auth_rollout_test_user",
                password_hash=pwd_hash,
                role="member",
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
        "username": "auth_rollout_test_user",
        "password": "test_pass_123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Write endpoints require auth (expect 401 without token)
# ---------------------------------------------------------------------------

class TestWriteEndpointsRequireAuth:
    """Verify write endpoints return 401 without token."""

    def test_github_pr_create_401(self, fresh_db):
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test", "body": "b", "head": "h",
        })
        assert resp.status_code == 401

    def test_github_labels_401(self, fresh_db):
        resp = client.post("/api/v1/github/issues/DEV-001/labels", json={
            "labels": ["bug"],
        })
        assert resp.status_code == 401

    def test_github_check_run_401(self, fresh_db):
        resp = client.post("/api/v1/github/check-run", json={
            "head_sha": "abc", "name": "CI", "status": "completed",
        })
        assert resp.status_code == 401

    def test_ecc_jobs_patch_401(self, fresh_db):
        resp = client.patch("/api/v1/ecc/jobs/nonexistent")
        assert resp.status_code == 401

    def test_session_resume_401(self, fresh_db):
        resp = client.post("/api/v1/runtime/sessions/nonexistent/resume")
        assert resp.status_code == 401

    def test_session_delete_401(self, fresh_db):
        resp = client.delete("/api/v1/runtime/sessions/nonexistent")
        assert resp.status_code == 401

    def test_agents_dispatch_401(self, fresh_db):
        resp = client.post("/api/v1/agents/dispatch", json={})
        assert resp.status_code == 401

    def test_agents_terminate_401(self, fresh_db):
        resp = client.post("/api/v1/agents/terminate", json={})
        assert resp.status_code == 401

    def test_quality_gate_verify_401(self, fresh_db):
        resp = client.post("/api/v1/quality/gate/verify", json={})
        assert resp.status_code == 401

    def test_autopilot_status_post_401(self, fresh_db):
        resp = client.post("/api/v1/autopilot/status", json={"enabled": True})
        assert resp.status_code == 401

    def test_autopilot_tick_401(self, fresh_db):
        resp = client.post("/api/v1/autopilot/tick")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Read endpoints remain accessible without auth
# ---------------------------------------------------------------------------

class TestReadEndpointsRemainPublic:
    """Verify read endpoints still work without auth."""

    def test_board_public(self, fresh_db):
        resp = client.get("/api/v1/board")
        assert resp.status_code == 200

    def test_ecc_jobs_public(self, fresh_db):
        resp = client.get("/api/v1/ecc/jobs")
        assert resp.status_code == 200

    def test_health_public(self, fresh_db):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_register_public(self, fresh_db):
        resp = client.post("/api/v1/auth/register", json={
            "username": "pub_test_v2", "password": "pub_pass_12345",
        })
        # 201 or 400 (already exists) — both mean it's public
        assert resp.status_code in (201, 400)

    def test_auth_token_public(self, fresh_db):
        resp = client.post("/api/v1/auth/token", json={
            "username": "nobody", "password": "wrong",
        })
        # 401 means the endpoint is reachable (public)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Write endpoints with valid token (should not return 401)
# ---------------------------------------------------------------------------

class TestWriteEndpointsWithToken:
    """Verify write endpoints accept valid token."""

    def test_github_pr_create_with_token(self, fresh_db):
        token = _get_token()
        resp = client.post("/api/v1/github/pr/create",
            json={"title": "t", "body": "b", "head": "h"},
            headers=_auth_header(token),
        )
        # 503 = GitHub not configured (expected in test), but NOT 401
        assert resp.status_code != 401

    def test_github_check_run_with_token(self, fresh_db):
        token = _get_token()
        resp = client.post("/api/v1/github/check-run",
            json={"head_sha": "abc", "name": "CI", "status": "completed"},
            headers=_auth_header(token),
        )
        assert resp.status_code != 401
