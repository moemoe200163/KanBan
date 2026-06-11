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
import { useNotificationsStore } from '~/stores/notifications'
import { useToast } from '~/composables/useToast'

interface NotificationInjection {
  type: 'issue_updated' | 'agent_status' | 'webhook' | 'job_update' | 'cycle_report'
  payload: any
  /** When true, also call useToast().add() to mimic the live WS path. */
  withToast?: boolean
}

declare global {
  interface Window {
    __DEVFLOW_E2E__?: {
      store: ReturnType<typeof useBoardStore>
      notifications: {
        store: ReturnType<typeof useNotificationsStore>
        /**
         * Push a notification through the same code path the
         * WebSocket composable uses. Used by the notifications
         * spec to verify toast + bell + inbox from a known
         * payload, without standing up a fake WS server.
         *
         * The handler mirrors useWebSocket.ts's switch on
         * `message.type` — keep them in sync if either moves.
         */
        injectFromWs(message: { type: string; payload?: any; job?: any }): void
        reset(): void
      }
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
  const notifStore = useNotificationsStore()
  notifStore.hydrate()

  const injectFromWs = (message: { type: string; payload?: any; job?: any }) => {
    const payload = message.payload
    const toast = useToast()
    switch (message.type) {
      case 'issue_updated': {
        const issueId = payload?.issueId ?? 'unknown-issue'
        const key = store.getIssueById(issueId)?.key ?? issueId
        const changes = payload?.changes ?? {}
        const parts: string[] = []
        if (changes.status) parts.push(`status → ${changes.status}`)
        if (changes.priority) parts.push(`priority → ${changes.priority}`)
        if (changes.title) parts.push('title updated')
        if (changes.description) parts.push('description updated')
        if (changes.assigneeName) parts.push(`assignee → ${changes.assigneeName}`)
        if (parts.length === 0) parts.push('Issue updated')
        const title = `${key} 已更新`
        notifStore.push({
          type: 'issue_updated',
          title,
          message: parts.join(' · '),
          link: '/',
          resource: issueId,
        })
        toast.add(title)
        break
      }
      case 'agent_status_changed': {
        if (payload?.status !== 'idle') break
        const title = `Agent ${payload.agentId} 已閒置`
        const notif = notifStore.push({
          type: 'agent_status',
          title,
          message: payload?.taskId
            ? `Task ${payload.taskId} 完成，回到 idle 等待下一輪`
            : 'Agent 已回到 idle 狀態',
          link: '/agents',
          resource: payload.agentId,
        })
        if (notif) toast.add(title)
        break
      }
      case 'webhook_received': {
        const source = payload?.source ?? payload?.type ?? 'webhook'
        const title = 'Webhook fired'
        const msg = String(payload?.message ?? payload?.event ?? `Received from ${source}`)
        const notif = notifStore.push({
          type: 'webhook',
          title,
          message: msg,
          link: '/settings/webhooks',
          resource: String(payload?.id ?? `${source}-${Date.now()}`),
        })
        if (notif) toast.add(`${title}: ${msg}`)
        break
      }
      case 'job_update': {
        const job = message.job
        if (!job) break
        const INTERESTING = new Set(['review_required', 'completed', 'failed'])
        if (!INTERESTING.has(job.status)) break
        const key = job.issue_key ?? job.issue_id ?? job.id
        const title = `Job ${key} → ${job.status}`
        const msg = String(job.message ?? `Status changed to ${job.status}`)
        const notif = notifStore.push({
          type: 'job_update',
          title,
          message: msg,
          link: '/runs',
          resource: String(job.id ?? key),
        })
        if (notif) toast.add(title)
        break
      }
      default:
        // Unknown type — ignore. We don't want the test to crash
        // when the message envelope grows a new variant.
        break
    }
  }

  window.__DEVFLOW_E2E__ = {
    store,
    notifications: {
      store: notifStore,
      injectFromWs,
      reset() {
        notifStore.clearAll()
      },
    },
  }
})
