"""Tests for GitHub webhook ingestion (PR/CI Automation v1)."""
import pytest
import asyncio
from datetime import datetime, timezone

import httpx
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel


@pytest.fixture
def client():
    """Synchronous TestClient for simple status/response tests."""
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with 5 issues (DEV-001 through DEV-005)."""
    db_path = tmp_path / "test_github_webhooks.db"
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
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            for i in range(1, 6):
                session.add(IssueModel(
                    id=f"issue-gh-{i}",
                    key=f"DEV-{i:03d}",
                    title=f"Test issue {i}",
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


# =============================================================================
# extract_issue_key unit tests
# =============================================================================

class TestExtractIssueKey:
    """Unit tests for extract_issue_key utility."""

    def test_from_branch_name_simple(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("feat/DEV-123-login") == "DEV-123"

    def test_from_branch_name_no_prefix(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("DEV-42-fix") == "DEV-42"

    def test_from_pr_title(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("feat: add login page DEV-100") == "DEV-100"

    def test_from_pr_body_closes(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("Closes DEV-55") == "DEV-55"

    def test_from_pr_body_fixes(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("Fixes DEV-99") == "DEV-99"

    def test_from_labels(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("DEV-7 bug priority:high") == "DEV-7"

    def test_case_insensitive(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("feat/dev-123-login") == "DEV-123"

    def test_no_match_returns_none(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("no issue key here") is None

    def test_empty_string(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("") is None

    def test_first_match_wins(self):
        from api.v1.endpoints.webhooks import extract_issue_key
        assert extract_issue_key("DEV-1 first mention DEV-99 second") == "DEV-1"


# =============================================================================
# find_issue_by_key unit tests (async with pytest-asyncio)
# =============================================================================

@pytest.mark.asyncio
class TestFindIssueByKey:
    """Unit tests for find_issue_by_key repository function."""

    async def test_finds_existing_issue(self, seeded_db):
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue is not None
        assert issue["key"] == "DEV-001"

    async def test_returns_none_for_missing_key(self, seeded_db):
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-999")
        assert issue is None

    async def test_case_sensitive(self, seeded_db):
        from db import repository as repo
        issue = await repo.find_issue_by_key("dev-001")
        assert issue is None


# =============================================================================
# GitHub pull_request webhook tests (async with httpx — runs background tasks)
# =============================================================================

@pytest.mark.asyncio
class TestGitHubPRWebhook:
    """Integration tests for POST /webhooks/github with pull_request events."""

    def _make_pr_payload(self, *, action="opened", number=42, title="feat: login DEV-1",
                         body="", branch="feat/DEV-1-login", merged=False,
                         labels=None, html_url=None):
        return {
            "action": action,
            "pull_request": {
                "number": number,
                "title": title,
                "body": body,
                "html_url": html_url or f"https://github.com/test/repo/pull/{number}",
                "head": {"ref": branch},
                "merged": merged,
                "labels": [{"name": l} for l in (labels or [])],
            },
        }

    async def test_pr_opened_sets_pr_url_and_ci_pending(self, seeded_db):
        """PR opened → issue gets pr_url and ci_status=pending."""
        payload = self._make_pr_payload(action="opened", branch="feat/DEV-001-login")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-1"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue["pr_url"] is not None
        assert "pull/42" in issue["pr_url"]
        assert issue["ci_status"] == "pending"

    async def test_pr_merged_moves_issue_to_done(self, seeded_db):
        """PR closed + merged=true → issue status=done."""
        payload = self._make_pr_payload(action="closed", merged=True, branch="feat/DEV-002-fix")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-2"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-002")
        assert issue["status"] == "done"

    async def test_pr_closed_not_merged_no_status_change(self, seeded_db):
        """PR closed + merged=false → status unchanged."""
        payload = self._make_pr_payload(action="closed", merged=False, branch="feat/DEV-003-test")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-3"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-003")
        assert issue["status"] == "backlog"

    async def test_pr_no_issue_key_returns_200(self, seeded_db):
        """PR with no DEV-NNN anywhere → 200, no crash."""
        payload = self._make_pr_payload(title="random PR", body="no issue here",
                                         branch="feature/random-thing")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-4"},
            )
        assert resp.status_code == 200

    async def test_pr_issue_key_from_title(self, seeded_db):
        """Issue key extracted from PR title when branch has no key."""
        payload = self._make_pr_payload(title="fix: resolve bug DEV-004", branch="fix/bug")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-5"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-004")
        assert issue is not None
        assert issue["pr_url"] is not None

    async def test_pr_issue_key_from_body(self, seeded_db):
        """Issue key extracted from PR body when branch and title have no key."""
        payload = self._make_pr_payload(title="misc changes", body="Closes DEV-005",
                                         branch="fix/misc")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-6"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-005")
        assert issue is not None

    async def test_pr_nonexistent_issue_returns_200(self, seeded_db):
        """PR with DEV-999 (not in DB) → 200, graceful skip."""
        payload = self._make_pr_payload(branch="feat/DEV-999-missing")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-7"},
            )
        assert resp.status_code == 200


# =============================================================================
# GitHub workflow_run webhook tests
# =============================================================================

@pytest.mark.asyncio
class TestGitHubWorkflowRunWebhook:
    """Integration tests for POST /webhooks/github with workflow_run events."""

    def _make_workflow_run_payload(self, *, conclusion="success", branch="feat/DEV-001-login",
                                    action="completed"):
        return {
            "action": action,
            "workflow_run": {
                "conclusion": conclusion,
                "head_branch": branch,
                "pull_requests": [{"number": 42}],
            },
        }

    async def test_workflow_success_sets_ci_passed(self, seeded_db):
        """workflow_run completed + success → ci_status=passed."""
        payload = self._make_workflow_run_payload(conclusion="success", branch="feat/DEV-001-login")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-1"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue["ci_status"] == "passed"

    async def test_workflow_failure_sets_ci_failed(self, seeded_db):
        """workflow_run completed + failure → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="failure", branch="feat/DEV-002-fix")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-2"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-002")
        assert issue["ci_status"] == "failed"

    async def test_workflow_cancelled_sets_ci_failed(self, seeded_db):
        """workflow_run completed + cancelled → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="cancelled", branch="feat/DEV-003-test")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-3"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-003")
        assert issue["ci_status"] == "failed"

    async def test_workflow_timed_out_sets_ci_failed(self, seeded_db):
        """workflow_run completed + timed_out → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="timed_out", branch="feat/DEV-004-time")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-4"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-004")
        assert issue["ci_status"] == "failed"

    async def test_workflow_non_completed_action_noop(self, seeded_db):
        """workflow_run action=queued → no ci_status change."""
        payload = self._make_workflow_run_payload(conclusion=None, action="queued",
                                                   branch="feat/DEV-005-flow")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-5"},
            )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-005")
        assert issue["ci_status"] is None

    async def test_workflow_no_issue_key_returns_200(self, seeded_db):
        """workflow_run with branch that has no DEV-NNN → 200."""
        payload = self._make_workflow_run_payload(branch="main")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-6"},
            )
        assert resp.status_code == 200


