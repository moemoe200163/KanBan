import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel
from core.kanban_protocol.handoff import HandoffService


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file, enable FK enforcement, and seed a parent issue.

    Mirrors backend/tests/test_handoff_service.py so the dev DB is never touched
    and FK constraints behave like they do on Postgres.
    """
    db_path = tmp_path / "test_handoffs_api.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Seed a parent issue that all tests can reference.
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-api-1",
                key="DEV-100",
                title="api test issue",
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
    new_engine.sync_engine.dispose()


def test_create_handoff_returns_pending(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {"diff_summary": "wip"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["toLane"] == "frontend"
    assert body["boardId"] == "board-default"


def test_create_handoff_rejects_unknown_lane(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "not-a-lane"},
    )
    assert response.status_code == 422


def test_list_handoffs_for_issue(fresh_db):
    svc = HandoffService()
    import asyncio
    asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.get(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["handoffs"][0]["toLane"] == "frontend"


def test_get_one_handoff(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.get(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}"
    )
    assert response.status_code == 200
    assert response.json()["id"] == handoff["id"]


def test_unknown_board_id_returns_404(fresh_db):
    response = client.get(
        "/api/v1/boards/some-other-board/issues/issue-api-1/handoffs"
    )
    assert response.status_code == 404


def test_create_handoff_rejects_denied_payload_key(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={
            "toLane": "frontend",
            "payload": {"sandbox_egress": "open"},
        },
    )
    assert response.status_code == 422
    assert "Scope denied" in response.json()["detail"]


def test_get_handoff_rejects_wrong_issue_id(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Request with a mismatched issue_id should return 404.
    response = client.get(
        f"/api/v1/boards/board-default/issues/wrong-issue/handoffs/{handoff['id']}"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Accept endpoint
# ---------------------------------------------------------------------------

def test_accept_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/accept",
        json={"actor": "bob"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["acceptedBy"] == "bob"


def test_accept_handoff_rejects_wrong_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Accept once -> accepted
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    # Second accept should fail (status is now "accepted", not "pending")
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/accept",
        json={"actor": "carol"},
    )
    assert response.status_code == 422


def test_accept_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/accept",
        json={"actor": "bob"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Dispatch endpoint
# ---------------------------------------------------------------------------

def test_dispatch_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/dispatch",
        json={"issueKey": "DEV-100", "profile": "frontend", "actor": "bob"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["handoff"]["status"] == "in_progress"
    assert body["job"]["status"] == "queued"


def test_dispatch_handoff_rejects_wrong_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Handoff is still "pending" — dispatch requires "accepted"
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/dispatch",
        json={"issueKey": "DEV-100", "profile": "frontend"},
    )
    assert response.status_code == 422


def test_dispatch_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/dispatch",
        json={"issueKey": "DEV-100", "profile": "frontend"},
    )
    assert response.status_code == 404


def test_dispatch_handoff_requires_approval(fresh_db):
    """Lane requires human_approval but no approver in payload -> 422."""
    import asyncio
    svc = HandoffService()
    # "product" lane has human_approval_required=True
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="product",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/dispatch",
        json={"issueKey": "DEV-100", "profile": "general", "actor": "bob"},
    )
    assert response.status_code == 422
    assert "human approval" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Complete endpoint
# ---------------------------------------------------------------------------

def test_complete_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    # complete accepts "in_progress" or "accepted"; frontend requires
    # diff_summary and screenshots.
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/complete",
        json={
            "actor": "bob",
            "payload": {"diff_summary": "done", "screenshots": []},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completedBy"] == "bob"


def test_complete_handoff_rejects_wrong_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Handoff is "pending" — complete only accepts "in_progress" or "accepted"
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/complete",
        json={"payload": {"diff_summary": "done", "screenshots": []}},
    )
    assert response.status_code == 422


def test_complete_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/complete",
        json={"payload": {"diff_summary": "done", "screenshots": []}},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Ownership validation — wrong issue_id with valid handoff
# ---------------------------------------------------------------------------

def _create_second_issue(session_maker):
    """Seed a second issue so ownership-mismatch tests hit the guard, not the issue check."""
    import asyncio
    from db.models import Issue as IssueModel
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    async def _seed():
        async with session_maker() as session:
            session.add(IssueModel(
                id="issue-api-2",
                key="DEV-101",
                title="second issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
    asyncio.run(_seed())


def test_accept_handoff_wrong_issue_returns_404(fresh_db, monkeypatch):
    """Accept with a valid handoff but wrong issue_id should 404."""
    from db import database as db_module
    _create_second_issue(db_module.AsyncSessionLocal)

    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Use the handoff id but a different (valid) issue_id.
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-2/handoffs/{handoff['id']}/accept",
        json={"actor": "bob"},
    )
    assert response.status_code == 404


def test_dispatch_handoff_wrong_issue_returns_404(fresh_db, monkeypatch):
    """Dispatch with a valid handoff but wrong issue_id should 404."""
    from db import database as db_module
    _create_second_issue(db_module.AsyncSessionLocal)

    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    # Use the handoff id but a different (valid) issue_id.
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-2/handoffs/{handoff['id']}/dispatch",
        json={"issueKey": "DEV-100", "profile": "frontend", "actor": "bob"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Block endpoint
# ---------------------------------------------------------------------------

def test_block_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/block",
        json={"actor": "bob", "blockReason": "waiting on design"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["blockReason"] == "waiting on design"


def test_block_handoff_rejects_terminal_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.cancel(handoff_id=handoff["id"], actor="alice"))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/block",
        json={"actor": "bob", "blockReason": "too late"},
    )
    assert response.status_code == 422


def test_block_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/block",
        json={"actor": "bob", "blockReason": "missing"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Unblock endpoint
# ---------------------------------------------------------------------------

def test_unblock_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.block(
        handoff_id=handoff["id"], actor="bob", reason="blocked for review"
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/unblock",
        json={"actor": "carol"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["blockReason"] is None


def test_unblock_handoff_rejects_wrong_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    # Handoff is still "pending" — unblock requires "blocked"
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/unblock",
        json={"actor": "carol"},
    )
    assert response.status_code == 422


def test_unblock_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/unblock",
        json={"actor": "carol"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------

def test_cancel_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/cancel",
        json={"actor": "bob"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelledBy"] == "bob"


def test_cancel_handoff_rejects_terminal_state(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.cancel(handoff_id=handoff["id"], actor="alice"))
    # Second cancel should fail (already cancelled)
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/cancel",
        json={"actor": "bob"},
    )
    assert response.status_code == 422


def test_cancel_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/cancel",
        json={"actor": "bob"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Comment endpoint
# ---------------------------------------------------------------------------

def test_comment_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/comment",
        json={
            "body": "Looks good, proceeding",
            "authorId": "user-1",
            "authorName": "Alice",
            "commentType": "handoff",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "Looks good, proceeding"
    assert body["authorId"] == "user-1"
    assert body["commentType"] == "handoff"


def test_comment_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/comment",
        json={"body": "orphan comment"},
    )
    assert response.status_code == 404


def test_comment_handoff_wrong_issue_returns_404(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    from db import database as db_module
    _create_second_issue(db_module.AsyncSessionLocal)
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-2/handoffs/{handoff['id']}/comment",
        json={"body": "wrong issue"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------

def test_preview_handoff_happy_path(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "added button"},
        created_by="alice",
    ))
    response = client.get(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/preview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["handoffId"] == handoff["id"]
    assert body["toLane"] == "frontend"
    assert body["displayName"] == "Frontend"
    assert body["defaultProvider"] == "claude-code"
    assert body["defaultModel"] == "claude-3-5-sonnet"
    assert "diff_summary" in body["allowedCommands"] or isinstance(body["allowedCommands"], list)
    # frontend requires diff_summary and screenshots
    assert body["requiredCompletionFields"] == ["diff_summary", "screenshots"]
    assert body["presentFields"] == ["diff_summary"]
    assert body["missingFields"] == ["screenshots"]
    assert body["humanApprovalRequired"] is False
    assert body["hasApprover"] is False
    assert body["timeoutSeconds"] == 1800
    assert body["retryPolicy"] == "fixed"
    assert body["retryMax"] == 1


def test_preview_handoff_with_approver(fresh_db):
    """Preview should set hasApprover=True when payload contains 'approver'."""
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="product",
        payload={"approver": "lead-dev"},
        created_by="alice",
    ))
    response = client.get(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/preview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["humanApprovalRequired"] is True
    assert body["hasApprover"] is True
    assert body["toLane"] == "product"


def test_preview_handoff_not_found(fresh_db):
    response = client.get(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/preview"
    )
    assert response.status_code == 404


def test_preview_handoff_wrong_issue_returns_404(fresh_db):
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    ))
    from db import database as db_module
    _create_second_issue(db_module.AsyncSessionLocal)
    response = client.get(
        f"/api/v1/boards/board-default/issues/issue-api-2/handoffs/{handoff['id']}/preview"
    )
    assert response.status_code == 404
