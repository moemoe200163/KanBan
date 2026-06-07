# Full Auth Rollout — Design Spec

> **Status:** Design (ready for implementation)
> **Date:** 2026-06-06

## Goal

Ensure all state-changing (write) endpoints require authentication, and admin-only operations enforce role-based access control.

## Scope

### In Scope

1. Add `Depends(require_auth)` to all write endpoints that currently lack it
2. Add `require_admin` dependency for admin-only operations
3. Enforce WebSocket auth (disable anonymous by default)
4. Tests verifying 401 on unauthenticated write requests

### Out of Scope

- Token refresh mechanism
- Logout / token revocation
- Rate limiting on auth endpoints
- CORS tightening
- API key direct auth (current flow: API key → JWT exchange is kept)

## Endpoints to Fix

### Write endpoints needing `Depends(require_auth)`:

| File | Endpoint | Method |
|------|----------|--------|
| `runtime.py` | `/runtime/sessions/{id}/resume` | POST |
| `runtime.py` | `/runtime/sessions/{id}` | DELETE |
| `agents.py` | `/agents/dispatch` | POST |
| `agents.py` | `/agents/terminate` | POST |
| `quality.py` | `/quality/gate/verify` | POST |
| `autopilot.py` | `/autopilot/status` | POST |
| `autopilot.py` | `/autopilot/tick` | POST |
| `github_api.py` | `/github/pr/create` | POST |
| `github_api.py` | `/github/issues/{key}/labels` | POST |
| `github_api.py` | `/github/check-run` | POST |
| `github_api.py` | `/github/pr/{number}` | GET (write-adjacent, proxy) |
| `ecc.py` | `/ecc/jobs/{id}` | PATCH |

### Admin-only endpoints (new `require_admin`):

| File | Endpoint | Reason |
|------|----------|--------|
| `autopilot.py` | `/autopilot/status` POST | Controls autonomous execution |
| `autopilot.py` | `/autopilot/tick` POST | Triggers dispatches |
| `quality.py` | `/quality/gate/verify` POST | Bypasses quality gate |
| `llm.py` | `/llm/providers/{id}/config` PUT | Changes LLM config |
| `llm.py` | `/llm/providers/{id}/test` POST | Tests LLM credentials |
| `llm.py` | `/llm/providers/{id}/select` POST | Changes active provider |
| `llm.py` | `/llm/defaults` PUT | Changes LLM defaults |

### Endpoints staying public (read-only):

All GET endpoints for board, issues, jobs, workers, runs, sessions, agents, lanes, analytics, audit-logs, health.

## Architecture

### `require_admin` dependency

New dependency in `backend/api/v1/auth_deps.py`:

```python
async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

### Auth pattern for endpoints

```python
@router.post("/endpoint")
async def handler(req: Request, current_user: dict = Depends(require_auth)):
    ...

@router.post("/admin-endpoint")
async def handler(req: Request, current_user: dict = Depends(require_admin)):
    ...
```

## Test Plan

### Unit tests (auth enforcement):

- Write endpoints return 401 without token
- Admin endpoints return 403 with non-admin user
- Admin endpoints return 200 with admin user
- Read endpoints remain public (200 without token)

### Regression:

- All existing tests pass
- Frontend builds
