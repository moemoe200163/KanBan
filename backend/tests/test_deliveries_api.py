"""Tests for /api/v1/deliveries — read-only cross-issue view of issue_artifacts.

Auth is intentionally open in this iteration (調研階段先快上), so no
JWT header is needed.
"""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel, IssueArtifact


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with one parent issue and a few issue_artifacts."""
    db_path = tmp_path / "test_deliveries.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

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
            # Two issues
            for issue_id, key in [("issue-del-1", "DEV-100"), ("issue-del-2", "DEV-101")]:
                session.add(IssueModel(
                    id=issue_id, key=key, title=f"issue {key}", description="",
                    status="done", priority="medium", board_id="board-default",
                    created_at=now, updated_at=now,
                ))
            # Four IssueArtifacts (deliveries)
            artifacts = [
                ("da-1", "issue-del-1", "screenshot",     "handoff_complete", "Login page",  "summary 1"),
                ("da-2", "issue-del-1", "test_log",       "dispatch",          "Test output", "summary 2"),
                ("da-3", "issue-del-2", "pr_link",        "handoff_complete", "PR #42",      "summary 3"),
                ("da-4", "issue-del-2", "diff_summary",   "dispatch",          "Diff",        "summary 4"),
            ]
            for iid, iss, atype, src, title, summ in artifacts:
                session.add(IssueArtifact(
                    id=iid, issue_id=iss, job_id=None,
                    title=title, artifact_type=atype, source=src,
                    path_or_url=f"https://example.com/{iid}",
                    sensitivity="public", summary=summ, extra_data={},
                    created_at=now, board_id="board-default",
                ))
            await session.commit()
    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


def _items(resp):
    return resp.json()["items"]


def test_list_all_deliveries(fresh_db):
    resp = client.get("/api/v1/deliveries")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 4
    assert body["missingIssues"] == 0
    # All four have enriched issue fields
    for it in body["items"]:
        assert it["issueKey"] in ("DEV-100", "DEV-101")
        assert it["issueTitle"].startswith("issue ")
        assert it["issueStatus"] == "done"


def test_filter_by_issue_id(fresh_db):
    resp = client.get("/api/v1/deliveries?issue_id=issue-del-1").json()
    assert resp["count"] == 2
    assert all(i["issueKey"] == "DEV-100" for i in resp["items"])


def test_filter_by_artifact_type(fresh_db):
    resp = client.get("/api/v1/deliveries?artifact_type=screenshot").json()
    assert resp["count"] == 1
    assert resp["items"][0]["title"] == "Login page"


def test_filter_by_source(fresh_db):
    resp = client.get("/api/v1/deliveries?source=handoff_complete").json()
    assert resp["count"] == 2
    assert all(i["source"] == "handoff_complete" for i in resp["items"])


def test_types_endpoint(fresh_db):
    resp = client.get("/api/v1/deliveries/types").json()
    assert resp["types"] == ["diff_summary", "pr_link", "screenshot", "test_log"]
    assert resp["count"] == 4


def test_sources_endpoint(fresh_db):
    resp = client.get("/api/v1/deliveries/sources").json()
    assert resp["sources"] == ["dispatch", "handoff_complete"]


def test_blob_excluded_from_payload(fresh_db):
    """Deliveries payload must never include the underlying binary.
    /deliveries is metadata-only by design; users go to /artifacts
    to grab the actual file blob."""
    resp = client.get("/api/v1/deliveries")
    for it in resp.json()["items"]:
        # The IssueArtifact.to_dict doesn't have a 'content' field, so
        # this is more of a smoke check — the field must simply be
        # absent (the deliveries enrichment shouldn't add it).
        assert "content" not in it
        assert "blob" not in it


def test_missing_issue_handled_gracefully(fresh_db):
    """An IssueArtifact that points to a deleted issue should still
    appear in the list (with null issue fields), not 500."""
    import asyncio
    async def _orphan():
        # Add a new IssueArtifact that references a nonexistent issue
        async with db_module.AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            session.add(IssueArtifact(
                id="da-orphan", issue_id="issue-deleted", job_id=None,
                title="Ghost", artifact_type="file", source="dispatch",
                path_or_url=None, sensitivity="public", summary="",
                extra_data={}, created_at=now, board_id="board-default",
            ))
            await session.commit()
    asyncio.run(_orphan())

    resp = client.get("/api/v1/deliveries").json()
    assert resp["count"] == 5
    assert resp["missingIssues"] == 1
    orphan = next(i for i in resp["items"] if i["id"] == "da-orphan")
    assert orphan["issueKey"] is None
    assert orphan["issueTitle"] is None
    assert orphan["issueStatus"] is None
