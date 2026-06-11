import { ref, onMounted, onUnmounted } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useNotificationsStore } from '~/stores/notifications'
import { useToast } from '~/composables/useToast'
import type { IssueStatus, Priority } from '~/types'

// WebSocket message types
interface WebSocketMessage {
  type: 'issue_updated' | 'agent_status_changed' | 'webhook_received' | 'pong' | 'job_update' | 'subscribed' | 'unsubscribed' | 'error'
  payload: any
  timestamp: string
}

interface AgentStatusEvent {
  agentId: string
  status: 'idle' | 'running' | 'error'
  taskId?: string
}

interface IssueUpdatePayload {
  issueId: string
  changes: Partial<{
    title: string
    description: string
    status: IssueStatus
    priority: Priority
    assigneeId: string | null
    assigneeName: string | null
    labels: Array<{ id: string; name: string; color: string }>
  }>
}

// Job-update event bus — subscribers register via onJobUpdate().
type JobUpdateHandler = (job: any) => void
const _jobUpdateHandlers: JobUpdateHandler[] = []

// Build a short, human-friendly summary of an issue_updated payload
// for the inbox row / toast. Keeps the message body from becoming
// "undefined changed to undefined" when the change set is sparse.
const buildIssueChangeSummary = (
  changes: IssueUpdatePayload['changes'] | undefined,
): string => {
  if (!changes) return 'Issue updated'
  const parts: string[] = []
  if (changes.status) parts.push(`status → ${changes.status}`)
  if (changes.priority) parts.push(`priority → ${changes.priority}`)
  if (changes.title) parts.push('title updated')
  if (changes.description) parts.push('description updated')
  if (changes.assigneeName) parts.push(`assignee → ${changes.assigneeName}`)
  else if (changes.assigneeId === null) parts.push('assignee cleared')
  if (changes.labels && changes.labels.length) {
    parts.push(`${changes.labels.length} label${changes.labels.length === 1 ? '' : 's'}`)
  }
  if (parts.length === 0) return 'Issue updated'
  return parts.join(' · ')
}

const onJobUpdate = (handler: JobUpdateHandler) => {
  _jobUpdateHandlers.push(handler)
}

const emitJobUpdate = (job: any) => {
  for (const handler of _jobUpdateHandlers) {
    try { handler(job) } catch (e) { console.error('[WebSocket] onJobUpdate handler error:', e) }
  }
}

