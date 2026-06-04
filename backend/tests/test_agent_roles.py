"""Tests for Agent Roles — role-based dispatch and capability matching.

Covers:
- AgentRole constants and validation
- Role-based claim filtering (claim_next_run respects capabilities)
- Run with no required_role claimable by any worker
- Run with required_role only claimable by matching worker
- Roles API endpoint
- ECC dispatch with required_role
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from core.runtime.orchestrator import AgentRole


# ---------------------------------------------------------------------------
# AgentRole constants
# ---------------------------------------------------------------------------

class TestAgentRole:
    def test_all_roles_defined(self):
        assert len(AgentRole.ALL) == 7
        assert AgentRole.SAFE_RUNNER in AgentRole.ALL
        assert AgentRole.BACKEND_DEV in AgentRole.ALL
        assert AgentRole.FRONTEND_DEV in AgentRole.ALL
        assert AgentRole.CODE_REVIEWER in AgentRole.ALL

    def test_is_valid_known_role(self):
        assert AgentRole.is_valid("backend-dev") is True
        assert AgentRole.is_valid("safe-runner") is True
        assert AgentRole.is_valid("qa") is True

    def test_is_valid_unknown_role(self):
        assert AgentRole.is_valid("unknown-role") is False
        assert AgentRole.is_valid("") is False


# ---------------------------------------------------------------------------
# Role-based claim matching (integration-style with mocked DB)
# ---------------------------------------------------------------------------

class TestRoleBasedClaim:
    @pytest.mark.asyncio
    async def test_claim_no_role_required(self):
        """A run with required_role=None can be claimed by any worker."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["safe-runner"]}
        fake_run = {"id": "run-1", "requiredRole": None, "status": "pending"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=[fake_run])), \
             patch.object(repo, "update_run_status", AsyncMock(return_value={**fake_run, "status": "claimed"})), \
             patch.object(repo, "update_worker_status", AsyncMock()), \
             patch.object(repo, "append_run_event", AsyncMock()):

            result = await claim_next_run("w1", "board-default")

        assert result is not None
        assert result["id"] == "run-1"

    @pytest.mark.asyncio
    async def test_claim_matching_role(self):
        """A worker with the required role can claim the run."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["backend-dev", "code-reviewer"]}
        fake_run = {"id": "run-2", "requiredRole": "backend-dev", "status": "pending"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=[fake_run])), \
             patch.object(repo, "update_run_status", AsyncMock(return_value={**fake_run, "status": "claimed"})), \
             patch.object(repo, "update_worker_status", AsyncMock()), \
             patch.object(repo, "append_run_event", AsyncMock()):

            result = await claim_next_run("w1", "board-default")

        assert result is not None
        assert result["id"] == "run-2"

    @pytest.mark.asyncio
    async def test_claim_role_mismatch(self):
        """A worker without the required role cannot claim the run."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["frontend-dev"]}
        fake_run = {"id": "run-3", "requiredRole": "backend-dev", "status": "pending"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=[fake_run])), \
             patch.object(repo, "update_run_status", AsyncMock()) as mock_update:

            result = await claim_next_run("w1", "board-default")

        assert result is None
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_skips_mismatched_runs(self):
        """Worker skips runs it can't claim and claims the first matching one."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["frontend-dev"]}
        runs = [
            {"id": "run-a", "requiredRole": "backend-dev", "status": "pending"},
            {"id": "run-b", "requiredRole": "frontend-dev", "status": "pending"},
            {"id": "run-c", "requiredRole": "code-reviewer", "status": "pending"},
        ]

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=runs)), \
             patch.object(repo, "update_run_status", AsyncMock(return_value={**runs[1], "status": "claimed"})), \
             patch.object(repo, "update_worker_status", AsyncMock()), \
             patch.object(repo, "append_run_event", AsyncMock()):

            result = await claim_next_run("w1", "board-default")

        assert result is not None
        assert result["id"] == "run-b"  # skipped run-a, claimed run-b

    @pytest.mark.asyncio
    async def test_claim_no_matching_runs(self):
        """Returns None when no runs match the worker's capabilities."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["safe-runner"]}
        runs = [
            {"id": "run-a", "requiredRole": "backend-dev", "status": "pending"},
            {"id": "run-b", "requiredRole": "frontend-dev", "status": "pending"},
        ]

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=runs)), \
             patch.object(repo, "update_run_status", AsyncMock()) as mock_update:

            result = await claim_next_run("w1", "board-default")

        assert result is None
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_empty_capabilities(self):
        """Worker with empty capabilities can only claim runs with no required_role."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": []}
        runs = [
            {"id": "run-a", "requiredRole": "backend-dev", "status": "pending"},
            {"id": "run-b", "requiredRole": None, "status": "pending"},
        ]

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "list_runs_by_board", AsyncMock(return_value=runs)), \
             patch.object(repo, "update_run_status", AsyncMock(return_value={**runs[1], "status": "claimed"})), \
             patch.object(repo, "update_worker_status", AsyncMock()), \
             patch.object(repo, "append_run_event", AsyncMock()):

            result = await claim_next_run("w1", "board-default")

        assert result is not None
        assert result["id"] == "run-b"  # skipped run-a, claimed run-b


# ---------------------------------------------------------------------------
# create_run_for_dispatch with required_role
# ---------------------------------------------------------------------------

class TestCreateRunWithRole:
    @pytest.mark.asyncio
    async def test_create_run_with_role(self):
        """create_run_for_dispatch passes required_role to repo."""
        from core.runtime.orchestrator import create_run_for_dispatch
        from db import repository as repo

        mock_create = AsyncMock(return_value={
            "id": "run-new", "requiredRole": "backend-dev", "status": "pending",
        })

        with patch.object(repo, "create_run", mock_create):
            result = await create_run_for_dispatch(
                issue_id="100",
                issue_key="DEV-100",
                command="test",
                required_role="backend-dev",
            )

        assert result["requiredRole"] == "backend-dev"
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["required_role"] == "backend-dev"

    @pytest.mark.asyncio
    async def test_create_run_without_role(self):
        """create_run_for_dispatch with no role sets required_role=None."""
        from core.runtime.orchestrator import create_run_for_dispatch
        from db import repository as repo

        mock_create = AsyncMock(return_value={
            "id": "run-new", "requiredRole": None, "status": "pending",
        })

        with patch.object(repo, "create_run", mock_create):
            result = await create_run_for_dispatch(
                issue_id="100",
                issue_key="DEV-100",
                command="test",
            )

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["required_role"] is None


# ---------------------------------------------------------------------------
# Roles API endpoint
# ---------------------------------------------------------------------------

class TestRolesAPI:
    def _get_api_client(self):
        """Create a test client with isolated DB."""
        import os
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")

        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from db import database, repository as repo
        from db.models import Base
        from fastapi.testclient import TestClient
        import main

        import tempfile
        import asyncio

        db_path = tempfile.mktemp(suffix=".db")
        new_url = f"sqlite+aiosqlite:///{db_path}"
        new_engine = create_async_engine(new_url, echo=False)
        new_sessionmaker = async_sessionmaker(
            new_engine, class_=AsyncSession, expire_on_commit=False
        )

        # Patch database module
        database.engine = new_engine
        database.AsyncSessionLocal = new_sessionmaker
        database._db_initialized = False
        database.DATABASE_URL = new_url

        async def _init():
            pass
        database.ensure_db_init = _init

        # Create tables
        async def _init_db():
            async with new_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_init_db())
        database._db_initialized = True

        client = TestClient(main.app)

        # Cleanup
        import atexit
        def cleanup():
            loop.run_until_complete(new_engine.dispose())
            loop.close()
            try:
                os.unlink(db_path)
            except OSError:
                pass

        return client, cleanup

    def test_list_roles(self):
        client, cleanup = self._get_api_client()
        try:
            resp = client.get("/api/v1/runtime/roles")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 7
            role_ids = [r["id"] for r in data["roles"]]
            assert "safe-runner" in role_ids
            assert "backend-dev" in role_ids
            assert "frontend-dev" in role_ids
            assert "code-reviewer" in role_ids
        finally:
            cleanup()
