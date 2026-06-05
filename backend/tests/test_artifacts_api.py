"""Tests for the artifact CRUD API endpoints (GET/POST /issues/{id}/artifacts)."""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel, User as UserModel
from api.v1.endpoints.auth import hash_password, create_jwt_token


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with a parent issue."""
    db_path = tmp_path / "test_artifacts_api.db"
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
                id="issue-art-api-1",
                key="DEV-300",
                title="artifact api test issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        # Create test user for JWT auth on write endpoints
        from sqlalchemy import select as sa_select
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
        headers = {"Authorization": f"Bearer {token}"}
        return headers

    headers = asyncio.run(_setup())
    yield headers
    new_engine.sync_engine.dispose()


# ---------------------------------------------------------------------------
# POST /issues/{id}/artifacts — create
# ---------------------------------------------------------------------------

def test_create_artifact_happy_path(fresh_db):
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={
            "title": "Login screenshot",
            "artifactType": "screenshot",
            "pathOrUrl": "https://example.com/login.png",
            "source": "handoff_complete",
            "sensitivity": "public",
            "summary": "Login page after refactor",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("art-")
    assert body["title"] == "Login screenshot"
    assert body["artifactType"] == "screenshot"
    assert body["pathOrUrl"] == "https://example.com/login.png"
    assert body["source"] == "handoff_complete"
    assert body["sensitivity"] == "public"
    assert body["summary"] == "Login page after refactor"
    assert body["issueId"] == "issue-art-api-1"


def test_create_artifact_minimal_fields(fresh_db):
    """Only title and artifactType are required."""
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={
            "title": "Test log",
            "artifactType": "test_log",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Test log"
    assert body["artifactType"] == "test_log"
    assert body["pathOrUrl"] is None
    assert body["summary"] is None
    assert body["source"] is None
    assert body["sensitivity"] == "public"


def test_create_artifact_with_metadata(fresh_db):
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={
            "title": "PR link",
            "artifactType": "pr_link",
            "pathOrUrl": "https://github.com/org/repo/pull/42",
            "metadata": {"additions": 120, "deletions": 30},
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["metadata"] == {"additions": 120, "deletions": 30}


def test_create_artifact_records_timeline_event(fresh_db):
    """Creating an artifact should also create an artifact_added event."""
    headers = fresh_db
    client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={
            "title": "Design doc",
            "artifactType": "design_doc",
            "createdById": "user-1",
            "createdByName": "Alice",
        },
        headers=headers,
    )
    # Fetch events for this issue
    resp = client.get("/api/v1/issues/issue-art-api-1/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    artifact_events = [e for e in events if e["eventType"] == "artifact_added"]
    assert len(artifact_events) == 1
    assert artifact_events[0]["actorId"] == "user-1"
    assert "Design doc" in artifact_events[0]["summary"]


def test_create_artifact_404_for_nonexistent_issue(fresh_db):
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/nonexistent/artifacts",
        json={"title": "Ghost", "artifactType": "file"},
        headers=headers,
    )
    assert response.status_code == 404


def test_create_artifact_rejects_missing_title(fresh_db):
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={"artifactType": "file"},
        headers=headers,
    )
    assert response.status_code == 422


def test_create_artifact_rejects_missing_type(fresh_db):
    headers = fresh_db
    response = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={"title": "No type"},
        headers=headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /issues/{id}/artifacts — list
# ---------------------------------------------------------------------------

def test_list_artifacts_empty(fresh_db):
    response = client.get("/api/v1/issues/issue-art-api-1/artifacts")
    assert response.status_code == 200
    body = response.json()
    assert body["artifacts"] == []
    assert body["total"] == 0


def test_list_artifacts_returns_newest_first(fresh_db):
    """Artifacts should be ordered by created_at descending."""
    headers = fresh_db
    # Create two artifacts
    client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={"title": "First", "artifactType": "file"},
        headers=headers,
    )
    client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={"title": "Second", "artifactType": "screenshot"},
        headers=headers,
    )
    response = client.get("/api/v1/issues/issue-art-api-1/artifacts")
    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 2
    # Newest first — "Second" should be first
    assert artifacts[0]["title"] == "Second"
    assert artifacts[1]["title"] == "First"


def test_list_artifacts_with_limit(fresh_db):
    headers = fresh_db
    for i in range(5):
        client.post(
            "/api/v1/issues/issue-art-api-1/artifacts",
            json={"title": f"Artifact {i}", "artifactType": "file"},
            headers=headers,
        )
    response = client.get("/api/v1/issues/issue-art-api-1/artifacts?limit=3")
    assert response.status_code == 200
    body = response.json()
    assert len(body["artifacts"]) == 3
    assert body["total"] == 3  # total matches returned count (limit applied server-side)


def test_list_artifacts_404_for_nonexistent_issue(fresh_db):
    response = client.get("/api/v1/issues/nonexistent/artifacts")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Round-trip: create via POST, verify via GET
# ---------------------------------------------------------------------------

def test_create_then_list_roundtrip(fresh_db):
    """Full round-trip: POST artifact → GET list → verify fields."""
    headers = fresh_db
    create_resp = client.post(
        "/api/v1/issues/issue-art-api-1/artifacts",
        json={
            "title": "Coverage report",
            "artifactType": "test_log",
            "source": "handoff_complete",
            "summary": "85% coverage, 42 tests passed",
            "sensitivity": "internal",
            "createdById": "ci-bot",
            "createdByName": "CI Bot",
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    created = create_resp.json()

    list_resp = client.get("/api/v1/issues/issue-art-api-1/artifacts")
    assert list_resp.status_code == 200
    artifacts = list_resp.json()["artifacts"]
    assert len(artifacts) == 1

    listed = artifacts[0]
    assert listed["id"] == created["id"]
    assert listed["title"] == "Coverage report"
    assert listed["artifactType"] == "test_log"
    assert listed["source"] == "handoff_complete"
    assert listed["summary"] == "85% coverage, 42 tests passed"
    assert listed["sensitivity"] == "internal"
    assert listed["createdById"] == "ci-bot"
    assert listed["createdByName"] == "CI Bot"
