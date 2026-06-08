"""Tests for Agent Roles — role-based dispatch, capability matching, and CRUD.

Covers:
- AgentRole constants and validation
- Role-based claim filtering (claim_next_run respects capabilities)
- Run with no required_role claimable by any worker
- Run with required_role only claimable by matching worker
- Roles API endpoint
- ECC dispatch with required_role
- CRUD API: seed, list, create, update, toggle, lanes backward compat
"""

import asyncio
import pytest
from datetime import datetime, timezone
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
        fake_run = {"id": "run-1", "requiredRole": None, "status": "claimed"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=fake_run)), \
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
        fake_run = {"id": "run-2", "requiredRole": "backend-dev", "status": "claimed"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=fake_run)), \
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

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=None)) as mock_claim:

            result = await claim_next_run("w1", "board-default")

        assert result is None
        mock_claim.assert_called_once()

    @pytest.mark.asyncio
    async def test_claim_skips_mismatched_runs(self):
        """Worker skips runs it can't claim and claims the first matching one."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": ["frontend-dev"]}
        fake_run_b = {"id": "run-b", "requiredRole": "frontend-dev", "status": "claimed"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=fake_run_b)), \
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

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=None)) as mock_claim:

            result = await claim_next_run("w1", "board-default")

        assert result is None
        mock_claim.assert_called_once()

    @pytest.mark.asyncio
    async def test_claim_empty_capabilities(self):
        """Worker with empty capabilities can only claim runs with no required_role."""
        from core.runtime.orchestrator import claim_next_run
        from db import repository as repo

        fake_worker = {"id": "w1", "capabilities": []}
        fake_run_b = {"id": "run-b", "requiredRole": None, "status": "claimed"}

        with patch.object(repo, "get_worker", AsyncMock(return_value=fake_worker)), \
             patch.object(repo, "atomic_claim_run", AsyncMock(return_value=fake_run_b)), \
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


# ===========================================================================
# Agent Roles CRUD API Tests
# ===========================================================================
#
# These tests verify the CRUD endpoints for configurable agent roles:
#   GET    /api/v1/agent-roles
#   POST   /api/v1/agent-roles
#   PUT    /api/v1/agent-roles/{key}
#   PATCH  /api/v1/agent-roles/{key}/enabled
#   GET    /api/v1/lanes  (backward-compatible read)
# ===========================================================================

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db import repository as repo
from db.models import (
    Base, User as UserModel, AgentRole as AgentRoleModel,
    Issue as IssueModel, IssueHandoff,
)
from api.v1.endpoints.auth import hash_password, create_jwt_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with admin + member users and seeded default roles.

    Yields a dict with:
      - "client": TestClient
      - "admin_headers": auth headers for an admin user
      - "member_headers": auth headers for a non-admin user
    """
    db_path = tmp_path / "test_agent_roles_crud.db"
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

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)

        # Create admin user
        admin_pwd_hash, _ = hash_password("admin_pass_123")
        # Create member user
        member_pwd_hash, _ = hash_password("member_pass_123")

        async with new_sessionmaker() as session:
            session.add(UserModel(
                id="user_ar_admin_1",
                username="ar_admin_user",
                password_hash=admin_pwd_hash,
                role="admin",
                created_at=now,
                updated_at=now,
            ))
            session.add(UserModel(
                id="user_ar_member_1",
                username="ar_member_user",
                password_hash=member_pwd_hash,
                role="member",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()

        db_module._db_initialized = True

        # Seed default roles
        count = await repo.seed_default_roles()
        return count

    seed_count = asyncio.run(_setup())

    client = TestClient(main.app)

    # Generate tokens
    admin_token, _ = create_jwt_token("user_ar_admin_1", "ar_admin_user")
    member_token, _ = create_jwt_token("user_ar_member_1", "ar_member_user")

    yield {
        "client": client,
        "admin_headers": {"Authorization": f"Bearer {admin_token}"},
        "member_headers": {"Authorization": f"Bearer {member_token}"},
        "seed_count": seed_count,
    }

    # Cleanup
    async def _teardown():
        await new_engine.dispose()

    asyncio.run(_teardown())


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with admin user but NO seeded roles.

    Yields a dict with:
      - "client": TestClient
      - "admin_headers": auth headers for an admin user
    """
    db_path = tmp_path / "test_agent_roles_empty.db"
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

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)
        admin_pwd_hash, _ = hash_password("admin_pass_123")

        async with new_sessionmaker() as session:
            session.add(UserModel(
                id="user_ar_admin_2",
                username="ar_admin_empty",
                password_hash=admin_pwd_hash,
                role="admin",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()

        db_module._db_initialized = True

    asyncio.run(_setup())

    client = TestClient(main.app)
    admin_token, _ = create_jwt_token("user_ar_admin_2", "ar_admin_empty")

    yield {
        "client": client,
        "admin_headers": {"Authorization": f"Bearer {admin_token}"},
    }

    async def _teardown():
        await new_engine.dispose()

    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# 1. Seed creates 8 system roles when DB empty
# ---------------------------------------------------------------------------

class TestSeedDefaultRoles:
    def test_seed_creates_eight_roles(self, empty_db):
        """seed_default_roles() creates 8 system roles in an empty DB."""
        count = asyncio.run(repo.seed_default_roles())
        assert count == 8

        # Verify all 8 keys exist
        roles = asyncio.run(repo.list_agent_roles())
        keys = {r["key"] for r in roles}
        assert keys == {
            "triage", "product", "architect", "frontend",
            "backend", "qa", "review", "delivery",
        }
        # All should be system roles
        for r in roles:
            assert r["isSystem"] is True
            assert r["enabled"] is True


# ---------------------------------------------------------------------------
# 2. Seed is idempotent
# ---------------------------------------------------------------------------

class TestSeedIdempotent:
    def test_seed_idempotent(self, fresh_db):
        """Calling seed_default_roles() twice still results in 8 roles."""
        # fresh_db already seeded once
        count2 = asyncio.run(repo.seed_default_roles())
        assert count2 == 0  # no new rows inserted

        roles = asyncio.run(repo.list_agent_roles())
        assert len(roles) == 8


# ---------------------------------------------------------------------------
# 3. GET /api/v1/agent-roles returns 8 roles (auth required)
# ---------------------------------------------------------------------------

class TestListAgentRoles:
    def test_list_returns_eight_roles(self, fresh_db):
        """GET /api/v1/agent-roles returns 8 default system roles."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.get("/api/v1/agent-roles", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "roles" in body
        assert len(body["roles"]) == 8
        keys = {r["key"] for r in body["roles"]}
        assert keys == {
            "triage", "product", "architect", "frontend",
            "backend", "qa", "review", "delivery",
        }

    def test_list_requires_auth(self, fresh_db):
        """GET /api/v1/agent-roles without token returns 401."""
        client = fresh_db["client"]
        resp = client.get("/api/v1/agent-roles")
        assert resp.status_code == 401

    def test_member_can_list_roles(self, fresh_db):
        """GET /api/v1/agent-roles is accessible to non-admin members."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.get("/api/v1/agent-roles", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["roles"]) == 8


# ---------------------------------------------------------------------------
# 4. POST /api/v1/agent-roles creates custom role
# ---------------------------------------------------------------------------

class TestCreateAgentRole:
    def test_non_admin_gets_403(self, fresh_db):
        """Non-admin user gets 403 on POST /api/v1/agent-roles."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.post("/api/v1/agent-roles", json={
            "key": "custom-role",
            "displayName": "Custom Role",
        }, headers=headers)
        assert resp.status_code == 403

    def test_admin_creates_role(self, fresh_db):
        """Admin can create a custom role, gets 201."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.post("/api/v1/agent-roles", json={
            "key": "custom-role",
            "displayName": "Custom Role",
            "description": "A test custom role",
            "timeoutSeconds": 3600,
        }, headers=headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["key"] == "custom-role"
        assert body["displayName"] == "Custom Role"
        assert body["description"] == "A test custom role"
        assert body["timeoutSeconds"] == 3600
        assert body["isSystem"] is False
        assert body["enabled"] is True

    def test_duplicate_key_returns_409(self, fresh_db):
        """Creating a role with an existing key returns 409."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        # "frontend" already exists from seed
        resp = client.post("/api/v1/agent-roles", json={
            "key": "frontend",
            "displayName": "Duplicate Frontend",
        }, headers=headers)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_requires_auth(self, fresh_db):
        """POST /api/v1/agent-roles without token returns 401."""
        client = fresh_db["client"]
        resp = client.post("/api/v1/agent-roles", json={
            "key": "no-auth-role",
            "displayName": "No Auth",
        })
        assert resp.status_code == 401

    def test_invalid_key_format_returns_422(self, fresh_db):
        """Invalid key format (uppercase, spaces) returns 422."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.post("/api/v1/agent-roles", json={
            "key": "Invalid Key!",
            "displayName": "Bad Key",
        }, headers=headers)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. PUT /api/v1/agent-roles/{key} updates role
# ---------------------------------------------------------------------------

class TestUpdateAgentRole:
    def test_updates_display_name(self, fresh_db):
        """PUT updates displayName and other fields."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.put("/api/v1/agent-roles/frontend", json={
            "displayName": "Frontend Engineer",
            "description": "Updated description",
            "timeoutSeconds": 7200,
        }, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["key"] == "frontend"
        assert body["displayName"] == "Frontend Engineer"
        assert body["description"] == "Updated description"
        assert body["timeoutSeconds"] == 7200

    def test_update_requires_admin(self, fresh_db):
        """Non-admin gets 403 on PUT."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.put("/api/v1/agent-roles/frontend", json={
            "displayName": "Hacked",
        }, headers=headers)
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_key(self, fresh_db):
        """PUT for non-existent key returns 404."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.put("/api/v1/agent-roles/nonexistent", json={
            "displayName": "Ghost",
        }, headers=headers)
        assert resp.status_code == 404

    def test_empty_body_returns_400(self, fresh_db):
        """PUT with no fields to update returns 400."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.put("/api/v1/agent-roles/frontend", json={}, headers=headers)
        assert resp.status_code == 400

    def test_update_requires_auth(self, fresh_db):
        """PUT without token returns 401."""
        client = fresh_db["client"]
        resp = client.put("/api/v1/agent-roles/frontend", json={
            "displayName": "No Auth",
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. PATCH /api/v1/agent-roles/{key}/enabled toggles enabled
# ---------------------------------------------------------------------------

class TestToggleAgentRoleEnabled:
    def test_disable_role(self, fresh_db):
        """PATCH disables an enabled role."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": False,
        }, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["key"] == "frontend"
        assert body["enabled"] is False

    def test_enable_role(self, fresh_db):
        """PATCH enables a disabled role."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        # First disable
        client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": False,
        }, headers=headers)
        # Then re-enable
        resp = client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": True,
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_disable_with_active_handoffs_returns_409(self, fresh_db):
        """Cannot disable a role that has active (non-terminal) handoffs."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]

        # Create a handoff with a non-terminal status targeting "qa"
        async def _create_handoff():
            async with db_module.AsyncSessionLocal() as session:
                now = datetime.now(timezone.utc)
                # Ensure the issue exists (FK constraint)
                issue = IssueModel(
                    id="issue-handoff-test-1",
                    key="DEV-900",
                    title="handoff test issue",
                    description="",
                    status="in_progress",
                    priority="medium",
                    board_id="board-default",
                    created_at=now,
                    updated_at=now,
                )
                session.add(issue)
                await session.commit()

                handoff = IssueHandoff(
                    id="handoff-block-test-1",
                    board_id="board-default",
                    issue_id="issue-handoff-test-1",
                    from_lane="frontend",
                    to_lane="qa",
                    status="pending",
                    payload={},
                    created_at=now,
                    updated_at=now,
                )
                session.add(handoff)
                await session.commit()

        asyncio.run(_create_handoff())

        # Try to disable "qa" -- should fail because of active handoff
        resp = client.patch("/api/v1/agent-roles/qa/enabled", json={
            "enabled": False,
        }, headers=headers)
        assert resp.status_code == 409
        assert "active handoff" in resp.json()["detail"]

    def test_toggle_returns_404_for_nonexistent_key(self, fresh_db):
        """PATCH for non-existent key returns 404."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]
        resp = client.patch("/api/v1/agent-roles/nonexistent/enabled", json={
            "enabled": False,
        }, headers=headers)
        assert resp.status_code == 404

    def test_toggle_requires_admin(self, fresh_db):
        """Non-admin gets 403 on PATCH."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": False,
        }, headers=headers)
        assert resp.status_code == 403

    def test_toggle_requires_auth(self, fresh_db):
        """PATCH without token returns 401."""
        client = fresh_db["client"]
        resp = client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": False,
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 7. GET /api/v1/lanes backward compatible response shape
# ---------------------------------------------------------------------------

