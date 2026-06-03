import { expect, test, type APIRequestContext } from '@playwright/test'

const createIssue = async (request: APIRequestContext, data: {
  title: string
  status?: string
  profile?: string
}) => {
  const response = await request.post('http://127.0.0.1:8000/api/v1/issues', {
    data: {
      description: 'debug',
      status: data.status ?? 'backlog',
      priority: 'medium',
      profile: data.profile ?? 'frontend',
      title: data.title
    }
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test('debug handoff render', async ({ page, request }) => {
  const title = `Debug ${Date.now()}`
  const issue = await createIssue(request, { title })
  const create = await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issue.id}/handoffs`,
    { data: { toLane: 'frontend', createdBy: 'e2e' } }
  )
  const handoff = await create.json()
  await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issue.id}/handoffs/${handoff.id}/accept`,
    { data: { actor: 'e2e' } }
  )

  await page.goto('/')
  const card = page.locator(`[data-testid="issue-card"][data-issue-id="${issue.id}"]`)
  await card.click()
  await expect(page.locator('.issue-detail__panel')).toBeVisible()
  await page.getByRole('button', { name: 'Handoffs' }).click()
  await page.waitForTimeout(2000)
  await page.screenshot({ path: 'test-results/debug-handoff.png', fullPage: true })

  // Capture the handoffs state from the store
  const debug = await page.evaluate(() => {
    const piniaApp = (window as any).$nuxt || (window as any).useNuxtApp
    return {
      handoffsHTML: document.querySelectorAll('.issue-detail__panel').length,
      hasCompleteBtn: document.body.innerText.includes('Complete'),
      hasAcceptedBadge: document.body.innerText.includes('Accepted'),
      bodyHasHandoffs: document.body.innerText.includes('handoff')
    }
  })
  console.log('DEBUG:', JSON.stringify(debug, null, 2))
})
