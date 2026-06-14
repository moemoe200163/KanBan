# PR/CI Outbound API v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add outbound GitHub API integration — shared client service, PR creation, label sync, and check run reporting.

**Architecture:** Standalone `GitHubClient` service in `core/github/client.py`, 4 new FastAPI endpoints in `api/v1/endpoints/github_api.py`, full test coverage.

**Tech Stack:** Python, FastAPI, httpx, pytest-asyncio, GitHub REST API v3

---

### Task 1: GitHubClient Service + Unit Tests

**Files:**
- Create: `backend/core/github/__init__.py`
- Create: `backend/core/github/client.py`
- Create: `backend/tests/test_github_outbound.py`

- [ ] **Step 1: Write failing tests for GitHubClient**

```python
# backend/tests/test_github_outbound.py
"""Tests for GitHub outbound API client and endpoints."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from core.github.client import GitHubClient, get_github_client


class TestGitHubClient:
    """Unit tests for GitHubClient methods."""

    @pytest.mark.asyncio
    async def test_create_pull_request_success(self):
        """Successful PR creation returns PR dict."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "title": "test PR",
        }
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42
        assert result["html_url"] == "https://github.com/owner/repo/pull/42"

    @pytest.mark.asyncio
    async def test_create_pull_request_already_exists(self):
        """422 response returns existing PR info if available."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        # First call: 422 with message about existing PR
        mock_422 = MagicMock()
        mock_422.status_code = 422
        mock_422.json.return_value = {
            "message": "Validation Failed",
            "errors": [{"message": "A pull request already exists for"}],
        }
        # Second call: find existing PR
        mock_list = MagicMock()
        mock_list.status_code = 200
        mock_list.json.return_value = [{
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "head": {"ref": "feature/test"},
        }]
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_422
            mock_http.get.return_value = mock_list
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_create_pull_request_network_error(self):
        """Network error returns None."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.side_effect = httpx.ConnectError("connection refused")
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test", body="body", head="feature/test",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_labels_success(self):
        """Label sync sends PUT with correct labels."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "bug"}, {"name": "p1"}]
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.put.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.sync_labels(issue_number=42, labels=["bug", "p1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_create_check_run_success(self):
        """Check run creation returns check run dict."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 12345,
            "html_url": "https://github.com/owner/repo/runs/12345",
            "status": "completed",
            "conclusion": "success",
        }
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_check_run(
                name="DevFlow CI", head_sha="abc123",
                status="completed", conclusion="success",
            )
        assert result is not None
        assert result["id"] == 12345

    @pytest.mark.asyncio
    async def test_get_github_client_returns_none_when_unconfigured(self):
        """Returns None when GITHUB_TOKEN is empty."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "", "GITHUB_REPO": ""}, clear=False):
            result = get_github_client()
        assert result is None

    def test_get_github_client_returns_client_when_configured(self):
        """Returns client when both env vars are set."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test", "GITHUB_REPO": "owner/repo"}, clear=False):
            result = get_github_client()
        assert result is not None
        assert isinstance(result, GitHubClient)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_github_outbound.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.github'`

- [ ] **Step 3: Implement GitHubClient**

Create `backend/core/github/__init__.py` (empty).

Create `backend/core/github/client.py`:

