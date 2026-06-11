# DevFlow — Project Memory for Agents

## Mandatory pre-commit / pre-push check

```bash
# Run from repo root
cd backend && AUDIT_DATABASE_URL='postgresql+psycopg2://devflow:devflow_secret@127.0.0.1:5433/devflow' \
  python3 scripts/audit_schema_drift.py
```

Exit 0 = safe to merge. **Exit 1 = drift detected, do not deploy.** Catches the
failure mode where a SQLAlchemy model field is added or renamed but no Alembic
migration is written to match — leaving ORM queries to explode at runtime with
`UndefinedColumnError` on the first request that touches the table.

The script parses `db/models.py` with `ast` (no async driver required) and
compares the declared columns against `sa.inspect` of the live database. It
also catches reverse drift (columns in the DB the model no longer references)
which usually means an incomplete migration rename.

## Known historical drift (resolved)

- `issue_artifacts.extra_data` vs `metadata` — fixed by migration `0015_issue_artifact_extra_data`.
- `issue_comments.extra_data` vs `metadata` — **still drifted** as of last audit. Needs a `0016` migration; not blocking daily work because no current endpoint queries IssueComment through the ORM (everything goes through raw SQL or repository helpers).
- `issue_handoffs.{decision, review_comment, reviewed_at, reviewed_by}` — **still drifted**. Four columns declared on the model but no migration has ever created them. Same impact profile as the `issue_comments` one.

## DB conventions

- Postgres 15 (`devflow-postgres` container), `DATABASE_URL=postgresql+asyncpg://...@postgres:5432/devflow` inside the network.
- Host port 5433 to avoid colliding with the `securityweb-db-1` Postgres on 5432.
- Alembic revisions live in `backend/alembic/versions/`. Current head: see `alembic heads`.
- New migrations: extend the `0016_*` sequence; the chain is `0014_artifact_folder_path -> 0015_issue_artifact_extra_data -> (next)`.

## Mavis collaboration mode (what it means here)

- The Kanban board is the source of truth for work. Each `Issue` corresponds to a single unit of work. Status transitions (`backlog -> in_progress -> blocked | human_review | done`) are the contract.
- `AgentRole` + `required_role` on the ECC dispatch is how we route to a specific agent (backend-dev, frontend-dev, etc).
- An `AgentRun` is one worker session executing a job. The cycle is: dispatch creates an ECCJob; the safe runner (P0) or a real adapter (when `ALLOW_REAL_LLM_EXECUTION=true`) drives the run; terminal status auto-promotes the linked Issue to the next lane.
- The board's WebSocket (`/ws`) broadcasts `issue_updated` for every status change — including those triggered by the auto-promote hook. Multiple operators see the same card move in real time.

## Deployment surface

- Single `docker compose up -d --build` rebuilds everything. The frontend stage is in the same multi-stage `Dockerfile` as the backend.
- A `.dockerignore` excludes `.output`, `.nuxt`, `node_modules`, `.git`, `.harness`, `.mavis` so host-side dev artifacts never leak into the image.
- `SEED_DEV_DATA` env (default `false`) gates `seed_if_empty` in the FastAPI lifespan. Set to `true` only for a fresh demo DB.
