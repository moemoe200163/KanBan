import { test, expect } from '@playwright/test'

test.describe('Sidebar navigation', () => {
  test('navigates to each route from sidebar', async ({ page, isMobile }) => {
    test.skip(isMobile, 'sidebar navigation is desktop-only')
    await page.goto('/')

    // Board is the default
    await expect(page.getByRole('heading', { name: 'AI Delivery Board' })).toBeVisible()

    // Command Center
    await page.locator('.sidebar__nav-item', { hasText: 'Command Center' }).click()
    await expect(page).toHaveURL(/\/command-center/)
    await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible()

    // Backlog
    await page.locator('.sidebar__nav-item', { hasText: 'Backlog' }).click()
    await expect(page).toHaveURL(/\/backlog/)
    await expect(page.getByRole('heading', { name: 'Backlog' })).toBeVisible()

    // Agents
    await page.locator('.sidebar__nav-item', { hasText: 'Agents' }).click()
    await expect(page).toHaveURL(/\/agents/)
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()

    // Runs
    await page.locator('.sidebar__nav-item', { hasText: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs/)
    await expect(page.getByRole('heading', { name: 'Runs' })).toBeVisible()

    // Analytics
    await page.locator('.sidebar__nav-item', { hasText: 'Analytics' }).click()
    await expect(page).toHaveURL(/\/analytics/)
    await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible()

    // Activity Log
    await page.locator('.sidebar__nav-item', { hasText: 'Activity Log' }).click()
    await expect(page).toHaveURL(/\/activity/)
    await expect(page.getByRole('heading', { name: 'Activity Log' })).toBeVisible()

    // Settings
    await page.locator('.sidebar__nav-item', { hasText: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings/)
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()

    // Back to Board
    await page.locator('.sidebar__nav-item', { hasText: 'Board' }).click()
    await expect(page).toHaveURL('/')
    await expect(page.getByRole('heading', { name: 'AI Delivery Board' })).toBeVisible()
  })
})

test.describe('MVP pages', () => {
  test('Backlog page shows backlog issues', async ({ page }) => {
    await page.goto('/backlog')
    await expect(page.getByRole('heading', { name: 'Backlog' })).toBeVisible()
    // Should show either issues or empty state
    await expect(
      page.locator('.backlog-page__list, .backlog-page__empty')
    ).toBeVisible()
  })

  test('Agents page shows profile matrix', async ({ page }) => {
    await page.goto('/agents')
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()
    await expect(page.locator('.agents-matrix')).toBeVisible()
  })

  test('Runs page shows job list with filters', async ({ page }) => {
    await page.goto('/runs')
    await expect(page.getByRole('heading', { name: 'Runs' })).toBeVisible()
    // Should show filter buttons
    await expect(page.locator('.runs-page__filter', { hasText: 'All' })).toBeVisible()
    await expect(page.locator('.runs-page__filter', { hasText: 'Running' })).toBeVisible()
  })

  test('Analytics page shows KPI cards', async ({ page }) => {
    await page.goto('/analytics')
    await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible()
    await expect(page.locator('.kpi-card').first()).toBeVisible()
  })

  test('Activity Log page shows audit entries', async ({ page }) => {
    await page.goto('/activity')
    await expect(page.getByRole('heading', { name: 'Activity Log' })).toBeVisible()
    // Should show either entries, empty state, or loading
    await expect(
      page.locator('.activity-timeline, .activity-page__empty, .activity-page__loading')
    ).toBeVisible()
  })

  test('Settings page shows backend status', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect(page.locator('.settings-card', { hasText: 'Backend Status' })).toBeVisible()
    await expect(page.locator('.settings-card', { hasText: 'Active Harness' })).toBeVisible()
  })

  test('redirect /lanes to /agents?tab=roles', async ({ page }) => {
    await page.goto('/lanes')
    await expect(page).toHaveURL(/\/agents\?tab=roles/)
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()
  })
})
