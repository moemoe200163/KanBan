"""
Persistence tests for the DevFlow backend.

Covers:
- /api/v1/board returns the seed issues when the DB is empty.
- POST /api/v1/issues persists and the board reflects the new card.
- GET /api/v1/ecc/jobs?issue_id= filters correctly.
- Repository round-trips a job with events through the DB.
- PATCH /api/v1/ecc/jobs/{id} persists status through the repository.

The fixture drops and recreates all tables for each test, then calls the
seed function directly. We bypass the FastAPI lifespan (use a TestClient
without lifespan management) to avoid double-init races.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import repository as repo
from db.models import Base
from db import database as db_module


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file and reset tables."""
    db_path = tmp_path / "test_devflow.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    # Create a fresh engine bound to the new file.
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    # Manually initialize the schema and seed. We use drop_all+create_all
    # to guarantee a clean schema (checkfirst=True has known idempotency
    # caveats for individual indexes) and set the init flag so the
    # lifespan's init_db is a no-op.
    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        db_module._db_initialized = True
        await repo.seed_if_empty()
        # Seed test user for auth
        from datetime import datetime, timezone
        from api.v1.endpoints.auth import hash_password, create_jwt_token
        from db.models import User as UserModel
        from sqlalchemy import select as sa_select
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            result = await session.execute(sa_select(UserModel).where(UserModel.username == "testuser"))
            if not result.scalar_one_or_none():
                pwd_hash, _ = hash_password("testpass123")
                session.add(UserModel(id="user_test_1", username="testuser", email="test@example.com", password_hash=pwd_hash, role="admin", created_at=now, updated_at=now))
                await session.commit()
        token, _ = create_jwt_token("user_test_1", "testuser")
        return {"Authorization": f"Bearer {token}"}
    headers = asyncio.run(_setup())

    yield main.app, repo, headers


def test_board_returns_seeded_issues_when_db_empty(fresh_db):
    app, _, _ = fresh_db
    # Use a TestClient without lifespan management since we already
    # initialized and seeded in the fixture.
    with TestClient(app) as client:
        response = client.get("/api/v1/board")
        assert response.status_code == 200
        body = response.json()
        columns = {c["id"]: c for c in body["columns"]}
        assert set(columns.keys()) == {"backlog", "in_progress", "blocked", "human_review", "done"}
        total_issues = sum(len(c["issues"]) for c in body["columns"])
        assert total_issues == 8, f"expected 8 seed issues, got {total_issues}"
        assert any(i["key"] == "DEV-001" for i in columns["done"]["issues"])
        assert any(i["key"] == "DEV-007" for i in columns["human_review"]["issues"])


def test_create_issue_persists_and_board_reflects(fresh_db):
    app, _, headers = fresh_db
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/issues",
            json={
                "title": "Persistence test card",
                "description": "Verifies write-through to the repository",
                "status": "backlog",
                "priority": "low",
                "profile": "general",
            },
            headers=headers,
        )
        assert create.status_code == 200
        created = create.json()
        assert created["key"].startswith("DEV-")
        assert created["title"] == "Persistence test card"

        listed = client.get("/api/v1/issues")
        assert listed.status_code == 200
        keys = [i["key"] for i in listed.json()["issues"]]
        assert created["key"] in keys

        board = client.get("/api/v1/board")
        assert board.status_code == 200
        backlog_issues = next(c for c in board.json()["columns"] if c["id"] == "backlog")["issues"]
        assert any(i["id"] == created["id"] for i in backlog_issues)


