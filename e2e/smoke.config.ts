import { defineConfig } from '@playwright/test'

const isCI = !!process.env.CI

/**
 * Lightweight Playwright config for the smoke suite.
 *
 * The full E2E suite (e2e/playwright.config.ts) is destructive: it spins
 * up its own `devflow_e2e` Postgres, calls the reset endpoint, and seeds
 * the board. We don't want that on every CI run — we just want a fast
 * "the live stack renders the right pages" gate.
 *
 * Assumptions:
 *  - The dev stack is already up: frontend on http://127.0.0.1:3010
 *    and backend on http://127.0.0.1:8000. The CI job brings the stack
 *    up via `docker compose up -d backend frontend` before invoking
 *    this config.
 *  - The smoke tests are read-only page-load checks. They must not
 *    reset the database, click dispatch buttons, or open drawers.
 *
 * If you need feature-level E2E (dispatch / drawer / modal flows),
 * use the full config: `npm run e2e`.
 */
export default defineConfig({
  testDir: '.',
  testMatch: /smoke\.spec\.ts$/,
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  // Single worker — smoke checks share the live backend, parallel
  // requests from one test run is plenty and avoids a flaky race
  // against the WebSocket / store hydration.
  workers: 1,
  // Local: one shot. CI: one retry on transient infra flake.
  retries: isCI ? 1 : 0,
  fullyParallel: false,
  outputDir: './test-results',
  reporter: isCI
    ? [['list'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:3010',
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
    trace: 'retain-on-failure',
  },
  // No webServer — the container is expected to be up. CI's
  // e2e-smoke job brings the stack up before running this suite.
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
})
