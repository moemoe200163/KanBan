# DevFlow P1 — Modularization Plan: Job/Logs + Postgres + E2E

## Task Type
- [x] Frontend (→ Gemini)  *(Gemini CLI unavailable — Claude synthesizes)*
- [x] Backend (→ Codex)    *(Codex CLI used for final review only)*
- [x] Fullstack (→ Parallel when models available; here Claude-led sequential)
- [x] Infra (Postgres wiring, Playwright install, E2E gate)

## Context Summary

### Already shipped (P0.5)
- `/api/v1/board` returns 8 seed issues across 5 columns
- `POST /api/v1/ecc/dispatch` returns immediately with `queued` job
- Safe runner emits deterministic `queued → running × 4 → review_required` events
- `_save_job_to_db()` is implemented and persists initial state to SQLite
- `applyECCJobToIssue()` maps `job.events` → `issue.eccLogs` (phase inference included)
- `Sidebar.vue` auto-refreshes `/api/v1/ecc/jobs` every 5s
- 16 backend tests pass; frontend `typecheck` + `build` green

### Current state of the targets
- `e2e/` already has `playwright.config.ts`, `board.spec.ts`, `kanban.spec.ts`, and a `node_modules` cache — but **`@playwright/test` is NOT in `package.json` devDependencies** and the config has a broken `webServer.command` (`npm run build && npm run preview -- --port 3010` which double-binds the port).
- `e2e/.nuxt/` exists and is **not** in `.gitignore` yet.
- `backend/docker-compose.yml` already defines Postgres at `localhost:5432` with `devflow/devflow_secret/devflow`. User reports it is already running.
- `.env.example` already has `DATABASE_URL=postgresql://...` (no `+asyncpg` driver prefix yet).
- `backend/db/database.py` hardcodes `sqlite+aiosqlite:///<path>`. Postgres is never actually wired.
- `backend/db/models.py::JobModel.events` is a `Column(String)` holding JSON text — works for SQLite, must move to `JSON` (cross-dialect) for Postgres.
- `backend/api/v1/endpoints/board.py` reads from `issues._issues_db` (in-memory list). On a real DB this is decoupled — needs a repository function.
- `backend/api/v1/endpoints/ecc.py::list_ecc_jobs` doesn't yet filter by `issue_id`.
- `src/stores/board.ts::createIssue` falls back to a local-only issue on failure with `console.warn` — violates the new requirement (inline error).
- `src/components/KanbanBoard.vue:74` calls `boardStore.createIssue('Untitled issue', 'backlog')` directly — no modal.
- `src/components/IssueDetail.vue` ECC Logs tab renders `issue.eccLogs` but does not show job metadata (id, command, profile, harness, status, created/updated).
- Existing test file: `backend/tests/test_api_smoke.py` (4 tests). Need to add DB-persistence and `?issue_id=` tests.

### Hard constraints (from CLAUDE.md)
- Frontend `3010`, backend `8000`, no stack replacement.
- Safe runner is the only execution path; no real Claude/ECC CLI, no multi-harness, no session resume.
- Don't block `/api/v1/ecc/dispatch`.
- Don't run user-provided shell commands.
- Don't mark E2E complete unless `@playwright/test` is in `devDependencies` and `npm run e2e` passes.
- Board must not be empty on startup unless explicitly requested.

### Pre-existing P1s from last Codex review (intentionally NOT in scope)
- `issues.py:199-200` `PUT /issues/{id}/status` takes `status` as query param, frontend sends body.
- `board.ts:1000-1004` `createIssue` accepts incomplete `IssueResponse` from backend (missing `labels`, `activityLog`, `createdAt`) and assigns it into the column.
- `ws.py:40-42` `JobConnectionManager.connect()` calls `accept()` a second time after the endpoint already accepted — disconnects on subscribe.
- `auth.py:73-75` `python-jose` import but `requirements.txt` only ships `PyJWT`.

These will be referenced as known follow-ups; touching them now violates "fix one loop at a time."

## Technical Solution

### Architecture (P1)

