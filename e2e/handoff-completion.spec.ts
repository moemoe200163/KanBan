import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

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

// Open an issue via the e2e store hook and switch to the Handoffs tab.
// The user-facing path is a card click, but the kanban columns container
// and the review-queue overlay can sit on top of the card's bounding
// box and intercept the click; the store-hook path is what
// e2e/dependency.spec.ts uses for the same reason. This is the tracked
// UX bug noted in the spec section 6, not a test methodology preference.
const openIssueAndSwitchToHandoffsTab = async (
  page: Page,
  issueId: string
) => {
  // Wait for the board to load so the store has the issue. Without
  // this, getAllIssues can be empty when the API-created issue hasn't
  // been fetched yet — same pattern dependency.spec.ts uses.
  await expect(
    page.locator(`[data-issue-id="${issueId}"]`)
  ).toBeVisible({ timeout: 5_000 })
  await page.evaluate((id) => {
    const hook = (window as Window).__DEVFLOW_E2E__
    if (!hook) {
      throw new Error(
        '__DEVFLOW_E2E__ not exposed. Confirm NUXT_PUBLIC_E2E=1 is set ' +
        'on the preview server (see e2e/playwright.config.ts webServer.env).'
      )
    }
    const issue = hook.store.getAllIssues.find(i => i.id === id)
    if (!issue) throw new Error(`Issue ${id} not found in store`)
    hook.store.selectIssue(issue)
  }, issueId)
  await expect(page.locator('.issue-detail__panel')).toBeVisible()
  await page.getByRole('button', { name: 'Handoffs' }).click()
}

test.describe('Handoff completion with required fields', () => {
  test('Frontend lane completion shows form for diff_summary + screenshots', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

    const title = `E2E handoff complete ${Date.now()}`
    const issue = await createIssue(request, { title, status: 'backlog', profile: 'frontend' })
    await createAcceptedHandoff(request, issue.id, 'frontend')

    await page.goto('/')

    // Open the issue and switch to the Handoffs tab.
    // Drive the store directly via the e2e hook (NUXT_PUBLIC_E2E=1).
    // A card click is the user-facing path, but with many seeded issues
    // the kanban columns container (and the review-queue overlay on the
    // right) can sit on top of the card's bounding box and intercept
    // the click. The store-hook path is what dependency.spec.ts uses
    // for the same reason — it tests the same flow (panel renders,
    // handoffs tab, Complete button) without depending on overlay
    // pointer routing.
    const card = page.locator(`[data-testid="issue-card"][data-issue-id="${issue.id}"]`)
    await expect(card).toBeVisible()
    await page.evaluate((issueId) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) {
        throw new Error(
          '__DEVFLOW_E2E__ not exposed. Confirm NUXT_PUBLIC_E2E=1 is set ' +
          'on the preview server (see e2e/playwright.config.ts webServer.env).'
        )
      }
      const issue = hook.store.getAllIssues.find(i => i.id === issueId)
      if (!issue) throw new Error(`Issue ${issueId} not found in store`)
      hook.store.selectIssue(issue)
    }, issue.id)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Handoffs' }).click()

    // The handoff created above should render in the section. Click
    // Complete — should pre-flight the preview and open the inline
    // form because the frontend lane requires diff_summary + screenshots.
    // Use the HandoffCard's data-testid; the bare `name: 'Complete'`
    // collides with sidebar job-item buttons whose job status text
    // contains "Complete" (e.g. "completed" past-tense).
    await page.getByTestId('handoff-complete-btn').click()

    // The new form should appear with one input per missing required field.
    await expect(page.getByTestId('completion-field-diff_summary')).toBeVisible()
    await expect(page.getByTestId('completion-field-screenshots')).toBeVisible()

    // Fill in the required fields and submit. The frontend lane's
    // `screenshots` is a typed `list[str]` on the wire (see
    // backend/core/kanban_protocol/payloads.py FrontendPayload) — the
    // form's submitCompletion tries JSON.parse on each value and
    // passes through the array when the input parses, so we send a
    // valid JSON array here. `diff_summary` is a plain string and
    // goes through unchanged.
    await page.getByTestId('completion-field-diff_summary').fill('E2E diff summary')
    await page.getByTestId('completion-field-screenshots').fill('["e2e.png"]')

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
    await page.evaluate((issueId) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ missing during open')
      const issue = hook.store.getAllIssues.find(i => i.id === issueId)
      if (!issue) throw new Error(`Issue ${issueId} not found in store`)
      hook.store.selectIssue(issue)
    }, issue.id)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Handoffs' }).click()

    let completedRequestFired = false
    page.on('request', req => {
      if (req.url().includes('/complete') && req.method() === 'POST') {
        completedRequestFired = true
      }
    })

    await page.getByTestId('handoff-complete-btn').click()
    await expect(page.getByTestId('completion-field-diff_summary')).toBeVisible()
    // Scope to the form's Cancel button via its testid; a bare
    // `getByRole('button', { name: 'Cancel' })` collides with the
    // HandoffCard's per-card Cancel action (the new-issue and handoff
    // create modals also have a Cancel).
    await page.getByTestId('cancel-completion').click()

    // Give a tick for any stray request to fire
    await page.waitForTimeout(300)
    expect(completedRequestFired).toBe(false)
    await expect(page.getByTestId('completion-field-diff_summary')).toHaveCount(0)

    // Handoff should still be accepted, not completed.
    await expect(page.getByText('Completed')).toHaveCount(0)
  })
})

