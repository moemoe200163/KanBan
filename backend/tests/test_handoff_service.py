import pytest

from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.lanes import WORKER_LANES
from core.kanban_protocol.scope_guard import ScopeDeniedError


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file, enable FK enforcement, and seed a parent issue.

    Mirrors the fixture in test_persistence.py so the dev DB is never touched
    and FK constraints behave like they do on Postgres.
    """
    from datetime import datetime, timezone

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    from db import database as db_module
    from db.models import Base, Issue as IssueModel

    db_path = tmp_path / "test_handoff.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    # Create a fresh engine bound to the new file.
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    # Enable SQLite FK enforcement on every new connection so future FK
    # violations are caught (production Postgres enforces FKs by default).
    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    # Manually initialize the schema and seed a parent issue. We use
    # drop_all+create_all to guarantee a clean schema and set the init
    # flag so the lifespan's init_db is a no-op.
    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Seed a parent issue so the FK from issue_handoffs.issue_id is satisfied.
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-1",
                key="TEST-1",
                title="test issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_create_returns_pending_handoff(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "wip"},
        created_by="alice",
    )
    assert handoff["status"] == "pending"
    assert handoff["toLane"] == "frontend"
    assert handoff["createdBy"] == "alice"
    assert handoff["boardId"] == "board-default"


@pytest.mark.asyncio
async def test_create_rejects_unknown_target_lane(fresh_db):
    svc = HandoffService()
    with pytest.raises(ValueError) as exc_info:
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="not-a-lane",
            payload={},
            created_by="alice",
        )
    assert "Unknown worker lane" in str(exc_info.value)


@pytest.mark.asyncio
async def test_accept_moves_pending_to_accepted(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    accepted = await svc.accept(handoff["id"], actor="bob")
    assert accepted["status"] == "accepted"
    assert accepted["acceptedBy"] == "bob"


@pytest.mark.asyncio
async def test_accept_rejects_non_pending_handoff(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ValueError) as exc_info:
        await svc.accept(handoff["id"], actor="bob")
    assert "cannot accept" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_accept_raises_when_handoff_missing(fresh_db):
    svc = HandoffService()
    with pytest.raises(ValueError, match="not found"):
        await svc.accept("h_doesnotexist", actor="bob")


@pytest.mark.asyncio
async def test_dispatch_creates_ecc_job_and_moves_to_in_progress(fresh_db):
    from db import repository as repo

    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "wip"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")

    # Seed an Issue row alongside the fresh-db parent so dispatch has a
    # realistic record. `upsert_issue` preserves the existing key, so
    # the original `TEST-1` stays put; dispatch uses the `issue_key`
    # argument we pass in directly.
    await repo.upsert_issue({
        "id": "issue-1",
        "key": "DEV-001",
        "title": "test",
        "description": "",
        "status": "in_progress",
    })

    result = await svc.dispatch(
        handoff_id=handoff["id"],
        issue_key="DEV-001",
        profile="frontend",
        actor="bob",
    )
    assert result["handoff"]["status"] == "in_progress"
    assert result["handoff"]["dispatchedBy"] == "bob"
    assert result["job"]["id"].startswith("ecc_")
    assert result["job"]["harness"] == "safe-runner"


@pytest.mark.asyncio
async def test_dispatch_rejects_when_approval_required_and_missing(fresh_db):
    from db import repository as repo

    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",  # qa requires human approval
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    await repo.upsert_issue({
        "id": "issue-1",
        "key": "DEV-002",
        "title": "t",
        "description": "",
        "status": "in_progress",
    })
    with pytest.raises(PermissionError) as exc_info:
        await svc.dispatch(
            handoff_id=handoff["id"],
            issue_key="DEV-002",
            profile="general",
            actor="bob",
        )
    assert "approval" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_dispatch_raises_when_handoff_missing(fresh_db):
    svc = HandoffService()
    with pytest.raises(ValueError, match="not found"):
        await svc.dispatch(
            handoff_id="h_doesnotexist",
            issue_key="DEV-001",
            profile="frontend",
            actor="bob",
        )


@pytest.mark.asyncio
async def test_dispatch_rejects_non_accepted_handoff(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    # Skip accept — handoff is still "pending"
    with pytest.raises(ValueError, match="only 'accepted' handoffs"):
        await svc.dispatch(
            handoff_id=handoff["id"],
            issue_key="DEV-001",
            profile="frontend",
            actor="bob",
        )


@pytest.mark.asyncio
async def test_complete_rejects_when_required_fields_missing(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",
        payload={},  # missing test_results and coverage_pct
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ValueError) as exc_info:
        await svc.complete(handoff_id=handoff["id"], actor="bob", payload=None)
    # Pydantic v2 returns structured errors; field names live in errors[].loc
    error_locs = [tuple(e["loc"]) for e in exc_info.value.errors]
    assert ("test_results",) in error_locs
    assert ("coverage_pct",) in error_locs


@pytest.mark.asyncio
async def test_complete_succeeds_with_all_required_fields(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",
        payload={"test_results": "ok", "coverage_pct": 95},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    completed = await svc.complete(
        handoff_id=handoff["id"], actor="bob", payload=None
    )
    assert completed["status"] == "completed"
    assert completed["completedBy"] == "bob"
    assert completed["completedAt"] is not None


@pytest.mark.asyncio
async def test_complete_merges_existing_and_new_payload(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",
        payload={"test_results": "ok"},  # coverage_pct missing
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    completed = await svc.complete(
        handoff_id=handoff["id"],
        actor="bob",
        payload={"coverage_pct": 95},
    )
    assert completed["payload"]["test_results"] == "ok"   # preserved (existing)
    assert completed["payload"]["coverage_pct"] == 95     # added (caller)
    # declared-only — no rogue keys leak through
    assert set(completed["payload"].keys()) == {"test_results", "coverage_pct"}


@pytest.mark.asyncio
async def test_block_rejects_empty_reason(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    with pytest.raises(ValueError):
        await svc.block(handoff_id=handoff["id"], actor="bob", reason="")


@pytest.mark.asyncio
async def test_block_and_unblock_round_trip(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    blocked = await svc.block(
        handoff_id=handoff["id"], actor="bob", reason="CI red"
    )
    assert blocked["status"] == "blocked"
    assert blocked["blockReason"] == "CI red"
    # unblock returns to the last non-terminal state (pending by default).
    restored = await svc.unblock(handoff_id=handoff["id"], actor="bob")
    assert restored["status"] == "pending"
    assert restored["blockReason"] is None


@pytest.mark.asyncio
async def test_cancel_allowed_from_non_terminal_state(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    cancelled = await svc.cancel(handoff_id=handoff["id"], actor="bob")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelledBy"] == "bob"


@pytest.mark.asyncio
async def test_cancel_rejected_from_completed_state(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "ok", "screenshots": ["ok"]},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    await svc.complete(handoff_id=handoff["id"], actor="bob", payload=None)
    with pytest.raises(ValueError):
        await svc.cancel(handoff_id=handoff["id"], actor="bob")


@pytest.mark.asyncio
async def test_cancel_rejected_from_cancelled_state(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.cancel(handoff_id=handoff["id"], actor="bob")
    with pytest.raises(ValueError):
        await svc.cancel(handoff_id=handoff["id"], actor="bob")


@pytest.mark.asyncio
async def test_scope_guard_fires_before_pydantic_for_denied_keys(fresh_db):
    """Guardrail #1: scope guard must run BEFORE Pydantic validation.

    If Pydantic's `extra="forbid"` ran first it would silently drop
    out-of-scope keys, and `check_payload` would never see them. This
    test pins the order.
    """
    from core.kanban_protocol.scope_guard import ScopeDeniedError

    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "ok"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ScopeDeniedError):
        await svc.complete(
            handoff_id=handoff["id"],
            actor="bob",
            payload={"sandbox_egress": "1.1.1.1"},
        )


@pytest.mark.asyncio
async def test_create_rejects_payload_with_denied_keys(fresh_db):
    svc = HandoffService()
    with pytest.raises(ScopeDeniedError):
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="frontend",
            payload={"sandbox_egress": "10.0.0.0/8"},
            created_by="alice",
        )


@pytest.mark.asyncio
async def test_complete_rejects_payload_with_denied_keys(fresh_db):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "ok", "screenshots": "ok"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ScopeDeniedError):
        await svc.complete(
            handoff_id=handoff["id"],
            actor="bob",
            payload={"iptables_rules": "ACCEPT"},
        )


@pytest.mark.asyncio
async def test_create_rejects_denied_key_nested_in_subdict(fresh_db):
    svc = HandoffService()
    with pytest.raises(ScopeDeniedError) as exc_info:
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="frontend",
            payload={"meta": {"sandbox_egress": "10.0.0.0/8"}},
            created_by="alice",
        )
    assert "sandbox_egress" in exc_info.value.offending_keys


@pytest.mark.asyncio
async def test_block_reason_preserved_across_non_block_updates(fresh_db):
    """Regression: update_issue_handoff used to unconditionally clear block_reason.

    Before the fix, any call to update_issue_handoff that didn't pass block_reason
    (accept, complete, etc.) would silently set it to None, wiping a stored reason.
    """
    svc = HandoffService()
    h = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="backend",
        payload={"diff_summary": "x", "test_results": "ok"},
        created_by="alice",
    )

    # Accept → accepted
    await svc.accept(h["id"], actor="alice")

    # Block with a reason
    blocked = await svc.block(handoff_id=h["id"], actor="bob", reason="needs review")
    assert blocked["blockReason"] == "needs review"

    # Unblock clears the reason explicitly
    unblocked = await svc.unblock(handoff_id=h["id"], actor="bob")
    assert unblocked["blockReason"] is None

    # Accept again — must NOT re-introduce a stale block_reason
    await svc.accept(h["id"], actor="alice")

    # Block again with a new reason
    blocked2 = await svc.block(handoff_id=h["id"], actor="carol", reason="second block")
    assert blocked2["blockReason"] == "second block"

    # Unblock
    await svc.unblock(handoff_id=h["id"], actor="carol")

    # Accept + Complete — block_reason should remain None (not "second block")
    await svc.accept(h["id"], actor="alice")
    completed = await svc.complete(
        handoff_id=h["id"], actor="alice",
        payload={"diff_summary": "v2", "test_results": "pass"},
    )
    assert completed["blockReason"] is None
