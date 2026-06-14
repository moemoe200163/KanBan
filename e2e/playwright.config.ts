import { defineConfig, devices } from '@playwright/test'

const isCI = !!process.env.CI

export default defineConfig({
  testDir: '.',
  // Exclude the smoke suite — it has its own config (e2e/smoke.config.ts)
  // and its own npm script (npm run e2e:smoke). Mixing them into the
  // destructive full suite would mean smoke checks run against a
  // pre-reset / devflow_e2e DB, which is not what the smoke gate is
  // for.
  testIgnore: ['**/smoke.spec.ts', '**/smoke.config.ts'],
  timeout: 30_000,
  expect: {
    timeout: 8_000
  },
  fullyParallel: !isCI,
  outputDir: './test-results',
  reporter: isCI
    ? [['list'], ['html', { open: 'never' }]]
    : 'list',
  globalSetup: './global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:3010',
    trace: 'on-first-retry',
    actionTimeout: 8_000
  },
  webServer: {
    command: 'npm run build && npm run preview',
    cwd: '..',
    url: 'http://127.0.0.1:3010',
    reuseExistingServer: !isCI,
    timeout: 120_000,
    // Enable window.__DEVFLOW_E2E__ in the preview bundle so the
    // dependency-graph spec can drive store actions that have no UI
    // affordance yet. See src/plugins/e2e-store-hook.client.ts.
    env: {
      NUXT_PUBLIC_E2E: '1',
      NUXT_PUBLIC_API_BASE: 'http://127.0.0.1:8000/api/v1'
    }
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }
    },
    {
      name: 'mobile',
      use: { ...devices['Pixel 5'] }
    }
  ]
})
