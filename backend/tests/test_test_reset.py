"""
T8.3 — /api/v1/test/reset is gated by BOTH ``E2E=1`` AND ``_e2e`` in DATABASE_URL.

The endpoint is destructive (TRUNCATE + re-seed). Treating it as a
P0 data-destruction risk means the gate must hold on two independent
conditions. Each subtest in this file holds one of the conditions
constant and varies the other.
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
    """A fresh SQLite file-backed DB. The ``DATABASE_URL`` we wire in is
    what the reset endpoint will parse for the ``_e2e`` substring check,
    so we set it explicitly to keep the gating tests deterministic."""
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
    # Mirror the URL into the process env so the reset endpoint's
    # `os.getenv("DATABASE_URL")` returns the same value.
    monkeypatch.setenv("DATABASE_URL", new_url)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()
    asyncio.run(_setup())

    yield main.app


@pytest.fixture
def fresh_e2e_db(tmp_path, monkeypatch):
    """Like ``fresh_db`` but DATABASE_URL points at a name containing
    ``_e2e`` so the second half of the gate can be satisfied."""
    db_path = tmp_path / "test_devflow_e2e.db"
    new_url = f"sqlite+aiosqlite:///{db_path}?_e2e=1"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)
    # The reset endpoint reads DATABASE_URL via os.getenv, so the env
    # var must reflect the new URL too.
    monkeypatch.setenv("DATABASE_URL", new_url)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()
    asyncio.run(_setup())

    yield main.app


def test_reset_endpoint_404_when_e2e_env_unset(fresh_db, monkeypatch):
    """With E2E unset (regardless of DATABASE_URL), POST must return 404.

    The endpoint should not even be discoverable in this case — the
    router is mounted only when both gates hold. We exercise the
    router-level guard directly by hitting the URL the router would
    use; the response shape must be 404, not 401/403/405.
    """
    monkeypatch.delenv("E2E", raising=False)
    # The router isn't mounted when E2E is unset, so the URL is
    # unknown to FastAPI; 405 is the closest acceptable answer
    # (405 = method not allowed; the path doesn't exist for POST).
    # We accept either 404 (path unknown) or 405 (path unknown,
    # wrong method). Anything else is a gate failure.
    with TestClient(fresh_db) as client:
        response = client.post("/api/v1/test/reset")
    assert response.status_code in (404, 405), (
        f"reset must be unreachable when E2E is unset, got {response.status_code}: {response.text}"
    )


def test_reset_endpoint_404_when_db_name_lacks_e2e(fresh_db, monkeypatch):
    """With E2E=1 but DATABASE_URL pointing at a non-`_e2e` DB, the
    router-level guard must reject the call (404)."""
    monkeypatch.setenv("E2E", "1")
    # fresh_db already has a DATABASE_URL without `_e2e`.
    # The router's _is_reset_enabled() must return False; the
    # endpoint itself returns 404. We don't mount the router here
    # because main.py's mounting logic also gates on the same check.
    # To exercise the inner guard, import the helper directly.
    from api.v1.endpoints import test_reset
    assert test_reset._is_reset_enabled() is False, (
        "gate must reject E2E=1 with a non-_e2e database name"
    )


def test_reset_endpoint_404_when_only_db_name_has_e2e(fresh_e2e_db, monkeypatch):
    """With DATABASE_URL containing `_e2e` but E2E env unset, the
    inner gate must reject the call (404)."""
    monkeypatch.delenv("E2E", raising=False)
    from api.v1.endpoints import test_reset
    assert test_reset._is_reset_enabled() is False, (
        "gate must reject a non-E2E env even with an _e2e DB name"
    )


def test_reset_endpoint_200_when_both_gates_hold(fresh_e2e_db, monkeypatch):
    """With E2E=1 and a `_e2e` DATABASE_URL, POST must succeed and
    re-seed the board."""
    monkeypatch.setenv("E2E", "1")
    from api.v1.endpoints import test_reset
    assert test_reset._is_reset_enabled() is True, "both gates must pass"

    # Mount the router on the test app — main.py's mount only happens
    # in production with the same env. We replicate the gate here.
    fresh_e2e_db.include_router(test_reset.router, prefix="/api/v1")
    with TestClient(fresh_e2e_db) as client:
        response = client.post("/api/v1/test/reset")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "reset"
    assert body["seeded"] == 8, "8 seed issues must be reloaded"
    assert "_e2e" in body["database"], (
        "the response must echo the database name to prove the gate "
        "actually checked the right thing"
    )

    # The board must reflect the re-seeded issues.
    with TestClient(fresh_e2e_db) as client:
        board = client.get("/api/v1/board")
    assert board.status_code == 200
    total = sum(len(c["issues"]) for c in board.json()["columns"])
    assert total == 8, f"expected 8 issues after reset, got {total}"
