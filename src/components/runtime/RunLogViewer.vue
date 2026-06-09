<script setup lang="ts">
/**
 * RunLogViewer — real-time log viewer for a selected run.
 *
 * Uses useRuntimeLogStream for WebSocket-based streaming.
 * Falls back to REST polling when WS is disconnected.
 */
import { ArrowDown, Circle, Wifi, WifiOff } from 'lucide-vue-next'
import { useRuntimeLogStream, type RuntimeLog } from '~/composables/useRuntime'

const props = defineProps<{
  runId: string | null
  /** Pre-fetched logs from REST (used as initial content) */
  initialLogs?: RuntimeLog[]
}>()

const { logs, isConnected, connect, subscribe, unsubscribe } = useRuntimeLogStream()

const autoScroll = ref(true)
const logContainer = ref<HTMLElement | null>(null)

// Initialize on mount
onMounted(() => {
  connect()
})

// Watch for runId changes
watch(() => props.runId, (newRunId, oldRunId) => {
  if (oldRunId) unsubscribe(oldRunId)
  if (newRunId) {
    subscribe(newRunId, props.initialLogs)
  }
}, { immediate: true })

// Auto-scroll to bottom when new logs arrive
watch(logs, () => {
  if (autoScroll.value && logContainer.value) {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
}, { deep: true })

const onScroll = () => {
  if (!logContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  autoScroll.value = scrollHeight - scrollTop - clientHeight < 50
}

const logLevel = (log: RuntimeLog): string => {
  const level = log.metadata?.level
  return typeof level === 'string' ? level : 'info'
}

const logLevelColor = (level: string): string => {
  switch (level) {
    case 'error': return 'var(--clay-red)'
    case 'warn': return 'var(--amber)'
    case 'debug': return 'var(--muted)'
    default: return 'var(--sage)'
  }
}

const formatTime = (iso: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onBeforeUnmount(() => {
  if (props.runId) unsubscribe(props.runId)
})
</script>

<template>
  <div class="log-viewer">
    <div class="log-viewer__header">
      <span class="log-viewer__title" v-if="runId">
        Logs — {{ runId.slice(0, 16) }}...
      </span>
      <span class="log-viewer__title log-viewer__title--empty" v-else>
        Select a run to view logs
      </span>
      <div class="log-viewer__status">
        <component
          :is="isConnected ? Wifi : WifiOff"
          :size="14"
          :style="{ color: isConnected ? 'var(--sage)' : 'var(--clay-red)' }"
        />
        <span class="log-viewer__count">{{ logs.length }} lines</span>
      </div>
    </div>

    <div
      ref="logContainer"
      class="log-viewer__body"
      @scroll="onScroll"
    >
      <div v-if="!logs.length && !runId" class="log-viewer__empty">
        Choose a run from the list to stream its logs in real-time.
      </div>
      <div v-else-if="!logs.length" class="log-viewer__empty">
        Waiting for log output...
      </div>
      <div
        v-for="log in logs"
        :key="log.id"
      >
        <div
          v-if="log.eventType === 'tool_call_completed' || log.eventType === 'tool_call_failed'"
          class="run-log__tool-card"
          :class="log.eventType === 'tool_call_failed' ? 'run-log__tool-card--failed' : ''"
        >
          <span class="run-log__tool-icon">🔧</span>
          <span class="run-log__tool-name">{{ (log.metadata as Record<string, unknown>)?.tool_name || 'tool' }}</span>
          <span class="run-log__tool-actor">{{ (log.metadata as Record<string, unknown>)?.actor || '' }}</span>
          <span
            class="run-log__tool-status"
            :class="log.eventType === 'tool_call_completed' ? 'text-green-500' : 'text-red-500'"
          >
            {{ log.eventType === 'tool_call_completed' ? 'OK' : 'FAILED' }}
          </span>
        </div>
        <div v-else class="log-viewer__line">
          <span class="log-viewer__time">{{ formatTime(log.createdAt) }}</span>
          <span
            class="log-viewer__level"
            :style="{ color: logLevelColor(logLevel(log)) }"
          >
            {{ logLevel(log).toUpperCase().padEnd(5) }}
          </span>
          <span class="log-viewer__message">{{ log.message }}</span>
        </div>
      </div>
    </div>

    <button
      v-if="!autoScroll"
      class="log-viewer__scroll-btn"
      @click="autoScroll = true; logContainer?.scrollTo({ top: logContainer.scrollHeight })"
    >
      <ArrowDown :size="14" />
      Scroll to bottom
    </button>
  </div>
</template>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  background: var(--surface-dark);
  border-radius: var(--radius-lg);
  overflow: hidden;
  height: 100%;
  min-height: 200px;
}

.log-viewer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--sidebar-border);
}

.log-viewer__title {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--on-dark-soft);
}

.log-viewer__title--empty {
  color: var(--sidebar-subtle);
}

.log-viewer__status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.log-viewer__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--sidebar-subtle);
}

.log-viewer__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}

.log-viewer__empty {
  color: var(--sidebar-subtle);
  font-style: italic;
  text-align: center;
  padding: var(--space-8) 0;
}

.log-viewer__line {
  display: flex;
  gap: var(--space-3);
  white-space: pre-wrap;
  word-break: break-all;
}

.log-viewer__time {
  color: var(--sidebar-subtle);
  flex-shrink: 0;
}

.log-viewer__level {
  flex-shrink: 0;
  font-weight: 500;
}

.log-viewer__message {
  color: var(--on-dark);
}

.log-viewer__scroll-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--primary);
  color: var(--on-primary);
  border: none;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.log-viewer__scroll-btn:hover {
  background: var(--primary-hover);
}

.run-log__tool-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin: 4px 0;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  font-size: 0.8rem;
}

.run-log__tool-card--failed {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.2);
}

.run-log__tool-name {
  font-weight: 700;
  color: var(--ink);
}

.run-log__tool-actor {
  color: var(--muted);
}
</style>