```
              ┌────────────── Frontend (Nuxt 3, port 3010) ──────────────┐
              │                                                            │
              │  boardStore  ──────────────►  /api/v1/board                │
              │  recentJobsStore  ─────────►  /api/v1/ecc/jobs?issue_id    │
              │  jobDetailStore  ──────────►  /api/v1/ecc/jobs/{id}        │
              │  newIssueModal  ───────────►  POST /api/v1/issues          │
              │  reviewQueue  ─────────────►  PUT /api/v1/issues/{id}/status│
              │                                  + POST /api/v1/ecc/dispatch│
              │                                                            │
              │  Polling (5s on Sidebar) remains — WebSocket still broken. │
              └────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
              ┌────────── Backend (FastAPI, port 8000, Postgres) ─────────┐
              │                                                             │
              │  Repositories:                                              │
              │    issue_repo  ─► IssueModel (JSON labels, JSON deps)      │
              │    job_repo    ─► JobModel  (JSON events, JSONB on PG)      │
              │                                                             │
              │  Lifespan:                                                  │
              │    init_db()   ─► ensure tables, then seed if empty        │
              │    load_jobs_from_db()                                       │
              │                                                             │
              │  Endpoints (all unchanged contract except ?issue_id=):      │
              │    GET  /api/v1/board                  (DB-backed)          │
              │    POST /api/v1/issues                 (persist + return)   │
              │    PUT  /api/v1/issues/{id}/status     (persist)            │
              │    POST /api/v1/ecc/dispatch           (safe runner, async) │
              │    GET  /api/v1/ecc/jobs               (?issue_id filter)   │
              │    GET  /api/v1/ecc/jobs/{id}                               │
              │    PATCH /api/v1/ecc/jobs/{id}                              │
              │    POST /api/v1/ecc/jobs/{id}/cancel                        │
              └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
              ┌──────────── Postgres @ localhost:5432/devflow ─────────────┐
              │  issues              (existing model, populated on seed)    │
              │  ecc_jobs            (JobModel, JSON events column)         │
              └─────────────────────────────────────────────────────────────┘
```

### Persistence: SQLite-compatible JSON + Postgres JSONB
- Keep `JobModel.events` as a single column. Use SQLAlchemy `JSON` type (works on both backends):
  - SQLite: stores as `TEXT` (TEXT-affinity JSON) — same as today.
  - Postgres: maps to `JSONB`.
- `to_dict()` continues to use `json.loads()` so callers stay agnostic.
- A `repository.py` wraps every read/write so the API endpoints never touch SQLAlchemy directly.

### Why a repository layer
- Endpoint code today couples to SQLAlchemy via `from db.models import JobModel`. Replacing storage, mocking in tests, or adding filters means editing every endpoint.
- A `repository.py` with `upsert_job`, `get_job`, `list_jobs(issue_id=None)`, `list_issues`, `upsert_issue`, `update_issue_status`, `seed_if_empty` keeps the surface small and lets the SQLite-fallback path stay valid.

## Implementation Steps

### Phase A — Postgres + persistence foundation (unblocks everything else)

**A1. Add `repository.py` (new file: `backend/db/repository.py`)**
- Functions: `seed_if_empty`, `list_issues`, `get_issue`, `upsert_issue`, `update_issue_status`, `upsert_job`, `get_job`, `list_jobs(issue_id=None)`, `load_all_jobs_into_memory`.
- All async; all use `AsyncSessionLocal` and `ensure_db_init`.
- Errors logged + swallowed at the function boundary (matches current `_save_job_to_db` non-blocking posture).

**A2. Switch `database.py` to read `DATABASE_URL` correctly**
- Currently: `f"sqlite+aiosqlite:///{_default_db_path}"` if env unset.
- Change: parse the env value, and if it's missing the driver prefix (`+asyncpg` or `+aiosqlite`), auto-add it based on scheme (`postgresql` → `postgresql+asyncpg`, `sqlite` → `sqlite+aiosqlite`).
- `.env.example` currently writes `postgresql://...` — add the `+asyncpg` prefix in the example to match what backend/requirements.txt actually installs.

