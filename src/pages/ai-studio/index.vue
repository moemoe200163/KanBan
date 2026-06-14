<script setup lang="ts">
/**
 * /ai-studio — Plan I main chat page.
 *
 * Phase 1 (I-MVP-2) scope:
 *  - Empty chat on first visit (no conversation yet)
 *  - User types a message → store creates a conversation →
 *    SSE stream → message bubbles render with a blinking caret
 *  - Provider/model picker at the top right; selection is
 *    persisted in localStorage and used for the next new
 *    conversation
 *  - Escape aborts the in-flight stream
 *
 * Out of scope for I-MVP-2 (landed with I-MVP-3):
 *  - Conversation history sidebar (Phase 2)
 *  - Deep-link to a specific conversation id
 */

import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { MessageSquare, Plus, Sparkles, Trash2 } from 'lucide-vue-next'
import ChatMessage from '~/components/ai-studio/ChatMessage.vue'
import ChatInput from '~/components/ai-studio/ChatInput.vue'
import ProviderSelector from '~/components/ai-studio/ProviderSelector.vue'
import { useAIStudio } from '~/composables/useAIStudio'
import { useAIStudioStore } from '~/stores/aiStudio'
import { useAuth } from '~/composables/useAuth'

const { sendMessage, cancelStream, ensureConversation } = useAIStudio()
const store = useAIStudioStore()
const { isAuthenticated, authChecked, fetchRole } = useAuth()

// We want the page to feel "alive" on the very first visit —
// kicking off a conversation as soon as the user clicks into
// the page means the first message only has to wait for the
// model, not for the conversation row to be created.
onMounted(async () => {
  // Make sure /me is current. In dev mode this seeds the
  // leader admin user so the backend lets the page through.
  if (!authChecked.value) await fetchRole()
  // Pre-create the conversation lazily on first send; the
  // page deliberately does not create one on mount so an
  // empty visit doesn't litter the sidebar with empty rows.
})

const messagesScroller = ref<HTMLElement | null>(null)
const showEmptyHint = computed(() => store.messages.length === 0 && !store.isStreaming)

// Auto-scroll to the bottom whenever the streaming buffer
// or the message list grows. The watcher uses
// ``requestAnimationFrame`` because the next-tick timing is
// too tight for a fresh ``<ChatMessage>`` to have measured its
// own height — the scrollTop lands a few pixels short
// otherwise.
watch(
  () => [store.messages.length, store.streaming.content.length, store.isStreaming],
  () => {
    if (typeof window === 'undefined') return
    requestAnimationFrame(() => {
      const el = messagesScroller.value
      if (!el) return
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
  },
)

async function onSend(content: string) {
  if (!isAuthenticated.value) {
    // The header already shows a "Sign in" CTA in the
    // unauthenticated state; we still surface a soft
    // message so the user knows why the click was a no-op.
    store.setStreamError('Please sign in to chat with AI Studio.')
    return
  }
  await sendMessage(content)
}

async function onAbort() {
  await cancelStream()
}

async function startNewChat() {
  store.clearConversation()
  // Don't create the row yet — wait for the first message
  // to keep the conversation history clean.
  void nextTick()
}

const isStreaming = computed(() => store.isStreaming)
</script>

<template>
  <section class="ai-studio">
    <header class="ai-studio__topbar">
      <div class="ai-studio__title">
        <Sparkles :size="20" class="ai-studio__title-icon" />
        <div>
          <h1>AI Studio</h1>
          <p>Chat with your LLM providers — streaming, with thinking &amp; tool call support (Phase 2)</p>
        </div>
      </div>
      <div class="ai-studio__controls">
        <ProviderSelector />
        <button
          type="button"
          class="ai-studio__new"
          data-testid="ai-studio-new-chat"
          title="Start a new conversation"
          @click="startNewChat"
        >
          <Plus :size="14" />
          <span>New chat</span>
        </button>
      </div>
    </header>

    <div class="ai-studio__chat">
      <div ref="messagesScroller" class="ai-studio__messages" data-testid="ai-studio-messages">
        <div v-if="showEmptyHint" class="ai-studio__empty">
          <MessageSquare :size="28" />
          <h2>Start a new conversation</h2>
          <p>
            Type a prompt below and press <kbd>Enter</kbd>. Pick a provider on the right
            to switch models between turns.
          </p>
          <ul class="ai-studio__empty-tips">
            <li><strong>Enter</strong> — send</li>
            <li><strong>Shift + Enter</strong> — newline</li>
            <li><strong>Esc</strong> — stop generating</li>
          </ul>
        </div>
        <template v-else>
          <ChatMessage
            v-for="m in store.messages"
            :key="m.id"
            :message="m"
          />
          <!--
            Live streaming bubble: rendered separately from the
            store's persisted message list so the user sees the
            text appear token-by-token, and so ``endStream()``
            can promote the live buffer into a real persisted
            row when ``message_end`` fires.
          -->
          <ChatMessage
            v-if="store.isStreaming || store.streaming.content"
            :key="`stream-${store.currentConversation?.id ?? 'none'}`"
            :message="{
              id: store.streaming.messageId ?? 'streaming',
              conversationId: store.currentConversation?.id ?? '',
              type: 'assistant',
              content: store.streaming.content,
              timestamp: new Date().toISOString(),
            }"
            is-streaming
          />
          <div v-if="store.streamingError" class="ai-studio__error" data-testid="ai-studio-error">
            <strong>Error:</strong>
            <span>{{ store.streamingError }}</span>
            <button
              type="button"
              class="ai-studio__error-dismiss"
              data-testid="ai-studio-error-dismiss"
              title="Dismiss"
              @click="store.setStreamError(null)"
            >
              <Trash2 :size="12" />
            </button>
          </div>
        </template>
      </div>

      <div class="ai-studio__composer">
        <ChatInput
          :disabled="!isAuthenticated"
          :is-streaming="isStreaming"
          @send="onSend"
          @abort="onAbort"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-studio {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--canvas);
}

