<script setup lang="ts">
import { PRIORITY_CONFIG } from '~/types'
import type { Priority } from '~/types'

interface Props {
  priority: Priority
  showLabel?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showLabel: false
})

const config = computed(() => PRIORITY_CONFIG[props.priority])

const priorityIcons: Record<Priority, string> = {
  critical: '🔥',
  high: '▲▲',
  medium: '▬',
  low: '▼'
}
</script>

<template>
  <span class="priority-indicator" :title="config.label">
    <svg
      v-if="props.priority === 'critical'"
      class="priority-icon priority-icon--critical"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M12 2C8 6 4 10 4 14a8 8 0 0016 0c0-4-4-8-8-12z" />
    </svg>
    <svg
      v-else-if="props.priority === 'high'"
      class="priority-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
    <svg
      v-else-if="props.priority === 'medium'"
      class="priority-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M5 12h14" />
    </svg>
    <svg
      v-else
      class="priority-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M12 5v14M5 12l7 7 7-7" />
    </svg>
    <span v-if="props.showLabel" class="priority-label">{{ config.label }}</span>
  </span>
</template>

<style scoped>
.priority-indicator {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.priority-icon {
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
}

.priority-icon--critical {
  color: var(--clay-red);
}

.priority-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
</style>