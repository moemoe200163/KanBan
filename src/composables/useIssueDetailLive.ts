/**
 * useIssueDetailLive — Plan F: subscribe to /ws/issues for the
 * currently open issue and refetch a provided set of resources
 * whenever the server announces a change.
 *
 * The shape of the server message is intentionally tiny:
 *     {
 *       "type": "issue_updated",
 *       "issue_id": "<uuid>",
 *       "change": "event" | "artifact" | "cycle_report_pass"
 *     }
 *
 * The client knows how to refetch itself — we just give it a
 * nudge. This composable mounts a second WebSocket (the global
 * useWebSocket channel is /ws and serves other consumers); both
 * are independent and the v1 dev mode has anonymous-WS enabled so
 * no auth handshake is needed.
 *
 * Scope creep guard:
 *  - No automatic reconnect. The dev container doesn't drop WS
 *    connections in normal use; if a reconnect is needed the
 *    operator can reload the page.
 *  - No optimistic updates. We only refetch — never mutate local
 *    state based on the WS message.
 *  - No cross-issue subscription. The composable takes one
 *    issueId at a time and swaps it on change.
 */

import { onBeforeUnmount, onMounted, watch } from 'vue'

interface UseIssueDetailLiveArgs {
  issueId: () => string | null | undefined
  onUpdate: (change: string) => void
}

export function useIssueDetailLive(args: UseIssueDetailLiveArgs) {
  let ws: WebSocket | null = null
  let currentIssueId: string | null = null
  let pendingSubscribe: string | null = null

  function buildUrl(): string {
    if (typeof window === 'undefined') return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws/issues`
  }

  function flushSubscribe() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    if (!pendingSubscribe) return
    ws.send(JSON.stringify({ action: 'subscribe', issue_id: pendingSubscribe }))
    pendingSubscribe = null
  }

  function connect() {
    if (typeof window === 'undefined') return
    // Don't open a second socket if one is already alive.
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      flushSubscribe()
      return
    }
    try {
      ws = new WebSocket(buildUrl())
    } catch (e) {
      console.warn('[IssueLive] connect failed:', e)
      return
    }
    ws.onopen = () => {
      flushSubscribe()
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as {
          type?: string
          issue_id?: string
          change?: string
        }
        if (data.type !== 'issue_updated') return
        if (data.issue_id !== currentIssueId) return
        args.onUpdate(data.change ?? 'unknown')
      } catch (e) {
        console.warn('[IssueLive] message parse failed:', e)
      }
    }
    ws.onclose = () => {
      // eslint-disable-next-line no-console
      console.log('[IssueLive] closed')
      ws = null
    }
    ws.onerror = (e) => {
      // eslint-disable-next-line no-console
      console.warn('[IssueLive] error:', e)
    }
  }

  function close() {
    if (!ws) return
    if (currentIssueId && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ action: 'unsubscribe', issue_id: currentIssueId }))
      } catch {
        // best-effort
      }
    }
    try {
      ws.close()
    } catch {
      // ignore
    }
    ws = null
  }

  function setIssue(id: string | null | undefined) {
    if (id === currentIssueId) return
    // Unsubscribe from the previous issue (best-effort).
    if (ws && ws.readyState === WebSocket.OPEN && currentIssueId) {
      try {
        ws.send(JSON.stringify({ action: 'unsubscribe', issue_id: currentIssueId }))
      } catch {
        // ignore
      }
    }
    currentIssueId = id ?? null
    pendingSubscribe = currentIssueId
    flushSubscribe()
  }

  onMounted(() => {
    connect()
    setIssue(args.issueId())
  })

  watch(
    () => args.issueId(),
    (next) => setIssue(next),
  )

  onBeforeUnmount(() => {
    close()
  })
}
