# PR/CI Automation v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept real GitHub webhook payloads and update issue pr_url, ci_status, and status from the event data.

**Architecture:** One new endpoint `POST /api/v1/webhooks/github` in existing webhooks.py, one new repo function `find_issue_by_key`, one new utility `extract_issue_key`. Background task processing for issue updates. Zero migration.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest, existing WebhookEvent model

---

### Task 1: extract_issue_key unit tests + implementation

**Files:**
- Test: `backend/tests/test_github_webhooks.py` (new file)
- Implementation: `backend/api/v1/endpoints/webhooks.py`

- [ ] **Step 1: Write failing tests for extract_issue_key**

```python
# backend/tests/test_github_webhooks.py
"""Tests for GitHub webhook ingestion (PR/CI Automation v1)."""

import pytest


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.v1.endpoints.webhooks'` or `ImportError: cannot import 'extract_issue_key'`

- [ ] **Step 3: Implement extract_issue_key**

Add to `backend/api/v1/endpoints/webhooks.py`:

```python
import re

_ISSUE_KEY_PATTERN = re.compile(r"(?:DEV-)(\d+)", re.IGNORECASE)


def extract_issue_key(text: str) -> "str | None":
    """Extract issue key (e.g. DEV-123) from text. Returns normalized uppercase or None."""
    match = _ISSUE_KEY_PATTERN.search(text)
    if match:
        return f"DEV-{match.group(1)}"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestExtractIssueKey -v`
