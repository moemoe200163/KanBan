"""Tests for the CI/PR webhook endpoints."""
import pytest
import hashlib
import hmac
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel, JobModel


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with an issue and an ECC job."""
    db_path = tmp_path / "test_webhooks_api.db"
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

    # Seed in-memory _jobs dict so _update_job_status_from_ci can find the job
    from api.v1.endpoints import ecc as ecc_module

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-wh-1",
                key="DEV-500",
                title="webhook test issue",
                description="",
                status="in_progress",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            session.add(JobModel(
                id="job-wh-1",
                issue_id="issue-wh-1",
                issue_key="DEV-500",
                command="test command",
                profile="general",
                harness="safe-runner",
                status="running",
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                events=[],
                board_id="board-default",
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())

    # Seed the in-memory _jobs dict
    now_str = datetime.now(timezone.utc).isoformat()
    from api.v1.endpoints.ecc import ECCDispatchJob
    ecc_module._jobs["job-wh-1"] = ECCDispatchJob(
        id="job-wh-1",
        issue_id="issue-wh-1",
        issue_key="DEV-500",
        command="test command",
        profile="general",
        harness="safe-runner",
        status="running",
        created_at=now_str,
        updated_at=now_str,
        events=[],
        board_id="board-default",
    )

    yield
    ecc_module._jobs.clear()
    new_engine.sync_engine.dispose()


# ---------------------------------------------------------------------------
# POST /webhooks/ci — CI webhook
# ---------------------------------------------------------------------------

def test_ci_webhook_happy_path(fresh_db):
    response = client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "build_success",
            "job_id": "job-wh-1",
            "metadata": {"message": "All tests passed"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["event_id"].startswith("wh_")
    assert "build_success" in body["message"]


def test_ci_webhook_build_failure(fresh_db):
    response = client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "build_failure",
            "job_id": "job-wh-1",
            "metadata": {"message": "Lint errors"},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_ci_webhook_invalid_event_type(fresh_db):
    response = client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "invalid_event",
            "job_id": "job-wh-1",
        },
    )
    assert response.status_code == 400
    assert "Invalid event_type" in response.json()["detail"]


def test_ci_webhook_updates_issue_ci_status(fresh_db):
    """build_success should update issue.ci_status to 'passed'."""
    client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "build_success",
            "job_id": "job-wh-1",
        },
    )
    # Background tasks run synchronously in TestClient.
    # Verify issue ci_status was updated.
    import asyncio
    from db import repository as repo

    issue = asyncio.run(repo.get_issue("issue-wh-1"))
    assert issue is not None
    assert issue["ciStatus"] == "passed"


def test_ci_webhook_failure_sets_failed_status(fresh_db):
    """build_failure should update issue.ci_status to 'failed'."""
    client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "build_failure",
            "job_id": "job-wh-1",
        },
    )
    import asyncio
    from db import repository as repo

    issue = asyncio.run(repo.get_issue("issue-wh-1"))
    assert issue["ciStatus"] == "failed"


def test_ci_webhook_unknown_job(fresh_db):
    """Webhook for unknown job should still return 200 (no crash)."""
    response = client.post(
        "/api/v1/webhooks/ci",
        json={
            "event_type": "build_success",
            "job_id": "nonexistent-job",
        },
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /webhooks/pr — PR webhook
# ---------------------------------------------------------------------------

def test_pr_webhook_happy_path(fresh_db):
    response = client.post(
        "/api/v1/webhooks/pr",
        json={
            "event_type": "pr_opened",
            "pr_number": 42,
            "title": "Fix login bug",
            "job_id": "job-wh-1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["event_id"].startswith("wh_")


def test_pr_webhook_invalid_event_type(fresh_db):
    response = client.post(
        "/api/v1/webhooks/pr",
        json={
            "event_type": "pr_approved",
            "pr_number": 1,
            "title": "Test",
            "job_id": "job-wh-1",
        },
    )
    assert response.status_code == 400
    assert "Invalid event_type" in response.json()["detail"]


def test_pr_webhook_updates_issue_pr_url(fresh_db):
    """pr_opened should update issue.pr_url."""
    client.post(
        "/api/v1/webhooks/pr",
        json={
            "event_type": "pr_opened",
            "pr_number": 42,
            "title": "Fix login bug",
            "job_id": "job-wh-1",
        },
    )
    import asyncio
    from db import repository as repo

    issue = asyncio.run(repo.get_issue("issue-wh-1"))
    assert issue is not None
    assert issue["prUrl"] is not None
    assert "pull/42" in issue["prUrl"]


def test_pr_webhook_merged_does_not_set_pr_url(fresh_db):
    """pr_merged should not set pr_url (only pr_opened does)."""
    client.post(
        "/api/v1/webhooks/pr",
        json={
            "event_type": "pr_merged",
            "pr_number": 42,
            "title": "Fix login bug",
            "job_id": "job-wh-1",
        },
    )
    import asyncio
    from db import repository as repo

    issue = asyncio.run(repo.get_issue("issue-wh-1"))
    assert issue["prUrl"] is None


def test_pr_webhook_unknown_job(fresh_db):
    """Webhook for unknown job should still return 200 (no crash)."""
    response = client.post(
        "/api/v1/webhooks/pr",
        json={
            "event_type": "pr_opened",
            "pr_number": 1,
            "title": "Test",
            "job_id": "nonexistent-job",
        },
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Webhook event persistence
# ---------------------------------------------------------------------------

def test_webhook_events_are_persisted(fresh_db):
    """Both CI and PR webhook events should be stored in the DB."""
    client.post(
        "/api/v1/webhooks/ci",
        json={"event_type": "build_success", "job_id": "job-wh-1"},
    )
    client.post(
        "/api/v1/webhooks/pr",
        json={"event_type": "pr_opened", "pr_number": 5, "title": "PR", "job_id": "job-wh-1"},
    )
    resp = client.get("/api/v1/webhooks/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 2
    event_types = {e["event_type"] for e in events}
    assert "ci_build_success" in event_types
    assert "pr_pr_opened" in event_types


def test_webhook_events_filter_by_type(fresh_db):
    client.post(
        "/api/v1/webhooks/ci",
        json={"event_type": "build_success", "job_id": "job-wh-1"},
    )
    client.post(
        "/api/v1/webhooks/pr",
        json={"event_type": "pr_opened", "pr_number": 5, "title": "PR", "job_id": "job-wh-1"},
    )
    resp = client.get("/api/v1/webhooks/events?event_type=ci_")
    assert resp.status_code == 200
    events = resp.json()
    assert all(e["event_type"].startswith("ci_") for e in events)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def test_ci_webhook_rejects_bad_signature(fresh_db, monkeypatch):
    """When WEBHOOK_SECRET is set, a bad signature should return 401."""
    monkeypatch.setattr("api.v1.endpoints.webhooks.WEBHOOK_SECRET", "test-secret-123")
    response = client.post(
        "/api/v1/webhooks/ci",
        json={"event_type": "build_success", "job_id": "job-wh-1"},
        headers={"X-Webhook-Signature": "sha256=invalidsignature"},
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


def test_ci_webhook_accepts_valid_signature(fresh_db, monkeypatch):
    """When WEBHOOK_SECRET is set, a valid signature should be accepted."""
    import json as _json
    monkeypatch.setattr("api.v1.endpoints.webhooks.WEBHOOK_SECRET", "test-secret-123")
    body_dict = {"event_type": "build_success", "job_id": "job-wh-1", "metadata": {}}
    payload = _json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False).encode()
    expected_sig = hmac.new(b"test-secret-123", payload, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/ci",
        content=payload,
        headers={
            "X-Webhook-Signature": f"sha256={expected_sig}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_ci_webhook_no_secret_skips_verification(fresh_db, monkeypatch):
    """When WEBHOOK_SECRET is empty, any request is accepted."""
    monkeypatch.setattr("api.v1.endpoints.webhooks.WEBHOOK_SECRET", "")
    response = client.post(
        "/api/v1/webhooks/ci",
        json={"event_type": "build_success", "job_id": "job-wh-1"},
    )
    assert response.status_code == 200
