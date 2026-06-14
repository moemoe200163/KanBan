<script setup lang="ts">
/**
 * ChatInput — text input + Send button.
 *
 * Behaviour (per the I-MVP-2 spec):
 *   - Enter sends, Shift+Enter inserts a newline.
 *   - Send is disabled when the input is empty or the parent
 *     is mid-stream (``disabled`` prop).
 *   - After send, the textarea clears and focus is restored
 *     so the user can keep typing without re-clicking.
 *   - Escape aborts the in-flight stream (``onAbort``). The
 *     parent owns the AbortController; this component just
 *     fires the event.
 */

import { ref, watch } from 'vue'
import { Send, Square } from 'lucide-vue-next'

interface Props {
  disabled?: boolean
  // Show the abort button (the square) instead of Send. The
  // page toggles this based on ``store.isStreaming``.
  isStreaming?: boolean
  placeholder?: string
}
const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  isStreaming: false,
  placeholder: 'Ask AI Studio…  (Enter to send, Shift+Enter for newline, Esc to stop)',
})

const emit = defineEmits<{
  send: [content: string]
  abort: []
}>()

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  // Reset so ``scrollHeight`` reflects the new content rather
  // than carrying the previous height forward.
  el.style.height = 'auto'
  // Cap at 8 lines so the input never crowds the chat.
  const maxHeight = 8 * 24
  el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
}

// Keep the textarea at a reasonable height as content
// changes (e.g. when the parent clears it after a send).
watch(text, () => {
  autoResize()
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.isStreaming) {
    e.preventDefault()
    emit('abort')
    return
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function submit() {
  if (props.disabled) return
  const value = text.value.trim()
  if (!value) return
  emit('send', value)
  text.value = ''
  // Restore focus so the user can fire off the next message
  // without reaching for the mouse.
  nextTick(() => textareaRef.value?.focus())
}

function onSendClick() {
  submit()
}

function onAbortClick() {
  emit('abort')
}

defineExpose({
  focus: () => textareaRef.value?.focus(),
})
</script>

<template>
  <div class="ci" :class="{ 'ci--streaming': isStreaming }">
    <textarea
      ref="textareaRef"
      v-model="text"
      class="ci__input"
      rows="1"
      :placeholder="placeholder"
      :disabled="disabled && !isStreaming"
      data-testid="ai-studio-input"
      @keydown="onKeydown"
    />
    <div class="ci__actions">
      <button
        v-if="isStreaming"
        type="button"
        class="ci__btn ci__btn--abort"
        data-testid="ai-studio-abort"
        title="Stop generating (Esc)"
        @click="onAbortClick"
      >
        <Square :size="14" />
        <span>Stop</span>
      </button>
      <button
        v-else
        type="button"
        class="ci__btn ci__btn--send"
        :disabled="!text.trim() || disabled"
        data-testid="ai-studio-send"
        title="Send (Enter)"
        @click="onSendClick"
      >
        <Send :size="14" />
        <span>Send</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.ci {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: end;
  padding: 12px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  box-shadow: 0 1px 0 var(--hairline-soft);
}
.ci--streaming {
  border-color: var(--primary);
}

.ci__input {
  resize: none;
  width: 100%;
  min-height: 24px;
  max-height: 192px;
  padding: 6px 4px;
  color: var(--ink);
  background: transparent;
  border: none;
  outline: none;
  font-family: var(--font-body);
  font-size: 0.9375rem;
  line-height: 1.5;
}
.ci__input::placeholder {
  color: var(--muted-soft);
}
.ci__input:disabled {
  color: var(--muted);
  cursor: not-allowed;
}

.ci__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ci__btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 8px;
  font-family: var(--font-display);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.ci__btn:hover:not(:disabled) {
  background: var(--primary-hover);
}
.ci__btn:disabled {
  color: var(--muted-soft);
  background: var(--surface-soft);
  border-color: var(--hairline);
  cursor: not-allowed;
}

.ci__btn--abort {
  color: var(--on-primary);
  background: var(--clay-red);
  border-color: var(--clay-red);
}
.ci__btn--abort:hover {
  background: var(--clay-red-muted);
}
</style>
