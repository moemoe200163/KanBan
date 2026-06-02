<script setup lang="ts">
/**
 * ControlPlaneStatus.vue
 * Shows current ECC harness status with visual indicator.
 * Displays harness name, status, and active job count.
 */

import { HARNESS_CONFIGS } from '~/types'
import type { HarnessType } from '~/types'

interface Props {
  harness: string
  status: 'idle' | 'running' | 'paused'
  activeJobs: number
}

const props = withDefaults(defineProps<Props>(), {
  harness: 'claude-code',
  status: 'idle',
  activeJobs: 0
})

// Get harness configuration
const harnessConfig = computed(() => {
  return HARNESS_CONFIGS.find(h => h.type === props.harness) || HARNESS_CONFIGS[0]
})

// Status indicator configuration
const statusConfig = computed(() => {
  const configs = {
    idle: {
      color: 'var(--sage)',
      label: 'Idle',
      description: 'Ready for tasks'
    },
    running: {
      color: 'var(--primary)',
      label: 'Running',
      description: 'Processing tasks'
    },
    paused: {
      color: 'var(--amber)',
      label: 'Paused',
      description: 'Temporarily stopped'
    }
  }
  return configs[props.status]
})
</script>

<template>
  <div class="control-plane-status">
    <div class="control-plane-status__header">
      <div class="control-plane-status__indicator" :style="{ backgroundColor: statusConfig.color }" />
      <span class="control-plane-status__status-label">{{ statusConfig.label }}</span>
    </div>

    <div class="control-plane-status__harness">
      <span
        class="control-plane-status__harness-badge"
        :style="{
          backgroundColor: `${harnessConfig.color}20`,
          color: harnessConfig.color,
          borderColor: `${harnessConfig.color}40`
        }"
      >
        {{ harnessConfig.name }}
      </span>
    </div>

    <div class="control-plane-status__jobs">
      <span class="control-plane-status__jobs-count">{{ activeJobs }}</span>
      <span class="control-plane-status__jobs-label">active job{{ activeJobs !== 1 ? 's' : '' }}</span>
    </div>
  </div>
</template>

<style scoped>
.control-plane-status {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--surface-dark);
  border: 1px solid rgba(122, 101, 82, 0.3);
  border-radius: var(--radius-md);
  min-width: 160px;
}

.control-plane-status__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.control-plane-status__indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.control-plane-status__status-label {
  font-family: var(--font-body);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--canvas);
}

.control-plane-status__harness {
  display: flex;
}

.control-plane-status__harness-badge {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid;
  font-size: 0.625rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.control-plane-status__jobs {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.control-plane-status__jobs-count {
  font-family: var(--font-display);
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--canvas);
  line-height: 1;
}

.control-plane-status__jobs-label {
  font-family: var(--font-body);
  font-size: 0.6875rem;
  color: var(--muted-soft);
}
</style>