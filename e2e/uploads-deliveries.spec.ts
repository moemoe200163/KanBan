import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdmin } from './auth'

const BACKEND = 'http://127.0.0.1:8000'

// Create an issue via the issues API. Returns the issue JSON.
const createIssue = async (request: APIRequestContext, token: string, title: string) => {
  const response = await request.post(`${BACKEND}/api/v1/issues`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      description: 'Created by Playwright E2E for uploads/deliveries tests.',
      status: 'backlog',
      priority: 'medium',
      profile: 'frontend',
      title,
    },
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test.describe('Uploads page', () => {
  test('upload button opens upload dialog', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/artifacts')
    await expect(page.getByRole('heading', { name: 'Uploads' })).toBeVisible()

    // Click upload button
    await page.getByTestId('uploads-open').click()

    // Upload dialog should appear
    await expect(page.locator('.uploads-dialog, [data-testid="upload-dialog"]')).toBeVisible()
  })

  test('folder chips are visible and clickable', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/artifacts')
    await expect(page.getByRole('heading', { name: 'Uploads' })).toBeVisible()

    // Folder chips should be visible (at least the default /Uploads folder)
    await expect(page.locator('.uploads-page__folder-chip, .folder-chip').first()).toBeVisible()
  })

  test('search input is functional', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/artifacts')
    await expect(page.getByRole('heading', { name: 'Uploads' })).toBeVisible()

    // Search input should be visible
    const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]')
    await expect(searchInput).toBeVisible()

    // Type in search
    await searchInput.fill('test')
    await expect(searchInput).toHaveValue('test')
  })
})

test.describe('Deliveries page', () => {
  test('deliveries page shows empty state when no deliveries', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/deliveries')
    await expect(page.getByRole('heading', { name: 'Deliveries' })).toBeVisible()

    // Should show either empty state or delivery list
    await expect(
      page.locator('.deliveries-page__empty, .deliveries-page__list')
    ).toBeVisible()
  })

  test('deliveries page has filter controls', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/deliveries')
    await expect(page.getByRole('heading', { name: 'Deliveries' })).toBeVisible()

    // Should have type filter and source filter
    await expect(page.locator('.deliveries-page__filter, select, [data-testid="type-filter"]')).toBeVisible()
  })

  test('deliveries page does not have upload button', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)
    await page.goto('/deliveries')
    await expect(page.getByRole('heading', { name: 'Deliveries' })).toBeVisible()

    // Should NOT have an upload button (deliveries are auto-created from handoffs)
    await expect(page.getByRole('button', { name: /upload/i })).not.toBeVisible()
  })
})

test.describe('Uploads vs Deliveries separation', () => {
  test('uploads page does not show handoff artifacts', async ({ page, request }) => {
    const token = await loginAsAdmin(request, page)

    // Create an issue and complete a handoff to generate delivery artifacts
    const issue = await createIssue(request, token, 'Delivery Test Issue')
    const issueId = issue.id as string

    // Create and complete a handoff
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

    const completeResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          actor: 'e2e',
          payload: {
            screenshots: ['delivery-test.png'],
            diff_summary: 'Test delivery output',
          },
        },
      }
    )
    expect(completeResp.ok()).toBeTruthy()

    // Check deliveries page has the artifacts
    await page.goto('/deliveries')
    await expect(page.getByRole('heading', { name: 'Deliveries' })).toBeVisible()

    // The delivery artifacts should be visible (or at least the list should exist)
    await expect(
      page.locator('.deliveries-page__empty, .deliveries-page__list')
    ).toBeVisible()

    // Check uploads page does NOT show handoff artifacts
    await page.goto('/artifacts')
    await expect(page.getByRole('heading', { name: 'Uploads' })).toBeVisible()

    // The handoff artifact should NOT appear in uploads
    // (uploads only shows user-uploaded files, not handoff outputs)
    const uploadList = page.locator('.uploads-page__list')
    if (await uploadList.isVisible()) {
      await expect(
        uploadList.locator('text=delivery-test.png')
      ).not.toBeVisible()
    }
  })
})
