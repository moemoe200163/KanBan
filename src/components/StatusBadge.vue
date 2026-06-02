<script setup lang="ts">
import { COLUMN_CONFIG } from '~/types'
import type { IssueStatus } from '~/types'

interface Props {
  status: IssueStatus
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md'
})

const config = computed(() => COLUMN_CONFIG[props.status])

const statusLabel = computed(() => {
  const labels: Record<IssueStatus, string> = {
    backlog: 'Backlog',
    in_progress: 'In Progress',
    blocked: 'Blocked',
    human_review: 'Human Review',
    done: 'Done'
  }
  return labels[props.status]
})
</script>

<template>
  <span
    :class="['status-badge', `status-badge--${props.size}`]"
    :style="{
      backgroundColor: `${config.color}20`,
      color: config.color,
      borderColor: `${config.color}40`
    }"
  >
    <span class="status-badge__dot" :style="{ backgroundColor: config.color }" />
    {{ statusLabel }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-body);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border: 1px solid;
  border-radius: var(--radius-sm);
}

.status-badge--sm {
  padding: 2px var(--space-2);
  font-size: 0.625rem;
}

.status-badge--md {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
}

.status-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-badge--sm .status-badge__dot {
  width: 5px;
  height: 5px;
}
</style>