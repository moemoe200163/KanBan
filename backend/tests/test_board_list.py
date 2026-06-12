"""Tests for the multi-board selector backend plumbing.

Covers:
- ``repo.list_boards()`` groups by ``board_id`` and reports counts.
- The default board is always returned, even on an empty database.
- ``_board_display_name`` projects a readable label for known ids.
- ``GET /api/v1/boards`` requires auth and returns BoardSummary rows.
"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database as _db_module
from db import repository as repo
from db.models import Base


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file with all tables created."""
    db_path = tmp_path / "test_board_list.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(_db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(_db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(_db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(_db_module, "DATABASE_URL", new_url, raising=False)
    import asyncio

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _db_module._db_initialized = True
    asyncio.run(_setup())
    yield repo


# ---------------------------------------------------------------------------
# list_boards — repository
# ---------------------------------------------------------------------------

class TestListBoards:
    @pytest.mark.asyncio
    async def test_empty_db_returns_only_default(self, fresh_db):
        boards = await repo.list_boards()
        # On an empty DB we still surface the default so the selector
        # has something to render.
        assert len(boards) == 1
        assert boards[0]["id"] == "board-default"
        assert boards[0]["name"] == "Default"
        assert boards[0]["issueCount"] == 0

    @pytest.mark.asyncio
    async def test_groups_by_board_id_and_counts(self, fresh_db):
        await repo.upsert_issue({
            "id": "i-a1", "key": "A-001", "board_id": "board-a",
            "title": "A1", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i-a2", "key": "A-002", "board_id": "board-a",
            "title": "A2", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i-b1", "key": "B-001", "board_id": "board-b",
            "title": "B1", "status": "backlog", "priority": "medium",
        })
        boards = await repo.list_boards()
        by_id = {b["id"]: b for b in boards}
        assert by_id["board-a"]["issueCount"] == 2
        assert by_id["board-b"]["issueCount"] == 1
        # Sorted by issue count desc, so board-a must come first.
        assert boards[0]["id"] == "board-a"

    @pytest.mark.asyncio
    async def test_default_board_always_present_even_when_empty(self, fresh_db):
        await repo.upsert_issue({
            "id": "i-x1", "key": "X-001", "board_id": "board-x",
            "title": "X1", "status": "backlog", "priority": "medium",
        })
        boards = await repo.list_boards()
        ids = {b["id"] for b in boards}
        # The default is added even when it carries no issues.
        assert "board-default" in ids
        assert "board-x" in ids


# ---------------------------------------------------------------------------
# _board_display_name — pure helper
# ---------------------------------------------------------------------------

class TestBoardDisplayName:
    def test_well_known_ids_get_friendly_names(self):
        from db.repository import _board_display_name
        assert _board_display_name("board-default") == "Default"
        assert _board_display_name("board-dev") == "Dev"
        assert _board_display_name("board-staging") == "Staging"
        assert _board_display_name("board-demo") == "Demo"

    def test_unknown_board_prefix_is_humanised(self):
        from db.repository import _board_display_name
        # Strips the "board-" prefix and title-cases the remainder.
        assert _board_display_name("board-team-alpha") == "Team Alpha"
        # Without the prefix, the raw id is returned unchanged.
        assert _board_display_name("custom-tenant") == "custom-tenant"

    def test_empty_prefix_falls_back_to_raw_id(self):
        from db.repository import _board_display_name
        # Edge case: "board-" with no suffix should not crash and
        # should not produce an empty string.
        assert _board_display_name("board-") == "board-"


# ---------------------------------------------------------------------------
# GET /api/v1/boards — endpoint auth + shape
# ---------------------------------------------------------------------------

class TestBoardsEndpoint:
    @pytest.mark.asyncio
    async def test_requires_auth(self):
        # The endpoint must reject unauthenticated callers with 401
        # (or 403 — anything that isn't 200).  We invoke the FastAPI
        # app directly so we exercise the actual dependency.
        from fastapi import FastAPI
        from api.v1.endpoints.board import router as board_router
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(board_router, prefix="/api/v1")
        # Patch the repo so we don't need a live DB.
        with patch(
            "api.v1.endpoints.board.repo.list_boards",
            new=AsyncMock(return_value=[{
                "id": "board-default", "name": "Default", "issueCount": 0,
            }]),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/boards")
            # No auth header — must be rejected.
            assert resp.status_code in (401, 403), (
                f"Expected 401/403 without auth, got {resp.status_code}"
            )

    @pytest.mark.asyncio
    async def test_returns_summaries_when_authenticated(self):
        from fastapi import FastAPI
        from api.v1.endpoints.board import router as board_router
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(board_router, prefix="/api/v1")

        # Override the auth dependency to skip the real JWT check.
        from api.v1.endpoints.board import require_auth

        async def _fake_auth():
            return {"user_id": "u1", "username": "tester", "role": "admin"}

        app.dependency_overrides[require_auth] = _fake_auth

        with patch(
            "api.v1.endpoints.board.repo.list_boards",
            new=AsyncMock(return_value=[
                {"id": "board-default", "name": "Default", "issueCount": 3},
                {"id": "board-dev", "name": "Dev", "issueCount": 1},
            ]),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/boards")
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, list)
            assert {b["id"] for b in body} == {"board-default", "board-dev"}
            assert body[0]["issueCount"] == 3
            assert body[1]["name"] == "Dev"