Expected: 10/10 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/endpoints/webhooks.py backend/tests/test_github_webhooks.py
git commit -m "feat(webhooks): add extract_issue_key utility with tests"
```

---

### Task 2: find_issue_by_key repo function

**Files:**
- Modify: `backend/db/repository.py`
- Test: `backend/tests/test_github_webhooks.py`

- [ ] **Step 1: Write failing test for find_issue_by_key**

Append to `backend/tests/test_github_webhooks.py`:

```python
@pytest.mark.asyncio
class TestFindIssueByKey:
    """Unit tests for find_issue_by_key repository function."""

    async def test_finds_existing_issue(self, seeded_db):
        """find_issue_by_key returns issue dict for existing key."""
        from db import repository as repo
        # seeded_db creates issues with DEV-001 through DEV-005
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue is not None
        assert issue["key"] == "DEV-001"

    async def test_returns_none_for_missing_key(self, seeded_db):
        """find_issue_by_key returns None for non-existent key."""
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-999")
        assert issue is None

    async def test_case_sensitive(self, seeded_db):
        """find_issue_by_key is case-sensitive on key."""
        from db import repository as repo
        issue = await repo.find_issue_by_key("dev-001")
        assert issue is None  # keys are stored as DEV-001
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestFindIssueByKey -v`
Expected: FAIL — `ImportError: cannot import name 'find_issue_by_key'`

- [ ] **Step 3: Implement find_issue_by_key**

Add to `backend/db/repository.py` (near the other issue lookup functions):

```python
async def find_issue_by_key(key: str) -> "Optional[dict]":
    """Find issue by exact key (e.g. DEV-123). Returns dict or None."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(IssueModel).where(IssueModel.key == key)
            )
            issue = result.scalar_one_or_none()
            if not issue:
                return None
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning("Failed to find issue by key %s: %s", key, e)
        return None
```

Also add `"find_issue_by_key"` to the `__all__` list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestFindIssueByKey -v`
Expected: 3/3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/db/repository.py
git commit -m "feat(repo): add find_issue_by_key function"
```

---

### Task 3: GitHub webhook endpoint + PR event handler

**Files:**
- Modify: `backend/api/v1/endpoints/webhooks.py`
- Test: `backend/tests/test_github_webhooks.py`

- [ ] **Step 1: Write failing tests for PR webhook**

Append to `backend/tests/test_github_webhooks.py`:

```python
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

    async def test_pr_opened_sets_pr_url_and_ci_pending(self, client, seeded_db):
        """PR opened → issue gets pr_url and ci_status=pending."""
        payload = self._make_pr_payload(action="opened", branch="feat/DEV-001-login")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        # Verify issue was updated
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue["prUrl"] is not None
        assert "pull/42" in issue["prUrl"]
        assert issue["ciStatus"] == "pending"

    async def test_pr_merged_moves_issue_to_done(self, client, seeded_db):
        """PR closed + merged=true → issue status=done."""
        payload = self._make_pr_payload(action="closed", merged=True, branch="feat/DEV-002-fix")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-2"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-002")
        assert issue["status"] == "done"

    async def test_pr_closed_not_merged_no_status_change(self, client, seeded_db):
        """PR closed + merged=false → status unchanged."""
        payload = self._make_pr_payload(action="closed", merged=False, branch="feat/DEV-003-test")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-3"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-003")
        assert issue["status"] == "backlog"  # unchanged

    async def test_pr_no_issue_key_returns_200(self, client, seeded_db):
        """PR with no DEV-NNN anywhere → 200, no crash."""
        payload = self._make_pr_payload(title="random PR", body="no issue here",
                                         branch="feature/random-thing")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-4"},
        )
        assert resp.status_code == 200

    async def test_pr_issue_key_from_title(self, client, seeded_db):
        """Issue key extracted from PR title when branch has no key."""
        payload = self._make_pr_payload(title="fix: resolve bug DEV-004", branch="fix/bug")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-5"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-004")
        assert issue is not None
        assert issue["prUrl"] is not None

    async def test_pr_issue_key_from_body(self, client, seeded_db):
        """Issue key extracted from PR body when branch and title have no key."""
        payload = self._make_pr_payload(title="misc changes", body="Closes DEV-005",
                                         branch="fix/misc")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-6"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-005")
        assert issue is not None

    async def test_pr_nonexistent_issue_returns_200(self, client, seeded_db):
        """PR with DEV-999 (not in DB) → 200, graceful skip."""
        payload = self._make_pr_payload(branch="feat/DEV-999-missing")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-7"},
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestGitHubPRWebhook -v`
Expected: FAIL — endpoint does not exist yet

- [ ] **Step 3: Implement receive_github_webhook endpoint + PR handler**

Add to `backend/api/v1/endpoints/webhooks.py`:

```python
@router.post("/webhooks/github", tags=["Webhooks"])
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
):
    """Receive real GitHub webhook payloads.

    Handles pull_request and workflow_run events.
    Returns 200 for all valid requests (GitHub expects 2xx for success).
    """
    body = await request.body()

    # Verify signature
    if x_hub_signature_256 and not verify_webhook_signature(body, x_hub_signature_256):
        logger.warning("GitHub webhook signature verification failed (delivery=%s)", x_github_delivery)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse payload
    try:
        import json
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Store event for audit
    event_type = f"github_{x_github_event or 'unknown'}"
    headers = {
        "x_github_event": x_github_event or "",
        "x_github_delivery": x_github_delivery or "",
        "user_agent": request.headers.get("user-agent", ""),
    }
    await _save_webhook_event(event_type=event_type, payload=payload, headers=headers)

    # Route to handler
    if x_github_event == "pull_request":
        background_tasks.add_task(_handle_github_pr_event, payload)
    elif x_github_event == "workflow_run":
        background_tasks.add_task(_handle_github_workflow_run_event, payload)
    else:
        logger.debug("GitHub webhook: unhandled event type '%s'", x_github_event)

    return {"status": "accepted", "event": x_github_event, "delivery": x_github_delivery}


async def _handle_github_pr_event(payload: dict) -> None:
    """Handle GitHub pull_request webhook event."""
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    if not pr:
        return

    issue_key = (
        extract_issue_key(pr.get("head", {}).get("ref", ""))
        or extract_issue_key(pr.get("title", ""))
        or extract_issue_key(pr.get("body", ""))
        or extract_issue_key(" ".join(l.get("name", "") for l in pr.get("labels", [])))
    )
    if not issue_key:
        logger.debug("GitHub PR event: no issue key in PR #%s", pr.get("number"))
        return

    issue = await _find_issue_by_key(issue_key)
    if not issue:
        return

    if action == "opened":
        await _update_issue_pr_url(issue["id"], pr.get("html_url", ""))
        await _update_issue_ci_status(issue["id"], "pending")
        logger.info("Issue %s: pr_url set, ci_status=pending (PR #%s opened)", issue_key, pr.get("number"))
    elif action == "closed" and pr.get("merged"):
        await _update_issue_status(issue["id"], "done")
        logger.info("Issue %s: status=done (PR #%s merged)", issue_key, pr.get("number"))
```

Note: The handlers call `_find_issue_by_key`, `_update_issue_pr_url`, `_update_issue_ci_status`, `_update_issue_status` which are thin wrappers around repository functions. We need to add these wrapper imports or use repo directly. Let me use repo directly in the implementation since it's the same pattern as existing handlers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestGitHubPRWebhook -v`
Expected: 8/8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/endpoints/webhooks.py
git commit -m "feat(webhooks): add GitHub webhook endpoint with PR event handler"
```

---

### Task 4: workflow_run event handler

**Files:**
- Modify: `backend/api/v1/endpoints/webhooks.py`
- Test: `backend/tests/test_github_webhooks.py`

- [ ] **Step 1: Write failing tests for workflow_run webhook**

Append to `backend/tests/test_github_webhooks.py`:

```python
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

    async def test_workflow_success_sets_ci_passed(self, client, seeded_db):
        """workflow_run completed + success → ci_status=passed."""
        payload = self._make_workflow_run_payload(conclusion="success", branch="feat/DEV-001-login")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-1"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-001")
        assert issue["ciStatus"] == "passed"

    async def test_workflow_failure_sets_ci_failed(self, client, seeded_db):
        """workflow_run completed + failure → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="failure", branch="feat/DEV-002-fix")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-2"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-002")
        assert issue["ciStatus"] == "failed"

    async def test_workflow_cancelled_sets_ci_failed(self, client, seeded_db):
        """workflow_run completed + cancelled → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="cancelled", branch="feat/DEV-003-test")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-3"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-003")
        assert issue["ciStatus"] == "failed"

    async def test_workflow_timed_out_sets_ci_failed(self, client, seeded_db):
        """workflow_run completed + timed_out → ci_status=failed."""
        payload = self._make_workflow_run_payload(conclusion="timed_out", branch="feat/DEV-004-time")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-4"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-004")
        assert issue["ciStatus"] == "failed"

    async def test_workflow_non_completed_action_noop(self, client, seeded_db):
        """workflow_run action=queued → no ci_status change."""
        payload = self._make_workflow_run_payload(conclusion=None, action="queued",
                                                   branch="feat/DEV-005-flow")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-5"},
        )
        assert resp.status_code == 200
        from db import repository as repo
        issue = await repo.find_issue_by_key("DEV-005")
        assert issue["ciStatus"] is None  # unchanged

    async def test_workflow_no_issue_key_returns_200(self, client, seeded_db):
        """workflow_run with branch that has no DEV-NNN → 200."""
        payload = self._make_workflow_run_payload(branch="main")
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run", "X-GitHub-Delivery": "test-wf-6"},
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestGitHubWorkflowRunWebhook -v`
Expected: FAIL — handler not implemented yet (or test passes if endpoint already routes correctly)

- [ ] **Step 3: Implement workflow_run handler**

Add `_handle_github_workflow_run_event` to `backend/api/v1/endpoints/webhooks.py`:

```python
async def _handle_github_workflow_run_event(payload: dict) -> None:
    """Handle GitHub workflow_run webhook event."""
    action = payload.get("action")
    if action != "completed":
        return

    wr = payload.get("workflow_run", {})
    conclusion = wr.get("conclusion")
    head_branch = wr.get("head_branch", "")

    status_map = {
        "success": "passed",
        "failure": "failed",
        "cancelled": "failed",
        "timed_out": "failed",
    }
    ci_status = status_map.get(conclusion)
    if not ci_status:
        return

    issue_key = extract_issue_key(head_branch)
    if not issue_key:
        logger.debug("GitHub workflow_run: no issue key from branch '%s'", head_branch)
        return

    from db import repository as repo
    issue = await repo.find_issue_by_key(issue_key)
    if not issue:
        return

    await repo.update_issue_ci_status(issue["id"], ci_status)
    logger.info("Issue %s: ci_status=%s (workflow_run %s)", issue_key, ci_status, conclusion)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestGitHubWorkflowRunWebhook -v`
Expected: 7/7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/endpoints/webhooks.py
git commit -m "feat(webhooks): add workflow_run event handler"
```

---

### Task 5: Signature verification + edge case tests

**Files:**
- Test: `backend/tests/test_github_webhooks.py`

- [ ] **Step 1: Write tests for signature verification and edge cases**

Append to `backend/tests/test_github_webhooks.py`:

```python
@pytest.mark.asyncio
class TestGitHubWebhookSignature:
    """Tests for HMAC signature verification on GitHub webhook endpoint."""

    async def test_invalid_signature_returns_401(self, client, seeded_db):
        """Invalid signature → 401."""
        payload = {"action": "opened", "pull_request": {"number": 1, "title": "test",
                   "body": "", "html_url": "https://example.com", "head": {"ref": "main"},
                   "merged": False, "labels": []}}
        resp = await client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-sig-1",
                "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            },
        )
        assert resp.status_code == 401

    async def test_unknown_event_type_returns_200(self, client, seeded_db):
        """Unknown event type → 200 (graceful)."""
        resp = await client.post(
            "/api/v1/webhooks/github",
            json={"some": "data"},
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "test-ev-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    async def test_invalid_json_returns_400(self, client, seeded_db):
        """Malformed JSON → 400."""
        resp = await client.post(
            "/api/v1/webhooks/github",
            content=b"not json",
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-bad-1"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they pass (endpoint already exists from Task 3)**

Run: `cd backend && PYTHONPATH=. pytest tests/test_github_webhooks.py::TestGitHubWebhookSignature -v`
Expected: 3/3 PASS (endpoint was implemented in Task 3)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_github_webhooks.py
git commit -m "test(webhooks): add signature and edge case tests"
```

---

### Task 6: Full regression

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && PYTHONPATH=. pytest -q tests`
Expected: ALL PASS (existing 535 + new ~28 tests)

- [ ] **Step 2: Run frontend typecheck + build**

Run: `npm run typecheck && npm run build`
Expected: clean

- [ ] **Step 3: Update CLAUDE.md and execution plan**

Update test counts and mark PR/CI automation v1 as done.

- [ ] **Step 4: Final commit**

```bash
git add CLAUDE.md docs/claude-code-execution-plan.md
git commit -m "docs: mark PR/CI automation v1 complete"
```
