import { defineConfig, devices } from '@playwright/test'

const isCI = !!process.env.CI

export default defineConfig({
  testDir: '.',
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
    timeout: 120_000
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