**A3. Move `JobModel.events` to SQLAlchemy `JSON` type**
- `from sqlalchemy import JSON` (already imported).
- `events = Column(JSON, nullable=False, default=list)`.
- `to_dict()` drops the `json.loads` call (JSON column already deserializes).
- `load_jobs_from_db` keeps using `ECCJobEvent(**e)` — `JSON` deserializes to Python list of dicts on read.

**A4. Wire lifespan to repository**
- `main.py` lifespan: after `init_db()`, call `repo.seed_if_empty()` and then `repo.load_all_jobs_into_memory()`.
- Drop the direct `from api.v1.endpoints.ecc import load_jobs_from_db` and let the repo own it.
- The `ecc.py` `_jobs` dict is still the in-memory hot path (events update frequently); the repo only loads at startup and on explicit save.

**A5. Wire endpoints to repo**
- `board.py::get_board` → `repo.list_issues()` and group.
- `issues.py::create_issue` and `update_issue_status` → `repo.upsert_issue` / `repo.update_issue_status` (after validation).
- `ecc.py::_save_job_to_db` → `repo.upsert_job`.
- `ecc.py::list_ecc_jobs` → `repo.list_jobs(issue_id=...)`.
- `_jobs` dict remains in `ecc.py` for the safe-runner hot path; persistence is now driven by the repo.

**A6. Update seed data**
- Move seed from `issues.py::_seed_initial_issues` (in-memory) to `repository.py::seed_if_empty` (DB-persisted).
- Same 8 issues, same statuses. Only seeds if the `issues` table is empty.

**A7. Tests**
- Add `backend/tests/test_persistence.py` (or extend `test_api_smoke.py`):
  - `test_board_returns_seeded_issues_when_db_empty` (use a fresh in-memory SQLite via `DATABASE_URL=sqlite+aiosqlite:///:memory:` fixture; or rely on the production SQLite at `backend/devflow.db` if Postgres is unavailable in CI).
  - `test_create_issue_persists_and_board_reflects`.
  - `test_list_jobs_filters_by_issue_id`.
  - `test_jobs_and_events_loaded_from_db_on_startup` — write a job via the API, then instantiate a fresh `TestClient` and verify the job is still there.
- Keep all 16 existing tests passing. The DB schema change is backward-compatible because:
  - SQLite: `JSON` is stored as TEXT — same bytes as the previous `String` column.
  - The repo's `to_dict` no longer calls `json.loads` (Postgres returns dicts, SQLite returns list-of-dicts after deserialization).

**A8. Smoke test against real Postgres**
- After A1–A7, run the full suite pointing at the user's running Postgres:
  - `export DATABASE_URL=postgresql+asyncpg://devflow:devflow_secret@localhost:5432/devflow`
  - `PYTHONPATH=backend pytest -q backend/tests`
  - 16+ tests pass.
- This is the gate that proves A2–A6 are correct on the real target.

### Phase B — Backend API completion

**B1. Add `GET /api/v1/ecc/jobs?issue_id=` filter**
- `ecc.py::list_ecc_jobs(issue_id: Optional[str] = None)` → uses `repo.list_jobs(issue_id=issue_id)`.
- The `issue_id` param comes from a FastAPI `Query(...)`.

**B2. Tests for B1**
- `test_list_jobs_returns_all_when_no_filter`.
- `test_list_jobs_filters_by_issue_id` — dispatch two jobs for two issues, filter, assert count + IDs.

### Phase C — Frontend: Job/Logs first-class

