<script setup lang="ts">
import { useToast } from '~/composables/useToast'

const { toasts, remove } = useToast()

const handleUndo = (toast: { undoAction?: () => void; id: string }) => {
  if (toast.undoAction) {
    toast.undoAction()
  }
  remove(toast.id)
}
</script>

<template>
  <div class="toast-container" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast"
      >
        <span class="toast__message">{{ toast.message }}</span>
        <button
          v-if="toast.undoAction"
          class="toast__undo"
          @click="handleUndo(toast)"
        >
          {{ toast.undoLabel ?? 'Undo' }}
        </button>
        <button
          class="toast__close"
          aria-label="Dismiss"
          @click="remove(toast.id)"
        >
          ×
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  font-size: 0.8125rem;
  color: var(--ink);
  pointer-events: all;
  min-width: 240px;
  max-width: 360px;
}

.toast__message {
  flex: 1;
}

.toast__undo {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s;
}

.toast__undo:hover {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
}

.toast__close {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 1.1rem;
  cursor: pointer;
  padding: 2px 4px;
  line-height: 1;
  transition: color 0.15s;
}

.toast__close:hover {
  color: var(--ink);
}

/* Transitions */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>