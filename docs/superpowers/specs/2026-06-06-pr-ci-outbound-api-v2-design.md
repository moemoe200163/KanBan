# PR/CI Outbound API v2 — Design Spec

> **Status:** Design (ready for implementation)
> **Date:** 2026-06-06
> **Prerequisite:** PR/CI v1 (webhook ingestion) is complete

## Goal

Extend DevFlow's GitHub integration from inbound-only (webhook ingestion) to bidirectional: outbound API calls that create PRs, sync labels, and report CI status back to GitHub as check runs.

## Design Principles

1. **Shared service, not adapter-coupled** — GitHub API client is a standalone service, usable by adapters, endpoints, and background tasks.
2. **Opt-in via env** — `GITHUB_TOKEN` and `GITHUB_REPO` control whether outbound features are active. No outbound calls when unconfigured.
3. **Idempotent operations** — PR creation handles "already exists" gracefully. Label sync is set-based, not additive.
4. **Webhook-first, polling-second** — Inbound webhooks (v1) remain the primary data source. Outbound calls supplement, not replace.

## Scope

### In Scope (v2)

| Feature | Description |
|---------|-------------|
| Shared GitHub client | Reusable service wrapping httpx for GitHub REST API |
| Auto-create PR | POST /api/v1/github/pr/create — create PR from execution result |
| Label sync | POST /api/v1/github/issues/{key}/labels — sync DevFlow labels to GitHub |
| Check run report | POST /api/v1/github/check-run — report ci_status as GitHub check run |

### Out of Scope

- GitHub GraphQL API (v4)
- GitHub App installation / OAuth flow
- Branch protection rules
- GitHub Actions trigger from DevFlow
- PR review automation
- PR merge automation

## Architecture

### Shared GitHub Client Service

New file: `backend/core/github/client.py`

```python
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
        self, title: str, body: str, head: str, base: str = "main"
    ) -> Optional[dict]:
        """Create a PR. Returns PR dict or None on failure."""

    async def get_pull_request(self, pr_number: int) -> Optional[dict]:
        """Get PR by number."""

    async def list_pull_requests(self, state: str = "open") -> list:
        """List PRs with state filter."""

    async def sync_labels(
        self, issue_number: int, labels: list[str]
    ) -> bool:
        """Set labels on a GitHub issue/PR (replaces all)."""

    async def create_check_run(
        self,
        name: str,
        head_sha: str,
        status: str,
        conclusion: Optional[str] = None,
        output: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create or update a check run."""

    async def get_branch(self, branch: str) -> Optional[dict]:
        """Get branch info (used for base validation)."""

    async def find_existing_pr(self, head: str, base: str = "main") -> Optional[dict]:
        """Find existing PR for a branch."""
```

### Error Handling

All methods return `None` on failure (network error, 4xx, 5xx). The client logs warnings but never raises. Callers check for `None` and handle gracefully.

Rate limit handling: if 423 (rate limited), log and return None. No retry logic in v2.

### Configuration

| Env Var | Required | Description |
|---------|----------|-------------|
| `GITHUB_TOKEN` | No | GitHub personal access token. If empty, all outbound features disabled. |
| `GITHUB_REPO` | No | Repository in `owner/repo` format. If empty, all outbound features disabled. |

The client is lazy-initialized: `GitHubClient(token=os.getenv("GITHUB_TOKEN"), repo=os.getenv("GITHUB_REPO"))`. A helper `get_github_client()` returns `None` if either env var is empty.

## API Endpoints

### POST /api/v1/github/pr/create

Create a pull request from execution result.

**Request:**
```json
{
  "issue_key": "DEV-001",
  "title": "feat(DEV-001): implement login",
  "body": "## Changes\n- Added login page\n- Added auth middleware",
  "head": "feature/dev-001-login",
  "base": "main"
}
```

**Response (200):**
```json
{
  "ok": true,
  "pr_url": "https://github.com/owner/repo/pull/42",
  "pr_number": 42,
  "already_existed": false
}
```

**Response (200, already exists):**
```json
{
  "ok": true,
  "pr_url": "https://github.com/owner/repo/pull/42",
  "pr_number": 42,
  "already_existed": true
}
```