**C1. Extend `src/stores/board.ts` with job store actions**
- State additions: `jobsById: Record<string, ECCDispatchJob>`, `jobsForIssue: Record<string, string[]>` (issue id → job id list).
- Actions:
  - `fetchJobs()` — `GET /ecc/jobs`; populates `jobsById`.
  - `fetchJob(jobId)` — `GET /ecc/jobs/{jobId}`; populates `jobsById` and `attachJobToIssue` if `issue_id` matches a known issue.
  - `fetchJobsForIssue(issueId)` — `GET /ecc/jobs?issue_id={id}`; populates `jobsForIssue[issueId]`.
  - `attachJobToIssue(issueId, job)` — sets the issue's `eccJobId/Status/Message/UpdatedAt/eccLogs` (reuse existing `applyECCJobToIssue` shape).
  - `getIssueJob(issueId): ECCDispatchJob | null` — getter.
  - `pollIssueJob(issueId)` — runs `fetchJob` immediately, then `setTimeout` for ~2.5s at 250ms intervals while the issue's `eccJobStatus` is `queued` or `running`, so the safe-runner events land in `eccLogs` reliably. (Already-implemented 350ms refresh in `dispatchAI` + the `completeAI` PATCH both also flow through `applyECCJobToIssue`, so the polling layer is for opens from `IssueDetail` after the initial events have arrived.)

**C2. Update `IssueDetail.vue` ECC Logs tab**
- New structure when a job is attached:
  - Header row: `Job #ecc_xxx · /loop-start --profile=frontend · claude-code` + status pill
  - Created/updated timestamps (formatted)
  - Event timeline (sorted by timestamp ASC). Each event: phase pill (using existing `getPhaseColor`), timestamp, message, optional confidence.
- Empty state: replace current "No ECC logs yet" copy with the plan's required text: **"No execution jobs yet"** and a hint line "Move the card to In Progress to dispatch an ECC job."
- When `activeTab === 'ecc-logs'` and the issue has no `eccJobId`, call `boardStore.pollIssueJob(issueId)` once on mount to catch up if a job exists server-side.

**C3. Status color tokens for ECC job status (Sidebar + IssueDetail share)**
- Add a small map `ECC_JOB_STATUS_COLORS` in `src/stores/board.ts` (or a new `src/utils/jobStatus.ts`) so the same colors are reused:
  - `queued` → `--amber`
  - `running` → `--coral` (rename from `var(--coral)` to `--coral` — check existing tokens; fallback `--primary` if not present)
  - `review_required` → `--dusty-blue` (fallback `--info` or a new CSS var)
  - `completed` → `--sage`
  - `failed` / `cancelled` → `--clay-red`
- Reuse the existing CSS variables where present; add new ones to `assets/css/tailwind.css` only if needed (single source of truth).

### Phase D — Frontend: Sidebar Recent Jobs formalized

**D1. Move polling into a `useRecentJobs()` composable (`src/composables/useRecentJobs.ts`)**
- Returns `{ jobs, isLoading, error, start, stop, refresh }`.
- Internal `setInterval` keyed on the composable instance.
- `Sidebar.vue` calls `useRecentJobs().start()` in `onMounted`, `.stop()` in `onUnmounted`. No more raw `setInterval` in the component.
- Defaults: refresh every 5000ms, take the 5 most recent jobs (sorted by `created_at` DESC).

**D2. Click handling**
- On click, find the issue in `boardStore.columns[*].issues` by `id === job.issue_id`.
- If found: `boardStore.openDetail(issue, 'ecc-logs')` — need a new store action that opens the panel and sets `activeDetailTab`.
- If not found: open a fallback modal/panel that shows the job detail (key, command, profile, harness, status, message, events). Implemented as a new `<JobDetailFallback>` inline component (no router change required).

**D3. Status colors use the new shared token map (Phase C3).**

**D4. Unit-test the composable (optional)**
- Vitest is not currently set up. Skip the unit test; rely on the E2E test added in Phase G.

### Phase E — Frontend: New Issue Modal

**E1. New component `src/components/NewIssueModal.vue`**
- Props: `open: boolean`. Emits: `close`, `created` (issue).
- Fields:
  - Title (required, autofocus, max 200 chars).
  - Description (textarea, optional, max 5000 chars).
  - Status (select; default `backlog`).
  - Priority (select; default `medium`).
  - Profile (select; default `general`).
- On submit:
  - `await boardStore.createIssue({ title, description, status, priority, profile })`.
  - If success: emit `created`, emit `close`, `boardStore.fetchBoard()`.
  - If failure: set local `error` ref to the backend message; do not close. Error is rendered inline above the Submit button (not `console.warn`).
