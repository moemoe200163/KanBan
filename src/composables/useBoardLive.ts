/**
 * useBoardLive — Plan F: keep the board page in sync with server
 * changes by subscribing to /ws/issues for every issue currently
 * on the board, and triggering a board refetch whenever any of
 * them gets an "issue_updated" nudge.
 *
 * Designed to be mounted once at the page level (pages/index.vue
 * or KanbanBoard.vue). The composable owns its own WebSocket and
 * keeps a Set of subscribed issue_ids in sync with the live
 * board store columns — issues that appear get subscribed,
 * issues that disappear get unsubscribed.
 *
 * Scope creep guard:
 *  - No per-issue granular refetch: a single board refetch on
 *    any update is enough for v1 (the board is small). If perf
 *    becomes an issue we'll switch to per-card updates.
 *  - No reconnect: see useIssueDetailLive for the same trade-off.
 *  - No deduplication across multiple KanbanBoard instances: if
 *    the page gets mounted twice the WS opens twice. The dev
 *    page doesn't do that, so we ignore it.
 */

import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useBoardStore } from '~/stores/board'

export function useBoardLive() {
  const boardStore = useBoardStore()

  let ws: WebSocket | null = null
  const subscribed = new Set<string>()
  let pendingSubscribes = new Set<string>()
  let pendingUnsubscribes = new Set<string>()
  let flushTimer: ReturnType<typeof setTimeout> | null = null

  function buildUrl(): string {
    if (typeof window === 'undefined') return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws/issues`
  }

  function send(action: string, issueId: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    try {
      ws.send(JSON.stringify({ action, issue_id: issueId }))
    } catch {
      // best-effort
    }
  }

  function scheduleFlush() {
    if (flushTimer) return
    flushTimer = setTimeout(() => {
      flushTimer = null
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      for (const id of pendingUnsubscribes) {
        send('unsubscribe', id)
        subscribed.delete(id)
      }
      for (const id of pendingSubscribes) {
        send('subscribe', id)
        subscribed.add(id)
      }
      pendingSubscribes.clear()
      pendingUnsubscribes.clear()
    }, 100)
  }

  function resync(visibleIds: string[]) {
    const wanted = new Set(visibleIds)
    for (const id of subscribed) {
      if (!wanted.has(id)) pendingUnsubscribes.add(id)
    }
    for (const id of wanted) {
      if (!subscribed.has(id) && !pendingUnsubscribes.has(id)) {
        pendingSubscribes.add(id)
      }
    }
    scheduleFlush()
  }

  function connect() {
    if (typeof window === 'undefined') return
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }
    try {
      ws = new WebSocket(buildUrl())
    } catch (e) {
      console.warn('[BoardLive] connect failed:', e)
      return
    }
    ws.onopen = () => {
      // eslint-disable-next-line no-console
      console.log('[BoardLive] connected to', buildUrl())
      // Re-subscribe to everything we know about, in case we reconnected.
      for (const id of subscribed) {
        send('subscribe', id)
      }
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as {
          type?: string
          issue_id?: string
          change?: string
        }
        if (data.type !== 'issue_updated') return
        if (!data.issue_id) return
        // A single board refetch on any change is enough for v1.
        void boardStore.fetchBoard()
      } catch (e) {
        console.warn('[BoardLive] message parse failed:', e)
      }
    }
    ws.onclose = () => {
      // eslint-disable-next-line no-console
      console.log('[BoardLive] closed')
      ws = null
    }
    ws.onerror = (e) => {
      // eslint-disable-next-line no-console
      console.warn('[BoardLive] error:', e)
    }
  }

  function close() {
    if (!ws) return
    for (const id of subscribed) {
      send('unsubscribe', id)
    }
    try {
      ws.close()
    } catch {
      // ignore
    }
    ws = null
  }

  function visibleIds(): string[] {
    const out: string[] = []
    for (const col of boardStore.columns) {
      for (const issue of col.issues ?? []) {
        if (issue?.id) out.push(issue.id)
      }
    }
    return out
  }

  onMounted(() => {
    connect()
    resync(visibleIds())
  })

  watch(
    () => boardStore.columns,
    () => resync(visibleIds()),
    { deep: true },
  )

  onBeforeUnmount(() => {
    close()
  })
}
