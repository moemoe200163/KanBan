"""
Regression tests for the E2E database schema fix.

Before this change, ``init_db`` used ``create_all(checkfirst=True)`` for
SQLite databases. When a test database (``*_e2e.db``) was reused from a
previous run with a stale schema, new columns like ``issues.board_id``
were silently skipped, causing the seed function to fail with
``no such column: issues.board_id``.

The fix drops and recreates all tables on init for E2E SQLite targets.
These tests pin that behavior so the bug does not regress.
"""
import os
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database as db_module
from db.models import Base


def _new_e2e_url(tmp_path, name: str = "devflow_e2e.db") -> str:
    return f"sqlite+aiosqlite:///{tmp_path / name}"


@pytest.fixture
def fresh_e2e_engine(tmp_path, monkeypatch):
    """Point the module-level engine at a fresh E2E SQLite file."""
    db_path = tmp_path / "devflow_e2e.db"
    new_url = _new_e2e_url(tmp_path)

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)
    monkeypatch.setenv("E2E", "1")
    # E2E gate is checked against the URL, not just the env var.
    monkeypatch.setenv("DATABASE_URL", new_url)
    return new_engine, new_url


@pytest.mark.asyncio
async def test_e2e_init_drops_and_recreates_stale_schema(fresh_e2e_engine, tmp_path):
    """A pre-existing E2E db with an old schema must be wiped and rebuilt."""
    engine, new_url = fresh_e2e_engine

    # Plant a "stale" table: same name as ``issues`` but missing the
    # board_id column that the current model requires.
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: sync_conn.exec_driver_sql(
                "CREATE TABLE issues ("
                " id VARCHAR(64) PRIMARY KEY,"
                " key VARCHAR(32) NOT NULL,"
                " title VARCHAR(512) NOT NULL,"
                " status VARCHAR(32) NOT NULL DEFAULT 'backlog')"
            )
        )
    # The current init_db path should wipe this and rebuild with
    # the full column set, including board_id.
    await db_module.init_db()

    async with engine.begin() as conn:
        rows = (await conn.execute(text("PRAGMA table_info(issues)"))).fetchall()
    column_names = {row[1] for row in rows}
    assert "board_id" in column_names, (
        "E2E init_db must rebuild the issues table with the current model "
        f"columns; got: {sorted(column_names)}"
    )


@pytest.mark.asyncio
async def test_e2e_init_runs_seed_cleanly_after_rebuild(fresh_e2e_engine):
    """After init, the seed function should find 8 fresh issues."""
    engine, new_url = fresh_e2e_engine

    await db_module.init_db()

    from db import repository as repo
    seeded = await repo.seed_if_empty()
    issues = await repo.list_issues()
    assert seeded == 8, f"Expected 8 seed issues, got {seeded}"
    assert len(issues) == 8


def test_e2e_url_detection_only_for_e2e_dbs(tmp_path, monkeypatch):
    """Sanity-check the gating function used by init_db."""
    monkeypatch.setenv("E2E", "0")
    monkeypatch.setattr(db_module, "DATABASE_URL", _new_e2e_url(tmp_path, "dev.db"), raising=False)
    assert db_module._is_e2e_sqlite_target() is False

    monkeypatch.setenv("E2E", "1")
    monkeypatch.setattr(db_module, "DATABASE_URL", _new_e2e_url(tmp_path, "dev_e2e.db"), raising=False)
    assert db_module._is_e2e_sqlite_target() is True

    monkeypatch.setenv("E2E", "1")
    monkeypatch.setattr(db_module, "DATABASE_URL", _new_e2e_url(tmp_path, "dev.db"), raising=False)
    assert db_module._is_e2e_sqlite_target() is False