- Disable Submit while in-flight.

**E2. Extend `boardStore.createIssue` to accept a full payload and surface errors**
- New signature: `createIssue(payload: { title; description?; status?; priority?; profile? })`.
- Throws on backend failure (no silent fallback). The fallback "local-only issue" path is removed in P1 because we expect the backend to be live.
- Returns the created `Issue` (with all fields populated; the previous P1 risk about missing fields is mitigated by re-fetching the board after success).
- The toolbar "New Issue" button uses the modal instead of calling `createIssue('Untitled issue', 'backlog')` directly.

**E3. `KanbanColumn.vue` inline "Add Issue" stays**
- The column-level quick-add still works for the fast path. It calls `boardStore.createIssue({ title, status: columnId })` with the new signature.

### Phase F — Frontend: Review Queue

**F1. New store actions on `boardStore`**
- `getReviewQueue(): Array<{ issue: Issue; job: ECCDispatchJob | null }>` — combines `human_review` column with jobs whose status is `review_required` linked to issues not yet in `human_review`.
- `approveReview(issueId)` — moves issue to `done` (uses existing `moveIssue` machinery, but with skip-dispatch since done is not AI-triggered).
- `requestChanges(issueId, reason?: string)` — moves issue to `in_progress` and re-dispatches the safe runner (calls `confirmMoveWithControlPlane` then `applyECCJobToIssue`).

**F2. New `src/components/ReviewQueue.vue`**
- Renders the list. Each row: issue key + title, latest job status pill + message, priority/profile chips.
- Buttons: `Approve`, `Request changes` (opens a small inline form for an optional `reason` text).
- Mounted in the Sidebar as a new section above `Recent Jobs`, OR as a board toolbar filter — implementation choice. Default: **sidebar section** (the Sidebar.vue already has three sections; add a fourth).

**F3. Empty state**: "Nothing in review. All clear." with a small icon.

### Phase G — E2E formalization

**G1. Add `@playwright/test` to `devDependencies`**
- Pin to a known-good version (1.49.x).
- Run `npm install` after editing `package.json`.

**G2. Fix `e2e/playwright.config.ts`**
- `webServer.command`: `'npm run build && HOST=127.0.0.1 PORT=3010 node .output/server/index.mjs'` (drop the `-- --port 3010` since the script already sets `PORT=3010`).
- `reuseExistingServer: !process.env.CI` (keeps local dev fast; CI always starts fresh).
- Add `outputDir: './e2e/test-results'` and `reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list'`.

**G3. Update `.gitignore`**
- Add `e2e/.nuxt/`, `e2e/node_modules/`, `e2e/test-results/`, `e2e/playwright-report/`.

**G4. Rewrite `e2e/board.spec.ts` to match the new product surface** (delete the old `kanban.spec.ts` — it has stale selectors)
- Tests:
  - `board loads with 5 columns and non-empty cards`
  - `New Issue modal creates a visible card` (open modal → fill → submit → assert card in backlog)
  - `moving an issue to In Progress creates a job` (drag, then assert ECC Logs tab shows the safe-runner events)
  - `IssueDetail ECC Logs shows job event timeline` (open detail → click ECC Logs tab → assert event count + first event message)
  - `Recent Jobs click opens linked issue detail` (sidebar → click first job → assert IssueDetail panel with ECC Logs tab active)
  - `Review Queue approve moves issue to Done` (open Review Queue → click Approve → assert card moved)
  - `Review Queue request changes moves issue to In Progress` (click Request changes → confirm → assert card moved)
  - `mobile board columns do not collapse` (already in the existing spec; keep)

**G5. Run `npm run e2e`**
- This is the gate. Must pass on a clean checkout (with Postgres running, backend started by the e2e harness, frontend built + previewed).

**G6. Backend lifecycle for E2E**
- The current config starts only the frontend webServer. Add a second `webServer` entry for the backend or use Playwright's `globalSetup` to run `uvicorn` once.
- Simpler: add a `e2e/global-setup.ts` that ensures the backend is reachable at `http://127.0.0.1:8000/health` and skips startup if already running.

