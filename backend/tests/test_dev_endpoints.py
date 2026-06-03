"""
Tests for dev management endpoints: GET /stats and POST /dev/reset.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import main
from db import database as db_module
from db import repository as repo
from db.models import Base


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB for dev endpoint tests."""
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
    monkeypatch.setenv("DATABASE_URL", new_url)
    # Ensure E2E is not set so dev mode is detected via "no DATABASE_URL"
    # ... but we DO set DATABASE_URL for the DB, so we need to unset it
    # for the dev mode check. The dev endpoint checks os.getenv("DATABASE_URL").
    # We'll handle this per-test.
    monkeypatch.delenv("E2E", raising=False)

    import asyncio

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()

    asyncio.run(_setup())

    # Mount the dev router (always mounted in production)
    from api.v1.endpoints import dev

    main.app.include_router(dev.router, prefix="/api/v1")
    yield main.app


def test_stats_returns_counts(fresh_db, monkeypatch):
    """GET /api/v1/dev/stats must return record counts for key tables."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(fresh_db) as client:
        response = client.get("/api/v1/dev/stats")
    assert response.status_code == 200
    body = response.json()
    counts = body["counts"]
    assert counts["issues"] == 8, "seed should create 8 issues"
    assert counts["ecc_jobs"] == 0, "no jobs at startup"
    assert counts["issue_handoffs"] == 0


def test_dev_reset_full_cleanup(fresh_db, monkeypatch):
    """POST /api/v1/dev/reset must clean all tables and re-seed."""
    # Unset DATABASE_URL so _is_dev_mode() returns True (default SQLite path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(fresh_db) as client:
        response = client.post("/api/v1/dev/reset")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "reset"
    assert body["seeded"] == 8
    assert body["deleted"]["issues"] == 8
    assert body["total_deleted"] >= 8, "at least 8 issues deleted; may include audit logs"


def test_dev_reset_404_in_production(monkeypatch):
    """POST /api/v1/dev/reset must return 404 when DATABASE_URL is set (prod mode)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/prod_db")
    monkeypatch.delenv("E2E", raising=False)
    from api.v1.endpoints import dev

    assert dev._is_dev_mode() is False


def test_stats_404_in_production(fresh_db, monkeypatch):
    """GET /api/v1/dev/stats must return 404 when DATABASE_URL is set (prod mode)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/prod_db")
    monkeypatch.delenv("E2E", raising=False)
    with TestClient(fresh_db) as client:
        response = client.get("/api/v1/dev/stats")
    assert response.status_code == 404


def test_dev_reset_works_in_e2e_mode(monkeypatch):
    """POST /api/v1/dev/reset must work when E2E=1."""
    monkeypatch.setenv("E2E", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///tmp/test_e2e.db")
    from api.v1.endpoints import dev

    assert dev._is_dev_mode() is True
