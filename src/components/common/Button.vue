<script setup lang="ts">
interface Props {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'md',
  disabled: false,
  loading: false
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

const handleClick = (e: MouseEvent) => {
  if (!props.disabled && !props.loading) {
    emit('click', e)
  }
}
</script>

<template>
  <button
    :class="[
      'btn',
      `btn--${props.variant}`,
      `btn--${props.size}`,
      { 'btn--disabled': props.disabled, 'btn--loading': props.loading }
    ]"
    :disabled="props.disabled || props.loading"
    @click="handleClick"
  >
    <span v-if="props.loading" class="btn__spinner" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: var(--font-body);
  font-weight: 500;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* Sizes */
.btn--sm {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
}

.btn--md {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-base);
}

.btn--lg {
  padding: var(--space-3) var(--space-6);
  font-size: var(--text-lg);
}

/* Variants */
.btn--primary {
  background: var(--primary);
  color: var(--on-primary);
  border-color: var(--primary);
}

.btn--primary:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

.btn--primary:active:not(:disabled) {
  background: var(--primary-active);
  border-color: var(--primary-active);
}

.btn--secondary {
  background: var(--canvas);
  color: var(--ink);
  border-color: var(--hairline);
}

.btn--secondary:hover:not(:disabled) {
  background: var(--surface-soft);
  border-color: var(--muted-soft);
}

.btn--secondary:active:not(:disabled) {
  background: var(--surface-card);
}

.btn--ghost {
  background: transparent;
  color: var(--muted);
  border-color: transparent;
}

.btn--ghost:hover:not(:disabled) {
  background: var(--surface-soft);
  color: var(--ink);
}

.btn--danger {
  background: var(--clay-red);
  color: var(--on-primary);
  border-color: var(--clay-red);
}

.btn--danger:hover:not(:disabled) {
  background: var(--clay-red-muted);
  border-color: var(--clay-red-muted);
}

/* States */
.btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--loading {
  position: relative;
  color: transparent;
}

.btn__spinner {
  position: absolute;
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
