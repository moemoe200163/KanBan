"""Tests for GET /api/v1/lanes — reads from agent_roles DB table."""
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db import database, repository as repo
from db.models import Base


@pytest.fixture()
def fresh_db():
    """Create a temporary SQLite DB, seed roles, and yield a TestClient.

    This avoids cross-test contamination from the shared _db_initialized
    flag and ensures the agent_roles table is populated.
    """
    import main

    db_path = tempfile.mktemp(suffix=".db")
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Patch database module so all repo calls use the fresh DB
    old_engine = database.engine
    old_sessionmaker = database.AsyncSessionLocal
    old_initialized = database._db_initialized
    old_url = database.DATABASE_URL

    database.engine = new_engine
    database.AsyncSessionLocal = new_sessionmaker
    database._db_initialized = False
    database.DATABASE_URL = new_url

    # Create tables and seed roles synchronously via asyncio
    import asyncio

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        database._db_initialized = True
        await repo.seed_default_roles()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup())

    client = TestClient(main.app)
    yield client

    # Cleanup
    async def _teardown():
        await new_engine.dispose()

    loop.run_until_complete(_teardown())
    loop.close()

    # Restore original database state
    database.engine = old_engine
    database.AsyncSessionLocal = old_sessionmaker
    database._db_initialized = old_initialized
    database.DATABASE_URL = old_url

    import os
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_get_lanes_returns_eight_lanes(fresh_db):
    response = fresh_db.get("/api/v1/lanes")
    assert response.status_code == 200
    body = response.json()
    assert "lanes" in body
    keys = {lane["key"] for lane in body["lanes"]}
    assert keys == {
        "triage", "product", "architect", "frontend",
        "backend", "qa", "review", "delivery",
    }
    # every lane exposes the fields the Lane Matrix needs
    for lane in body["lanes"]:
        assert "displayName" in lane
        assert "defaultProvider" in lane
        assert "defaultModel" in lane
        assert "requiredCompletionFields" in lane
        assert "humanApprovalRequired" in lane