# =============================================================================
# Signature + edge case tests
# =============================================================================

class TestGitHubWebhookSignature:
    """Tests for HMAC signature verification on GitHub webhook endpoint."""

    def test_invalid_signature_returns_401(self, client, seeded_db, monkeypatch):
        """Invalid signature → 401."""
        monkeypatch.setenv("WEBHOOK_SECRET", "test-secret-key-for-signing")
        # Re-read the module-level WEBHOOK_SECRET
        import api.v1.endpoints.webhooks as wh_mod
        monkeypatch.setattr(wh_mod, "WEBHOOK_SECRET", "test-secret-key-for-signing")

        payload = {"action": "opened", "pull_request": {"number": 1, "title": "test",
                   "body": "", "html_url": "https://example.com", "head": {"ref": "main"},
                   "merged": False, "labels": []}}
        resp = client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-sig-1",
                "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            },
        )
        assert resp.status_code == 401

    def test_unknown_event_type_returns_200(self, client, seeded_db):
        """Unknown event type → 200 (graceful)."""
        resp = client.post(
            "/api/v1/webhooks/github",
            json={"some": "data"},
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "test-ev-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_invalid_json_returns_400(self, client, seeded_db):
        """Malformed JSON → 400."""
        resp = client.post(
            "/api/v1/webhooks/github",
            content=b"not json",
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-bad-1"},
        )
        assert resp.status_code == 400
