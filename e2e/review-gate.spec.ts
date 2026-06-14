import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdmin } from './auth'

const BACKEND = 'http://127.0.0.1:8000'

const createIssue = async (request: APIRequestContext, token: string, title: string) => {
  const response = await request.post(`${BACKEND}/api/v1/issues`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      description: 'Created by Playwright E2E for review gate tests.',
      status: 'backlog',
      priority: 'medium',
      profile: 'frontend',
      title,
    },
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test.describe('Review Gate', () => {
  test('approving a completed review handoff shows decision badge and hides review buttons', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only review flow')
    const token = await loginAsAdmin(request, page)

    const issue = await createIssue(request, token, 'Review Gate E2E')
    const issueId = issue.id as string

    // Create handoff to the review lane.
    const createResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs`,
      { headers: { Authorization: `Bearer ${token}` }, data: { fromLane: 'frontend', toLane: 'review', createdBy: 'e2e' } }
    )
    expect(createResp.ok()).toBeTruthy()
    const handoff = await createResp.json()

    // Accept the handoff.
    const acceptResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/accept`,
      { headers: { Authorization: `Bearer ${token}` }, data: { actor: 'e2e' } }
    )
    expect(acceptResp.ok()).toBeTruthy()

    // Complete with review-lane payload (reviewer, decision, approver required).
    const completeResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          actor: 'e2e',
          payload: {
            reviewer: 'e2e-reviewer',
            decision: 'approve',
            approver: 'e2e-approver',
          },
        },
      }
    )
    expect(completeResp.ok()).toBeTruthy()

    // Verify handoff is completed and has no decision yet.
    const getResp = await request.get(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    expect(getResp.ok()).toBeTruthy()
    const handoffData = await getResp.json()
    expect(handoffData.status).toBe('completed')
    expect(handoffData.decision).toBeNull()

    // Open issue in UI.
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

    // Switch to Handoffs tab.
    await page.getByRole('button', { name: 'Handoffs' }).click()

    // Review action buttons should be visible.
    const reviewActions = page.getByTestId('review-actions')
    await expect(reviewActions).toBeVisible({ timeout: 5_000 })

    // Auto-accept the confirm dialog.
    page.on('dialog', dialog => dialog.accept())

    // Click Approve.
    await page.getByTestId('review-approve-btn').click()

    // Review buttons should disappear and decision badge should appear.
    await expect(reviewActions).not.toBeVisible({ timeout: 5_000 })
    await expect(page.getByTestId('review-decision-badge')).toBeVisible()
    await expect(
      page.locator('[data-testid="review-decision-badge"]', { hasText: 'Approved' })
    ).toBeVisible()

    // Verify via API that the decision was persisted.
    const finalResp = await request.get(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    expect(finalResp.ok()).toBeTruthy()
    const finalData = await finalResp.json()
    expect(finalData.decision).toBe('approve')
  })

  test('requesting rework sets decision and shows rework badge', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only review flow')
    const token = await loginAsAdmin(request, page)

    const issue = await createIssue(request, token, 'Rework Gate E2E')
    const issueId = issue.id as string

    // Create, accept, and complete a handoff to the review lane.
    const createResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs`,
      { headers: { Authorization: `Bearer ${token}` }, data: { fromLane: 'backend', toLane: 'review', createdBy: 'e2e' } }
    )
    expect(createResp.ok()).toBeTruthy()
    const handoff = await createResp.json()

    await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/accept`,
      { headers: { Authorization: `Bearer ${token}` }, data: { actor: 'e2e' } }
    )

    const completeResp = await request.post(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          actor: 'e2e',
          payload: {
            reviewer: 'e2e-reviewer',
            decision: 'approve',
            approver: 'e2e-approver',
          },
        },
      }
    )
    expect(completeResp.ok()).toBeTruthy()

    // Open issue in UI and switch to Handoffs tab.
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
    await page.getByRole('button', { name: 'Handoffs' }).click()

    // Review actions visible.
    await expect(page.getByTestId('review-actions')).toBeVisible({ timeout: 5_000 })

    // Auto-accept confirm and click Request Rework.
    page.on('dialog', dialog => dialog.accept())
    await page.getByTestId('review-rework-btn').click()

    // Decision badge should show "Rework Requested".
    await expect(page.getByTestId('review-actions')).not.toBeVisible({ timeout: 5_000 })
    await expect(
      page.locator('[data-testid="review-decision-badge"]', { hasText: 'Rework Requested' })
    ).toBeVisible()

    // Verify via API.
    const finalResp = await request.get(
      `${BACKEND}/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    expect(finalResp.ok()).toBeTruthy()
    const finalData = await finalResp.json()
    expect(finalData.decision).toBe('request_changes')
  })
})
