"""Tests for DB Queue Hardening — atomic claim, stale reclaim, retry, heartbeat.

Covers:
- Atomic claim: only one worker can claim a pending run
- Stale reclaim: runs stuck in claimed/running are reclaimed
- Retry/backoff: failed runs with max_retries > 0 are requeued
- Heartbeat: run heartbeat updates last_heartbeat_at
- Max runtime: enforcement in worker loop
- Kanban Tool Protocol: all 9 tools work correctly
"""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from db import repository as repo
from db.models import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB for queue hardening tests."""
    from db import database as db_module
    db_path = tmp_path / "test_queue.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield new_engine, new_sessionmaker


# ---------------------------------------------------------------------------
# Atomic Claim
# ---------------------------------------------------------------------------

class TestAtomicClaim:
    @pytest.mark.asyncio
    async def test_atomic_claim_basic(self, fresh_db):
        """Basic atomic claim picks up a pending run."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
        )
        assert run["status"] == "pending"

        claimed = await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        assert claimed is not None
        assert claimed["id"] == "run-1"
        assert claimed["status"] == "claimed"
        assert claimed["workerId"] == "w1"

    @pytest.mark.asyncio
    async def test_atomic_claim_fifo_order(self, fresh_db):
        """Atomic claim picks the oldest pending run first."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        await repo.create_run(id="run-old", board_id="board-default", issue_id="i1", issue_key="OLD", command="/a")
        await repo.create_run(id="run-new", board_id="board-default", issue_id="i2", issue_key="NEW", command="/b")

        claimed = await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        assert claimed["id"] == "run-old"  # oldest first

    @pytest.mark.asyncio
    async def test_atomic_claim_only_pending(self, fresh_db):
        """Atomic claim only picks up pending runs."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(id="run-1", board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/test")
        # Manually set to running
        await repo.update_run_status("run-1", "running", worker_id="w1")

        claimed = await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_atomic_claim_board_isolation(self, fresh_db):
        """Workers only claim runs from their board."""
        await repo.upsert_worker(id="w-a", board_id="board-a", worker_type="safe-runner")
        await repo.upsert_worker(id="w-b", board_id="board-b", worker_type="safe-runner")
        await repo.create_run(id="run-a", board_id="board-a", issue_id="i1", issue_key="A-001", command="/a")
        await repo.create_run(id="run-b", board_id="board-b", issue_id="i2", issue_key="B-001", command="/b")

        claimed_a = await repo.atomic_claim_run(worker_id="w-a", board_id="board-a")
        assert claimed_a["id"] == "run-a"

        claimed_b = await repo.atomic_claim_run(worker_id="w-b", board_id="board-b")
        assert claimed_b["id"] == "run-b"

    @pytest.mark.asyncio
    async def test_atomic_claim_role_matching(self, fresh_db):
        """Atomic claim respects required_role matching capabilities."""
        await repo.upsert_worker(id="w-be", board_id="board-default", worker_type="claude-code", capabilities=["backend-dev"])
        await repo.create_run(id="run-be", board_id="board-default", issue_id="i1", issue_key="BE-001", command="/be", required_role="backend-dev")
        await repo.create_run(id="run-fe", board_id="board-default", issue_id="i2", issue_key="FE-001", command="/fe", required_role="frontend-dev")

        claimed = await repo.atomic_claim_run(worker_id="w-be", board_id="board-default", capabilities=["backend-dev"])
        assert claimed is not None
        assert claimed["id"] == "run-be"

    @pytest.mark.asyncio
    async def test_atomic_claim_no_match_returns_none(self, fresh_db):
        """Returns None when no runs match the worker's capabilities."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="claude-code", capabilities=["qa"])
        await repo.create_run(id="run-1", board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/test", required_role="backend-dev")

        claimed = await repo.atomic_claim_run(worker_id="w1", board_id="board-default", capabilities=["qa"])
        assert claimed is None

    @pytest.mark.asyncio
    async def test_atomic_claim_skips_retry_not_ready(self, fresh_db):
        """Atomic claim skips runs with next_retry_at in the future."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
            max_retries=3,
        )
        # Fail the run first, then schedule retry in the future
        await repo.update_run_status("run-1", "failed", error_message="test")
        await repo.schedule_retry("run-1", delay_seconds=3600)

        claimed = await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_atomic_claim_double_claim_prevented(self, fresh_db):
        """Two workers cannot claim the same run."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        await repo.upsert_worker(id="w2", board_id="board-default", worker_type="safe-runner")
        await repo.create_run(id="run-1", board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/test")

        claimed1 = await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        assert claimed1 is not None

        claimed2 = await repo.atomic_claim_run(worker_id="w2", board_id="board-default")
        assert claimed2 is None  # run already claimed


# ---------------------------------------------------------------------------
# Stale Reclaim
# ---------------------------------------------------------------------------

class TestStaleReclaim:
    @pytest.mark.asyncio
    async def test_reclaim_stale_claimed_run(self, fresh_db):
        """Stale claimed run is requeued when retry_count < max_retries."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
            max_retries=3,
        )
        # Claim and backdate started_at
        await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        old_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        await repo.update_run_status("run-1", "claimed", worker_id="w1", started_at=old_time)

        reclaimed = await repo.reclaim_stale_runs(stale_threshold_seconds=300)
        assert len(reclaimed) == 1
        assert reclaimed[0]["status"] == "pending"
        assert reclaimed[0]["retryCount"] == 1

    @pytest.mark.asyncio
    async def test_reclaim_stale_run_max_retries_exceeded(self, fresh_db):
        """Stale run with retry_count >= max_retries is marked failed."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
            max_retries=1,
        )
        await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        old_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        await repo.update_run_status("run-1", "claimed", worker_id="w1", started_at=old_time)
        # Set retry_count to max
        await repo.schedule_retry("run-1", delay_seconds=0)
        # Requeue puts it back to pending with retry_count=1
        # Claim again and backdate
        await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        await repo.update_run_status("run-1", "claimed", worker_id="w1", started_at=old_time)

        reclaimed = await repo.reclaim_stale_runs(stale_threshold_seconds=300, max_retries=1)
        assert len(reclaimed) == 1
        assert reclaimed[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_reclaim_skips_active_runs(self, fresh_db):
        """Runs with recent heartbeats are not reclaimed."""
        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
        )
        await repo.atomic_claim_run(worker_id="w1", board_id="board-default")
        # Set recent heartbeat
        await repo.update_run_heartbeat("run-1")

        reclaimed = await repo.reclaim_stale_runs(stale_threshold_seconds=300)
        assert len(reclaimed) == 0


# ---------------------------------------------------------------------------
# Retry / Backoff
# ---------------------------------------------------------------------------

class TestRetryBackoff:
    @pytest.mark.asyncio
    async def test_schedule_retry(self, fresh_db):
        """schedule_retry increments retry_count and sets next_retry_at."""
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
            max_retries=3,
        )
        # Fail the run
        await repo.update_run_status("run-1", "failed", error_message="test error")

        result = await repo.schedule_retry("run-1", delay_seconds=60)
        assert result is not None
        assert result["retryCount"] == 1
        assert result["nextRetryAt"] is not None
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_schedule_retry_exhausted(self, fresh_db):
        """schedule_retry returns None when max_retries exceeded."""
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
            max_retries=1,
        )
        await repo.update_run_status("run-1", "failed", error_message="test error")
        await repo.schedule_retry("run-1", delay_seconds=60)

        # Second retry should fail (retry_count=1 >= max_retries=1)
        result = await repo.schedule_retry("run-1", delay_seconds=60)
        assert result is None


# ---------------------------------------------------------------------------
# Run Heartbeat
# ---------------------------------------------------------------------------

class TestRunHeartbeat:
    @pytest.mark.asyncio
    async def test_update_run_heartbeat(self, fresh_db):
        """update_run_heartbeat sets last_heartbeat_at."""
        run = await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
        )
        result = await repo.update_run_heartbeat("run-1")
        assert result is not None
        assert result["lastHeartbeatAt"] is not None


# ---------------------------------------------------------------------------
# Kanban Tool Protocol
# ---------------------------------------------------------------------------

class TestKanbanTools:
    @pytest.mark.asyncio
    async def test_kanban_list(self, fresh_db):
        """kanban_list returns issues on a board."""
        from core.kanban_protocol.tools import kanban_list, KanbanToolContext

        # Create some issues
        await repo.upsert_issue({
            "id": "i1", "key": "DEV-001", "board_id": "board-default",
            "title": "Issue 1", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i2", "key": "DEV-002", "board_id": "board-default",
            "title": "Issue 2", "status": "in_progress", "priority": "high",
        })

        ctx = KanbanToolContext(board_id="board-default")
        result = await kanban_list(ctx)
        assert result.ok
        assert result.data["total"] >= 2

    @pytest.mark.asyncio
    async def test_kanban_list_filter_status(self, fresh_db):
        """kanban_list filters by status."""
        from core.kanban_protocol.tools import kanban_list, KanbanToolContext

        await repo.upsert_issue({
            "id": "i1", "key": "DEV-001", "board_id": "board-default",
            "title": "Backlog", "status": "backlog", "priority": "medium",
        })
        await repo.upsert_issue({
            "id": "i2", "key": "DEV-002", "board_id": "board-default",
            "title": "Done", "status": "done", "priority": "medium",
        })

        ctx = KanbanToolContext(board_id="board-default", payload={"status": "backlog"})
        result = await kanban_list(ctx)
        assert result.ok
        assert all(i.get("status") == "backlog" for i in result.data["issues"])

    @pytest.mark.asyncio
    async def test_kanban_create(self, fresh_db):
        """kanban_create creates a new issue."""
        from core.kanban_protocol.tools import kanban_create, KanbanToolContext

        ctx = KanbanToolContext(
            board_id="board-default",
            actor="test-agent",
            payload={"title": "New Issue", "description": "Test description"},
        )
        result = await kanban_create(ctx)
        assert result.ok
        assert result.data["issue"]["title"] == "New Issue"

    @pytest.mark.asyncio
    async def test_kanban_create_requires_title(self, fresh_db):
        """kanban_create fails without title."""
        from core.kanban_protocol.tools import kanban_create, KanbanToolContext

        ctx = KanbanToolContext(board_id="board-default", payload={})
        result = await kanban_create(ctx)
        assert not result.ok
        assert "title" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kanban_show(self, fresh_db):
        """kanban_show returns issue details."""
        from core.kanban_protocol.tools import kanban_show, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-show", "key": "DEV-SHOW", "board_id": "board-default",
            "title": "Show Me", "status": "backlog", "priority": "medium",
        })

        ctx = KanbanToolContext(board_id="board-default", issue_id=issue["id"])
        result = await kanban_show(ctx)
        assert result.ok
        assert result.data["issue"]["title"] == "Show Me"
        assert "handoffs" in result.data
        assert "artifacts" in result.data

    @pytest.mark.asyncio
    async def test_kanban_comment(self, fresh_db):
        """kanban_comment adds a comment to an issue."""
        from core.kanban_protocol.tools import kanban_comment, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-cmt", "key": "DEV-CMT", "board_id": "board-default",
            "title": "Comment Test", "status": "backlog", "priority": "medium",
        })

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            actor="test-agent",
            payload={"body": "This is a test comment"},
        )
        result = await kanban_comment(ctx)
        assert result.ok
        assert result.data["comment"]["body"] == "This is a test comment"

    @pytest.mark.asyncio
    async def test_kanban_link(self, fresh_db):
        """kanban_link attaches an artifact to an issue."""
        from core.kanban_protocol.tools import kanban_link, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-link", "key": "DEV-LINK", "board_id": "board-default",
            "title": "Link Test", "status": "backlog", "priority": "medium",
        })

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            payload={"type": "pr", "title": "PR #42", "url": "https://github.com/test/pr/42"},
        )
        result = await kanban_link(ctx)
        assert result.ok
        assert result.data["artifact"]["pathOrUrl"] == "https://github.com/test/pr/42"

    @pytest.mark.asyncio
    async def test_kanban_link_requires_url(self, fresh_db):
        """kanban_link fails without url."""
        from core.kanban_protocol.tools import kanban_link, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-nourl", "key": "DEV-NOURL", "board_id": "board-default",
            "title": "Link Test", "status": "backlog", "priority": "medium",
        })

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            payload={"type": "pr", "title": "No URL"},
        )
        result = await kanban_link(ctx)
        assert not result.ok
        assert "url" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kanban_heartbeat(self, fresh_db):
        """kanban_heartbeat updates worker and run heartbeats."""
        from core.kanban_protocol.tools import kanban_heartbeat, KanbanToolContext

        await repo.upsert_worker(id="w1", board_id="board-default", worker_type="safe-runner")
        await repo.create_run(
            id="run-1", board_id="board-default",
            issue_id="i1", issue_key="DEV-001", command="/test",
        )

        ctx = KanbanToolContext(
            board_id="board-default",
            payload={"worker_id": "w1", "run_id": "run-1"},
        )
        result = await kanban_heartbeat(ctx)
        assert result.ok

    @pytest.mark.asyncio
    async def test_invoke_tool_unknown(self, fresh_db):
        """invoke_tool returns error for unknown tool."""
        from core.kanban_protocol.tools import invoke_tool, KanbanToolContext

        ctx = KanbanToolContext(board_id="board-default")
        result = await invoke_tool("nonexistent_tool", ctx)
        assert not result.ok
        assert "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kanban_tool_list_endpoint(self, fresh_db):
        """GET /api/v1/kanban/tools returns tool list."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/kanban/tools")
            assert resp.status_code == 200
            tools = resp.json()["tools"]
            tool_names = [t["name"] for t in tools]
            assert "kanban_list" in tool_names
            assert "kanban_show" in tool_names
            assert "kanban_create" in tool_names
            assert "kanban_comment" in tool_names
            assert "kanban_complete" in tool_names

    @pytest.mark.asyncio
    async def test_kanban_block(self, fresh_db):
        """kanban_block blocks an issue and its active handoffs."""
        from core.kanban_protocol.tools import kanban_block, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-block", "key": "DEV-BLOCK", "board_id": "board-default",
            "title": "Block Test", "status": "in_progress", "priority": "medium",
        })

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            actor="test-agent",
            payload={"reason": "Missing dependency"},
        )
        result = await kanban_block(ctx)
        assert result.ok
        assert result.data["reason"] == "Missing dependency"

        # Verify issue status changed to blocked
        updated = await repo.get_issue(issue["id"])
        assert updated["status"] == "blocked"

    @pytest.mark.asyncio
    async def test_kanban_block_missing_issue(self, fresh_db):
        """kanban_block returns error for nonexistent issue."""
        from core.kanban_protocol.tools import kanban_block, KanbanToolContext

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_key="NOPE-999",
            payload={"reason": "test"},
        )
        result = await kanban_block(ctx)
        assert not result.ok
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kanban_unblock(self, fresh_db):
        """kanban_unblock unblocks a blocked issue."""
        from core.kanban_protocol.tools import kanban_block, kanban_unblock, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-unblock", "key": "DEV-UNBLOCK", "board_id": "board-default",
            "title": "Unblock Test", "status": "blocked", "priority": "medium",
        })

        # First block it
        ctx_block = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            actor="test-agent",
            payload={"reason": "Test block"},
        )
        await kanban_block(ctx_block)

        # Then unblock
        ctx_unblock = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            actor="test-agent",
        )
        result = await kanban_unblock(ctx_unblock)
        assert result.ok

        # Verify issue status restored
        updated = await repo.get_issue(issue["id"])
        assert updated["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_kanban_unblock_missing_issue(self, fresh_db):
        """kanban_unblock returns error for nonexistent issue."""
        from core.kanban_protocol.tools import kanban_unblock, KanbanToolContext

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_key="NOPE-999",
        )
        result = await kanban_unblock(ctx)
        assert not result.ok
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kanban_complete(self, fresh_db):
        """kanban_complete creates a review handoff with evidence."""
        from core.kanban_protocol.tools import kanban_complete, KanbanToolContext

        issue = await repo.upsert_issue({
            "id": "i-done", "key": "DEV-DONE", "board_id": "board-default",
            "title": "Complete Test", "status": "in_progress", "priority": "medium",
        })

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_id=issue["id"],
            actor="test-agent",
            agent_role="backend",
            next_role="review",
            payload={"result_summary": "All tests pass", "evidence": ["coverage 92%"]},
            artifacts=[{"type": "pr", "title": "PR #100", "url": "https://github.com/test/pr/100"}],
        )
        result = await kanban_complete(ctx)
        assert result.ok
        assert "handoff" in result.data
        assert result.data["handoff"]["toLane"] == "review"

    @pytest.mark.asyncio
    async def test_kanban_complete_missing_issue(self, fresh_db):
        """kanban_complete returns error for nonexistent issue."""
        from core.kanban_protocol.tools import kanban_complete, KanbanToolContext

        ctx = KanbanToolContext(
            board_id="board-default",
            issue_key="NOPE-999",
            payload={"result_summary": "done"},
        )
        result = await kanban_complete(ctx)
        assert not result.ok
        assert "not found" in result.error.lower()