```python
"""Shared GitHub REST API client for outbound API calls."""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GitHubClient:
    """Shared GitHub REST API client."""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    async def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Optional[dict]:
        """Create a PR. Returns PR dict or None on failure."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Validate base branch exists
                branch_resp = await client.get(
                    f"{self.base_url}/branches/{base}",
                    headers=self._headers,
                )
                if branch_resp.status_code != 200:
                    logger.warning("Base branch '%s' not found", base)
                    return None

                # Create PR
                pr_resp = await client.post(
                    f"{self.base_url}/pulls",
                    headers=self._headers,
                    json={"title": title, "body": body, "head": head, "base": base},
                )
                if pr_resp.status_code == 201:
                    data = pr_resp.json()
                    return {
                        "number": data["number"],
                        "html_url": data["html_url"],
                        "title": data.get("title", ""),
                    }

                # Handle "PR already exists"
                if pr_resp.status_code == 422:
                    return await self._find_existing_pr(client, head, base)

                logger.warning("PR creation failed: %s", pr_resp.status_code)
                return None
        except Exception as e:
            logger.warning("Failed to create PR: %s", e)
            return None

    async def _find_existing_pr(
        self, client: httpx.AsyncClient, head: str, base: str = "main"
    ) -> Optional[dict]:
        """Find existing PR for a branch."""
        try:
            resp = await client.get(
                f"{self.base_url}/pulls",
                headers=self._headers,
                params={"state": "all", "head": head, "base": base},
            )
            if resp.status_code == 200:
                prs = resp.json()
                if prs:
                    pr = prs[0]
                    return {
                        "number": pr["number"],
                        "html_url": pr["html_url"],
                        "title": pr.get("title", ""),
                    }
        except Exception:
            pass
        return None

    async def sync_labels(self, issue_number: int, labels: list[str]) -> bool:
        """Set labels on a GitHub issue/PR (replaces all)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.put(
                    f"{self.base_url}/issues/{issue_number}/labels",
                    headers=self._headers,
                    json={"labels": labels},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning("Failed to sync labels: %s", e)
            return False

    async def create_check_run(
        self,
        name: str,
        head_sha: str,
        status: str,
        conclusion: Optional[str] = None,
        output: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create a check run."""
        try:
            payload = {"name": name, "head_sha": head_sha, "status": status}
            if conclusion:
                payload["conclusion"] = conclusion
            if output:
                payload["output"] = output
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/check-runs",
                    headers=self._headers,
                    json=payload,
                )
                if resp.status_code == 201:
                    data = resp.json()
                    return {
                        "id": data["id"],
                        "html_url": data.get("html_url", ""),
                        "status": data.get("status", status),
                        "conclusion": data.get("conclusion"),
                    }
                logger.warning("Check run creation failed: %s", resp.status_code)
                return None
        except Exception as e:
            logger.warning("Failed to create check run: %s", e)
            return None

    async def get_pull_request(self, pr_number: int) -> Optional[dict]:
        """Get PR by number."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/pulls/{pr_number}",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception as e:
            logger.warning("Failed to get PR %d: %s", pr_number, e)
            return None

    async def get_branch(self, branch: str) -> Optional[dict]:
        """Get branch info."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/branches/{branch}",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception as e:
            logger.warning("Failed to get branch %s: %s", branch, e)
            return None


def get_github_client() -> Optional[GitHubClient]:
    """Get a GitHubClient if configured, None otherwise."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return None
    return GitHubClient(token=token, repo=repo)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_github_outbound.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/github/ backend/tests/test_github_outbound.py
git commit -m "feat(github): add shared GitHubClient service with unit tests"
```

---

### Task 2: GitHub API Endpoints

**Files:**
- Create: `backend/api/v1/endpoints/github_api.py`
- Modify: `backend/main.py` — Register router
- Modify: `backend/tests/test_github_outbound.py` — Add endpoint tests

- [ ] **Step 1: Write failing tests for endpoints**

Add to `backend/tests/test_github_outbound.py`:

```python
import json
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


class TestGitHubAPIEndpoints:
    """Integration tests for GitHub outbound API endpoints."""

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_create_pr_success(self, mock_get_client, client):
        """POST /github/pr/create returns PR info."""
        mock_gh = AsyncMock()
        mock_gh.create_pull_request.return_value = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "title": "test PR",
        }
        mock_get_client.return_value = mock_gh

        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test PR",
            "body": "body",
            "head": "feature/test",
            "base": "main",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["pr_number"] == 42

    def test_create_pr_missing_head(self, client):
        """POST /github/pr/create with missing head returns 422."""
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test",
            "body": "body",
        })
        assert resp.status_code == 422

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_create_pr_unconfigured(self, mock_get_client, client):
        """POST /github/pr/create returns 503 when GITHUB_TOKEN is empty."""
        mock_get_client.return_value = None
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test", "body": "body", "head": "feature/test",
        })
        assert resp.status_code == 503

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_sync_labels_success(self, mock_get_client, client):
        """POST /github/issues/{key}/labels syncs labels."""
        mock_gh = AsyncMock()
        mock_gh.sync_labels.return_value = True
        mock_get_client.return_value = mock_gh

        resp = client.post("/api/v1/github/issues/DEV-001/labels", json={
            "labels": ["bug", "p1"],
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_check_run_success(self, mock_get_client, client):
        """POST /github/check-run creates check run."""
        mock_gh = AsyncMock()
        mock_gh.create_check_run.return_value = {
            "id": 12345,
            "html_url": "https://github.com/owner/repo/runs/12345",
            "status": "completed",
            "conclusion": "success",
        }
        mock_get_client.return_value = mock_gh

        resp = client.post("/api/v1/github/check-run", json={
            "name": "DevFlow CI",
            "head_sha": "abc123",
            "status": "completed",
            "conclusion": "success",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["check_run_id"] == 12345
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_github_outbound.py::TestGitHubAPIEndpoints -v`
Expected: FAIL — 404 on all endpoints

