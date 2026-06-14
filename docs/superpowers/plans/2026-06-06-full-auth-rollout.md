# Full Auth Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add authentication to all write endpoints and RBAC to admin-only operations.

**Architecture:** Add `Depends(require_auth)` to unprotected write endpoints. Add `require_admin` dependency for sensitive operations. Tests verify 401/403 enforcement.

**Tech Stack:** Python, FastAPI, pytest

---

### Task 1: Add `require_admin` dependency + tests

**Files:**
- Modify: `backend/api/v1/auth_deps.py` — add `require_admin`
- Create: `backend/tests/test_auth_rollout_v2.py` — auth enforcement tests

- [ ] **Step 1: Add `require_admin` to auth_deps.py**

Add after existing `require_auth` / `optional_auth`:

```python
async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

Also add the import for HTTPException if not already present.

- [ ] **Step 2: Write auth enforcement tests**

Create `backend/tests/test_auth_rollout_v2.py`:

```python
"""Tests for full auth rollout — verify write endpoints require auth."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


@pytest.fixture
def auth_token():
    """Get a valid auth token for test user."""
    import main
    c = TestClient(main.app)
    # Register test user
    c.post("/api/v1/auth/register", json={
        "username": "auth_test_user",
        "password": "test_pass_123",
    })
    # Login
    resp = c.post("/api/v1/auth/token", json={
        "username": "auth_test_user",
        "password": "test_pass_123",
    })
    return resp.json().get("access_token", "")


class TestWriteEndpointsRequireAuth:
    """Verify write endpoints return 401 without token."""

    def test_github_pr_create_401(self, client):
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test", "body": "b", "head": "h",
        })
        assert resp.status_code == 401

    def test_github_labels_401(self, client):
        resp = client.post("/api/v1/github/issues/DEV-001/labels", json={
            "labels": ["bug"],
        })
        assert resp.status_code == 401

    def test_github_check_run_401(self, client):
        resp = client.post("/api/v1/github/check-run", json={
            "head_sha": "abc", "name": "CI", "status": "completed",
        })
        assert resp.status_code == 401

    def test_ecc_jobs_patch_401(self, client):
        resp = client.patch("/api/v1/ecc/jobs/nonexistent")
        assert resp.status_code == 401

    def test_session_resume_401(self, client):
        resp = client.post("/api/v1/runtime/sessions/nonexistent/resume")
        assert resp.status_code == 401

    def test_session_delete_401(self, client):
        resp = client.delete("/api/v1/runtime/sessions/nonexistent")
        assert resp.status_code == 401

    def test_agents_dispatch_401(self, client):
        resp = client.post("/api/v1/agents/dispatch", json={})
        assert resp.status_code == 401

    def test_agents_terminate_401(self, client):
        resp = client.post("/api/v1/agents/terminate", json={})
        assert resp.status_code == 401

    def test_quality_gate_verify_401(self, client):
        resp = client.post("/api/v1/quality/gate/verify", json={})
        assert resp.status_code == 401

    def test_autopilot_status_post_401(self, client):
        resp = client.post("/api/v1/autopilot/status", json={"enabled": True})
        assert resp.status_code == 401

    def test_autopilot_tick_401(self, client):
        resp = client.post("/api/v1/autopilot/tick")
        assert resp.status_code == 401


class TestReadEndpointsRemainPublic:
    """Verify read endpoints still work without auth."""

    def test_board_public(self, client):
        resp = client.get("/api/v1/board")
        assert resp.status_code == 200

    def test_ecc_jobs_public(self, client):
        resp = client.get("/api/v1/ecc/jobs")
        assert resp.status_code == 200

    def test_health_public(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_register_public(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "pub_test", "password": "pub_pass_123",
        })
        # 200 or 409 (already exists) — both mean it's public
        assert resp.status_code in (200, 409)

    def test_auth_token_public(self, client):
        resp = client.post("/api/v1/auth/token", json={
            "username": "nobody", "password": "wrong",
        })
        # 401 means the endpoint is reachable (public)
        assert resp.status_code == 401


class TestWriteEndpointsWithToken:
    """Verify write endpoints work with valid token (where possible)."""

    def test_github_pr_create_with_token(self, client, auth_token):
        resp = client.post("/api/v1/github/pr/create",
            json={"title": "t", "body": "b", "head": "h"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # 503 = GitHub not configured (expected in test), but NOT 401
        assert resp.status_code != 401

    def test_github_check_run_with_token(self, client, auth_token):
        resp = client.post("/api/v1/github/check-run",
            json={"head_sha": "abc", "name": "CI", "status": "completed"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code != 401
```

- [ ] **Step 3: Run tests to verify they FAIL**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_auth_rollout_v2.py -v`
Expected: FAIL — write endpoints return 200/other instead of 401

- [ ] **Step 4: Commit**

```bash
cd /Users/user/Code/kanban
git add backend/api/v1/auth_deps.py backend/tests/test_auth_rollout_v2.py
git commit -m "feat(auth): add require_admin dependency and auth enforcement tests"
```

---

### Task 2: Add auth to unprotected write endpoints

**Files:**
- Modify: `backend/api/v1/endpoints/runtime.py` — add auth to session resume/delete
- Modify: `backend/api/v1/endpoints/agents.py` — add auth to dispatch/terminate
- Modify: `backend/api/v1/endpoints/quality.py` — add auth to gate verify
- Modify: `backend/api/v1/endpoints/autopilot.py` — add auth to status/tick
- Modify: `backend/api/v1/endpoints/ecc.py` — add auth to PATCH jobs
- Modify: `backend/api/v1/endpoints/github_api.py` — add auth to all endpoints

- [ ] **Step 1: Add auth to each file**

For each file, add `from api.v1.auth_deps import require_auth` (or `require_admin` where appropriate) and add `Depends(require_auth)` to the endpoint function signature.

**runtime.py:**
```python
# Add import
from api.v1.auth_deps import require_auth

# session resume endpoint - add Depends
async def resume_session(session_id: str, current_user: dict = Depends(require_auth)):
# session delete endpoint - add Depends
async def delete_session(session_id: str, current_user: dict = Depends(require_auth)):
```

**agents.py:**
```python
from api.v1.auth_deps import require_auth

# dispatch endpoint
async def dispatch_agent(..., current_user: dict = Depends(require_auth)):
# terminate endpoint
async def terminate_agent(..., current_user: dict = Depends(require_auth)):
```

**quality.py:**
```python
from api.v1.auth_deps import require_admin

# gate verify endpoint (admin only)
async def verify_gate(..., current_user: dict = Depends(require_admin)):
```

**autopilot.py:**
```python
from api.v1.auth_deps import require_auth, require_admin

# status POST endpoint (admin only)
async def set_autopilot_status(..., current_user: dict = Depends(require_admin)):
# tick endpoint (admin only)
async def autopilot_tick(current_user: dict = Depends(require_admin)):
```

**ecc.py:**
```python
from api.v1.auth_deps import require_auth

# PATCH jobs endpoint
async def update_job(job_id: str, ..., current_user: dict = Depends(require_auth)):
```

**github_api.py:**
```python
from api.v1.auth_deps import require_auth

# Add to all 4 endpoints
@router.post("/github/pr/create", tags=["GitHub"])
async def create_pr(req: PRCreateRequest, current_user: dict = Depends(require_auth)):

@router.post("/github/issues/{issue_key}/labels", tags=["GitHub"])
async def sync_labels(issue_key: str, req: LabelSyncRequest, current_user: dict = Depends(require_auth)):

@router.post("/github/check-run", tags=["GitHub"])
async def create_check_run(req: CheckRunRequest, current_user: dict = Depends(require_auth)):

@router.get("/github/pr/{pr_number}", tags=["GitHub"])
async def get_pr(pr_number: int, current_user: dict = Depends(require_auth)):
```

- [ ] **Step 2: Run tests to verify they PASS**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_auth_rollout_v2.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full backend regression**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/user/Code/kanban
git add backend/api/v1/endpoints/runtime.py backend/api/v1/endpoints/agents.py \
  backend/api/v1/endpoints/quality.py backend/api/v1/endpoints/autopilot.py \
  backend/api/v1/endpoints/ecc.py backend/api/v1/endpoints/github_api.py
git commit -m "feat(auth): add require_auth to all unprotected write endpoints"
```

---

### Task 3: Add RBAC to admin-only endpoints + docs

**Files:**
- Modify: `backend/api/v1/endpoints/llm.py` — add `require_admin` to config/test/select/defaults

- [ ] **Step 1: Add require_admin to LLM config endpoints**

In `backend/api/v1/endpoints/llm.py`:
- Add `from api.v1.auth_deps import require_admin`
- Change existing `Depends(get_current_user)` to `Depends(require_admin)` on:
  - `PUT /llm/providers/{id}/config`
  - `POST /llm/providers/{id}/test`
  - `POST /llm/providers/{id}/select`
  - `PUT /llm/defaults`

- [ ] **Step 2: Run full regression**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: ALL PASS

- [ ] **Step 3: Frontend typecheck + build**

Run: `npm run typecheck && npm run build`
Expected: ALL PASS

- [ ] **Step 4: Update CLAUDE.md and execution plan**

- Update test count
- Add milestone 15: Full auth rollout

- [ ] **Step 5: Commit**

```bash
cd /Users/user/Code/kanban
git add backend/api/v1/endpoints/llm.py CLAUDE.md docs/claude-code-execution-plan.md
git commit -m "feat(auth): add RBAC to admin-only LLM endpoints, update docs"
```
