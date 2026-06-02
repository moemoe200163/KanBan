# DevFlow scripts

## `smoke.sh`

End-to-end Docker stack health check. The single source of truth for
"the canonical Docker stack is startable, migratable, and serving
requests."

```bash
./scripts/smoke.sh
```

What it does:

1. `docker compose config` — validate the compose file.
2. `docker compose up -d --wait postgres redis backend` — start the
   core services and wait for their healthchecks.
3. Poll `GET /health` until 200 (max 60s).
4. `GET /health/ready` must report `database=ok`.
5. `GET /api/v1/board` must return at least one seeded `DEV-*` issue.
6. `GET /api/v1/ecc/jobs` must return HTTP 200.
7. Inside the `postgres` container, `SELECT version_num FROM
   alembic_version` must equal `0002_remaining_tables`.
8. `docker compose down -v` to tear down (also runs in a `trap` so a
   Ctrl-C mid-script still cleans up).

Each step prints `PASS` or `FAIL`; the script exits non-zero on the
first failure. The teardown always runs, so you don't have to worry
about dangling volumes.

### Configuration

| Env var        | Default                  | Meaning |
|----------------|--------------------------|---------|
| `COMPOSE_FILE` | `docker-compose.yml`     | Compose file to test against. |
| `BACKEND_URL`  | `http://127.0.0.1:8000`  | Backend base URL. |

The script is intentionally hermetic: it brings the stack up, checks
it, and tears it down. Running it in CI is safe and idempotent.
