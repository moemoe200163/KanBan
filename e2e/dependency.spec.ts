import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdmin } from './auth'

// E2E for the dependency-graph auto-unlock path
// (src/stores/board.ts::processDependencyUnlock).
//
// Why this spec exists as a safety net (before any board.ts refactor):
//   - The unlock logic is pure front-end: when a blocker moves to
//     `done`, any blocked issue whose `dependencies` are now all done
//     is automatically moved to `backlog`.
//   - The backend `POST /api/v1/issues` ignores `dependencies` today
//     and there is no UI affordance to set them, so this code path is
//     entirely untested from the outside without a hook.
//   - Refactoring board.ts (1700+ lines, planned) must not silently
//     break unlock. This spec pins the contract: blocker→done causes
//     dependent→backlog within the 500ms scheduled callback.
//
// How the hook works:
//   - `NUXT_PUBLIC_E2E=1` (set in e2e/playwright.config.ts webServer)
//     enables src/plugins/e2e-store-hook.client.ts, which attaches the
//     store to `window.__DEVFLOW_E2E__.store`. Without the flag the
//     plugin is a no-op, so production bundles are unaffected.

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
      description: 'Created by Playwright E2E (dependency spec).',
      status: data.status ?? 'backlog',
      priority: data.priority ?? 'medium',
      profile: data.profile ?? 'frontend',
      title: data.title
    }
  })
  expect(response.ok()).toBeTruthy()
  return await response.json() as { id: string; key: string }
}

test.describe('Dependency graph auto-unlock', () => {
  test('completed blocker moves dependent issue from blocked to backlog', async ({
    page,
    request,
    isMobile
  }) => {
    test.skip(isMobile, 'store-hook flow runs in the desktop project')
    const token = await loginAsAdmin(request, page)

    const ts = Date.now()
    const blocker = await createIssue(request, token, {
      title: `E2E blocker ${ts}`,
      status: 'in_progress',
      profile: 'frontend'
    })
    const dependent = await createIssue(request, token, {
      title: `E2E dependent ${ts}`,
      status: 'blocked',
      profile: 'frontend'
    })

    await page.goto('/')

    // Wait for both cards to render before touching the store.
    await expect(
      page.locator(`[data-testid="kanban-column-in_progress"] [data-issue-id="${blocker.id}"]`)
    ).toBeVisible()
    await expect(
      page.locator(`[data-testid="kanban-column-blocked"] [data-issue-id="${dependent.id}"]`)
    ).toBeVisible()

    // Inject dependency on the dependent issue. Backend `upsert_issue`
    // does not persist `dependencies`, so the only way to exercise the
    // unlock path is to mutate the live store. The store hook is gated
    // behind NUXT_PUBLIC_E2E=1; if it is missing, surface a clear error
    // instead of silently mis-passing.
    await page.evaluate(({ dependentId, blockerKey }) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) {
        throw new Error(
          '__DEVFLOW_E2E__ not exposed. Confirm NUXT_PUBLIC_E2E=1 is set ' +
          'on the preview server (see e2e/playwright.config.ts webServer.env).'
        )
      }
      const issue = hook.store.getAllIssues.find(i => i.id === dependentId)
      if (!issue) {
        throw new Error(`Dependent issue ${dependentId} not found in store`)
      }
      issue.dependencies = [blockerKey]
    }, { dependentId: dependent.id, blockerKey: blocker.key })

    // Drive the blocker through moveIssueWithUnlock: this is the
    // exact entry point board.ts uses when a card moves to Done, so
    // the spec exercises the production code path verbatim.
    await page.evaluate(({ blockerId }) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ missing during move')
      return hook.store.moveIssueWithUnlock(blockerId, 'in_progress', 'done', 0)
    }, { blockerId: blocker.id })

    // Assert: blocker landed in done.
    await expect(
      page.locator(`[data-testid="kanban-column-done"] [data-issue-id="${blocker.id}"]`)
    ).toBeVisible({ timeout: 5_000 })

    // Assert: dependent auto-unlocked to backlog within the 500ms
    // scheduled callback (+ generous buffer).
    await expect(
      page.locator(`[data-testid="kanban-column-backlog"] [data-issue-id="${dependent.id}"]`)
    ).toBeVisible({ timeout: 5_000 })

    // Assert: dependent is no longer in blocked.
    await expect(
      page.locator(`[data-testid="kanban-column-blocked"] [data-issue-id="${dependent.id}"]`)
    ).toHaveCount(0)
  })

  test('dependent stays blocked when only some dependencies are done', async ({
    page,
    request,
    isMobile
  }) => {
    test.skip(isMobile, 'store-hook flow runs in the desktop project')
    const token = await loginAsAdmin(request, page)

    const ts = Date.now()
    const blocker1 = await createIssue(request, token, {
      title: `E2E partial-blocker-1 ${ts}`,
      status: 'in_progress',
      profile: 'frontend'
    })
    const blocker2 = await createIssue(request, token, {
      title: `E2E partial-blocker-2 ${ts}`,
      status: 'in_progress',
      profile: 'frontend'
    })
    const dependent = await createIssue(request, token, {
      title: `E2E partial-dependent ${ts}`,
      status: 'blocked',
      profile: 'frontend'
    })

    await page.goto('/')

    await expect(
      page.locator(`[data-testid="kanban-column-blocked"] [data-issue-id="${dependent.id}"]`)
    ).toBeVisible()

    // Two blockers required; only one will complete this turn.
    await page.evaluate(({ dependentId, key1, key2 }) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ missing')
      const issue = hook.store.getAllIssues.find(i => i.id === dependentId)
      if (!issue) throw new Error(`Dependent ${dependentId} missing`)
      issue.dependencies = [key1, key2]
    }, { dependentId: dependent.id, key1: blocker1.key, key2: blocker2.key })

    await page.evaluate(({ blockerId }) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ missing')
      return hook.store.moveIssueWithUnlock(blockerId, 'in_progress', 'done', 0)
    }, { blockerId: blocker1.id })

    await expect(
      page.locator(`[data-testid="kanban-column-done"] [data-issue-id="${blocker1.id}"]`)
    ).toBeVisible({ timeout: 5_000 })

    // Wait the same 500ms window the unlock callback uses, plus
    // buffer, to make sure no spurious move happened.
    await page.waitForTimeout(1_500)

    // Dependent must still be blocked: blocker2 is not done.
    await expect(
      page.locator(`[data-testid="kanban-column-blocked"] [data-issue-id="${dependent.id}"]`)
    ).toBeVisible()
    await expect(
      page.locator(`[data-testid="kanban-column-backlog"] [data-issue-id="${dependent.id}"]`)
    ).toHaveCount(0)
  })
})
