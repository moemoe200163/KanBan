import { expect, test, type APIRequestContext } from '@playwright/test'

const createIssue = async (request: APIRequestContext, data: {
  title: string
  status?: string
  priority?: string
  profile?: string
}) => {
  const response = await request.post('http://127.0.0.1:8000/api/v1/issues', {
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
  test('loads the board and opens an issue detail panel', async ({ page, isMobile }) => {
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

  test('New Issue modal creates a visible issue', async ({ page, isMobile }) => {
    test.skip(isMobile, 'modal creation is covered in the desktop control-plane flow')
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

  test('moving an issue to In Progress creates a job and shows ECC logs', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'drag/drop execution flow is covered in the desktop project')
    const title = `E2E dispatch issue ${Date.now()}`
    const issue = await createIssue(request, { title, status: 'backlog', profile: 'frontend' })

    await page.goto('/')

    const backlogCard = page.locator(`[data-testid="kanban-column-backlog"] [data-testid="issue-card"][data-issue-id="${issue.id}"]`)
    const inProgressColumn = page.getByTestId('kanban-column-in_progress')

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
    const title = `E2E review issue ${Date.now()}`
    const issue = await createIssue(request, { title, status: 'human_review', profile: 'security', priority: 'high' })

    await page.goto('/')

    const reviewItem = page.getByTestId('review-item').filter({ hasText: issue.key }).first()
    await expect(reviewItem).toBeVisible()
    const key = await reviewItem.locator('.review-queue__key').innerText()
    await reviewItem.getByTestId('review-approve').click()

    await expect(page.locator('[data-testid="kanban-column-done"]', { hasText: key })).toBeVisible({ timeout: 10_000 })
  })

  test('filters issues without collapsing the board', async ({ page, isMobile }) => {
    test.skip(isMobile, 'mobile has a dedicated board usability assertion')
    await page.goto('/')

    await page.getByPlaceholder('Search key, title, or label').fill('security')

    await expect(page.locator('.issue-card').first()).toBeVisible()
    const columnsBox = await page.locator('.kanban-board__columns').boundingBox()
    expect(columnsBox?.height ?? 0).toBeGreaterThan(260)
  })

  test('keeps mobile board columns usable', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'mobile layout check only runs in the mobile project')

    await page.goto('/')

    await expect(page.locator('.kanban-board')).toBeVisible()
    await expect(page.locator('.kanban-column')).toHaveCount(5)

    const columnsBox = await page.locator('.kanban-board__columns').boundingBox()
    expect(columnsBox?.height ?? 0).toBeGreaterThan(280)
  })
})
