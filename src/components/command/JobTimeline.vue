<script setup lang="ts">
import { computed } from 'vue'
import type { ECCJobEvent, ECCJobStatus } from '~/types'
import { CheckCircle2, Clock, Eye, Loader2, XCircle, AlertCircle, Square } from 'lucide-vue-next'

const props = defineProps<{ events: ECCJobEvent[] }>()

const ordered = computed(() =>
  [...props.events].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
)

const icon = (status: ECCJobStatus) => {
  switch (status) {
    case 'queued': return Clock
    case 'running': return Loader2
    case 'review_required': return Eye
    case 'completed': return CheckCircle2
    case 'failed': return XCircle
    case 'cancelled': return Square
    case 'paused': return AlertCircle
    default: return Clock
  }
}
const color = (status: ECCJobStatus) => {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'queued': return 'var(--amber)'
    case 'review_required': return 'var(--dusty-blue)'
    case 'completed': return 'var(--sage)'
    case 'failed': return 'var(--clay-red)'
    case 'cancelled': return 'var(--muted)'
    case 'paused': return 'var(--amber)'
    default: return 'var(--muted)'
  }
}
const fmt = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <ol class="timeline" data-testid="job-timeline">
    <li
      v-for="(ev, i) in ordered"
      :key="`${ev.timestamp}_${i}`"
      class="timeline__item"
    >
      <span
        class="timeline__dot"
        :style="{ background: color(ev.status) }"
      >
        <component
          :is="icon(ev.status)"
          :size="10"
          :class="{ spin: ev.status === 'running' }"
        />
      </span>
      <div class="timeline__body">
        <div class="timeline__head">
          <span class="timeline__status" :style="{ color: color(ev.status) }">
            {{ ev.status }}
          </span>
          <span class="timeline__time">{{ fmt(ev.timestamp) }}</span>
        </div>
        <p class="timeline__msg">{{ ev.message }}</p>
      </div>
    </li>
    <li v-if="!ordered.length" class="timeline__empty">
      No events yet
    </li>
  </ol>
</template>

<style scoped>
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.timeline__item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 10px;
  padding: 8px 0;
  position: relative;
}
.timeline__item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 28px;
  bottom: -2px;
  width: 2px;
  background: var(--hairline);
}
.timeline__dot {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: var(--on-primary);
  flex-shrink: 0;
  z-index: 1;
}
.timeline__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.timeline__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.timeline__status {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
}
.timeline__time {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}
.timeline__msg {
  margin: 0;
  color: var(--ink);
  font-size: 0.8125rem;
  line-height: 1.4;
  word-break: break-word;
}
.timeline__empty {
  color: var(--muted);
  padding: 12px 0;
  font-size: 0.8125rem;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
