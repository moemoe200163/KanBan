import { expect, test, type APIRequestContext } from '@playwright/test'

// Create an issue via the issues endpoint. Returns the issue JSON.
const createIssue = async (request: APIRequestContext, data: {
  title: string
  status?: string
  profile?: string
}) => {
  const response = await request.post('http://127.0.0.1:8000/api/v1/issues', {
    data: {
      description: 'Created by Playwright E2E for handoff completion flow.',
      status: data.status ?? 'backlog',
      priority: 'medium',
      profile: data.profile ?? 'frontend',
      title: data.title
    }
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

// Create a handoff directly via the API and accept it. Returns the
// accepted handoff. We go through the API here (not the UI create
// form) so the test stays focused on the new completion-with-fields
// flow rather than re-exercising the create/accept UI paths.
const createAcceptedHandoff = async (
  request: APIRequestContext,
  issueId: string,
  toLane: string
) => {
  const create = await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issueId}/handoffs`,
    { data: { toLane, createdBy: 'e2e' } }
  )
  expect(create.ok(), `create handoff: ${create.status()} ${await create.text()}`).toBeTruthy()
  const handoff = await create.json()

  const accept = await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/accept`,
    { data: { actor: 'e2e' } }
  )
  expect(accept.ok(), `accept handoff: ${accept.status()} ${await accept.text()}`).toBeTruthy()
  return await accept.json()
}

test.describe('Handoff completion with required fields', () => {
  test('Frontend lane completion shows form for diff_summary + screenshots', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

    const title = `E2E handoff complete ${Date.now()}`
    const issue = await createIssue(request, { title, status: 'backlog', profile: 'frontend' })
    await createAcceptedHandoff(request, issue.id, 'frontend')

    await page.goto('/')

    // Open the issue and switch to the Handoffs tab
    const card = page.locator(`[data-testid="issue-card"][data-issue-id="${issue.id}"]`)
    await expect(card).toBeVisible()
    await card.click()
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Handoffs' }).click()

    // The handoff created above should render in the section. Click
    // Complete — should pre-flight the preview and open the inline
    // form because the frontend lane requires diff_summary + screenshots.
    await page.getByRole('button', { name: 'Complete' }).click()

    // The new form should appear with one input per missing required field.
    await expect(page.getByTestId('completion-field-diff_summary')).toBeVisible()
    await expect(page.getByTestId('completion-field-screenshots')).toBeVisible()

    // Fill in the required fields and submit.
    await page.getByTestId('completion-field-diff_summary').fill('E2E diff summary')
    await page.getByTestId('completion-field-screenshots').fill('e2e.png')

    await Promise.all([
      page.waitForResponse(response =>
        response.url().includes('/handoffs/') &&
        response.url().endsWith('/complete') &&
        response.status() === 200
      ),
      page.getByTestId('submit-completion').click()
    ])

    // Form should be gone, and the handoff card should now read Completed.
    await expect(page.getByTestId('completion-field-diff_summary')).toHaveCount(0)
    await expect(page.getByText('Completed').first()).toBeVisible()
  })

  test('Cancel button on the completion form dismisses without submitting', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

    const title = `E2E handoff cancel ${Date.now()}`
    const issue = await createIssue(request, { title, status: 'backlog', profile: 'frontend' })
    await createAcceptedHandoff(request, issue.id, 'frontend')

    await page.goto('/')

    const card = page.locator(`[data-testid="issue-card"][data-issue-id="${issue.id}"]`)
    await expect(card).toBeVisible()
    await card.click()
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Handoffs' }).click()

    let completedRequestFired = false
    page.on('request', req => {
      if (req.url().includes('/complete') && req.method() === 'POST') {
        completedRequestFired = true
      }
    })

    await page.getByRole('button', { name: 'Complete' }).click()
    await expect(page.getByTestId('completion-field-diff_summary')).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()

    // Give a tick for any stray request to fire
    await page.waitForTimeout(300)
    expect(completedRequestFired).toBe(false)
    await expect(page.getByTestId('completion-field-diff_summary')).toHaveCount(0)

    // Handoff should still be accepted, not completed.
    await expect(page.getByText('Completed')).toHaveCount(0)
  })
})
