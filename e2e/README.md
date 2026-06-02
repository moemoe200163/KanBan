# E2E tests

> **The E2E suite is destructive.** It assumes the backend is running
> against the `devflow_e2e` database. If you point the E2E suite at a
> dev or production database, the reset endpoint will **truncate your
> `issues` and `ecc_jobs` tables**.

## Running the E2E stack

```bash
# 1. Bring up the E2E stack (postgres + backend, with the override).
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d

# 2. Wait for the backend to be ready.
curl --retry 30 --retry-delay 2 --retry-connrefused \
  http://127.0.0.1:8000/health/ready

# 3. Run the Playwright suite.
npm run e2e
```

The E2E compose override (`docker-compose.e2e.yml`) sets two things:

1. `POSTGRES_DB=devflow_e2e` on the postgres service, so a fresh
   database is created and **named** with `_e2e`.
2. `E2E=1` on the backend service.

Both conditions must hold for the reset endpoint to be wired up; this
is the second half of the double-gate described in
`/Users/user/Code/kanban/.claude/plan/p0-postgres-hardening.md`.

## What the global setup does

`global-setup.ts` runs **once** before any spec:

1. Poll `GET /health` until 200 (max 60s) — proves the backend is up.
2. Poll `GET /health/ready` until 200 (max 30s) — proves the DB is
   reachable.
3. `POST /api/v1/test/reset` — truncates `issues` and `ecc_jobs` and
   re-seeds the board. Safe only because the previous two checks
   passed.

## Cleanup

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v
```

The `-v` flag removes the `postgres-data` volume so the next run
starts from a clean `devflow_e2e` database.
