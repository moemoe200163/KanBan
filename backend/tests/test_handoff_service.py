import pytest

from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.lanes import WORKER_LANES


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
