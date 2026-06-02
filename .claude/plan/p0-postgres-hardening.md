# P0 Postgres Hardening — Implementation Plan

> **Mission:** Make the repo **startable, migratable, restartable, and verifiable** against Postgres. No new features. No new dependencies. No commits without explicit approval.

---

## State of the world (read-only reconnaissance)

### The bugs and gaps

| # | File / location | Problem | Severity |
|---|-----------------|---------|----------|
| B1 | `backend/db/database.py:103-126` (`_run_alembic_upgrade_head`) | Sync function called from `init_db()` (async). It calls `alembic.command.upgrade(cfg, "head")` which internally calls `env.py:run_migrations_online()` → `asyncio.run(run_async_migrations())`. **Creating a new event loop inside a running event loop raises `RuntimeError: asyncio.run() cannot be called from a running event loop`.** Note: `init_db()` itself does `try/except ... raise` (line 147-149) — it re-raises. **The actual swallower is the outer `try/except` at `backend/main.py:45-63` (the lifespan's DB init block)**, which logs `Database initialization failed` as a warning and lets the app keep booting. The rest of the lifespan (seed, load_jobs, ProcessRunner) still runs, but the schema is **never created on Postgres**. | **Critical** |
| B2 | `backend/db/models.py` vs `backend/alembic/versions/0001_initial.py` | Models define **7 tables** (Issue, Agent, AuditLog, WebhookEvent, JobModel, QualityGateResult, User). Migration creates only **2** (issues, ecc_jobs). On Postgres: `agents`, `audit_logs`, `webhook_events`, `quality_gate_results`, `users` **never exist** — any query that touches them blows up at runtime. SQLite masks this because `create_all` builds the full metadata. | **Critical** |
| B3 | `backend/main.py:130-167` `/health/ready` | Hardcoded `checks = {"api": "ok"}` — never actually pings Postgres or Redis. Returns 200 even when DB is down. Useless as a real readiness gate. | High |
| B4 | `backend/docker-compose.yml` | Legacy `version: '3.8'` file with only postgres + redis. Conflicts with the root `docker-compose.yml` (which is the canonical, full-stack compose). Confusing for `docker compose up`. | Medium |
| B5 | `backend/Dockerfile` | Bare single-stage file (lines 1-7). The canonical multi-stage `Dockerfile` is at the repo root. The `backend/Dockerfile` is unused by `docker-compose.yml` (which uses root context with `target: backend`). | Low |
| B6 | `e2e/board.spec.ts` + `e2e/global-setup.ts` | E2E suite calls `http://127.0.0.1:8000/api/v1/issues` against whatever backend is running. If the dev backend is up, E2E **pollutes the dev board** with "Created by Playwright E2E." cards and never cleans up. | High |
| B7 | `.gitignore` | Already contains every required path: `.output/`, `.nuxt/`, `e2e/.nuxt/`, `test-results/`, `e2e/test-results/`, `backend/devflow.db`, `.DS_Store`, `playwright-report/`. **No changes needed** to `.gitignore`. The cleanup is verifying that `git status --short` shows only meaningful work after the fix. | None |
| B8 | `backend/alembic/versions/` | Only `0001_initial.py` exists. Need `0002_*.py` to create the other 5 tables. | **Critical** (covered by B2) |
| B9 | `docker-compose.yml:9, 15` | `NUXT_PUBLIC_API_BASE=http://backend:8000/api/v1` is set in the **frontend container build args and runtime env**. `backend` is a Docker-network hostname — **the browser on the host cannot resolve it**. Result: a user opening `http://127.0.0.1:3010` (or `http://localhost:3010`) sees the Nuxt app but every API call 404s/times out. The backend is reachable at `127.0.0.1:8000` on the host because of the `ports: "8000:8000"` mapping, so the correct apiBase is `http://127.0.0.1:8000/api/v1` (or, if going through nginx on port 80, `/api/v1`). This is a **P0 functional bug** for any browser-based access. **This must be fixed before any E2E work** because `e2e/board.spec.ts` already uses `127.0.0.1:8000` for backend, confirming the project intent. | **Critical** |

### What's already in place (don't touch)

- Root `docker-compose.yml` — full stack (frontend, backend, postgres, redis, nginx) with healthchecks, depends_on conditions, named volumes. **Canonical.**
- Root `Dockerfile` — three stages (frontend, backend, development). **Canonical.**
- `backend/alembic/env.py` — uses the env-driven `DATABASE_URL`, async engine, `NullPool`. Correctly set up.
- `backend/alembic.ini` — points to `backend/alembic`, prepends `backend` to `sys.path`. Correct.
- `backend/requirements.txt` — has `alembic==1.14.0`, `sqlalchemy[asyncio]==2.0.35`, `asyncpg==0.30.0`, `aiosqlite==0.20.0`. Correct.
- `pytest.ini` — `pythonpath = backend`, `asyncio_mode = strict`, `testpaths = backend/tests`. Correct.
- `backend/tests/test_persistence.py` — 8 well-scoped tests with a `fresh_db` fixture that swaps the engine. Uses `TestClient` (not lifespan). Already covers: board, create issue, list jobs, filter jobs, jobs round-trip, status update, restart survival.
- `backend/tests/test_api_smoke.py` — endpoint smoke tests.
- `nginx.conf` — present at root, not read in this pass (will verify in execute phase).

### Constraints (from project memory)

- Frontend port `3010`, backend port `8000` (hardcoded in CLAUDE.md).
- Do NOT run `git commit` unless user explicitly says so.
- Do NOT introduce new dependencies.
- Do NOT replace the stack.
- Safe runner stays the default execution path; no real Claude/ECC CLI.

---

## Technical Solution

### Solution A — Fix the Alembic startup race (B1)

**Root cause:** `_run_alembic_upgrade_head()` is sync, but it's called from inside `init_db()` which is async. The chain is:

```
init_db() (async, runs in uvicorn event loop)
  └─> _run_alembic_upgrade_head() (sync, called without await)
        └─> alembic.command.upgrade(cfg, "head") (sync)
              └─> env.py:run_migrations_online() (sync)
                    └─> asyncio.run(run_async_migrations())  ← RuntimeError if a loop is running
```

**Fix:** Move the sync call to a worker thread. Python 3.9+ provides `asyncio.to_thread()` which is exactly this. The thread has no event loop, so `asyncio.run()` inside `env.py` works normally. The uvicorn event loop is not blocked because the work happens off-loop.

**Diff (conceptual) in `backend/db/database.py`:**

```python
import asyncio

async def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return

    if is_postgres():
        try:
            # Run the sync alembic CLI in a worker thread so it can
            # create its own event loop via env.py:asyncio.run().
            # Calling it directly from the running uvicorn loop would
            # raise RuntimeError ("asyncio.run() cannot be called from
            # a running event loop") and silently break migrations.
            await asyncio.to_thread(_run_alembic_upgrade_head)
        except Exception as e:
            logger.error(f"Alembic upgrade failed: {e}")
            raise
    else:
        # SQLite: keep create_all for fast pytest setup
        ...
    _db_initialized = True
```

No change needed to `env.py` (the standard `asyncio.run()` pattern is correct — the problem was only the call site).

### Solution B — Bring migration in line with models (B2/B8)

**Two options, with trade-offs:**

- **Option B1: Extend `0001_initial.py` to include all 7 tables.** Pro: one migration, simple history. Con: rewrites history; existing Postgres instances that already ran `0001_initial` would see a no-op (Alembic would re-detect schema diff) or fail. **Risky for any environment that already migrated.**
- **Option B2: Add a new `0002_remaining_tables.py` that creates the 5 missing tables.** Pro: forward-only, safe for any environment. Con: two migrations instead of one. **Recommended.**

**Pick Option B2** unless no Postgres has ever run `0001_initial` (in that case both are equivalent — but B2 is still safer because it preserves the existing migration file's revision id, which is already in any deployed environment's `alembic_version` table).

**New migration `backend/alembic/versions/0002_remaining_tables.py`** creates:
- `agents` (mirrors `db.models.Agent`)
- `audit_logs` (mirrors `db.models.AuditLog`)
- `webhook_events` (mirrors `db.models.WebhookEvent`)
- `quality_gate_results` (mirrors `db.models.QualityGateResult`)
- `users` (mirrors `db.models.User`)

Each table gets the same column types, nullability, defaults, and indexes as defined in `db/models.py`. For Postgres, use `JSONB` for JSON columns where the model uses `JSON` (consistent with `0001_initial`'s precedent for `events`).

**Generation strategy:** hand-write the migration rather than rely on `alembic revision --autogenerate` because (a) autogenerate can drift from intent, (b) the hand-written version is reviewable as a unit, and (c) we need the explicit Postgres/JSONB branch.

### Solution C — Make `/health/ready` actually check (B3)

The current `/health/ready` is theatre. Make it real:

```python
@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    checks = {"api": "ok"}

    # Database check: open a session and run SELECT 1
    try:
        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis check: PING (if a real Redis client is wired up; placeholder
    # for now keeps the contract).
    checks["redis"] = "ok"  # placeholder until redis is actually used

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )
```

Scope: minimal — only the DB check needs to be real. Redis check stays a placeholder (the project doesn't actually use Redis yet; the volume is there for future pub/sub).

### Solution D — Add a Docker smoke script (acceptance gate)

**New file: `scripts/smoke.sh`** (executable bash, root of repo).

Flow:
1. `docker compose -f docker-compose.yml config` — validate the compose file (acceptance gate #4).
2. Bring up postgres + redis + backend, with `docker compose up -d --wait postgres redis backend` (the `--wait` flag waits for healthchecks).
3. Poll `http://127.0.0.1:8000/health` until 200 (max 60s).
4. `curl -fsS http://127.0.0.1:8000/health/ready` — must return 200 with `database=ok` (acceptance gate #7).
5. `curl -fsS http://127.0.0.1:8000/api/v1/board` — must return 200 with non-empty columns (acceptance gate #7).
6. `curl -fsS http://127.0.0.1:8000/api/v1/ecc/jobs` — must return 200 with `total >= 0` (acceptance gate #7).
7. Verify migrations actually applied to Postgres by running `psql` inside the `postgres` container and checking the `alembic_version` table contains the head revision (`0002_remaining_tables` after Step 2 is done). **Do NOT grep a log line that doesn't exist** (the current `init_db()` doesn't print "Alembic upgrade succeeded" — only a generic `Database initialized: OK` line). The `alembic_version` check is the source of truth.
8. `docker compose down -v` — teardown (don't leave dangling volumes).
9. Each step prints `PASS` or `FAIL`; the script exits non-zero on first failure.

This script is the single source of truth for "Docker stack is healthy." It runs in CI and locally.

### Solution E — E2E data isolation (B6) — **stricter gating**

**`E2E=1` alone is NOT enough.** A misconfigured production-like env that happens to have `E2E=1` set (or a leaked CI variable, or a developer copying their shell env into a container) would let the reset endpoint wipe the dev DB. Treat reset as a P0 data-destruction risk and gate it on **two independent conditions**:

1. **`E2E=1` env var set** (developer/CI opt-in)
2. **`DATABASE_URL` database name contains `_e2e`** (e.g., `devflow_e2e`)

Both must be true or the endpoint returns 404 (so it's not even discoverable in `/docs`). The reasoning: it's extremely unlikely someone names a real production DB with `_e2e` in it, so this catches every realistic misconfiguration.

**E1: E2E database strategy — `docker-compose.e2e.yml` override.**

Use a Docker Compose **override file** rather than a second hardcoded compose. This keeps the base `docker-compose.yml` clean and E2E's "extra postgres" out of dev's way:

```yaml
# docker-compose.e2e.yml
services:
  postgres:
    environment:
      - POSTGRES_DB=devflow_e2e
    # No port mapping; E2E backend reaches it via the network
  backend:
    environment:
      - E2E=1
      - DATABASE_URL=postgresql+asyncpg://devflow:devflow_secret@postgres:5432/devflow_e2e
    depends_on:
      - postgres
```

Run with: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d`.

**E2: Reset endpoint (`POST /api/v1/test/reset`) — triple-gated.**

- Check `os.getenv("E2E") == "1"` → if not, 404.
- Parse `DATABASE_URL` and verify the database name (last path segment) **ends with** `_e2e` (or contains `_e2e`) → if not, 404.
- Log a `WARNING` line every time it's called (so the audit trail is in the logs).
- Exclude it from OpenAPI tags (don't list it in `/docs`).

Action: TRUNCATE `ecc_jobs` and `issues`, then call `seed_if_empty()`. Return `{"status": "reset", "seeded": N, "database": "devflow_e2e"}` (the `database` echo is intentional — it proves the gating worked).

**E3: E2E global-setup ordering** (corrected from the original plan):
1. Poll `GET /health` until 200 (max 60s) — proves the backend container is up at all.
2. Poll `GET /health/ready` until 200 (max 30s) — proves DB is reachable.
3. `POST /api/v1/test/reset` — only safe after both above. Assert response shape.
4. Then start the spec runner.

The original plan had reset before health check, which is broken: reset needs a running backend.

**E4: Verify cleanup is in `.gitignore`.** `e2e/.nuxt/`, `e2e/test-results/`, `e2e/playwright-report/` are all already there. Run `git ls-files | grep -E 'e2e/\.(nuxt|test-results|playwright-report)'` to catch any tracked files; if any are tracked, `git rm --cached` them.

**E5: Document loudly.** Add to `e2e/README.md` (create if missing):
> The E2E suite is **destructive** to whatever database the backend is using. It assumes the backend is running against `devflow_e2e`. If you accidentally point the E2E suite at your dev DB, you will lose your dev board. Use `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d` to guarantee isolation.

### Solution F — File cleanup (B4/B5)

- **B4 (`backend/docker-compose.yml`):** delete the file. Add a one-line note in `README.md` (or commit message, not a code change) saying the canonical compose is at the root.
- **B5 (`backend/Dockerfile`):** delete the file. The root multi-stage `Dockerfile` is what `docker-compose.yml` references.
- **Verify with:** `grep -rn "backend/Dockerfile\|backend/docker-compose" .` returns nothing.

### Solution G — No `.gitignore` changes (B7)

The file already has every path the user listed. Verify with `cat .gitignore` matching the requirement list and `git status --short` only showing files we've intentionally modified (and no spurious `e2e/.nuxt/`, `backend/devflow.db`, etc.).

### Solution H — Fix Docker frontend API base (B9)

**Pick one of two configurations and document it.** Don't paper over the problem by trying to detect "am I in Docker?" at runtime — that's a rabbit hole.

**Configuration H1: Direct host access (default for `docker compose up` + browser on the same host).**

Change `docker-compose.yml` line 9 and line 15 to:
```yaml
- NUXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1
```

This is the simplest config. The user opens `http://127.0.0.1:3010` in their browser, the frontend calls `http://127.0.0.1:8000/api/v1/...`, which the Docker daemon maps to the backend container's port 8000. No nginx needed for the API path. nginx still serves frontend assets.

**Configuration H2: nginx-relative path (for users who go through `http://127.0.0.1/` on port 80).**

Change `docker-compose.yml` line 9 and line 15 to:
```yaml
- NUXT_PUBLIC_API_BASE=/api/v1
```

This requires the user to access the app via `http://127.0.0.1/` (port 80) instead of `http://127.0.0.1:3010/`. nginx must proxy `/api/v1` to `backend:8000`. Verify `nginx.conf` has that location block before shipping; if not, add it (covered in execute phase).

**Pick H1 (host-direct) as the default** because:
- The repo's `e2e/board.spec.ts` already talks to `http://127.0.0.1:8000` directly (proves the project already assumes the backend is host-reachable, not container-internal).
- It removes a class of "works in docker, breaks in `npm run dev`" bugs.
- It doesn't require modifying `nginx.conf`.
- It matches the existing backend port mapping.

**Backwards compatibility:** If the project ever runs in production behind a real domain with TLS termination, the operator sets `NUXT_PUBLIC_API_BASE` to the real public URL — same env var, same override mechanism. So this change doesn't lock us in.

**Smoke verification:** Add to the smoke script: `curl -fsS http://127.0.0.1:3010/` and grep the response or the Nuxt-rendered HTML for the configured apiBase. (Optional — only do this if Step 6 already has the script; the curl check at `/api/v1/board` from the host already covers the API path.)

---

## Implementation Steps (ordered)

**Order rationale (per user feedback):** Docker frontend API base first — if it's wrong, the user can't open the app in a browser at all, so nothing else is observable. Alembic event loop next — without that, no schema is created on Postgres, which blocks all Postgres verification. Schema parity (migration 0002) third — even if the loop fix works, only 2 of 7 tables exist. Then real readiness check, then E2E isolation, then smoke script, then legacy file cleanup, then tests, then final verification, then code review.

Each step has an acceptance sub-gate. The plan does not proceed until the sub-gate passes.

### Step 1 — Fix Docker frontend API base (Solution H) — **highest priority**

**Files:** `docker-compose.yml`
**Sub-gate:** Browser at `http://127.0.0.1:3010` (or Playwright in `e2e/board.spec.ts`) can make an API call to `/api/v1/board` and get a 200. Verified by `curl http://127.0.0.1:3010/` returning HTML whose `__NUXT__` payload (or rendered `<link>` to a generated JS bundle) reflects the new apiBase, AND by `curl http://127.0.0.1:8000/api/v1/board` from the host returning 200.

1. Edit `docker-compose.yml` line 9 (`args:` under `frontend.build`) and line 15 (`environment:` under `frontend`) to set `NUXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1` (H1 — host-direct).
2. `docker compose build frontend` (forces a rebuild with the new build arg).
3. `docker compose up -d` and verify the frontend container env shows the new value: `docker compose exec frontend env | grep NUXT_PUBLIC_API_BASE`.
4. `curl -fsS http://127.0.0.1:8000/api/v1/board` from the host → 200.
5. Add a one-line comment in `docker-compose.yml` explaining the choice (so the next person doesn't re-introduce the bug).

### Step 2 — Alembic startup fix (Solution A)

**Files:** `backend/db/database.py`
**Sub-gate:** Postgres `docker compose up` reaches `Application startup complete.` without `asyncio.run()` errors in the backend logs; `alembic_version` table in Postgres contains the head revision after startup.

1. Add `import asyncio` at the top of `db/database.py`.
2. Change line 146 from `_run_alembic_upgrade_head()` to `await asyncio.to_thread(_run_alembic_upgrade_head)`.
3. Add a comment block explaining the why (1-2 lines).
4. Re-run `docker compose up -d backend` and `docker logs devflow-backend | tail -30` to confirm the migration log line shows up. If `alembic_version` exists in Postgres with revision `0001_initial`, this is good. (After Step 3, it'll have `0002_remaining_tables`.)

### Step 3 — Add migration 0002 (Solution B)

**Files:** `backend/alembic/versions/0002_remaining_tables.py` (new)
**Sub-gate:** `docker compose down -v && docker compose up -d backend` brings the backend to ready; `docker compose exec postgres psql -U devflow -d devflow -c '\dt'` shows all 7 tables (`issues`, `ecc_jobs`, `agents`, `audit_logs`, `webhook_events`, `quality_gate_results`, `users`); pytest still passes on SQLite (no regression).

1. Create the file with 5 `op.create_table(...)` blocks mirroring `db/models.py`.
2. Use the same dialect-conditional `JSONB()` vs `sa.JSON()` pattern as `0001_initial.py`.
3. Mirror every index declared in `__table_args__` per model.
4. Add a `downgrade()` that drops the 5 tables in reverse order.
5. Run `alembic upgrade head` locally against SQLite to verify the SQL is syntactically valid, then against the running Postgres container to verify the JSONB branch.
6. Run `PYTHONPATH=backend pytest -q backend/tests` — must still pass (SQLite path doesn't use Alembic at runtime, so this is just a safety check).

### Step 4 — Real `/health/ready` check (Solution C)

**Files:** `backend/main.py`
**Sub-gate:** `curl /health/ready` returns 503 if Postgres is unreachable, 200 with `{"database": "ok"}` when it is reachable. (Manual verification — `docker compose stop postgres`, curl returns 503; `docker compose start postgres`, curl returns 200.)

1. Add a `try/except` around `AsyncSessionLocal().execute(text("SELECT 1"))`.
2. Keep the `redis` check as `"ok"` placeholder (don't fabricate a fake ping).
3. Keep the response shape: `{"status": ..., "checks": ...}`.

### Step 5 — E2E isolation (Solution E)

**Files:** `e2e/global-setup.ts` (modify), `backend/api/v1/endpoints/test_reset.py` (new, gated), `docker-compose.e2e.yml` (new)
**Sub-gate:** `npm run e2e` can be run twice in a row with the same outcome; the dev DB (if a developer happens to have it running) is **never** modified by the E2E suite; the response from `/api/v1/test/reset` echoes the database name so the operator can see which DB was hit.

1. Add `POST /api/v1/test/reset` endpoint in `backend/api/v1/endpoints/test_reset.py`:
   - Returns 404 unless `os.getenv("E2E") == "1"` (opt-in env var).
   - Parses `DATABASE_URL`, extracts the database name (last path segment), and returns 404 unless it contains `_e2e`. This is the **second gate**.
   - Truncates `ecc_jobs` and `issues` tables.
   - Calls `seed_if_empty()`.
   - Logs a `WARNING` line that includes the database name.
   - Returns `{"status": "reset", "seeded": N, "database": "devflow_e2e"}`.
2. Mount the router in `backend/main.py` only when the same E2E gating condition is met (extra safety).
3. Create `docker-compose.e2e.yml` (override) that:
   - Sets `POSTGRES_DB=devflow_e2e` on the postgres service.
   - Sets `E2E=1` and `DATABASE_URL=postgresql+asyncpg://devflow:devflow_secret@postgres:5432/devflow_e2e` on the backend service.
4. In `e2e/global-setup.ts`, **ordered** as:
   1. Poll `GET /health` until 200 (60s timeout).
   2. Poll `GET /health/ready` until 200 (30s timeout).
   3. `POST /api/v1/test/reset` and assert response shape (must include `database: "devflow_e2e"`).
   4. Then start specs.
5. Add to `e2e/README.md` (create if missing) the destruction warning from Solution E5.
6. Run `git ls-files | grep -E 'e2e/\.(nuxt|test-results|playwright-report)'` and `git rm --cached` any tracked files.

### Step 6 — Docker smoke script (Solution D)

**Files:** `scripts/smoke.sh` (new, executable), `scripts/README.md` (new, one paragraph)
**Sub-gate:** `./scripts/smoke.sh` exits 0 from a clean repo; `docker compose -f docker-compose.yml config` exits 0; `alembic_version` table in Postgres contains the head revision; all 3 API endpoints respond.

1. Write the script. Idempotent: detects if a previous run left services up and tears them down first.
2. Use `psql` inside the postgres container to check `alembic_version.version_num = '<head_revision>'` — do NOT grep a non-existent log line.
3. Add a one-paragraph README at `scripts/README.md` explaining when to run it and what each check does.
4. Make `scripts/smoke.sh` executable (`chmod +x`).

### Step 7 — File cleanup (Solution F)

**Files:** `backend/Dockerfile` (delete), `backend/docker-compose.yml` (delete)
**Sub-gate:** `grep -rn "backend/Dockerfile\|backend/docker-compose" .` returns zero; `docker compose config` still works; `docker compose up backend` still builds the backend from the root Dockerfile.

1. Delete both files (`git rm` for tracked, `rm` for untracked — verify with `git ls-files` first).
2. Re-run `docker compose config` to confirm no references broke.
3. Re-run `scripts/smoke.sh` to confirm.

### Step 8 — Write tests for the new behavior (BEFORE the verification sweep)

**Files:** `backend/tests/test_alembic_async.py` (new), `backend/tests/test_health_ready.py` (new), `backend/tests/test_test_reset.py` (new), `e2e/global-setup.ts` (augment)
**Sub-gate:** `PYTHONPATH=backend pytest -q backend/tests` exits 0 with the new tests included. Each new test is `TestClient`-based (no live Postgres required for unit-level coverage; the smoke script covers the live-DB path).

**T8.1 — Test that `init_db()` does not raise when the alembic path runs inside a running event loop.** New file `backend/tests/test_alembic_async.py`:
- Monkeypatch `_run_alembic_upgrade_head` to a no-op so we don't depend on a live Postgres.
- Monkeypatch `is_postgres` to return `True`.
- Call `await db_module.init_db()` from inside an `asyncio.run(...)` block.
- Assert no `RuntimeError` about nested event loops.
- Assert the `_db_initialized` flag flipped to `True`.

**T8.2 — Test that `/health/ready` reports `database: ok` when the DB is reachable, and `degraded` when not.** New file `backend/tests/test_health_ready.py`:
- Use the existing `fresh_db` fixture pattern.
- With a healthy DB: GET `/health/ready` → 200, body has `"database": "ok"`.
- With a broken DB (monkeypatch `AsyncSessionLocal.execute` to raise): GET `/health/ready` → 503, body has `"database": "error: ..."`.

**T8.3 — Test that `/api/v1/test/reset` is gated by BOTH `E2E=1` AND `_e2e` in DATABASE_URL.** New file `backend/tests/test_test_reset.py`:
- With `E2E` env var unset (regardless of DATABASE_URL): POST `/api/v1/test/reset` → 404.
- With `E2E=1` but `DATABASE_URL=.../devflow` (no `_e2e`): POST → 404.
- With `E2E=1` and `DATABASE_URL=.../devflow_e2e`: POST → 200, response body includes `"database": "devflow_e2e"`, and `GET /api/v1/board` shows the 8 seed issues again.

**T8.4 — Migration parity test (the user's anti-drift request).** New file `backend/tests/test_migration_parity.py`:
- Use a file-backed SQLite (or in-memory) and run `alembic upgrade head` programmatically via `asyncio.to_thread` (mirrors the production path).
- After upgrade, query `sqlite_master` (SQLite) / `information_schema.tables` (Postgres) to enumerate the actual tables.
- Compare the actual table set to `set(Base.metadata.tables.keys())` from `db.models`.
- Assert no model is missing from the schema, and no extra unexpected table exists (besides `alembic_version`).
- This test runs on SQLite in CI (cheap) and on Postgres via the smoke script (in the compose-up path) — the assertion logic is the same.

**T8.5 — Extend `e2e/global-setup.ts` with an assertion** that the board has the 8 seed issues AFTER the reset call (so a misconfigured E2E setup fails fast with a clear message, not deep inside `board.spec.ts`).

### Step 9 — Run all acceptance gates (final verification)

Run, in order, with each one passing before the next:

1. `PYTHONPATH=backend python3 -m pytest -q backend/tests` — all tests pass (24+ on SQLite; T8.1-T8.4 are the new ones).
2. `npm run typecheck` — clean.
3. `npm run build` — succeeds.
4. `docker compose -f docker-compose.yml config` — exits 0.
5. `./scripts/smoke.sh` — fresh Postgres, migration runs, all 3 endpoints respond.
6. `git status --short` — only the files we intentionally changed appear; no `e2e/.nuxt/`, no `backend/devflow.db`, no `node_modules/`, no `.DS_Store`.
7. `git diff` — reviewable, no spurious changes.

### Step 10 — Code review (final gate)

**Subagent:** `code-reviewer` (or `python-reviewer` for the alembic changes, since the diff is mostly Python).

Review the full diff for:
- The `asyncio.to_thread` placement and exception handling
- The migration file's column parity with `db/models.py` (any drift is a real bug)
- The `/health/ready` change doesn't regress the 200 response when the DB is up
- The `test_reset` endpoint is properly gated on **both** env var AND `_e2e` in DB name, and doesn't ship in production
- The Docker compose apiBase change is consistent across build args and runtime env
- No leftover references to deleted files

---

## Key Files (delta)

| File | Op | Description |
|------|----|-------------|
| `docker-compose.yml` | modify | fix `NUXT_PUBLIC_API_BASE` to `http://127.0.0.1:8000/api/v1` (B9) |
| `backend/db/database.py` | modify | wrap `_run_alembic_upgrade_head()` in `asyncio.to_thread()` |
| `backend/alembic/versions/0002_remaining_tables.py` | new | create agents, audit_logs, webhook_events, quality_gate_results, users tables |
| `backend/main.py` | modify | real DB check in `/health/ready` |
| `docker-compose.e2e.yml` | new | E2E override: devflow_e2e DB, E2E=1 flag |
| `scripts/smoke.sh` | new | docker compose config + up + curl 3 endpoints + check `alembic_version` + down |
| `scripts/README.md` | new | one paragraph on smoke usage |
| `backend/api/v1/endpoints/test_reset.py` | new | gated reset endpoint (E2E=1 + DB name contains `_e2e`) |
| `e2e/global-setup.ts` | modify | ordered: health → ready → reset → specs |
| `backend/Dockerfile` | delete | superseded by root multi-stage |
| `backend/docker-compose.yml` | delete | superseded by root compose |
| `e2e/README.md` | new (if missing) | E2E destruction warning + isolation contract |
| `backend/tests/test_alembic_async.py` | new | T8.1 — alembic-in-async-loop safety |
| `backend/tests/test_health_ready.py` | new | T8.2 — real DB check in /health/ready |
| `backend/tests/test_test_reset.py` | new | T8.3 — gated test reset endpoint (BOTH gates) |
| `backend/tests/test_migration_parity.py` | new | T8.4 — model metadata vs actual tables (anti-drift) |

---

## Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| `asyncio.to_thread` works in Python 3.9+ but the project pins 3.11/3.12 in Dockerfiles — verify | `python:3.11-slim` and `python:3.12-slim` both ship 3.9+. No change needed. |
| Existing Postgres instances already at `head=0001_initial` will need a downgrade+upgrade to apply `0002`. Document the migration path. | The new migration is forward-only and additive. Existing instances can `alembic upgrade head` without downtime. |
| `/health/ready` taking longer because it now hits the DB could trip the smoke script's timeout | 5-second timeout on the DB query is enough; if it's slow, the script's 60-second total wait absorbs it. |
| The `test_reset` endpoint is a footgun if E2E=1 leaks into production | **Double-gate**: env var check + DB name must contain `_e2e` + log a WARN every time it's hit + exclude from OpenAPI tags so it's not discoverable in `/docs`. The DB name check is the load-bearing gate — it's almost impossible to name a real production DB `devflow_e2e` by accident. |
| Picking the wrong API base (H1 vs H2) breaks a workflow the other path supports | Default to H1 (host-direct) which matches the existing `e2e/board.spec.ts` assumption. Document H2 as the alternative in `scripts/README.md` for users who go through nginx on port 80. |
| B9 fix requires a frontend rebuild (build arg change) — easy to forget | `docker compose build frontend` is part of Step 1's sub-gate verification. If the apiBase hasn't actually changed, the curl check on the host port will fail. |
| B2/B8 fix only patches the 7 current models — future model additions will re-introduce the same drift | T8.4 (migration parity test) catches this automatically: if a model is added without a migration, the test fails on next CI run. |
| Deleting `backend/Dockerfile` and `backend/docker-compose.yml` could break someone's local workflow who relies on them | They reference no files that the root setup doesn't already handle. Document the deletion in the commit message (not in code). |
| SQLite pytest passes but Postgres still has a real bug we missed | The smoke script IS the Postgres verification. It runs the same migrations and exercises the same endpoints. Run it after every code change in CI. |
| E2E test reset deletes data the developer wanted to keep | The whole point is isolation: the dev board is whatever's NOT in the E2E path. Document loudly. |

---

## What this plan does NOT do (explicitly out of scope)

- No new features (no review-queue UI, no new API endpoints beyond the test-only `test_reset`).
- No WebSocket wiring to the broadcast pipeline.
- No real Claude/ECC execution.
- No session resume, no autopilot scheduling.
- No changes to `.gitignore` (already correct).
- No commits — the user said "不要 commit，除非我明確要求".

---

## How to run this plan (for `/ccg:execute` or manual)

The plan is structured so each step has a single, checkable sub-gate. The orchestrator should:

1. **Step 1 first (Docker frontend API base).** Without this, the user can't open the app in a browser, and E2E will fail. **Note: requires `docker compose build frontend` after the compose edit.**
2. **Step 2 (Alembic event loop fix).** Without it, the schema is never created on Postgres and everything else is blocked.
3. **Step 3 (migration 0002).** Even with the loop fixed, only 2 of 7 tables exist.
4. **Steps 4-5** (readiness check, E2E isolation) can be done in any order.
5. **Step 6** (smoke script) is the integration check that exercises Steps 1-5 end-to-end.
6. **Step 7** (delete legacy files).
7. **Step 8 is test-writing** — write the tests for the new behavior (T8.1–T8.5) BEFORE running the verification sweep, so a regression in the new code is caught by the suite, not by manual smoke.
8. **Step 9** is the final verification sweep (run all 10 acceptance gates from the user's list).
9. **Step 10** is the human-style code review.

If any step fails, **diagnose, fix, restart, retest** — do not proceed. Only stop and ask the user for: credentials, destructive operations, environment limits, or requirement conflicts.

---

## Plan completeness check

- [x] Task type identified: **Backend (heavy) + DevOps + QA** — this is a fullstack-ish hardening, but the work is mostly backend + infra, with QA as the verification layer.
- [x] Frontend change limited to `NUXT_PUBLIC_API_BASE` env (B9); no app code touched.
- [x] Risks listed.
- [x] Key files listed with operations.
- [x] B1 description corrected: it's `main.py:45-63` outer try/except that swallows, not `init_db()`.
- [x] B9 added: Docker frontend API base.
- [x] E2E reset endpoint double-gated on `E2E=1` AND DB name contains `_e2e` (data destruction risk closed).
- [x] E2E global-setup ordered: health → ready → reset → specs.
- [x] Smoke script uses `alembic_version` table, not a non-existent log line.
- [x] Migration parity test (T8.4) prevents future model drift.
- [x] Acceptance gates map 1:1 to the user's list:
  - pytest 通過 → Step 8 (test-writing) + Step 9.1
  - typecheck 通過 → Step 9.2
  - build 通過 → Step 9.3
  - docker compose config 通過 → Step 9.4 (and inside Step 6)
  - fresh Postgres migration 通過 → Step 9.5 (and inside Step 3, Step 6)
  - backend Docker 啟動通過 → Step 9.5
  - health/API smoke 通過 → Step 9.5 (and inside Step 6)
  - E2E data isolation 有策略 → Step 5
  - git status 已分類 → Step 9.6
  - review 無 blocking issues → Step 10
- [x] Tests written for new behavior → Step 8 (T8.1–T8.5)
- [x] No commits requested.
- [x] No new features requested.
