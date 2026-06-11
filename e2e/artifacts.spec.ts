import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdmin } from './auth'

const BACKEND = 'http://127.0.0.1:8000'

// Create an issue via the issues API. Returns the issue JSON.
const createIssue = async (request: APIRequestContext, token: string, title: string) => {
  const response = await request.post(`${BACKEND}/api/v1/issues`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      description: 'Created by Playwright E2E for artifact tests.',
      status: 'backlog',
      priority: 'medium',
      profile: 'frontend',
      title,
    },
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test.describe('Manual artifact creation', () => {
  test('clicking "+ Add Artifact" opens modal, filling form creates artifact', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only artifact creation flow')
    const token = await loginAsAdmin(request, page)

    const issue = await createIssue(request, token, 'Artifact E2E Test')
    const issueId = issue.id as string

    // Navigate to board, wait for the issue card to appear.
    await page.goto('/')
    await expect(
      page.locator(`[data-issue-id="${issueId}"]`)
    ).toBeVisible({ timeout: 5_000 })

    // Open issue detail via e2e store hook.
    await page.evaluate((id) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ not exposed')
      const issue = hook.store.getAllIssues.find(i => i.id === id)
      if (!issue) throw new Error(`Issue ${id} not found in store`)
      hook.store.selectIssue(issue)
    }, issueId)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()

    // Switch to Collaboration tab.
    await page.getByRole('button', { name: 'Notes' }).click()

    // Click "+ Add Artifact" button.
    await page.getByTestId('add-artifact-btn').click()
    await expect(page.getByTestId('add-artifact-modal')).toBeVisible()

    // Fill the form.
    await page.getByTestId('artifact-title').fill('Test Screenshot')
    await page.getByTestId('artifact-type').selectOption('screenshot')
    await page.getByTestId('artifact-path').fill('https://example.com/screenshot.png')
    await page.getByTestId('artifact-summary').fill('A test screenshot from E2E')

    // Submit.
    await page.getByTestId('artifact-submit').click()

    // Modal should close.
    await expect(page.getByTestId('add-artifact-modal')).not.toBeVisible()

    // Artifact should appear in the list.
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'Test Screenshot' })
    ).toBeVisible({ timeout: 5_000 })
  })

  test('completing a handoff auto-creates artifacts visible in Collaboration tab', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only artifact creation flow')
    const token = await loginAsAdmin(request, page)

    const issue = await createIssue(request, token, 'Handoff Artifact E2E')
    const issueId = issue.id as string

    // Create and accept a handoff via API.
    const createResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs`,
      { headers: { Authorization: `Bearer ${token}` }, data: { toLane: 'frontend', createdBy: 'e2e' } }
    )
    expect(createResp.ok()).toBeTruthy()
    const handoff = await createResp.json()

    const acceptResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/accept`,
      { headers: { Authorization: `Bearer ${token}` }, data: { actor: 'e2e' } }
    )
    expect(acceptResp.ok()).toBeTruthy()

    // Complete with payload containing screenshots and diff_summary.
    const completeResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          actor: 'e2e',
          payload: {
            screenshots: ['login-v2.png'],
            diff_summary: 'Updated auth flow',
          },
        },
      }
    )
    expect(completeResp.ok()).toBeTruthy()

    // Verify artifacts were created via API before checking UI.
    const artifactsResp = await request.get(
      `${BACKEND}/api/v1/issues/${issueId}/artifacts`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    expect(artifactsResp.ok()).toBeTruthy()
    const artifactsData = await artifactsResp.json()
    expect(artifactsData.total).toBeGreaterThanOrEqual(2)

    // Open issue in UI and switch to Notes tab.
    await page.goto('/')
    await expect(
      page.locator(`[data-issue-id="${issueId}"]`)
    ).toBeVisible({ timeout: 5_000 })

    await page.evaluate((id) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ not exposed')
      const issue = hook.store.getAllIssues.find(i => i.id === id)
      if (!issue) throw new Error(`Issue ${id} not found in store`)
      hook.store.selectIssue(issue)
    }, issueId)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Notes' }).click()

    // Both auto-created artifacts should appear.
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'login-v2.png' })
    ).toBeVisible({ timeout: 5_000 })
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'Diff Summary' })
    ).toBeVisible()
  })
})
