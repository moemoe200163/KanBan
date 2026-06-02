"""
T8.2 — /health/ready reports database=ok when DB is reachable, degraded when not.

The endpoint used to be theatre: it returned 200 with a hardcoded
``{"api": "ok"}`` regardless of DB state. After the P0 fix, the endpoint
opens an ``AsyncSession`` and runs ``SELECT 1``; failure is reported as
``"database": "error: ..."`` and the HTTP status flips to 503.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base
from db import repository as repo


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file and reset tables."""
    db_path = tmp_path / "test_devflow.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()
    asyncio.run(_setup())

    yield main.app


def test_health_ready_reports_database_ok_when_db_reachable(fresh_db):
    """A healthy DB must produce 200 with ``database=ok``."""
    with TestClient(fresh_db) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["api"] == "ok"


def test_health_ready_reports_degraded_when_db_raises(fresh_db, monkeypatch):
    """When the session raises, the endpoint must return 503 and surface
    the error string in the ``database`` field."""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            raise RuntimeError("simulated DB outage")

    def _fake_session_local():
        return _FakeSession()

    monkeypatch.setattr(db_module, "AsyncSessionLocal", _fake_session_local)

    with TestClient(fresh_db) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503, (
        "503 must be returned when the DB is unreachable so a load "
        "balancer can stop routing traffic to this pod"
    )
    body = response.json()
    assert body["status"] == "degraded"
    assert "simulated DB outage" in body["checks"]["database"]