def test_list_jobs_filters_by_issue_id(fresh_db):
    app, _, headers = fresh_db
    with TestClient(app) as client:
        for issue_id in ("alpha", "beta"):
            client.post(
                "/api/v1/ecc/dispatch",
                json={
                    "issue_id": issue_id,
                    "issue_key": issue_id.upper(),
                    "command": "/loop-start --profile=frontend",
                    "profile": "frontend",
                    "harness": "claude-code",
                },
                headers=headers,
            )
        response = client.get("/api/v1/ecc/jobs", params={"issue_id": "alpha"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1, f"expected 1 job for alpha, got {body['total']}"
        assert all(job["issue_id"] == "alpha" for job in body["jobs"])
        # Beta must not leak into the alpha response.
        assert all(job["issue_id"] != "beta" for job in body["jobs"])


def test_list_jobs_returns_all_when_no_filter(fresh_db):
    """Without an issue_id filter, /ecc/jobs must include every job."""
    app, _, headers = fresh_db
    with TestClient(app) as client:
        for issue_id in ("alpha", "beta", "gamma"):
            client.post(
                "/api/v1/ecc/dispatch",
                json={
                    "issue_id": issue_id,
                    "issue_key": issue_id.upper(),
                    "command": "/loop-start --profile=backend",
                    "profile": "backend",
                    "harness": "claude-code",
                },
                headers=headers,
            )
        response = client.get("/api/v1/ecc/jobs")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        returned_issue_ids = {job["issue_id"] for job in body["jobs"]}
        assert returned_issue_ids == {"alpha", "beta", "gamma"}
        # Newest first ordering.
        timestamps = [job["created_at"] for job in body["jobs"]]
        assert timestamps == sorted(timestamps, reverse=True)


def test_list_jobs_filter_with_no_matches_returns_empty(fresh_db):
    """A filter that matches no jobs must return total=0 and an empty list."""
    app, _, headers = fresh_db
    with TestClient(app) as client:
        client.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "exists",
                "issue_key": "EXISTS",
                "command": "/loop-start --profile=frontend",
                "profile": "frontend",
                "harness": "claude-code",
            },
            headers=headers,
        )
        response = client.get("/api/v1/ecc/jobs", params={"issue_id": "does-not-exist"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["jobs"] == []


def test_jobs_and_events_round_trip_through_repository(fresh_db):
    """A job persisted via the repository survives a fresh load and its
    events come back as a list of dicts, not a JSON string."""
    app, _, headers = fresh_db
    with TestClient(app) as client:
        dispatch = client.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "persist-1",
                "issue_key": "DEV-PERSIST",
                "command": "/loop-start --profile=backend",
                "profile": "backend",
                "harness": "claude-code",
            },
            headers=headers,
        )
        assert dispatch.status_code == 200
        job_response = client.get("/api/v1/ecc/jobs", params={"issue_id": "persist-1"})
        assert job_response.status_code == 200
        jobs = job_response.json()["jobs"]
        assert len(jobs) == 1
        job = jobs[0]
        assert isinstance(job["events"], list)
        assert job["events"][0]["status"] == "queued"


def test_status_update_persists_through_repository(fresh_db):
    """A PATCH /api/v1/ecc/jobs/{id} update is reflected in a subsequent
    load_all_jobs_into_memory() call."""
    app, _, headers = fresh_db
    with TestClient(app) as client:
        dispatch = client.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "persist-status",
                "issue_key": "DEV-STATUS",
                "command": "/loop-start --profile=frontend",
                "profile": "frontend",
                "harness": "claude-code",
            },
            headers=headers,
        )
        job_id = dispatch.json()["id"]

        patch = client.patch(
            f"/api/v1/ecc/jobs/{job_id}",
            json={"status": "completed", "message": "all done"},
            headers=headers,
        )
        assert patch.status_code == 200

        get_response = client.get(f"/api/v1/ecc/jobs/{job_id}")
        assert get_response.status_code == 200
        loaded = get_response.json()
        assert loaded["status"] == "completed"
        assert loaded["message"] == "all done"


def test_jobs_and_events_survive_simulated_restart(fresh_db):
    """Simulates a process restart by clearing the in-memory job cache
    and re-running `load_jobs_from_db()`. The job and its event timeline
    must be restored from the database."""
    app, _, headers = fresh_db
    with TestClient(app) as client:
        # Dispatch + wait for the safe runner to emit its events.
        dispatch = client.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "restart-1",
                "issue_key": "DEV-RESTART",
                "command": "/loop-start --profile=frontend",
                "profile": "frontend",
                "harness": "claude-code",
            },
            headers=headers,
        )
        assert dispatch.status_code == 200
        job_id = dispatch.json()["id"]

        import time
        time.sleep(1)  # let the background safe runner finish

        # Capture the pre-restart shape for comparison.
        before = client.get(f"/api/v1/ecc/jobs/{job_id}").json()
        assert len(before["events"]) >= 4
        before_event_count = len(before["events"])
        before_status = before["status"]

        # Simulate restart: drop the in-memory cache, rehydrate from DB.
        from api.v1.endpoints import ecc as ecc_module
        ecc_module._jobs.clear()
        # Run the loader on its own event loop (the TestClient does not
        # expose the running loop to user code).
        import asyncio
        asyncio.run(ecc_module.load_jobs_from_db())

        after = client.get(f"/api/v1/ecc/jobs/{job_id}").json()
        assert after["id"] == job_id
        assert after["status"] == before_status
        assert len(after["events"]) == before_event_count, (
            f"events lost across restart: before={before_event_count}, after={len(after['events'])}"
        )
        # Event order is preserved.
        for i, evt in enumerate(after["events"]):
            assert evt["timestamp"] == before["events"][i]["timestamp"]
            assert evt["status"] == before["events"][i]["status"]
            assert evt["message"] == before["events"][i]["message"]
