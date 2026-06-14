"""Tests for the handoff review gate endpoint."""
import asyncio
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
    """Point the engine at a fresh SQLite file, enable FK enforcement, and seed a parent issue."""
    db_path = tmp_path / "test_handoff_review.db"
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

    async def _setup():
        from api.v1.endpoints.auth import hash_password, create_jwt_token
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Seed a parent issue that all tests can reference.
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-review-1",
                key="DEV-200",
                title="review test issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        # Create a test user for JWT auth on write endpoints.
        async with new_sessionmaker() as session:
            result = await session.execute(sa_select(UserModel).where(UserModel.username == "testuser"))
            if not result.scalar_one_or_none():
                pwd_hash, _ = hash_password("testpass123")
                session.add(UserModel(
                    id="user_test_1",
                    username="testuser",
                    email="test@example.com",
                    password_hash=pwd_hash,
                    role="admin",
                    created_at=now,
                    updated_at=now,
                ))
                await session.commit()
        token, _ = create_jwt_token("user_test_1", "testuser")
        db_module._db_initialized = True
        return {"Authorization": f"Bearer {token}"}

    headers = asyncio.run(_setup())
    yield {"headers": headers}
    new_engine.sync_engine.dispose()


def _create_and_complete_handoff(client, *, to_lane="review", from_lane="frontend"):
    """Create, accept, and complete a handoff for testing review decisions.

    For the review lane, the completion payload requires: reviewer, decision, approver.
    For other lanes, a minimal payload is used.
    """
    svc = HandoffService()

    # Create
    handoff = asyncio.run(svc.create(
        issue_id="issue-review-1",
        board_id="board-default",
        from_lane=from_lane,
        to_lane=to_lane,
        payload={},
        created_by="alice",
    ))

    # Accept
    asyncio.run(svc.accept(handoff["id"], actor="bob"))

    # Complete — use lane-appropriate payload.
    if to_lane == "review":
        payload = {
            "reviewer": "carol",
            "decision": "approve",
            "approver": "lead-dev",
        }
    elif to_lane == "frontend":
        payload = {"diff_summary": "done", "screenshots": []}
    elif to_lane == "qa":
        payload = {"test_results": "passed", "coverage_pct": 85, "approver": "lead-dev"}
    else:
        payload = {}

    asyncio.run(svc.complete(
        handoff_id=handoff["id"],
        actor="bob",
        payload=payload,
    ))

    return handoff


# ---------------------------------------------------------------------------
# Review endpoint — happy paths
# ---------------------------------------------------------------------------


def test_review_approve_sets_decision_and_status(fresh_db):
    """Approving a completed handoff sets decision='approve' and routes to next lane."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client)

    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    h = body["handoff"]
    assert h["status"] == "approved"
    assert h["decision"] == "approve"
    assert h["reviewedBy"] == "carol"
    assert h["reviewedAt"] is not None
    assert h["reviewComment"] is None
    # Approve: routes to first next_lane (delivery for review lane)
    assert body["routing"]["action"] == "approve"
    assert body["routing"]["next_lane"] == "delivery"
    next_h = body["routing"]["next_handoff"]
    assert next_h is not None
    assert next_h["toLane"] == "delivery"
    assert next_h["fromLane"] == "review"
    assert next_h["status"] == "pending"


def test_review_reject_sets_decision_and_routes_to_triage(fresh_db):
    """Rejecting creates a new handoff to triage with rejection context."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client, from_lane="frontend")

    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "reject", "actor": "carol", "comment": "Needs more work"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    h = body["handoff"]
    assert h["status"] == "rejected"
    assert h["decision"] == "reject"
    assert h["reviewedBy"] == "carol"
    assert h["reviewComment"] == "Needs more work"
    assert h["reviewedAt"] is not None
    # Reject: auto-routes to triage
    assert body["routing"]["action"] == "reject"
    assert body["routing"]["next_lane"] == "triage"
    next_h = body["routing"]["next_handoff"]
    assert next_h is not None
    assert next_h["toLane"] == "triage"
    assert next_h["fromLane"] == "review"
    assert next_h["status"] == "pending"
    assert next_h["payload"]["rejection_reason"] == "Needs more work"
    assert next_h["payload"]["rejected_from_lane"] == "frontend"


def test_review_request_changes_creates_rework_handoff(fresh_db):
    """Requesting changes creates a rework handoff back to the originating lane."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client, from_lane="backend")

    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "request_changes", "actor": "carol", "comment": "Fix tests"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    h = body["handoff"]
    assert h["status"] == "rework"
    assert h["decision"] == "request_changes"
    # Rework: auto-routes back to backend
    assert body["routing"]["action"] == "rework"
    assert body["routing"]["next_lane"] == "backend"
    next_h = body["routing"]["next_handoff"]
    assert next_h is not None
    assert next_h["toLane"] == "backend"
    assert next_h["fromLane"] == "review"
    assert next_h["status"] == "pending"
    assert next_h["payload"]["rework_reason"] == "Fix tests"
    assert next_h["payload"]["rework_from_review"] == handoff["id"]


def test_review_reject_without_from_lane_routes_to_triage(fresh_db):
    """Reject/rework with from_lane=None routes to triage."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client, from_lane=None)

    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "reject", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    h = body["handoff"]
    assert h["status"] == "rejected"
    assert h["decision"] == "reject"
    # Routes to triage
    assert body["routing"]["action"] == "reject"
    assert body["routing"]["next_lane"] == "triage"
    next_h = body["routing"]["next_handoff"]
    assert next_h["toLane"] == "triage"
    assert next_h["payload"]["rejected_from_lane"] is None


# ---------------------------------------------------------------------------
# Review endpoint — error cases
# ---------------------------------------------------------------------------


def test_review_reject_on_already_reviewed_handoff_fails(fresh_db):
    """Cannot review a handoff that already has a decision."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client)

    # First review succeeds
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 200

    # Second review should fail with 422
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "reject", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "already reviewed" in response.json()["detail"].lower()


def test_review_on_non_completed_handoff_fails(fresh_db):
    """Cannot review a handoff that is not in 'completed' status."""
    headers = fresh_db["headers"]
    svc = HandoffService()
    handoff = asyncio.run(svc.create(
        issue_id="issue-review-1",
        board_id="board-default",
        from_lane=None,
        to_lane="review",
        payload={},
        created_by="alice",
    ))
    # Handoff is still "pending" — review requires "completed"
    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "cannot review" in response.json()["detail"].lower()


def test_review_with_invalid_decision_fails(fresh_db):
    """Invalid decision value is rejected by Pydantic validation."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client)

    response = client.post(
        f"/api/v1/boards/board-default/issues/issue-review-1/handoffs/{handoff['id']}/review",
        json={"decision": "maybe", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Review endpoint — ownership validation
# ---------------------------------------------------------------------------


def test_review_not_found(fresh_db):
    """Reviewing a non-existent handoff returns 404."""
    headers = fresh_db["headers"]
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-review-1/handoffs/h_nonexistent/review",
        json={"decision": "approve", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 404


def test_review_wrong_issue_returns_404(fresh_db):
    """Review with a valid handoff but wrong issue_id should 404."""
    headers = fresh_db["headers"]
    handoff = _create_and_complete_handoff(client)

    response = client.post(
        f"/api/v1/boards/board-default/issues/wrong-issue/handoffs/{handoff['id']}/review",
        json={"decision": "approve", "actor": "carol"},
        headers=headers,
    )
    assert response.status_code == 404
