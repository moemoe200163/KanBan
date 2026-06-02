<script setup lang="ts">
import type { Label } from '~/types'

interface Props {
  label: Label
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md'
})
</script>

<template>
  <span
    :class="['label-chip', `label-chip--${props.size}`]"
    :style="{
      backgroundColor: `${props.label.color}20`,
      color: props.label.color,
      borderColor: `${props.label.color}40`
    }"
  >
    {{ props.label.name }}
  </span>
</template>

<style scoped>
.label-chip {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-body);
  font-weight: 500;
  border: 1px solid;
  border-radius: var(--radius-sm);
}

.label-chip--sm {
  padding: 1px var(--space-2);
  font-size: 0.625rem;
}

.label-chip--md {
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
}
</style>