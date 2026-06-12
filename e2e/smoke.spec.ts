import { test, expect, type ConsoleMessage } from '@playwright/test'

/**
 * Smoke suite — read-only page-load checks against the live stack.
 *
 * These tests intentionally do NOT:
 *  - reset the database (the full E2E suite owns the devflow_e2e DB)
 *  - click dispatch / drawer / modal affordances
 *  - rely on row counts (the dev DB state varies)
 *
 * The contract is: "the live dev stack renders each page without
 * 4xx/5xx and surfaces the expected primary content". Anything
 * feature-flavored lives in the full E2E suite (e2e/*.spec.ts).
 */

const consoleErrors: string[] = []

function attachConsoleListener(page: import('@playwright/test').Page) {
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      // Filter out noise that doesn't indicate a real regression:
      //  - WebSocket drops during navigation are expected
      //  - 4xx fetches that the page handles gracefully are fine
      //    (e.g. /api/v1/auth/me returning 401 on a fresh dev DB is
      //     the auth-composable's normal "unauthenticated" signal)
      //  - favicon 404s
      const text = msg.text()
      if (/WebSocket|ws:\/\/127|favicon/i.test(text)) return
      if (/Failed to load resource.*status of 4\d\d/i.test(text)) return
      consoleErrors.push(text)
    }
  })
}

test.beforeEach(async ({ page }) => {
  attachConsoleListener(page)
})

test.afterEach(() => {
  consoleErrors.length = 0
})

test('smoke: home loads with AI Control Plane shell', async ({ page }) => {
  const response = await page.goto('/')
  expect(response, 'navigation response should exist').not.toBeNull()
  expect(response!.status(), 'home should return 2xx').toBeLessThan(400)

  // The global app title is set in src/app.vue via useHead().
  await expect(page).toHaveTitle(/AI Control Plane/)

  // The sidebar shell renders the project brand.
  await expect(page.getByText('AI Control Plane', { exact: false })).toBeVisible()

  // The board page itself renders the primary H1.
  await expect(
    page.getByRole('heading', { name: 'AI Delivery Board' })
  ).toBeVisible()

  // No stray console errors during the load.
  expect(consoleErrors, `console errors: ${consoleErrors.join(' | ')}`).toEqual([])
})

test('smoke: /reviews loads with status filter', async ({ page }) => {
  const response = await page.goto('/reviews')
  expect(response, 'navigation response should exist').not.toBeNull()
  expect(response!.status(), '/reviews should return 2xx').toBeLessThan(400)

  // The reviews page exposes a data-testid on the status select.
  await expect(page.getByTestId('reviews-status-filter')).toBeVisible()
  // Page also renders either status text (e.g. "Awaiting review") or
  // a filter label — both prove the page is past the loader.
  const filterOrStatus = page
    .locator('.reviews-page__filter, .reviews-page__empty, .reviews-list')
    .first()
  await expect(filterOrStatus).toBeVisible()
})

test('smoke: /notifications loads (empty state allowed)', async ({ page }) => {
  const response = await page.goto('/notifications')
  expect(response, 'navigation response should exist').not.toBeNull()
  expect(response!.status(), '/notifications should return 2xx').toBeLessThan(400)

  // The inbox may be empty on a fresh stack; the page must still
  // render its primary structure (heading + filter row + inbox area).
  // exact: true avoids matching the empty-state <h2>No notifications yet</h2>.
  await expect(
    page.getByRole('heading', { name: 'Notifications', exact: true })
  ).toBeVisible()
  await expect(
    page.locator('.notifications-page, .notifications-page__empty, .notifications-page__list').first()
  ).toBeVisible()
})

test('smoke: /settings loads with tab nav', async ({ page }) => {
  const response = await page.goto('/settings')
  expect(response, 'navigation response should exist').not.toBeNull()
  expect(response!.status(), '/settings should return 2xx').toBeLessThan(400)

  await expect(
    page.getByRole('heading', { name: 'Settings' })
  ).toBeVisible()
  // The settings shell has a tab nav with .settings-tab entries.
  await expect(page.locator('.settings-tab').first()).toBeVisible()
})

test('smoke: /dashboard loads with real KPIs', async ({ page }) => {
  const response = await page.goto('/dashboard')
  expect(response, 'navigation response should exist').not.toBeNull()
  expect(response!.status(), '/dashboard should return 2xx').toBeLessThan(400)

  await expect(
    page.getByRole('heading', { name: 'Delivery Dashboard' })
  ).toBeVisible()

  // The KPI strip pulls from /analytics/stats. We don't assert on
  // values (they vary), but the labels must render — that proves
  // the dashboard hydrated past the loader with real data.
  const body = await page.locator('body').textContent()
  expect(body, 'dashboard should mention Active Runs or Review').toMatch(
    /Active Runs|Review/i
  )
})