### Phase H — Verification gates (must all pass before declaring done)

```bash
# Backend
export DATABASE_URL=postgresql+asyncpg://devflow:devflow_secret@localhost:5432/devflow
PYTHONPATH=backend python3 -m pytest -q backend/tests
# expected: 16 existing + ~6 new = 22 passed

# Frontend
npm run typecheck
npm run build

# E2E
npm run e2e
# expected: all green; on CI, must include Postgres in the runner
```

Manual smoke:
1. Start backend with Postgres URL.
2. `curl http://127.0.0.1:8000/api/v1/board` → returns the 8 seeded issues.
3. `curl http://127.0.0.1:8000/api/v1/ecc/jobs?issue_id=seed-1` → empty list.
4. `curl -X POST http://127.0.0.1:8000/api/v1/ecc/dispatch -d '{...}'` → returns job immediately.
5. After 1s, `GET /api/v1/ecc/jobs/{id}` → status `review_required`, events ≥ 4.
6. Restart backend → re-`GET` → job still there, events preserved.

## Key Files

| File | Operation | Description |
|------|-----------|-------------|
| `backend/db/database.py` | Modify | Auto-prefix driver on `DATABASE_URL`; remove hardcoded sqlite default behavior |
| `backend/db/models.py` | Modify | `JobModel.events` → `JSON` type; drop `to_dict` json.loads |
| `backend/db/repository.py` | New | All DB I/O: `seed_if_empty`, `list_issues`, `upsert_issue`, `update_issue_status`, `upsert_job`, `get_job`, `list_jobs(issue_id=None)`, `load_all_jobs_into_memory` |
| `backend/main.py` | Modify | Lifespan calls `repo.seed_if_empty` and `repo.load_all_jobs_into_memory` |
| `backend/api/v1/endpoints/board.py` | Modify | Read from `repo.list_issues` instead of `issues._issues_db` |
| `backend/api/v1/endpoints/issues.py` | Modify | Persist via `repo.upsert_issue` / `repo.update_issue_status`; drop in-memory `_issues_db` seed |
| `backend/api/v1/endpoints/ecc.py` | Modify | `list_ecc_jobs(issue_id=None)` filters via repo; `_save_job_to_db` delegates to `repo.upsert_job`; `load_jobs_from_db` delegates to `repo.load_all_jobs_into_memory` |
| `backend/tests/test_api_smoke.py` | Add | DB-persistence + `?issue_id=` tests |
| `src/stores/board.ts` | Modify | Add `jobsById`, `jobsForIssue`, `fetchJobs`, `fetchJob`, `fetchJobsForIssue`, `attachJobToIssue`, `getIssueJob`, `pollIssueJob`; new `createIssue({ payload })` signature; new `openDetail(issue, tab)`; new `getReviewQueue`, `approveReview`, `requestChanges` |
| `src/components/IssueDetail.vue` | Modify | ECC Logs tab renders job metadata + event timeline; new empty state copy; mount-time `pollIssueJob` |
| `src/components/sidebar/Sidebar.vue` | Modify | Replace raw setInterval with `useRecentJobs()`; add Review Queue section |
| `src/composables/useRecentJobs.ts` | New | Composable owning the 5s polling lifecycle |
| `src/components/NewIssueModal.vue` | New | Modal with title/description/status/priority/profile + inline error |
| `src/components/ReviewQueue.vue` | New | Review list with Approve / Request changes |
| `src/utils/jobStatus.ts` | New | Shared `ECC_JOB_STATUS_COLORS` map |
| `package.json` | Modify | Add `@playwright/test` to `devDependencies` |
| `e2e/playwright.config.ts` | Modify | Fix `webServer.command`, add CI-aware `reuseExistingServer`, set `outputDir` and `reporter` |
| `e2e/board.spec.ts` | Rewrite | Replace stale tests with the 8 listed in Phase G4 |
| `e2e/kanban.spec.ts` | Delete | Superseded by board.spec.ts |
| `e2e/global-setup.ts` | New | Backend health check; skip if already running |
| `.gitignore` | Modify | Add `e2e/.nuxt/`, `e2e/node_modules/`, `e2e/test-results/`, `e2e/playwright-report/` |
| `.env.example` | Modify | `DATABASE_URL=postgresql+asyncpg://...` (add driver prefix) |

## Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| Postgres schema migration from SQLite data is a no-go — different files | Plan keeps `JobModel.events` JSON-compatible. New dev DBs start empty (seeding inserts). Existing dev DBs can be deleted; this is dev-only data. |
| `JSON` column on SQLite stores as TEXT — but `to_dict` no longer calls `json.loads`. The new behavior must still work for SQLite | Unit-test `repo.get_job` and `list_jobs` against both backends. CI runs only against SQLite for tests (cheap, fast); manual Postgres smoke is separate (Phase A8). |
| `e2e/` already has `node_modules` from a previous install — might be stale | `npm install` after `package.json` change will reconcile. Add a CI step `rm -rf e2e/node_modules` before install if needed. |
| `npm run preview -- --port 3010` (the original bad config) double-binds the port because the `preview` script already sets `PORT=3010` | Replace with explicit command that doesn't double-bind. |
| `npm run e2e` will try to start the backend if it's not running — but the existing config doesn't | Add `e2e/global-setup.ts` to verify backend health (no auto-start, to keep config simple). Document that the dev workflow is "start backend, then `npm run e2e`." |
| Backend startup race: `seed_if_empty` and `load_all_jobs_into_memory` both run in lifespan. If a job is dispatched in a race window, it could be lost. | Existing code already has `_save_job_to_db` always being called inside the dispatch handler. The repo path keeps that contract. Tests cover the race. |
| `createIssue` throwing on backend failure breaks the previous "local-only fallback" UX | This is intentional per the plan. The inline error in the modal surfaces the failure cleanly. If the backend is truly down, the user sees the error and can retry. |
| WebSocket double-accept P1 from last review still unfixed | Polling path remains default. WebSocket fix is a follow-up. |
| `PUT /issues/{id}/status` body vs query P1 from last review | Modal and review queue call `moveIssue` which already does `$fetch(... { method: 'PUT', body: ... })`. If that path returns 422 the dispatch silently fails (current bug). Flagged in delivery report as known follow-up; not in this phase per "fix one loop at a time." |

## SESSION_ID
- CODEX_SESSION: N/A (Codex CLI used at audit only, no long-running session)
- GEMINI_SESSION: N/A (Gemini CLI not installed in this environment)

## Validation Commands

After implementation:

```bash
# Backend
export DATABASE_URL=postgresql+asyncpg://devflow:devflow_secret@localhost:5432/devflow
PYTHONPATH=backend python3 -m pytest -q backend/tests
# expected: 22 passed (16 existing + 6 new)

# Frontend
npm run typecheck
npm run build
# both should be clean

# E2E (backend must already be running on 8000)
npm run e2e
# expected: 8 specs, all green

# Manual smoke (Postgres)
curl -s http://127.0.0.1:8000/api/v1/board | jq '.columns | length'   # 5
curl -s -X POST http://127.0.0.1:8000/api/v1/ecc/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"issue_id":"seed-1","issue_key":"DEV-001","command":"/loop-start --profile=frontend","profile":"frontend","harness":"claude-code"}'
curl -s 'http://127.0.0.1:8000/api/v1/ecc/jobs?issue_id=seed-1' | jq '.jobs | length'  # ≥ 1
```

## Estimated Effort

This plan covers 6 modules. Realistic breakdown:
- Phase A (Postgres + persistence): 4–6 hours, including the test suite
- Phase B (issue_id filter): 30 minutes
- Phase C (Job/Logs frontend): 3–4 hours
- Phase D (Sidebar formalization): 1–2 hours
- Phase E (New Issue Modal): 1–2 hours
- Phase F (Review Queue): 2–3 hours
- Phase G (E2E): 2–3 hours, dominated by `npm install` + Playwright browser download

Total: roughly **2 working days** for one focused pass. Suggest executing Phase A + G first as a single commit, then B + C + D + E + F in feature branches.
