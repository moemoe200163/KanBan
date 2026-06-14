/**
 * useRuntime — composable for the Agent Runtime API.
 *
 * Provides reactive state for workers, runs, and logs with polling fallback.
 * WebSocket log streaming is handled separately via useRuntimeLogStream.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

function useApiBase() {
  const config = useRuntimeConfig()
  return config.public.apiBase as string
}

function useAuthHeaders(): Record<string, string> {
  const token = useCookie('auth_token').value
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface RuntimeWorker {
  id: string
  boardId: string
  workerType: string
  harness: string | null
  status: string
  capabilities: string[]
  maxConcurrency: number
  activeRunId: string | null
  claimedAt: string | null
  startedAt: string | null
  stoppedAt: string | null
  lastHeartbeatAt: string | null
  errorMessage: string | null
  metadata: Record<string, unknown>
  createdAt: string | null
  updatedAt: string | null
}

export interface RuntimeRun {
  id: string
  workerId: string | null
  boardId: string
  issueId: string | null
  issueKey: string | null
  jobId: string | null
  status: string
  command: string | null
  profile: string | null
  harness: string | null
  provider: string | null
  model: string | null
  requiredRole: string | null
  resultSummary: string | null
  errorMessage: string | null
  metadata: Record<string, unknown>
  createdAt: string | null
  startedAt: string | null
  completedAt: string | null
}

export interface RuntimeLog {
  id: string
  runId: string
  eventType: string
  message: string | null
  metadata: Record<string, unknown>
  createdAt: string | null
}

export interface AgentRole {
  id: string
  displayName: string
}

export const useRuntime = (options: { refreshMs?: number } = {}) => {
  const refreshMs = options.refreshMs ?? 5_000
  const apiBase = useApiBase()
  const authHeaders = useAuthHeaders()

  const workers = ref<RuntimeWorker[]>([])
  const runs = ref<RuntimeRun[]>([])
  const roles = ref<AgentRole[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<string | null>(null)

  let intervalHandle: ReturnType<typeof setInterval> | null = null

  // --- Fetch functions ---

  const fetchWorkers = async () => {
    try {
      const res = await fetch(`${apiBase}/runtime/workers?board_id=board-default`, { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      workers.value = data.workers ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch workers'
    }
  }

  const fetchRuns = async (status?: string) => {
    try {
      const params = new URLSearchParams({ board_id: 'board-default', limit: '50' })
      if (status) params.set('status', status)
      const res = await fetch(`${apiBase}/runtime/runs?${params}`, { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      runs.value = data.runs ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch runs'
    }
  }

  const fetchRunsByJobId = async (jobId: string): Promise<RuntimeRun[]> => {
    try {
      const params = new URLSearchParams({ board_id: 'board-default', job_id: jobId, limit: '50' })
      const res = await fetch(`${apiBase}/runtime/runs?${params}`, { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      return data.runs ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch runs'
      return []
    }
  }

  const fetchRunLogs = async (runId: string): Promise<RuntimeLog[]> => {
    try {
      const res = await fetch(`${apiBase}/runtime/runs/${runId}/logs`, { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      return data.logs ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch logs'
      return []
    }
  }

  const fetchRoles = async () => {
    try {
      const res = await fetch(`${apiBase}/runtime/roles`, { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      roles.value = data.roles ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch roles'
    }
  }

  const refresh = async () => {
    isLoading.value = true
    await Promise.all([fetchWorkers(), fetchRuns()])
    lastUpdated.value = new Date().toISOString()
    isLoading.value = false
    error.value = null
  }

  // --- Polling ---

  const startPolling = () => {
    if (intervalHandle) return
    void refresh()
    intervalHandle = setInterval(() => { void refresh() }, refreshMs)
  }

  const stopPolling = () => {
    if (intervalHandle) {
      clearInterval(intervalHandle)
      intervalHandle = null
    }
  }

  onBeforeUnmount(stopPolling)

  return {
    workers,
    runs,
    roles,
    isLoading,
    error,
    lastUpdated,
    fetchWorkers,
    fetchRuns,
    fetchRunsByJobId,
    fetchRunLogs,
    fetchRoles,
    refresh,
    startPolling,
    stopPolling,
  }
}

/**
 * useRuntimeLogStream — WebSocket-based real-time log streaming for a run.
 *
 * Connects to /ws/runtime/runs and subscribes to a specific run_id.
 */
export const useRuntimeLogStream = () => {
  const logs = ref<RuntimeLog[]>([])
  const isConnected = ref(false)
  const subscribedRunId = ref<string | null>(null)

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECT = 5

  const connect = () => {
    if (ws && ws.readyState === WebSocket.OPEN) return

    const config = useRuntimeConfig()
    const apiBase = config.public.apiBase as string
    const token = useCookie('auth_token').value || 'dev'
    // Derive WS URL from API base: http://host:port/api/v1 → ws://host:port
    const httpBase = apiBase.replace(/\/api\/v1\/?$/, '')
    const wsProtocol = httpBase.startsWith('https') ? 'wss' : 'ws'
    const wsHost = httpBase.replace(/^https?:\/\//, '')
    const wsUrl = `${wsProtocol}://${wsHost}/ws/runtime/runs?token=${token}`
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      isConnected.value = true
      reconnectAttempts = 0
      // Re-subscribe if we had a run
      if (subscribedRunId.value) {
        subscribe(subscribedRunId.value)
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'run_log' && msg.event) {
          logs.value = [...logs.value, {
            id: msg.event.id ?? `log_${Date.now()}`,
            runId: msg.run_id,
            eventType: msg.event.eventType ?? 'log',
            message: msg.event.message ?? '',
            metadata: msg.event.metadata ?? {},
            createdAt: msg.event.createdAt ?? new Date().toISOString(),
          }]
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      isConnected.value = false
      ws = null
      if (reconnectAttempts < MAX_RECONNECT) {
        const delay = Math.min(1000 * 2 ** reconnectAttempts, 30_000)
        reconnectTimer = setTimeout(() => {
          reconnectAttempts++
          connect()
        }, delay)
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  const subscribe = (runId: string, initialLogs?: RuntimeLog[]) => {
    subscribedRunId.value = runId
    // Preserve REST pre-fetched logs; only clear if no initial logs provided
    if (initialLogs?.length) {
      logs.value = [...initialLogs]
    } else {
      logs.value = []
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'subscribe', run_id: runId }))
    }
  }

  const unsubscribe = (runId: string) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'unsubscribe', run_id: runId }))
    }
    if (subscribedRunId.value === runId) {
      subscribedRunId.value = null
    }
  }

  const disconnect = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected.value = false
    subscribedRunId.value = null
  }

  onBeforeUnmount(disconnect)

  return {
    logs,
    isConnected,
    subscribedRunId,
    connect,
    subscribe,
    unsubscribe,
    disconnect,
  }
}
