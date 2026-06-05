"""Snake Game Pilot — end-to-end handoff chain test.

T7: Seed a "Build Snake Game" issue
T8: Run the full handoff chain: product → frontend → qa → review → delivery
T10: Verify ECC job creation and safe-runner execution
"""

import pytest
from typing import Optional
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event, select as sa_select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, User as UserModel


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB for pilot tests."""
    db_path = tmp_path / "test_snake_pilot.db"
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
        db_module._db_initialized = True

        from api.v1.endpoints.auth import hash_password, create_jwt_token

        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            result = await session.execute(
                sa_select(UserModel).where(UserModel.username == "testuser")
            )
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
        return {"Authorization": f"Bearer {token}"}

    headers = asyncio.run(_setup())
    yield headers
    new_engine.sync_engine.dispose()


BOARD = "board-default"


def _create_issue(title: str, headers: dict) -> dict:
    """Create an issue and return the response body."""
    resp = client.post("/api/v1/issues", json={
        "title": title,
        "description": f"Test: {title}",
        "status": "backlog",
        "priority": "medium",
        "profile": "frontend",
    }, headers=headers)
    assert resp.status_code in (200, 201), f"create issue failed: {resp.text}"
    return resp.json()


def _create_handoff(issue_id: str, to_lane: str, payload: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    resp = client.post(
        f"/api/v1/boards/{BOARD}/issues/{issue_id}/handoffs",
        json={"toLane": to_lane, "payload": payload or {}},
        headers=headers,
    )
    assert resp.status_code == 201, f"create handoff to {to_lane} failed: {resp.text}"
    return resp.json()


def _accept_handoff(issue_id: str, handoff_id: str, headers: Optional[dict] = None) -> dict:
    resp = client.post(
        f"/api/v1/boards/{BOARD}/issues/{issue_id}/handoffs/{handoff_id}/accept",
        json={"actor": "user"},
        headers=headers,
    )
    assert resp.status_code == 200, f"accept handoff failed: {resp.text}"
    return resp.json()


def _dispatch_handoff(issue_id: str, handoff_id: str, issue_key: str, headers: Optional[dict] = None) -> dict:
    resp = client.post(
        f"/api/v1/boards/{BOARD}/issues/{issue_id}/handoffs/{handoff_id}/dispatch",
        json={"issueKey": issue_key, "profile": "frontend", "actor": "user"},
        headers=headers,
    )
    assert resp.status_code == 200, f"dispatch handoff failed: {resp.text}"
    return resp.json()


def _complete_handoff(issue_id: str, handoff_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    resp = client.post(
        f"/api/v1/boards/{BOARD}/issues/{issue_id}/handoffs/{handoff_id}/complete",
        json={"actor": "user", "payload": payload or {}},
        headers=headers,
    )
    assert resp.status_code == 200, f"complete handoff failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# T7: Create Snake Game issue
# ---------------------------------------------------------------------------

def test_snake_create_issue(fresh_db):
    """Seed a 'Build Snake Game' issue via the API."""
    headers = fresh_db
    body = _create_issue("Build Snake Game", headers=headers)
    assert body["title"] == "Build Snake Game"
    assert body["status"] == "backlog"
    assert body["key"].startswith("DEV-")


# ---------------------------------------------------------------------------
# T8: Handoff chain — product → frontend → qa → review → delivery
# ---------------------------------------------------------------------------

def test_snake_full_handoff_chain(fresh_db):
    """Run the complete handoff chain for the Snake Game issue.

    Lanes requiring human approval (product, architect, qa, review, delivery)
    must include an 'approver' field in the payload before dispatch.
    """
    headers = fresh_db
    issue = _create_issue("Build Snake Game", headers=headers)
    issue_id = issue["id"]
    issue_key = issue["key"]

    # --- Step 1: product → frontend (dispatch creates ECC job) ---
    h1 = _create_handoff(issue_id, "product", {
        "acceptance_criteria": "Playable snake game with score display",
        "approver": "user",
    }, headers=headers)
    assert h1["status"] == "pending"
    h1_accepted = _accept_handoff(issue_id, h1["id"], headers=headers)
    assert h1_accepted["status"] == "accepted"
    h1_dispatched = _dispatch_handoff(issue_id, h1["id"], issue_key, headers=headers)
    assert h1_dispatched["handoff"]["status"] == "in_progress"
    assert "job" in h1_dispatched
    assert h1_dispatched["job"]["id"].startswith("ecc_")
    h1_completed = _complete_handoff(issue_id, h1["id"], {
        "acceptance_criteria": ["Snake game is playable", "Score is displayed"],
    }, headers=headers)
    assert h1_completed["status"] == "completed"

    # --- Step 2: frontend → qa (frontend requires diff_summary + screenshots) ---
    h2 = _create_handoff(issue_id, "frontend", {
        "diff_summary": "Snake game ready for QA",
    }, headers=headers)
    h2_accepted = _accept_handoff(issue_id, h2["id"], headers=headers)
    assert h2_accepted["status"] == "accepted"
    h2_completed = _complete_handoff(issue_id, h2["id"], {
        "diff_summary": "Created snake game",
        "screenshots": ["snake-game.png"],
    }, headers=headers)
    assert h2_completed["status"] == "completed"

    # --- Step 3: qa → review (qa requires test_results + coverage_pct + approver) ---
    h3 = _create_handoff(issue_id, "qa", {
        "test_results": "All manual tests pass",
        "coverage_pct": 85,
        "approver": "user",
    }, headers=headers)
    h3_accepted = _accept_handoff(issue_id, h3["id"], headers=headers)
    assert h3_accepted["status"] == "accepted"
    h3_completed = _complete_handoff(issue_id, h3["id"], {
        "test_results": "All manual tests pass",
        "coverage_pct": 85,
    }, headers=headers)
    assert h3_completed["status"] == "completed"

    # --- Step 4: review → delivery (review requires reviewer + decision + approver) ---
    h4 = _create_handoff(issue_id, "review", {
        "reviewer": "user",
        "decision": "approve",
        "approver": "user",
    }, headers=headers)
    h4_accepted = _accept_handoff(issue_id, h4["id"], headers=headers)
    assert h4_accepted["status"] == "accepted"
    h4_completed = _complete_handoff(issue_id, h4["id"], {
        "reviewer": "user",
        "decision": "approve",
    }, headers=headers)
    assert h4_completed["status"] == "completed"

    # --- Verify all handoffs completed ---
    list_resp = client.get(f"/api/v1/boards/{BOARD}/issues/{issue_id}/handoffs")
    assert list_resp.status_code == 200
    handoffs = list_resp.json()["handoffs"]
    assert len(handoffs) == 4
    assert all(h["status"] == "completed" for h in handoffs)


def test_snake_dispatch_creates_job(fresh_db):
    """Dispatch handoff creates an ECC job with safe-runner harness."""
    headers = fresh_db
    issue = _create_issue("Snake Job Test", headers=headers)
    issue_id = issue["id"]
    issue_key = issue["key"]

    h = _create_handoff(issue_id, "frontend", headers=headers)
    _accept_handoff(issue_id, h["id"], headers=headers)
    result = _dispatch_handoff(issue_id, h["id"], issue_key, headers=headers)

    job = result["job"]
    assert job["id"].startswith("ecc_")
    assert job["harness"] == "safe-runner"
    assert job["status"] in ("queued", "running", "review_required")
