// E2E-only store exposure.
//
// When `NUXT_PUBLIC_E2E === '1'`, expose the board store on
// `window.__DEVFLOW_E2E__` so Playwright specs can drive store actions
// directly (e.g. inject dependencies + trigger moveIssueWithUnlock to
// exercise the dependency-graph unlock path, which has no UI affordance
// today).
//
// Why this is safe:
//   1. The runtime config flag defaults to '0' (see nuxt.config.ts).
//   2. The plugin is `.client.ts`, so it never runs on the server.
//   3. The hook only attaches when the flag is exactly '1', so a
//      regular `npm run build && npm run preview` ships a no-op.
//   4. We expose a single, narrowly-typed handle (`store`), not the
//      whole Pinia instance.
//
// If you remove this plugin, e2e/dependency.spec.ts will fail with a
// clear "boardStore not exposed for E2E" error — fix the flag, do not
// quietly silence the spec.
import { useBoardStore } from '~/stores/board'

declare global {
  interface Window {
    __DEVFLOW_E2E__?: {
      store: ReturnType<typeof useBoardStore>
    }
  }
}

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  // Coerce to string: NUXT_PUBLIC_E2E=1 is serialized to `window.__NUXT__.config`
  // as a JSON number (1) rather than a string ("1"), so a strict `!== '1'`
  // comparison would always be true and the hook would never attach.
  if (String(config.public.e2e) !== '1') {
    return
  }

  const store = useBoardStore()
  window.__DEVFLOW_E2E__ = { store }
})
