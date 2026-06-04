<script setup lang="ts">
/**
 * WorkerCard — displays a single agent worker's status and metadata.
 */
import { Bot, Circle, Clock, Zap } from 'lucide-vue-next'
import type { RuntimeWorker } from '~/composables/useRuntime'

const props = defineProps<{ worker: RuntimeWorker }>()

const statusColor = computed(() => {
  switch (props.worker.status) {
    case 'idle': return 'var(--sage)'
    case 'claimed': return 'var(--amber)'
    case 'running': return 'var(--dusty-blue)'
    case 'stopped':
    case 'error': return 'var(--clay-red)'
    default: return 'var(--muted)'
  }
})

const statusLabel = computed(() => {
  return props.worker.status.charAt(0).toUpperCase() + props.worker.status.slice(1)
})

const timeSinceHeartbeat = computed(() => {
  if (!props.worker.lastHeartbeatAt) return 'never'
  const diff = Date.now() - new Date(props.worker.lastHeartbeatAt).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
})

const roleTags = computed(() => {
  return (props.worker.capabilities ?? []).map(c => ({
    id: c,
    label: c.replace(/-/g, ' '),
  }))
})
</script>

<template>
  <div class="worker-card">
    <div class="worker-card__header">
      <div class="worker-card__icon">
        <Bot :size="18" />
      </div>
      <div class="worker-card__info">
        <span class="worker-card__id">{{ worker.id }}</span>
        <span class="worker-card__type">{{ worker.workerType }}</span>
      </div>
      <div class="worker-card__status" :style="{ '--status-color': statusColor }">
        <Circle :size="8" fill="currentColor" />
        <span>{{ statusLabel }}</span>
      </div>
    </div>

    <div class="worker-card__meta">
      <div class="worker-card__meta-item" v-if="worker.activeRunId">
        <Zap :size="12" />
        <span>Run: {{ worker.activeRunId.slice(0, 12) }}...</span>
      </div>
      <div class="worker-card__meta-item">
        <Clock :size="12" />
        <span>Heartbeat: {{ timeSinceHeartbeat }}</span>
      </div>
    </div>

    <div class="worker-card__roles" v-if="roleTags.length">
      <span
        v-for="role in roleTags"
        :key="role.id"
        class="worker-card__role-tag"
      >
        {{ role.label }}
      </span>
    </div>

    <div class="worker-card__error" v-if="worker.errorMessage">
      {{ worker.errorMessage }}
    </div>
  </div>
</template>

<style scoped>
.worker-card {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  transition: border-color 0.15s ease;
}

.worker-card:hover {
  border-color: var(--primary);
}

.worker-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.worker-card__icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  flex-shrink: 0;
}

.worker-card__info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.worker-card__id {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.worker-card__type {
  font-size: 12px;
  color: var(--muted);
}

.worker-card__status {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 12px;
  font-weight: 500;
  color: var(--status-color, var(--muted));
  white-space: nowrap;
}

.worker-card__meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.worker-card__meta-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 12px;
  color: var(--muted);
}

.worker-card__roles {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.worker-card__role-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  color: var(--muted);
  text-transform: capitalize;
}

.worker-card__error {
  font-size: 12px;
  color: var(--clay-red);
  padding: var(--space-2);
  background: rgba(184, 92, 77, 0.08);
  border-radius: var(--radius-sm);
}
</style>
