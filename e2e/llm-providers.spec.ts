import { expect, test, type APIRequestContext } from '@playwright/test'

const BACKEND = 'http://127.0.0.1:8000'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Register a user; tolerates 409 (already exists). */
async function registerUser(
  request: APIRequestContext,
  username: string,
  password = 'testpass123',
): Promise<void> {
  const res = await request.post(`${BACKEND}/api/v1/auth/register`, {
    data: { username, password },
    failOnStatusCode: false,
  })
  // 201 = created, 409 = already exists — both are fine
  expect([201, 409]).toContain(res.status())
}

/** Login and return the JWT access token. */
async function login(
  request: APIRequestContext,
  username: string,
  password = 'testpass123',
): Promise<string> {
  const res = await request.post(`${BACKEND}/api/v1/auth/token`, {
    data: { username, password },
  })
  expect(res.ok(), `login failed: ${res.status()} ${await res.text()}`).toBeTruthy()
  const body = await res.json()
  return body.access_token
}

/** Configure a provider via the API. */
async function configureProvider(
  request: APIRequestContext,
  token: string,
  providerId: string,
  config: Record<string, unknown>,
): Promise<void> {
  const res = await request.put(
    `${BACKEND}/api/v1/llm/providers/${providerId}/config`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: config,
      failOnStatusCode: false,
    },
  )
  expect(res.ok(), `configure ${providerId}: ${res.status()} ${await res.text()}`).toBeTruthy()
}

/** Navigate from / to /settings and click the LLM Providers tab. */
async function openLLMProvidersTab(page: import('@playwright/test').Page) {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await page.locator('.settings-tab', { hasText: 'LLM Providers' }).click()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('LLM Providers settings', () => {
  test('provider cards render on settings page', async ({ page }) => {
    await openLLMProvidersTab(page)

    // The providers grid should load (may show loading spinner briefly)
    const grid = page.locator('.providers-grid')
    await expect(grid).toBeVisible({ timeout: 10_000 })

    // Verify well-known provider cards are present. Use the provider-card__name
    // selector with :text-is() for exact match to avoid "OpenAI" matching "OpenAI Codex".
    const expectedNames = ['OpenAI', 'Anthropic', 'MiniMax', 'Safe Runner']
    for (const name of expectedNames) {
      const nameEl = page.locator(`.provider-card__name:text-is("${name}")`)
      await expect(nameEl).toBeVisible()
    }

    // Each card should display a health badge
    const badges = page.locator('.health-badge')
    await expect(badges.first()).toBeVisible()
    const count = await badges.count()
    expect(count).toBeGreaterThanOrEqual(expectedNames.length)
  })

  test('provider card expands to show config fields', async ({ page }) => {
    await openLLMProvidersTab(page)

    // Wait for providers to load
    await expect(page.locator('.providers-grid')).toBeVisible({ timeout: 10_000 })

    // Click on the MiniMax card header to expand it
    const minimaxCard = page.locator('.provider-card', { hasText: 'MiniMax' })
    await expect(minimaxCard).toBeVisible()
    await minimaxCard.locator('.provider-card__header').click()

    // Expanded details should be visible
    const details = minimaxCard.locator('.provider-card__details')
    await expect(details).toBeVisible()

    // Verify Base URL, Model, and API Key fields exist
    await expect(details.getByText('Base URL:')).toBeVisible()
    await expect(details.getByText('Model:')).toBeVisible()
    await expect(details.getByText('API Key:')).toBeVisible()

    // Test button should be visible
    await expect(details.locator('.action-btn--test')).toBeVisible()
  })

  test('test button triggers health check and shows result', async ({ page, request }) => {
    // --- API setup: register, login, configure MiniMax ---
    const ts = Date.now()
    const username = `e2e-llm-${ts}`
    await registerUser(request, username)
    const token = await login(request, username)

    await configureProvider(request, token, 'minimax', {
      baseUrl: 'https://api.minimax.io/v1',
      model: 'MiniMax-M3',
      apiKey: 'test-key-for-e2e',
    })

    // Set the auth token cookie so the UI's testHealth call can authenticate.
    // The store reads `useCookie('auth_token').value` for the Bearer header.
    await page.context().addCookies([{
      name: 'auth_token',
      value: token,
      domain: '127.0.0.1',
      path: '/',
    }])

    // --- UI: navigate to providers, expand MiniMax, click Test ---
    await openLLMProvidersTab(page)
    await expect(page.locator('.providers-grid')).toBeVisible({ timeout: 10_000 })

    const minimaxCard = page.locator('.provider-card', { hasText: 'MiniMax' })
    await expect(minimaxCard).toBeVisible()
    await minimaxCard.locator('.provider-card__header').click()

    const details = minimaxCard.locator('.provider-card__details')
    await expect(details).toBeVisible()

    const testBtn = details.locator('.action-btn--test')
    await expect(testBtn).toBeVisible()

    // Click Test and wait for the response (spinner disappears, badge updates)
    await testBtn.click()

    // The button should show a spinner while the test is in progress
    // Then the health badge should update to a non-default state
    // (auth_error or endpoint_error expected with a fake key)
    const healthBadge = minimaxCard.locator('.health-badge')
    await expect(healthBadge).not.toHaveText('Unknown', { timeout: 15_000 })

    // The badge should show a known status (not "Not Configured" since we set a key).
    // CSS text-transform:uppercase renders badge text in uppercase, so normalize.
    const badgeText = (await healthBadge.innerText()).toLowerCase().replace(/\s+/g, '_')
    const knownStatuses = [
      'healthy', 'auth_error', 'billing_error', 'model_error',
      'rate_limited', 'endpoint_error', 'timeout', 'unhealthy', 'unknown',
    ]
    expect(knownStatuses).toContain(badgeText)
  })
})