.ai-studio__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  background: var(--surface-card);
  border-bottom: 1px solid var(--hairline);
}

.ai-studio__title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.ai-studio__title-icon {
  color: var(--primary);
  flex-shrink: 0;
}
.ai-studio__title h1 {
  margin: 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.125rem;
  font-weight: 600;
  line-height: 1.2;
}
.ai-studio__title p {
  margin: 0;
  color: var(--muted);
  font-size: 0.8125rem;
}

.ai-studio__controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ai-studio__new {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-family: var(--font-body);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}
.ai-studio__new:hover {
  background: var(--surface-soft);
  border-color: var(--primary);
}

.ai-studio__chat {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 16px 24px 20px;
  gap: 14px;
}

.ai-studio__messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ai-studio__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  min-height: 280px;
  color: var(--muted);
  text-align: center;
}
.ai-studio__empty h2 {
  margin: 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.125rem;
  font-weight: 600;
}
.ai-studio__empty p {
  max-width: 480px;
  margin: 0;
  font-size: 0.9375rem;
  line-height: 1.5;
}
.ai-studio__empty kbd {
  padding: 1px 6px;
  color: var(--ink);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
.ai-studio__empty-tips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px 14px;
  margin: 8px 0 0 0;
  padding: 0;
  list-style: none;
  color: var(--muted);
  font-size: 0.8125rem;
}
.ai-studio__empty-tips strong {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.ai-studio__error {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  max-width: 100%;
  padding: 8px 10px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid var(--clay-red-muted);
  border-radius: 8px;
  font-size: 0.8125rem;
}
.ai-studio__error strong {
  color: var(--clay-red-muted);
  font-weight: 600;
}
.ai-studio__error-dismiss {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  color: var(--clay-red-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  margin-left: auto;
  flex-shrink: 0;
}
.ai-studio__error-dismiss:hover {
  background: rgba(184, 92, 77, 0.16);
  border-color: var(--clay-red-muted);
}

.ai-studio__composer {
  flex-shrink: 0;
}

@media (max-width: 720px) {
  .ai-studio__topbar {
    flex-direction: column;
    align-items: stretch;
  }
  .ai-studio__controls {
    justify-content: flex-start;
  }
}
</style>
