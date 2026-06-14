/**
 * Shared E2E auth helpers.
 *
 * The E2E reset endpoint seeds two users:
 * - e2e_admin (role=admin) — for admin-gated tests
 * - e2e_member (role=member) — for logged-in non-admin tests
 *
 * Both use password: testpass123
 *
 * Usage in specs:
 *   import { loginAsAdmin, loginAsMember, clearAuth } from './auth'
 *
 *   // Admin auth required (provider config, agent roles CRUD, etc.)
 *   test('admin can configure provider', async ({ page, request }) => {
 *     await loginAsAdmin(request, page)
 *     // ... test assumes admin context
 *   })
 *
 *   // No auth (read-only behavior)
 *   test('board loads without auth', async ({ page }) => {
 *     await clearAuth(page)
 *     await page.goto('/')
 *     // ... test verifies read-only behavior
 *   })
 */

import type { APIRequestContext, Page } from '@playwright/test'

const BACKEND = 'http://127.0.0.1:8000'
const COOKIE_NAME = 'auth_token'
const E2E_ADMIN_USER = 'e2e_admin'
const E2E_MEMBER_USER = 'e2e_member'
const E2E_PASSWORD = 'testpass123'

// ---------------------------------------------------------------------------
// Low-level helpers
// ---------------------------------------------------------------------------

/** Login and return the JWT access token. */
export async function login(
  request: APIRequestContext,
  username: string,
  password = E2E_PASSWORD,
): Promise<string> {
  const res = await request.post(`${BACKEND}/api/v1/auth/token`, {
    data: { username, password },
  })
  if (!res.ok()) {
    throw new Error(`login failed: ${res.status()} ${await res.text()}`)
  }
  const body = await res.json()
  return body.access_token as string
}

/** Set the auth_token cookie in the browser context. */
export async function setAuthCookie(page: Page, token: string): Promise<void> {
  // Use page.evaluate to set cookie via document.cookie (same as browser JS)
  // This ensures the cookie is set with the correct attributes for cross-origin access
  await page.evaluate(([name, value]) => {
    document.cookie = `${name}=${value}; path=/; SameSite=Lax`
  }, [COOKIE_NAME, token])
}

// ---------------------------------------------------------------------------
// High-level auth helpers
// ---------------------------------------------------------------------------

/**
 * Log in as the seeded e2e_admin user and set auth cookie in browser.
 * Returns the token so callers can use it for API calls.
 * Use for tests that need admin privileges (provider config, agent roles CRUD, etc.)
 */
export async function loginAsAdmin(
  request: APIRequestContext,
  page: Page,
): Promise<string> {
  const token = await login(request, E2E_ADMIN_USER, E2E_PASSWORD)
  // Navigate to frontend first so we have a document context to set cookie
  await page.goto('http://127.0.0.1:3010/', { waitUntil: 'domcontentloaded' })
  await setAuthCookie(page, token)

  // Verify admin status
  const res = await request.get(`${BACKEND}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.ok()) {
    const data = await res.json()
    if (data.role !== 'admin') {
      throw new Error(`[auth] e2e_admin has role="${data.role}", expected admin`)
    }
  }
  return token
}

/**
 * Log in as the seeded e2e_member user and set auth cookie in browser.
 * Use for tests that need a logged-in non-admin user.
 */
export async function loginAsMember(
  request: APIRequestContext,
  page: Page,
): Promise<void> {
  const token = await login(request, E2E_MEMBER_USER, E2E_PASSWORD)
  await page.goto('http://127.0.0.1:3010/', { waitUntil: 'domcontentloaded' })
  await setAuthCookie(page, token)
}

/**
 * Clear all auth state from the browser context.
 * Use for tests that explicitly verify unauthenticated behavior.
 */
export async function clearAuth(page: Page): Promise<void> {
  await page.context().clearCookies()
}
