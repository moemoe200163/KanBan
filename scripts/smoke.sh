#!/usr/bin/env bash
#
# DevFlow Docker smoke test.
#
# Verifies the canonical stack (postgres + redis + backend) is healthy
# end-to-end against a fresh volume. This is the single source of truth
# for "the Docker stack is startable, migratable, and serving requests."
#
# Steps (each prints PASS/FAIL; non-zero exit on first failure):
#   1. Validate the base compose file (`docker compose config`).
#   2. Bring up postgres + redis + backend with `--wait`.
#   3. Poll /health until 200 (max 60s).
#   4. Curl /health/ready — must show `database=ok`.
#   5. Curl /api/v1/board — must return 200 with non-empty columns.
#   6. Curl /api/v1/ecc/jobs — must return 200 with `total >= 0`.
#   7. Verify Postgres `alembic_version` table contains `0002_remaining_tables`.
#   8. `docker compose down -v` to clean up.
#
# Usage:
#   ./scripts/smoke.sh
#
# Exits non-zero on any failure. The teardown step runs in a trap so a
# Ctrl-C or a mid-script failure still removes the dangling volume.

set -euo pipefail

readonly COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
readonly BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
readonly HEAD_REVISION="0002_remaining_tables"
readonly HEALTH_TIMEOUT_S=60
readonly READY_TIMEOUT_S=30
readonly STEP_TIMEOUT_S=10

PASS_COUNT=0
FAIL_COUNT=0

# ANSI colors; suppressed when not a TTY.
if [[ -t 1 ]]; then
    readonly C_RED=$'\033[0;31m'
    readonly C_GREEN=$'\033[0;32m'
    readonly C_YELLOW=$'\033[0;33m'
    readonly C_RESET=$'\033[0m'
else
    readonly C_RED="" C_GREEN="" C_YELLOW="" C_RESET=""
fi

log()   { printf '%s[smoke]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
pass()  { printf '%s[smoke]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail()  { printf '%s[smoke]%s %s\n' "$C_RED" "$C_RESET" "$*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
abort() { fail "$*"; cleanup; exit 1; }

cleanup() {
    log "tearing down compose stack (down -v)..."
    docker compose -f "$COMPOSE_FILE" down -v >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Step 1: validate compose file
# ---------------------------------------------------------------------------
log "step 1: validating compose file $COMPOSE_FILE"
if ! docker compose -f "$COMPOSE_FILE" config >/dev/null 2>&1; then
    abort "docker compose config failed for $COMPOSE_FILE"
fi
pass "step 1: compose file is valid"

# ---------------------------------------------------------------------------
# Step 2: bring up the stack with --wait
# ---------------------------------------------------------------------------
log "step 2: bringing up postgres + redis + backend (--wait)"
if ! docker compose -f "$COMPOSE_FILE" up -d --wait postgres redis backend; then
    abort "docker compose up -d --wait failed"
fi
pass "step 2: postgres, redis, and backend are up and healthy"

# ---------------------------------------------------------------------------
# Step 3: poll /health
# ---------------------------------------------------------------------------
log "step 3: polling $BACKEND_URL/health (max ${HEALTH_TIMEOUT_S}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
health_ok=0
while [[ $(date +%s) -lt $deadline ]]; do
    if curl -fsS --max-time "$STEP_TIMEOUT_S" "$BACKEND_URL/health" >/dev/null 2>&1; then
        health_ok=1
        break
    fi
    sleep 1
done
if [[ $health_ok -ne 1 ]]; then
    abort "/health did not return 200 within ${HEALTH_TIMEOUT_S}s"
fi
pass "step 3: /health returns 200"

# ---------------------------------------------------------------------------
# Step 4: /health/ready must show database=ok
# ---------------------------------------------------------------------------
log "step 4: $BACKEND_URL/health/ready must report database=ok"
ready_body="$(curl -fsS --max-time "$STEP_TIMEOUT_S" "$BACKEND_URL/health/ready" 2>/dev/null || true)"
if [[ -z "$ready_body" ]]; then
    abort "/health/ready did not return a body"
fi
echo "  body: $ready_body"
# The check is on the `database` substring; the status field can be "ready" or "degraded".
if ! printf '%s' "$ready_body" | grep -q '"database":"ok"'; then
    abort "/health/ready did not report database=ok (body: $ready_body)"
fi
pass "step 4: /health/ready reports database=ok"

# ---------------------------------------------------------------------------
# Step 5: /api/v1/board — non-empty columns
# ---------------------------------------------------------------------------
log "step 5: $BACKEND_URL/api/v1/board must have non-empty columns"
board_body="$(curl -fsS --max-time "$STEP_TIMEOUT_S" "$BACKEND_URL/api/v1/board" 2>/dev/null || true)"
if [[ -z "$board_body" ]]; then
    abort "/api/v1/board did not return a body"
fi
# The board returns 5 columns, each with an `issues` array. We expect at
# least one issue somewhere (seed issues are loaded on first init).
total_issues=$(printf '%s' "$board_body" | grep -o '"id":"DEV-' | wc -l | tr -d ' ')
if [[ "$total_issues" -lt 1 ]]; then
    abort "/api/v1/board returned no DEV-* issues (body: $board_body)"
fi
pass "step 5: /api/v1/board has $total_issues seed issues"

# ---------------------------------------------------------------------------
# Step 6: /api/v1/ecc/jobs — total >= 0
# ---------------------------------------------------------------------------
log "step 6: $BACKEND_URL/api/v1/ecc/jobs must respond 200"
jobs_status=$(curl -fsS --max-time "$STEP_TIMEOUT_S" -o /tmp/smoke.jobs.json -w '%{http_code}' \
    "$BACKEND_URL/api/v1/ecc/jobs" 2>/dev/null || echo "000")
if [[ "$jobs_status" != "200" ]]; then
    abort "/api/v1/ecc/jobs returned HTTP $jobs_status"
fi
pass "step 6: /api/v1/ecc/jobs returns 200"

# ---------------------------------------------------------------------------
# Step 7: verify alembic_version head revision in Postgres
# ---------------------------------------------------------------------------
log "step 7: alembic_version must contain $HEAD_REVISION"
alembic_rev="$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U devflow -d devflow -tA -c "SELECT version_num FROM alembic_version" 2>/dev/null || true)"
alembic_rev="$(printf '%s' "$alembic_rev" | tr -d '[:space:]')"
if [[ "$alembic_rev" != "$HEAD_REVISION" ]]; then
    abort "alembic_version is '$alembic_rev', expected '$HEAD_REVISION'"
fi
pass "step 7: alembic_version = $HEAD_REVISION"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
printf '%s[smoke]%s %d passed, %d failed\n' "$C_GREEN" "$C_RESET" "$PASS_COUNT" "$FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
    exit 1
fi
exit 0
