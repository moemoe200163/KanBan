# DevFlow

AI Kanban control plane for turning board movement into ECC-style agent jobs, review gates, and delivery status.

The product design source of truth is [Design.md](./Design.md).

## Local Ports

| Service | URL |
|---|---|
| Frontend | http://127.0.0.1:3010 |
| Backend | http://127.0.0.1:8000 |

## Quick Start (Postgres via Docker, official dev path)

The official local dev path is Postgres on `localhost:5432`. SQLite is
kept only as a pytest / local fallback and is not used by `docker compose`.

```bash
# 1. Boot Postgres + backend + frontend + nginx + redis.
docker compose up --build

# 2. Wait for the backend log: "Database initialized: OK (postgresql+asyncpg://...)"
#    The FastAPI lifespan runs Alembic to head on startup, so the schema
#    is provisioned automatically.

# 3. Open the app
open http://127.0.0.1:3010/
```

Alembic is the source of truth for the Postgres schema. To add a new
migration after editing `backend/db/models.py`:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head   # apply locally; the backend container applies it on boot
```

## Local Ports

| Service | URL |
|---|---|
| Frontend (via Nginx) | http://127.0.0.1:80 |
| Frontend (direct)    | http://127.0.0.1:3010 |
| Backend              | http://127.0.0.1:8000 |
| Postgres             | localhost:5432 (`devflow` / `devflow_secret`) |

## Quick Start (SQLite fallback, no Docker)

For working without Docker, the backend falls back to a local SQLite
file when `DATABASE_URL` is unset. This path is intended for pytest
and offline tinkering, not as a supported dev workflow.

```bash
npm install
python3 -m pip install -r backend/requirements.txt

# Backend (creates ./backend/devflow.db via create_all on first run)
PYTHONPATH=backend python3 -m uvicorn main:app --host 127.0.0.1 --port 8000

# Frontend
npm run dev
```

## Verification

```bash
# Backend tests (SQLite pytest path, includes persistence + restart tests)
PYTHONPATH=backend pytest -q backend/tests

# Frontend type check
npm run typecheck

# Frontend production build
npm run build
```

## Current Architecture

```text
Nuxt 3 / Vue 3 board
  -> FastAPI control plane
    -> ECC job lifecycle API
      -> future durable queue / agent runner
```

Current workflow statuses:

- `backlog`
- `in_progress`
- `blocked`
- `human_review`
- `done`

Current ECC job statuses:

- `queued`
- `running`
- `paused`
- `failed`
- `review_required`
- `completed`
- `cancelled`

## Control Plane API

Dispatch an ECC job:

```http
POST /api/v1/ecc/dispatch
```

```json
{
  "issue_id": "issue-1",
  "issue_key": "DEV-001",
  "command": "/loop-start --profile=frontend",
  "profile": "frontend",
  "harness": "claude-code"
}
```

List jobs:

```http
GET /api/v1/ecc/jobs
GET /api/v1/ecc/jobs?issue_id={issue_id}
```

Read one job:

```http
GET /api/v1/ecc/jobs/{job_id}
```

Update job status:

```http
PATCH /api/v1/ecc/jobs/{job_id}
```

Cancel a job:

```http
POST /api/v1/ecc/jobs/{job_id}/cancel
```

## Near-Term Implementation Plan

1. Persist issues and ECC jobs instead of relying on in-memory state.
2. Replace simulated ECC execution with a real process runner.
3. Stream job logs into the issue detail panel.
4. Add CI and GitHub PR webhooks.
5. Add E2E coverage for board load, card selection, drag dispatch, and mobile layout.

## Notes

- The frontend standard port is `3010`, not Nuxt's default `3000`.
- The backend allows CORS from `127.0.0.1:3010` and `localhost:3010`.
- `PLAN.md` and `SPEC.md` are historical planning documents. Prefer `Design.md` and this README for current implementation decisions.
