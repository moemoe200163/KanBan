// E2E global setup: verify the backend control plane is reachable and
// the test database is in a known state before any spec runs.
//
// Ordering (each step is a hard gate for the next):
//   1. Poll `GET /health` until 200 (max 60s) — the backend is up.
//   2. Poll `GET /health/ready` until 200 (max 30s) — the DB is reachable.
//   3. `POST /api/v1/test/reset` — truncate + re-seed. Safe only
//      because steps 1 and 2 succeeded. The endpoint itself is
//      double-gated server-side (E2E=1 + db name contains `_e2e`).
//
// We do **not** auto-start the backend; the developer is expected to
// run `docker compose up` (with the e2e override) or `uvicorn` first.
// A hard fail here surfaces the most common gate failure with a clear
// message instead of confusing spec-level timeouts.

import { request, APIResponse } from '@playwright/test'

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL
  ?? 'http://127.0.0.1:8000'

const HEALTH_URL = `${BACKEND_BASE_URL}/health`
const READY_URL = `${BACKEND_BASE_URL}/health/ready`
const RESET_URL = `${BACKEND_BASE_URL}/api/v1/test/reset`

const HEALTH_TIMEOUT_MS = 60_000
const READY_TIMEOUT_MS = 30_000

async function pollUntilOk(
  url: string,
  timeoutMs: number,
  label: string,
  context: Awaited<ReturnType<typeof request.newContext>>
): Promise<APIResponse> {
  const deadline = Date.now() + timeoutMs
  let lastStatus: number | null = null
  let lastError: string | null = null

  while (Date.now() < deadline) {
    try {
      const response = await context.get(url, {
        timeout: 5_000,
        failOnStatusCode: false
      })
      lastStatus = response.status()
      if (response.ok()) {
        console.log(`[e2e] ${label} OK at ${url}`)
        return response
      }
      lastError = `status ${response.status()}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await new Promise(resolve => setTimeout(resolve, 1_000))
  }

  throw new Error(
    `[e2e] ${label} did not become OK at ${url} within ${timeoutMs}ms ` +
    `(last status: ${lastStatus}, last error: ${lastError}). ` +
    `Start the backend with: cd backend && PYTHONPATH=backend python3 -m uvicorn main:app --port 8000 ` +
    `or: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d`
  )
}

export default async function globalSetup(): Promise<void> {
  const context = await request.newContext()
  try {
    // 1. Backend is up at all.
    await pollUntilOk(HEALTH_URL, HEALTH_TIMEOUT_MS, 'backend /health', context)

    // 2. Backend can talk to its database.
    await pollUntilOk(READY_URL, READY_TIMEOUT_MS, 'backend /health/ready', context)

    // 3. Reset the E2E database to a known seed state.
    const resetResponse = await context.post(RESET_URL, {
      timeout: 10_000,
      failOnStatusCode: false
    })
    if (!resetResponse.ok()) {
      const body = await resetResponse.text()
      throw new Error(
        `E2E reset returned ${resetResponse.status()} at ${RESET_URL}. ` +
        `Body: ${body}. ` +
        `Confirm E2E=1 is set on the backend and DATABASE_URL contains '_e2e' (e.g. devflow_e2e).`
      )
    }
    const resetBody = await resetResponse.json() as {
      status: string
      seeded: number
      database: string
    }
    if (resetBody.status !== 'reset') {
      throw new Error(
        `E2E reset returned unexpected body: ${JSON.stringify(resetBody)}`
      )
    }
    console.log(
      `[e2e] database reset OK: seeded=${resetBody.seeded} database=${resetBody.database}`
    )

    // T8.5: assert the board actually has the 8 seed issues after the
    // reset call. A misconfigured E2E setup (wrong E2E flag, wrong
    // db name) would silently leave the board empty; failing fast
    // here surfaces that with a clear message instead of deep inside
    // board.spec.ts.
    const expectedSeedCount = 8
    if (resetBody.seeded !== expectedSeedCount) {
      throw new Error(
        `E2E reset seeded=${resetBody.seeded} issues, expected ${expectedSeedCount}. ` +
        `Check that dev/db/repository.py::SEED_ISSUES still has ${expectedSeedCount} entries.`
      )
    }
    const boardResponse = await context.get(`${BACKEND_BASE_URL}/api/v1/board`, {
      timeout: 10_000,
      failOnStatusCode: false
    })
    if (!boardResponse.ok()) {
      throw new Error(
        `/api/v1/board returned ${boardResponse.status()} after reset at ${boardResponse.url()}`
      )
    }
    const board = await boardResponse.json() as {
      columns: Array<{ id: string; issues: unknown[] }>
    }
    const totalIssues = board.columns.reduce(
      (sum, col) => sum + col.issues.length,
      0
    )
    if (totalIssues !== expectedSeedCount) {
      throw new Error(
        `E2E board has ${totalIssues} issues after reset, expected ${expectedSeedCount}. ` +
        `Column counts: ${board.columns.map(c => `${c.id}=${c.issues.length}`).join(', ')}`
      )
    }
    console.log(`[e2e] board has ${totalIssues} seed issues (matches reset.seeded)`)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new Error(
      `DevFlow E2E prerequisites failed.\n` +
      `Start the backend with: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d\n` +
      `Or locally: cd backend && PYTHONPATH=backend python3 -m uvicorn main:app --port 8000\n` +
      `Underlying error: ${message}`
    )
  } finally {
    await context.dispose()
  }
}
