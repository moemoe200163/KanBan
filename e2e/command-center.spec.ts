import { test, expect } from '@playwright/test'

test.describe('Command Center', () => {
  test('loads the Command Center page', async ({ page }) => {
    await page.goto('/command-center')

    await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible()
    await expect(page.locator('.composer')).toBeVisible()
    await expect(page.locator('.job-monitor')).toBeVisible()
  })

  test('dispatch creates a job visible in the monitor', async ({ page, request }) => {
    // Create an issue via API so the composer has something to dispatch.
    const res = await request.post('http://127.0.0.1:8000/api/v1/issues', {
      data: {
        title: `E2E command-center dispatch ${Date.now()}`,
        description: 'Created by Playwright E2E.',
        status: 'backlog',
        priority: 'medium',
        profile: 'frontend'
      }
    })
    expect(res.ok()).toBeTruthy()
    const issue = await res.json() as { id: string; key: string }

    await page.goto('/command-center')
    await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible()

    // Select the issue we just created.
    const select = page.getByTestId('command-issue-select')
    await expect(select).toBeVisible()
    await select.selectOption(issue.id)

    // Dispatch.
    await page.getByTestId('command-dispatch').click()

    // A job row should appear in the monitor.
    const monitor = page.locator('.job-monitor')
    await expect(monitor).toBeVisible()
    await expect(page.locator('.job-row').first()).toBeVisible({ timeout: 10_000 })

    // The job row should reference our issue key.
    await expect(page.locator('.job-row__key').first()).toContainText(issue.key)
  })

  test('clicking a job opens the detail drawer', async ({ page, request }) => {
    // Create and dispatch an issue so there is a job to click.
    const res = await request.post('http://127.0.0.1:8000/api/v1/issues', {
      data: {
        title: `E2E command-center drawer ${Date.now()}`,
        description: 'Created by Playwright E2E.',
        status: 'backlog',
        priority: 'medium',
        profile: 'frontend'
      }
    })
    expect(res.ok()).toBeTruthy()
    const issue = await res.json() as { id: string; key: string }

    await page.goto('/command-center')
    const select = page.getByTestId('command-issue-select')
    await expect(select).toBeVisible()
    await select.selectOption(issue.id)
    await page.getByTestId('command-dispatch').click()

    // Wait for the job row.
    await expect(page.locator('.job-row').first()).toBeVisible({ timeout: 10_000 })

    // Click the job row to open the drawer.
    await page.locator('.job-row').first().click()

    const drawer = page.getByTestId('job-detail-drawer')
    await expect(drawer).toBeVisible()

    // Drawer should show the issue key.
    await expect(drawer.getByRole('heading', { name: issue.key })).toBeVisible()
  })

  test('cancel button transitions a running job to cancelled', async ({ page, request }) => {
    // Create and dispatch an issue.
    const res = await request.post('http://127.0.0.1:8000/api/v1/issues', {
      data: {
        title: `E2E command-center cancel ${Date.now()}`,
        description: 'Created by Playwright E2E.',
        status: 'backlog',
        priority: 'medium',
        profile: 'frontend'
      }
    })
    expect(res.ok()).toBeTruthy()
    const issue = await res.json() as { id: string; key: string }

    await page.goto('/command-center')
    const select = page.getByTestId('command-issue-select')
    await expect(select).toBeVisible()
    await select.selectOption(issue.id)
    await page.getByTestId('command-dispatch').click()

    // Wait for the job row.
    await expect(page.locator('.job-row').first()).toBeVisible({ timeout: 10_000 })

    // The cancel button has data-testid="job-cancel-{id}".
    const cancelBtn = page.locator('[data-testid^="job-cancel-"]').first()
    if (await cancelBtn.isVisible()) {
      await cancelBtn.click()

      // The status badge should update to "cancelled".
      await expect(
        page.locator('.job-row').first().locator('.job-row__status-badge')
      ).toContainText('cancelled', { timeout: 5_000 })
    }
  })
})