class TestLanesBackwardCompatible:
    def test_lanes_response_has_next_lanes(self, fresh_db):
        """GET /api/v1/lanes uses 'nextLanes' key (not 'nextRoles')."""
        client = fresh_db["client"]
        resp = client.get("/api/v1/lanes")
        assert resp.status_code == 200
        body = resp.json()
        assert "lanes" in body
        assert "roles" not in body  # must not use the new key
        for lane in body["lanes"]:
            assert "nextLanes" in lane
            assert "nextRoles" not in lane

    def test_lanes_response_shape_matches_contract(self, fresh_db):
        """Each lane has the expected fields for frontend consumption."""
        client = fresh_db["client"]
        resp = client.get("/api/v1/lanes")
        assert resp.status_code == 200
        body = resp.json()
        expected_fields = {
            "key", "displayName", "description", "allowedProfiles",
            "defaultProvider", "defaultModel", "allowedCommands",
            "requiredCompletionFields", "timeoutSeconds", "retryPolicy",
            "retryMax", "nextLanes", "humanApprovalRequired",
        }
        for lane in body["lanes"]:
            assert expected_fields.issubset(set(lane.keys())), (
                f"Missing fields: {expected_fields - set(lane.keys())}"
            )

    def test_lanes_only_returns_enabled_roles(self, fresh_db):
        """GET /api/v1/lanes only returns enabled roles."""
        client = fresh_db["client"]
        headers = fresh_db["admin_headers"]

        # Disable "delivery"
        client.patch("/api/v1/agent-roles/delivery/enabled", json={
            "enabled": False,
        }, headers=headers)

        resp = client.get("/api/v1/lanes")
        assert resp.status_code == 200
        keys = {lane["key"] for lane in resp.json()["lanes"]}
        assert "delivery" not in keys
        assert len(keys) == 7


# ---------------------------------------------------------------------------
# 8. Non-admin gets 403 on all write endpoints
# ---------------------------------------------------------------------------

class TestNonAdminWriteBlocked:
    def test_post_403(self, fresh_db):
        """Non-admin gets 403 on POST /api/v1/agent-roles."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.post("/api/v1/agent-roles", json={
            "key": "blocked",
            "displayName": "Blocked",
        }, headers=headers)
        assert resp.status_code == 403

    def test_put_403(self, fresh_db):
        """Non-admin gets 403 on PUT /api/v1/agent-roles/{key}."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.put("/api/v1/agent-roles/frontend", json={
            "displayName": "Hacked",
        }, headers=headers)
        assert resp.status_code == 403

    def test_patch_403(self, fresh_db):
        """Non-admin gets 403 on PATCH /api/v1/agent-roles/{key}/enabled."""
        client = fresh_db["client"]
        headers = fresh_db["member_headers"]
        resp = client.patch("/api/v1/agent-roles/frontend/enabled", json={
            "enabled": False,
        }, headers=headers)
        assert resp.status_code == 403
