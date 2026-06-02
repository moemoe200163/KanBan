<script setup lang="ts">
/**
 * MetricsRow.vue
 * A row component that displays a metric with label, value, and trend indicator.
 * Styled with warm editorial dark design language.
 */

interface Props {
  label: string
  value: string | number
  trend: 'up' | 'down' | 'neutral'
  trendValue: string
}

const props = withDefaults(defineProps<Props>(), {
  trend: 'neutral',
  trendValue: ''
})

// Trend indicator configuration
const trendConfig = computed(() => {
  const configs = {
    up: {
      color: 'var(--sage)',
      icon: '↑',
      label: 'Increasing'
    },
    down: {
      color: 'var(--clay-red)',
      icon: '↓',
      label: 'Decreasing'
    },
    neutral: {
      color: 'var(--muted-soft)',
      icon: '→',
      label: 'No change'
    }
  }
  return configs[props.trend]
})
</script>

<template>
  <div class="metrics-row">
    <div class="metrics-row__content">
      <span class="metrics-row__label">{{ label }}</span>
      <span class="metrics-row__value">{{ value }}</span>
    </div>
    <div class="metrics-row__trend" :style="{ color: trendConfig.color }">
      <span class="metrics-row__trend-icon">{{ trendConfig.icon }}</span>
      <span class="metrics-row__trend-value">{{ trendValue }}</span>
    </div>
  </div>
</template>

<style scoped>
.metrics-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--surface-dark);
  border: 1px solid rgba(122, 101, 82, 0.3);
  border-radius: var(--radius-md);
  transition: border-color 200ms ease;
}

.metrics-row:hover {
  border-color: rgba(122, 101, 82, 0.5);
}

.metrics-row__content {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.metrics-row__label {
  font-family: var(--font-body);
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted-soft);
}

.metrics-row__value {
  font-family: var(--font-display);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--canvas);
  line-height: 1.2;
}

.metrics-row__trend {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
}

.metrics-row__trend-icon {
  font-size: 0.875rem;
  font-weight: 700;
}

.metrics-row__trend-value {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 500;
}
</style>