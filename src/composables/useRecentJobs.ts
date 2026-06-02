import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useWebSocket } from '~/composables/useWebSocket'
import type { ECCDispatchJob } from '~/types'

const DEFAULT_REFRESH_MS = 5_000
const DEFAULT_LIMIT = 5

export const useRecentJobs = (options: { refreshMs?: number; limit?: number } = {}) => {
  const boardStore = useBoardStore()
  const ws = useWebSocket()
  const refreshMs = options.refreshMs ?? DEFAULT_REFRESH_MS
  const limit = options.limit ?? DEFAULT_LIMIT

  const isLoading = computed(() => boardStore.isLoadingJobs)
  const error = ref<string | null>(null)
  const jobs = computed<ECCDispatchJob[]>(() => boardStore.recentJobs.slice(0, limit))
  const lastUpdated = ref<string | null>(null)

  let intervalHandle: ReturnType<typeof setInterval> | null = null

  const refresh = async () => {
    try {
      await boardStore.fetchJobs()
      lastUpdated.value = new Date().toISOString()
      error.value = null
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unable to refresh jobs'
    }
  }

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

  // When WS is connected, the store updates itself. Polling is
  // only a fallback for offline / reconnect windows.
  const stop = () => stopPolling()
  const start = () => {
    if (ws.isConnected.value) return
    startPolling()
  }

  // React to WS reconnects: stop polling, and on next disconnect
  // resume it.
  watch(ws.isConnected, (connected) => {
    if (connected) {
      stopPolling()
    } else {
      startPolling()
    }
  })

  onBeforeUnmount(stop)

  return {
    jobs,
    isLoading,
    error,
    lastUpdated,
    start,
    stop,
    refresh
  }
}