test('Backend rejects bad coverage_pct with structured 422 (P1.5 regression)', async ({ request, isMobile }) => {
  test.skip(isMobile, 'desktop-only API regression')

  const title = `E2E qa bad coverage ${Date.now()}`
  const issue = await createIssue(request, { title, status: 'backlog', profile: 'general' })
  const handoff = await createAcceptedHandoff(request, issue.id, 'qa')

  // The lane requires test_results + coverage_pct. Sending coverage_pct
  // out of range exercises the typed contract end-to-end.
  const response = await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issue.id}/handoffs/${handoff.id}/complete`,
    { data: { actor: 'e2e', payload: { test_results: 'ok', coverage_pct: 150 } } }
  )
  expect(response.status()).toBe(422)
  const body = await response.json()
  expect(body.detail).toBeTruthy()
  expect(body.detail.lane).toBe('qa')
  expect(Array.isArray(body.detail.errors)).toBe(true)
  expect(body.detail.errors.some(
    (e: any) => Array.isArray(e.loc) && e.loc[0] === 'coverage_pct'
  )).toBe(true)
})

test('completed handoff shows View evidence toggle and expands', async ({
  page, request, isMobile
}) => {
  test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

  // Seed: issue + handoff + accept + complete with a typed payload that
  // exercises both string and list[str] field rendering.
  const title = `E2E handoff evidence ${Date.now()}`
  const issue = await createIssue(request, { title, profile: 'frontend' })
  const handoff = await createAcceptedHandoff(request, issue.id, 'frontend')
  await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issue.id}/handoffs/${handoff.id}/complete`,
    {
      data: {
        actor: 'e2e',
        payload: {
          diff_summary: 'Adds the evidence toggle to HandoffCard.',
          screenshots: ['shot-1.png', 'shot-2.png']
        }
      }
    }
  )

  await page.goto('/')
  await openIssueAndSwitchToHandoffsTab(page, issue.id)

  // Toggle visible, body hidden by default. (Body assertions come in Task 2.)
  const toggle = page.getByTestId('handoff-evidence-toggle')
  await expect(toggle).toBeVisible()
  await expect(toggle).toContainText('View evidence (2 fields)')
  await expect(page.getByTestId('handoff-evidence-body')).toHaveCount(0)
})
