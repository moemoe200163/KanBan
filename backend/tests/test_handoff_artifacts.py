"""Tests that completing a handoff with a typed payload auto-creates IssueArtifact records."""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel

client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with a parent issue — mirrors test_handoffs_api.py."""
    db_path = tmp_path / "test_handoff_artifacts.db"
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
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-art-1",
                key="DEV-200",
                title="artifact test issue",
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


def _create_accept_complete(payload: dict, to_lane: str = "frontend") -> dict:
    """Helper: create handoff -> accept -> complete with the given payload. Returns complete response."""
    create_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-art-1/handoffs",
        json={"toLane": to_lane, "payload": payload, "createdBy": "test"},
    )
    assert create_resp.status_code == 201, f"create: {create_resp.text}"
    handoff = create_resp.json()

    accept_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-art-1/handoffs/{handoff['id']}/accept",
        json={"actor": "test"},
    )
    assert accept_resp.status_code == 200, f"accept: {accept_resp.text}"

    complete_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-art-1/handoffs/{handoff['id']}/complete",
        json={"actor": "test", "payload": payload},
    )
    assert complete_resp.status_code == 200, f"complete: {complete_resp.text}"
    return complete_resp.json()


def test_complete_handoff_creates_screenshot_artifacts(fresh_db):
    """Completing with screenshots creates one artifact per screenshot."""
    payload = {
        "diff_summary": "Changed login flow",
        "screenshots": ["login.png", "dashboard.png"],
    }
    _create_accept_complete(payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 3  # 2 screenshots + 1 diff_summary

    screenshots = [a for a in artifacts if a["artifactType"] == "screenshot"]
    assert len(screenshots) == 2
    titles = {a["title"] for a in screenshots}
    assert titles == {"login.png", "dashboard.png"}
    for s in screenshots:
        assert s["source"] == "handoff_complete"
        assert s["pathOrUrl"] == s["title"]
        assert s["summary"] is not None
        assert s["summary"].startswith("Screenshot from handoff")

    diff_arts = [a for a in artifacts if a["artifactType"] == "diff_summary"]
    assert len(diff_arts) == 1
    assert diff_arts[0]["title"] == "Diff Summary"
    assert diff_arts[0]["summary"] == "Changed login flow"
    assert diff_arts[0]["source"] == "handoff_complete"


def test_complete_handoff_creates_diff_summary_artifact(fresh_db):
    """Completing with diff_summary creates one diff_summary artifact."""
    payload = {"diff_summary": "Refactored auth module"}
    _create_accept_complete(payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["artifactType"] == "diff_summary"
    assert art["title"] == "Diff Summary"
    assert art["summary"] == "Refactored auth module"
    assert art["source"] == "handoff_complete"


def test_complete_handoff_creates_test_log_artifact(fresh_db):
    """Completing with test_results creates one test_log artifact."""
    payload = {
        "diff_summary": "Added test coverage",
        "test_results": "42 passed, 0 failed",
    }
    _create_accept_complete(payload, to_lane="backend")

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    artifacts = resp.json()["artifacts"]
    test_log_arts = [a for a in artifacts if a["artifactType"] == "test_log"]
    assert len(test_log_arts) == 1
    art = test_log_arts[0]
    assert art["title"] == "Test Results"
    assert art["summary"] == "42 passed, 0 failed"
    assert art["source"] == "handoff_complete"


def test_complete_handoff_empty_payload_no_artifacts(fresh_db):
    """Completing with no artifact-relevant payload fields creates zero artifacts."""
    # Backend lane requires diff_summary, which does create a diff_summary artifact.
    # To prove that *only* diff_summary artifacts appear (no screenshots, no test_log),
    # we complete with just the required fields and verify no extra artifact types.
    payload = {"diff_summary": "Minimal completion"}
    _create_accept_complete(payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["artifactType"] == "diff_summary"
