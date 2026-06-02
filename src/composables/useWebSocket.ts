import { ref, onMounted, onUnmounted } from 'vue'
import { useBoardStore } from '~/stores/board'
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
          break

        case 'agent_status_changed':
          boardStore.handleAgentStatusUpdate(message.payload as AgentStatusEvent)
          break

        case 'webhook_received':
          handleWebhookReceived(message.payload)
          break

        case 'job_update':
          emitJobUpdate((message as any).job)
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