export const useWebSocket = () => {
  const boardStore = useBoardStore()
  const isConnected = ref(false)
  const reconnectAttempts = ref(0)
  const MAX_RECONNECT_ATTEMPTS = 5

  let ws: WebSocket | null = null
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null

  const WS_URL = 'ws://localhost:8000/ws'
  const BASE_RECONNECT_DELAY = 1000 // 1 second
  const MAX_RECONNECT_DELAY = 30000 // 30 seconds

  /**
   * Calculate delay with exponential backoff
   * Uses jitter to prevent thundering herd problem
   */
  const getReconnectDelay = (attempt: number): number => {
    const exponentialDelay = Math.min(
      BASE_RECONNECT_DELAY * Math.pow(2, attempt),
      MAX_RECONNECT_DELAY
    )
    // Add jitter (0-25% of delay)
    const jitter = exponentialDelay * Math.random() * 0.25
    return exponentialDelay + jitter
  }

  /**
   * Clean up WebSocket resources
   */
  const cleanup = () => {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }
    if (ws) {
      ws.onopen = null
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
      ws = null
    }
  }

  /**
   * Connect to WebSocket server
   */
  const connect = () => {
    // Prevent duplicate connections
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    try {
      ws = new WebSocket(WS_URL)

      ws.onopen = () => {
        console.log('[WebSocket] Connected to', WS_URL)
        isConnected.value = true
        reconnectAttempts.value = 0

        // Send heartbeat/ping to keep connection alive
        startHeartbeat()
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] Connection closed', { code: event.code, reason: event.reason })
        isConnected.value = false
        stopHeartbeat()
        cleanup()

        // Attempt reconnection if not a clean close
        if (event.code !== 1000 && reconnectAttempts.value < MAX_RECONNECT_ATTEMPTS) {
          scheduleReconnect()
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
        isConnected.value = false
      }

      ws.onmessage = (event: MessageEvent) => {
        handleMessage(event)
      }
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error)
      isConnected.value = false
      scheduleReconnect()
    }
  }

  /**
   * Schedule reconnection with exponential backoff
   */
  const scheduleReconnect = () => {
    if (reconnectAttempts.value >= MAX_RECONNECT_ATTEMPTS) {
      console.log('[WebSocket] Max reconnection attempts reached. Giving up.')
      return
    }

    const delay = getReconnectDelay(reconnectAttempts.value)
    reconnectAttempts.value++

    console.log(`[WebSocket] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts.value}/${MAX_RECONNECT_ATTEMPTS})`)

    reconnectTimeout = setTimeout(() => {
      connect()
    }, delay)
  }

  /**
   * Handle incoming WebSocket messages
   */
  const handleMessage = (event: MessageEvent) => {
    try {
      const data = event.data

      const message: WebSocketMessage = JSON.parse(data)

      if (message.type === 'pong') {
        return
      }

      console.log('[WebSocket] Received message:', message.type, message.timestamp)

      switch (message.type) {
        case 'issue_updated':
          boardStore.handleIssueUpdate(message.payload as IssueUpdatePayload)
          handleIssueUpdatedNotification(message.payload as IssueUpdatePayload)
          break

        case 'agent_status_changed':
          boardStore.handleAgentStatusUpdate(message.payload as AgentStatusEvent)
          handleAgentStatusNotification(message.payload as AgentStatusEvent)
          break

        case 'webhook_received':
          handleWebhookReceived(message.payload)
          handleWebhookNotification(message.payload)
          break

        case 'job_update':
          emitJobUpdate((message as any).job)
          handleJobUpdateNotification((message as any).job)
          break

        case 'subscribed':
        case 'unsubscribed':
          // Acknowledgement messages — no action needed
          break

        case 'error':
          console.warn('[WebSocket] Server error:', (message as any).message)
          break

        default:
          console.warn('[WebSocket] Unknown message type:', message.type)
      }
    } catch (error) {
      console.error('[WebSocket] Failed to parse message:', error)
    }
  }

  /**
   * Handle webhook received events
   */
  const handleWebhookReceived = (payload: any) => {
    console.log('[WebSocket] Webhook received:', payload)

    // Dispatch custom event for components to listen to
    if (import.meta.client) {
      window.dispatchEvent(new CustomEvent('webhook-received', { detail: payload }))
    }
  }

  // ---------------------------------------------------------------------------
  // Notification side-effects
  // ---------------------------------------------------------------------------
  //
  // Each WebSocket event is a chance to surface something the operator
  // would otherwise miss. The store handles dedup (30s window per
  // type+resource) and the FIFO cap, so we just hand it a payload and
  // the store decides whether to keep it.
  //
  // Toast lifetime is intentionally short (default 3s) — the inbox
  // page is the durable surface; the toast is the "hey, look up"
  // ping.
  const _safeNotifications = (): ReturnType<typeof useNotificationsStore> | null => {
    try {
      return useNotificationsStore()
    } catch {
      // SSR / no Pinia — should not happen in practice, the composable
      // is client-only via onMounted.
      return null
    }
  }

  const _safeToast = (): ReturnType<typeof useToast> | null => {
    try {
      return useToast()
    } catch {
      return null
    }
  }

  const handleIssueUpdatedNotification = (payload: IssueUpdatePayload | undefined) => {
    if (!payload) return
    const issue = boardStore.getIssueById(payload.issueId)
    const key = issue?.key ?? payload.issueId
    const title = `${key} 已更新`
    const message = buildIssueChangeSummary(payload.changes)
    const ns = _safeNotifications()
    if (!ns) return
    const notif = ns.push({
      type: 'issue_updated',
      title,
      message,
      link: '/',
      resource: payload.issueId,
    })
    if (notif) {
      _safeToast()?.add(title)
    }
  }

  const handleAgentStatusNotification = (payload: AgentStatusEvent | undefined) => {
    if (!payload) return
    // Suppress running churn — only idle (or error) flips are worth
    // interrupting the operator with. Error is debatable but the
    // sidebar already lights up the global AI status, so a separate
    // inbox row would be noise.
    if (payload.status !== 'idle') return
    const ns = _safeNotifications()
    if (!ns) return
    const notif = ns.push({
      type: 'agent_status',
      title: `Agent ${payload.agentId} 已閒置`,
      message: payload.taskId
        ? `Task ${payload.taskId} 完成，回到 idle 等待下一輪`
        : 'Agent 已回到 idle 狀態',
      link: '/agents',
      resource: payload.agentId,
    })
    if (notif) {
      _safeToast()?.add(`Agent ${payload.agentId} 已閒置`)
    }
  }

  const handleWebhookNotification = (payload: any) => {
    if (!payload) return
    const ns = _safeNotifications()
    if (!ns) return
    // The backend payload shape varies by webhook source; pick the
    // most useful identifier for the message body.
    const source = payload?.source ?? payload?.type ?? 'webhook'
    const resource = String(
      payload?.id ?? payload?.event ?? `${source}-${Date.now()}`,
    )
    const title = 'Webhook fired'
    const message = String(payload?.message ?? payload?.event ?? `Received from ${source}`)
    const notif = ns.push({
      type: 'webhook',
      title,
      message,
      link: '/settings/webhooks',
      resource,
    })
    if (notif) {
      _safeToast()?.add(`${title}: ${message}`)
    }
  }

  const handleJobUpdateNotification = (job: any) => {
    if (!job) return
    const status = job?.status
    // Only surface terminal-ish transitions that change operator
    // workload. Running/queued are too noisy to justify an inbox row.
    const INTERESTING = new Set(['review_required', 'completed', 'failed'])
    if (!INTERESTING.has(status)) return
    const ns = _safeNotifications()
    if (!ns) return
    const key = job.issue_key ?? job.issue_id ?? job.id
    const title = `Job ${key} → ${status}`
    const message = String(job.message ?? `Status changed to ${status}`)
    const notif = ns.push({
      type: 'job_update',
      title,
      message,
      link: '/runs',
      resource: String(job.id ?? key),
    })
    if (notif) {
      _safeToast()?.add(title)
    }
  }

  // Heartbeat management
  let heartbeatInterval: ReturnType<typeof setInterval> | null = null
  const HEARTBEAT_INTERVAL = 30000 // 30 seconds

  const startHeartbeat = () => {
    stopHeartbeat()
    heartbeatInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', timestamp: new Date().toISOString() }))
      }
    }, HEARTBEAT_INTERVAL)
  }

  const stopHeartbeat = () => {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval)
      heartbeatInterval = null
    }
  }

  /**
   * Manually reconnect
   */
  const reconnect = () => {
    console.log('[WebSocket] Manual reconnect requested')
    cleanup()
    reconnectAttempts.value = 0
    connect()
  }

  /**
   * Send message to WebSocket server
   */
  const send = (message: object) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message))
    } else {
      console.warn('[WebSocket] Cannot send message: connection not open')
    }
  }

  const subscribe = (jobId: string) => {
    send({ action: 'subscribe', job_id: jobId })
  }

  const unsubscribe = (jobId: string) => {
    send({ action: 'unsubscribe', job_id: jobId })
  }

  // Pipe job_update events into the board store. The listener fires
  // for every incoming job update, regardless of who subscribed; the
  // store is the single source of truth for job data.
  onJobUpdate((job) => {
    boardStore.handleJobUpdate(job as any)
  })

  // Lifecycle
  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    cleanup()
  })

  return {
    isConnected,
    reconnectAttempts,
    connect,
    reconnect,
    send,
    subscribe,
    unsubscribe
  }
}

export { onJobUpdate }