class TestKanbanToolSchemas:
    @pytest.mark.asyncio
    async def test_tools_return_input_schema(self, fresh_db):
        """GET /api/v1/kanban/tools returns input_schema for each tool."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/kanban/tools")
            assert resp.status_code == 200
            tools = resp.json()["tools"]
            for tool in tools:
                assert "input_schema" in tool, f"{tool['name']} missing input_schema"
                schema = tool["input_schema"]
                assert schema.get("type") == "object"
                props = schema.get("properties", {})
                assert "board_id" in props, f"{tool['name']} schema missing board_id"


class TestToolCallAudit:
    @pytest.mark.asyncio
    async def test_tool_call_writes_event_on_success(self, fresh_db):
        """Successful tool call writes a tool_call_completed event."""
        from fastapi.testclient import TestClient
        from main import app
        from db import repository as repo
        from db.models import AgentRunEvent
        from sqlalchemy import select
        from conftest import seed_test_user

        _, sessionmaker = fresh_db
        headers = await seed_test_user(sessionmaker)

        # Create an issue first
        issue = await repo.upsert_issue({
            "id": "i-audit", "key": "DEV-AUDIT", "board_id": "board-default",
            "title": "Audit Test", "status": "backlog", "priority": "medium",
        })

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/kanban/kanban_show",
                json={"board_id": "board-default", "issue_id": issue["id"], "run_id": "run-audit-test-001"},
                headers=headers,
            )
            assert resp.status_code == 200

        # Verify the audit event was written to the DB
        async with sessionmaker() as session:
            result = await session.execute(
                select(AgentRunEvent).where(AgentRunEvent.run_id == "run-audit-test-001")
            )
            events = result.scalars().all()
            assert len(events) == 1
            event = events[0]
            assert event.event_type == "tool_call_completed"
            meta = event.extra_metadata
            assert meta["tool_name"] == "kanban_show"
            assert meta["ok"] is True

    @pytest.mark.asyncio
    async def test_tool_call_writes_event_on_failure(self, fresh_db):
        """Failed tool call writes a tool_call_failed event."""
        from fastapi.testclient import TestClient
        from main import app
        from db.models import AgentRunEvent
        from sqlalchemy import select
        from conftest import seed_test_user

        _, sessionmaker = fresh_db
        headers = await seed_test_user(sessionmaker)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/kanban/kanban_show",
                json={"board_id": "board-default", "issue_key": "NOPE-999", "run_id": "run-audit-test-002"},
                headers=headers,
            )
            assert resp.status_code == 400

        # Verify the audit event was written to the DB
        async with sessionmaker() as session:
            result = await session.execute(
                select(AgentRunEvent).where(AgentRunEvent.run_id == "run-audit-test-002")
            )
            events = result.scalars().all()
            assert len(events) == 1
            event = events[0]
            assert event.event_type == "tool_call_failed"
            meta = event.extra_metadata
            assert meta["ok"] is False