**Response (422):**
```json
{
  "ok": false,
  "error": "Missing required fields: head"
}
```

**Side effects:**
- Sets `issue.pr_url` on the linked issue (if issue_key provided)

### POST /api/v1/github/issues/{issue_key}/labels

Sync labels on the GitHub issue/PR linked to a DevFlow issue.

**Request:**
```json
{
  "labels": ["bug", "priority:high", "status:in-progress"]
}
```

**Response (200):**
```json
{
  "ok": true,
  "labels": ["bug", "priority:high", "status:in-progress"],
  "github_pr_number": 42
}
```

**Behavior:**
- Looks up issue by key, gets `pr_url`, extracts PR number
- If no `pr_url`, returns 404
- Replaces all labels on the GitHub issue/PR (set-based, not additive)

### POST /api/v1/github/check-run

Report a check run status to GitHub.

**Request:**
```json
{
  "issue_key": "DEV-001",
  "name": "DevFlow CI",
  "head_sha": "abc123def456",
  "status": "completed",
  "conclusion": "success",
  "output": {
    "title": "All checks passed",
    "summary": "Build and tests passed"
  }
}
```

**Response (200):**
```json
{
  "ok": true,
  "check_run_id": 12345,
  "html_url": "https://github.com/owner/repo/runs/12345"
}
```

**Conclusions:** `success`, `failure`, `neutral`, `cancelled`, `timed_out`, `action_required`

### GET /api/v1/github/pr/{pr_number}

Get PR details from GitHub (proxy endpoint).

**Response (200):**
```json
{
  "number": 42,
  "title": "feat(DEV-001): implement login",
  "state": "open",
  "html_url": "https://github.com/owner/repo/pull/42",
  "head": { "ref": "feature/dev-001-login", "sha": "abc123" },
  "base": { "ref": "main" },
  "user": { "login": "devflow-bot" },
  "created_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:30:00Z"
}
```

## File Structure

```
backend/
├── core/github/
│   ├── __init__.py
│   └── client.py              # GitHubClient class + get_github_client()
├── api/v1/endpoints/
│   └── github_api.py          # New endpoint file for outbound GitHub routes
├── tests/
│   └── test_github_outbound.py  # Tests for client + endpoints
```

## Integration Points

### Auto-create PR on execution complete

Modify `backend/core/runtime/orchestrator.py` `complete_run()` (line 200):
- After run completes, if adapter returned `pr_url`, update issue
- If no `pr_url` but `GITHUB_TOKEN` is set, optionally create PR via shared client

This is a future integration point — v2 provides the building blocks, not the auto-trigger.

### Label sync from issue update

When issue labels are updated via API, optionally sync to GitHub. This is also a future integration point.

## Test Plan

### Unit tests (GitHubClient)

- `test_create_pull_request_success` — mock httpx, verify request shape
- `test_create_pull_request_already_exists` — mock 422 response
- `test_sync_labels_success` — mock httpx, verify PUT request
- `test_create_check_run_success` — mock httpx, verify POST request
- `test_client_returns_none_on_network_error`
- `test_client_returns_none_on_4xx`
- `test_get_github_client_returns_none_when_unconfigured`

### Integration tests (API endpoints)

- `test_create_pr_success` — mock GitHub client, verify endpoint
- `test_create_pr_missing_fields` — 422 validation
- `test_sync_labels_success` — mock GitHub client
- `test_sync_labels_no_pr_url` — 404 when issue has no PR
- `test_check_run_success` — mock GitHub client
- `test_get_pr_proxy` — mock GitHub client

### Regression

- `cd backend && PYTHONPATH=backend pytest -q backend/tests` — all pass
- `cd frontend && npm run typecheck && npm run build` — all pass

## Risks

| Risk | Mitigation |
|------|------------|
| GitHub API rate limits | Log and return None, no retry in v2 |
| Token exposure | Token never in responses, env-only config |
| Webhook/event ordering | Outbound calls are idempotent |
| PR creation race condition | `find_existing_pr()` before create |
