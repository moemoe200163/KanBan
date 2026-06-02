<script setup lang="ts">
import type { AIAgentStatus, HarnessType } from '~/types'
import { HARNESS_CONFIGS } from '~/types'

interface Props {
  status: AIAgentStatus
  task?: string | null
  harness?: HarnessType
}

const props = withDefaults(defineProps<Props>(), {
  task: null,
  harness: 'claude-code'
})

const statusConfig = computed(() => {
  const configs = {
    idle: { label: 'AI Ready', color: 'var(--sage)', icon: '✓' },
    running: { label: 'AI Working...', color: 'var(--primary)', icon: '◐' },
    error: { label: 'AI Error', color: 'var(--clay-red)', icon: '✗' },
    paused: { label: 'AI Paused', color: 'var(--amber)', icon: '⏸' }
  }
  return configs[props.status]
})

const harnessConfig = computed(() => {
  return HARNESS_CONFIGS.find(h => h.type === props.harness) || HARNESS_CONFIGS[0]
})
</script>

<template>
  <div class="ai-status">
    <span class="ai-status__indicator" :style="{ backgroundColor: statusConfig.color }" />
    <span class="ai-status__label">{{ statusConfig.label }}</span>
    <span v-if="props.task" class="ai-status__task">{{ props.task }}</span>
    <span
      class="ai-status__harness"
      :style="{ backgroundColor: `${harnessConfig.color}15`, color: harnessConfig.color }"
      :title="harnessConfig.name"
    >
      {{ harnessConfig.name }}
    </span>
  </div>
</template>

<style scoped>
.ai-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

.ai-status__indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.ai-status__indicator:has(+ .ai-status__label:contains('Working')) {
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.ai-status__label {
  color: var(--ink);
  font-weight: 500;
}

.ai-status__task {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.ai-status__harness {
  padding: 1px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
</style>
