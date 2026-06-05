import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event, select as sa_select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel, User as UserModel
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

        # Create a test user for JWT auth
        from api.v1.endpoints.auth import hash_password, create_jwt_token
        now_u = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            result = await session.execute(sa_select(UserModel).where(UserModel.username == "testuser"))
            if not result.scalar_one_or_none():
                pwd_hash, _ = hash_password("testpass123")
                session.add(UserModel(
                    id="user_test_1", username="testuser", email="test@example.com",
                    password_hash=pwd_hash, role="admin",
                    created_at=now_u, updated_at=now_u,
                ))
                await session.commit()
        token, _ = create_jwt_token("user_test_1", "testuser")
        return {"Authorization": f"Bearer {token}"}

    headers = asyncio.run(_setup())
    yield headers
    new_engine.sync_engine.dispose()


def test_create_handoff_returns_pending(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {"diff_summary": "wip"}},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_accept_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/accept",
        json={"actor": "bob"},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_dispatch_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/dispatch",
        json={"issueKey": "DEV-100", "profile": "frontend"},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_complete_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/complete",
        json={"payload": {"diff_summary": "done", "screenshots": []}},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_block_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/block",
        json={"actor": "bob", "blockReason": "missing"},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_unblock_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/unblock",
        json={"actor": "carol"},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
    )
    assert response.status_code == 422


def test_cancel_handoff_not_found(fresh_db):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs/h_nonexistent/cancel",
        json={"actor": "bob"},
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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
        headers=fresh_db,
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


# ---------------------------------------------------------------------------
# Task 7: structured 422 response shape for /complete endpoint
# ---------------------------------------------------------------------------

import asyncio
from typing import Optional


def _create_and_accept(to_lane: str, initial_payload: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    """Helper for the new tests: create a handoff and accept it via the service."""
    create = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": to_lane, "payload": initial_payload or {}},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    handoff = create.json()
    asyncio.run(HandoffService().accept(handoff["id"], actor="bob"))
    return handoff


def test_complete_returns_structured_422_on_type_error(fresh_db):
    """coverage_pct: 'abc' must trigger the typed 422 with detail.lane='qa'."""
    handoff = _create_and_accept("qa", initial_payload={"test_results": "ok"}, headers=fresh_db)
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/complete",
        json={"actor": "tester", "payload": {"test_results": "ok", "coverage_pct": "abc"}},
        headers=fresh_db,
    )
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], dict)
    assert body["detail"]["lane"] == "qa"
    assert body["detail"]["message"].startswith("Validation failed for lane 'qa'")
    assert isinstance(body["detail"]["errors"], list)
    assert any(
        e["loc"] == ["coverage_pct"] for e in body["detail"]["errors"]
    )


def test_complete_returns_422_with_per_field_loc(fresh_db):
    """Multiple bad fields should all appear in detail.errors[].loc."""
    handoff = _create_and_accept("qa", headers=fresh_db)
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/complete",
        json={"actor": "tester", "payload": {}},  # both required fields missing
        headers=fresh_db,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["lane"] == "qa"
    locs = {tuple(e["loc"]) for e in body["detail"]["errors"]}
    assert ("test_results",) in locs
    assert ("coverage_pct",) in locs


def test_complete_existing_422_value_error_unchanged(fresh_db):
    """Legacy ValueError path (status check) still returns a string detail."""
    # Create a handoff but DO NOT accept it — completion must 422 with
    # a string detail (legacy ValueError), not the new structured dict.
    create = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {"diff_summary": "x"}},
        headers=fresh_db,
    )
    assert create.status_code == 201
    handoff = create.json()
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/complete",
        json={"actor": "tester", "payload": {"diff_summary": "x"}},
        headers=fresh_db,
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "cannot complete" in detail.lower()


# ---------------------------------------------------------------------------
# Advance endpoint — gating tests
# ---------------------------------------------------------------------------

def test_advance_rejects_non_approved_handoff(fresh_db):
    """Advance requires status='approved'; pending/accepted/in_progress should 422."""
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="review",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    asyncio.run(svc.complete(
        handoff_id=handoff["id"],
        actor="bob",
        payload={"reviewer": "carol", "decision": "approve", "approver": "lead-dev"},
    ))
    # Status is "completed" (not "approved") — advance should fail
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/advance",
        json={"actor": "carol"},
        headers=fresh_db,
    )
    assert response.status_code == 422
    assert "not approved" in response.json()["detail"].lower()


def test_advance_on_already_reviewed_does_not_duplicate(fresh_db):
    """After approve (which auto-creates next handoff), advance must not create another."""
    import asyncio
    svc = HandoffService()
    # Create a handoff to review lane, complete it, then approve it.
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane="frontend",
        to_lane="review",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    asyncio.run(svc.complete(
        handoff_id=handoff["id"],
        actor="bob",
        payload={"reviewer": "carol", "decision": "approve", "approver": "lead-dev"},
    ))
    # Approve — this auto-creates the next handoff via routing.
    review_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=fresh_db,
    )
    assert review_resp.status_code == 200
    routing = review_resp.json()["routing"]
    assert routing["action"] == "approve"
    assert routing["next_handoff"] is not None
    first_next_id = routing["next_handoff"]["id"]

    # Now attempt advance on the same handoff — should fail (status is "approved"
    # but the endpoint must guard against double-advance).
    advance_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/advance",
        json={"actor": "carol"},
        headers=fresh_db,
    )
    # The advance endpoint should either 422 (already has next) or succeed idempotently.
    # Either way, verify no duplicate handoff was created.
    handoffs_after = client.get(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs"
    ).json()["handoffs"]
    delivery_handoffs = [h for h in handoffs_after if h["toLane"] == "delivery"]
    assert len(delivery_handoffs) == 1, (
        f"Expected exactly 1 delivery handoff, got {len(delivery_handoffs)} — "
        "approve auto-route + advance created a duplicate"
    )
    assert delivery_handoffs[0]["id"] == first_next_id


def test_approve_auto_creates_next_handoff(fresh_db):
    """Verify approve routing creates the next handoff in one step (no advance needed)."""
    import asyncio
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane="backend",
        to_lane="review",
        payload={},
        created_by="alice",
    ))
    asyncio.run(svc.accept(handoff["id"], actor="bob"))
    asyncio.run(svc.complete(
        handoff_id=handoff["id"],
        actor="bob",
        payload={"reviewer": "carol", "decision": "approve", "approver": "lead-dev"},
    ))
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-api-1/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=fresh_db,
    )
    assert response.status_code == 200
    body = response.json()
    # Review created next handoff automatically
    assert body["routing"]["action"] == "approve"
    next_h = body["routing"]["next_handoff"]
    assert next_h is not None
    assert next_h["toLane"] == "delivery"
    assert next_h["fromLane"] == "review"
    assert next_h["status"] == "pending"
    # The original handoff is now "approved"
    assert body["handoff"]["status"] == "approved"
    assert body["handoff"]["decision"] == "approve"
