import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdmin, clearAuth } from './auth'

const BACKEND = 'http://127.0.0.1:8000'

const createIssue = async (request: APIRequestContext, token: string, data: {
  title: string
  status?: string
  priority?: string
  profile?: string
}) => {
  const response = await request.post(`${BACKEND}/api/v1/issues`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      description: 'Created by Playwright E2E.',
      status: data.status ?? 'backlog',
      priority: data.priority ?? 'medium',
      profile: data.profile ?? 'frontend',
      title: data.title
    }
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test.describe('DevFlow board', () => {
  // ---------------------------------------------------------------------------
  // Read-only tests (no auth required)
  // ---------------------------------------------------------------------------

  test('loads the board and opens an issue detail panel', async ({ page, isMobile }) => {
    await clearAuth(page)
    await page.goto('/')

    await expect(page.getByRole('heading', { name: 'AI Delivery Board' })).toBeVisible()
    if (!isMobile) {
      await expect(page.locator('.sidebar')).toBeVisible()
    }
    await expect(page.locator('.kanban-column')).toHaveCount(5)
    await expect(page.getByTestId('issue-card').first()).toBeVisible()

    await page.getByTestId('issue-card').first().click()

    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await expect(page.locator('.issue-detail__key')).toContainText(/DEV-/)
  })

  test('filters issues without collapsing the board', async ({ page, isMobile }) => {
    test.skip(isMobile, 'mobile has a dedicated board usability assertion')
    await clearAuth(page)
    await page.goto('/')

    await page.getByPlaceholder('Search key, title, or label').fill('security')

    await expect(page.locator('.issue-card').first()).toBeVisible()
    const columnsBox = await page.locator('.kanban-board__columns').boundingBox()
    expect(columnsBox?.height ?? 0).toBeGreaterThan(260)
  })

  test('keeps mobile board columns usable', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'mobile layout check only runs in the mobile project')
    await clearAuth(page)
    await page.goto('/')

    await expect(page.locator('.kanban-board')).toBeVisible()
    await expect(page.locator('.kanban-column')).toHaveCount(5)

    const columnsBox = await page.locator('.kanban-board__columns').boundingBox()
    expect(columnsBox?.height ?? 0).toBeGreaterThan(280)
  })

  // ---------------------------------------------------------------------------
  // Auth-gated tests (admin required for write operations)
  // ---------------------------------------------------------------------------

  test('New Issue modal creates a visible issue', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'modal creation is covered in the desktop control-plane flow')
    await loginAsAdmin(request, page)
    await page.goto('/')

    const title = `E2E modal issue ${Date.now()}`
    await page.getByTestId('new-issue-open').click()
    await expect(page.getByTestId('new-issue-modal')).toBeVisible()
    await page.getByTestId('new-issue-title').fill(title)
    await page.getByTestId('new-issue-description').fill('Created by the Playwright gate.')
    await page.getByTestId('new-issue-status').selectOption('backlog')
    await page.getByTestId('new-issue-priority').selectOption('medium')
    await page.getByTestId('new-issue-profile').selectOption('frontend')
    await page.getByTestId('new-issue-submit').click()

    await expect(page.getByText(title)).toBeVisible()
  })

  test('New Issue and Review buttons are mutually exclusive (UI-01 regression)', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only interaction test')
    await loginAsAdmin(request, page)
    await page.goto('/')

    // New Issue opens modal, Review panel stays closed
    await page.getByTestId('new-issue-open').click()
    await expect(page.getByTestId('new-issue-modal')).toBeVisible()
    await expect(page.locator('.review-panel')).not.toBeVisible()
    // Close via the X button in the modal header
    await page.getByRole('button', { name: 'Close modal' }).click()
    // Wait for modal to fully close (transition/animation)
    await expect(page.getByTestId('new-issue-modal')).not.toBeVisible({ timeout: 5000 })

    // Review button opens Review panel, New Issue modal stays closed
    await page.getByTestId('review-queue-toggle').click()
    await expect(page.locator('.review-panel')).toBeVisible()
    await expect(page.getByTestId('new-issue-modal')).not.toBeVisible()
  })

  test('Start issue shows Undo toast that auto-dismisses', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only toast interaction')
    const token = await loginAsAdmin(request, page)

    const title = `E2E toast undo ${Date.now()}`
    const issue = await createIssue(request, token, { title, status: 'backlog', profile: 'frontend' })

    await page.goto('/')

    const backlogCard = page.locator(`[data-testid="kanban-column-backlog"] [data-testid="issue-card"][data-issue-id="${issue.id}"]`)
    await expect(backlogCard).toBeVisible()

    // Click Start — should show a toast with Undo
    await backlogCard.getByTestId('start-issue').click()

    // Toast should appear
    const toast = page.locator('.toast').first()
    await expect(toast).toBeVisible({ timeout: 3000 })
    await expect(toast).toContainText('Undo')

    // Toast should auto-dismiss after ~3 seconds
    await expect(toast).not.toBeVisible({ timeout: 5000 })
  })

  test('moving an issue to In Progress creates a job and shows ECC logs', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'drag/drop execution flow is covered in the desktop project')
    const token = await loginAsAdmin(request, page)

    const title = `E2E dispatch issue ${Date.now()}`
    const issue = await createIssue(request, token, { title, status: 'backlog', profile: 'frontend' })

    await page.goto('/')

    const backlogCard = page.locator(`[data-testid="kanban-column-backlog"] [data-testid="issue-card"][data-issue-id="${issue.id}"]`)

    await expect(backlogCard).toBeVisible()
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/v1/ecc/dispatch') && response.status() === 200),
      backlogCard.getByTestId('start-issue').click()
    ])

    await expect(page.getByTestId('recent-job').first()).toBeVisible({ timeout: 10_000 })

    await page.getByTestId('recent-job').first().click()
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await expect(page.getByTestId('ecc-job-summary')).toBeVisible()
    await expect(page.getByTestId('ecc-log-entry').first()).toBeVisible()
  })

  test('Review Queue approve moves an item to Done', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'review actions are covered in the desktop project')
    const token = await loginAsAdmin(request, page)

    const title = `E2E review issue ${Date.now()}`
    const issue = await createIssue(request, token, { title, status: 'human_review', profile: 'security', priority: 'high' })

    await page.goto('/')

    // Open the Review Queue panel (hidden by default in the compact toolbar design)
    await page.getByTestId('review-queue-toggle').click()

    const reviewItem = page.getByTestId('review-item').filter({ hasText: issue.key }).first()
    await expect(reviewItem).toBeVisible()
    const key = await reviewItem.locator('.review-queue__key').innerText()
    await reviewItem.getByTestId('review-approve').click()

    await expect(page.locator('[data-testid="kanban-column-done"]', { hasText: key })).toBeVisible({ timeout: 10_000 })
  })
})