- [ ] **Step 3: Implement endpoints**

Create `backend/api/v1/endpoints/github_api.py`:

```python
"""GitHub outbound API endpoints."""
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class PRCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    body: str = Field("")
    head: str = Field(..., min_length=1)
    base: str = Field("main")
    issue_key: Optional[str] = Field(None)


class LabelSyncRequest(BaseModel):
    labels: List[str] = Field(...)


class CheckRunRequest(BaseModel):
    issue_key: Optional[str] = Field(None)
    name: str = Field("DevFlow CI")
    head_sha: str = Field(..., min_length=1)
    status: str = Field("completed")
    conclusion: Optional[str] = Field(None)
    output: Optional[dict] = Field(None)


@router.post("/github/pr/create", tags=["GitHub"])
async def create_pr(req: PRCreateRequest):
    """Create a pull request on GitHub."""
    from core.github.client import get_github_client
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured (set GITHUB_TOKEN and GITHUB_REPO)")

    result = await gh.create_pull_request(
        title=req.title, body=req.body, head=req.head, base=req.base,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    # Link PR to issue if issue_key provided
    if req.issue_key:
        from db.repository import find_issue_by_key, update_issue_pr_url
        issue = await find_issue_by_key(req.issue_key)
        if issue:
            await update_issue_pr_url(issue["id"], result["html_url"])

    return {
        "ok": True,
        "pr_url": result["html_url"],
        "pr_number": result["number"],
        "already_existed": False,
    }


@router.post("/github/issues/{issue_key}/labels", tags=["GitHub"])
async def sync_labels(issue_key: str, req: LabelSyncRequest):
    """Sync labels on the GitHub PR linked to a DevFlow issue."""
    from core.github.client import get_github_client
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    # Find PR number from issue
    from db.repository import find_issue_by_key
    issue = await find_issue_by_key(issue_key)
    if not issue or not issue.get("pr_url"):
        raise HTTPException(status_code=404, detail=f"No PR linked to issue {issue_key}")

    # Extract PR number from pr_url
    pr_number = None
    pr_url = issue["pr_url"]
    parts = pr_url.rstrip("/").split("/")
    if "pull" in parts:
        idx = parts.index("pull")
        if idx + 1 < len(parts):
            try:
                pr_number = int(parts[idx + 1])
            except ValueError:
                pass
    if not pr_number:
        raise HTTPException(status_code=422, detail="Cannot extract PR number from pr_url")

    ok = await gh.sync_labels(issue_number=pr_number, labels=req.labels)
    if not ok:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    return {"ok": True, "labels": req.labels, "github_pr_number": pr_number}


@router.post("/github/check-run", tags=["GitHub"])
async def create_check_run(req: CheckRunRequest):
    """Create a check run on GitHub."""
    from core.github.client import get_github_client
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    result = await gh.create_check_run(
        name=req.name,
        head_sha=req.head_sha,
        status=req.status,
        conclusion=req.conclusion,
        output=req.output,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    return {
        "ok": True,
        "check_run_id": result["id"],
        "html_url": result["html_url"],
    }


@router.get("/github/pr/{pr_number}", tags=["GitHub"])
async def get_pr(pr_number: int):
    """Get PR details from GitHub (proxy)."""
    from core.github.client import get_github_client
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    result = await gh.get_pull_request(pr_number)
    if not result:
        raise HTTPException(status_code=404, detail=f"PR #{pr_number} not found")

    return result
```

- [ ] **Step 4: Register router in main.py**

Add after existing router includes (around line 60-70):

```python
from api.v1.endpoints.github_api import router as github_router
app.include_router(github_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_github_outbound.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/core/github/ backend/api/v1/endpoints/github_api.py backend/main.py backend/tests/test_github_outbound.py
git commit -m "feat(github): add outbound GitHub API endpoints (PR create, label sync, check run)"
```

---

### Task 3: Regression + Docs

**Files:**
- None (verification only)

- [ ] **Step 1: Run full backend regression**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: ALL PASS

- [ ] **Step 2: Run frontend typecheck + build**

Run: `npm run typecheck && npm run build`
Expected: ALL PASS

- [ ] **Step 3: Update CLAUDE.md and execution plan**

- Update test count
- Add milestone 14: PR/CI outbound API v2

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md docs/claude-code-execution-plan.md
git commit -m "docs: mark PR/CI outbound API v2 complete, update test counts"
```
