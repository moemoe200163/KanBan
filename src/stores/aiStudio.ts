/**
 * aiStudio — Pinia store for the AI Studio chat experience.
 *
 * Owns:
 *  - The currently-open conversation (``currentConversation``).
 *  - The message list for that conversation.
 *  - The streaming state (``isStreaming``, ``streamingContent``,
 *    ``streamingError``, ``abortController``).
 *  - The provider/model the user picked for *new* conversations
 *    (``selectedProviderId``, ``selectedModel``). Persisted in
 *    localStorage so a refresh keeps the choice.
 *
 * The store deliberately does NOT own the HTTP layer — that lives
 * in ``composables/useAIStudio.ts`` so the store stays testable
 * and the composable can wrap fetch with the right headers.
 */

import { defineStore } from 'pinia'
import { authHeaders } from '~/utils/authHeaders'

function useApiBase() {
  return useRuntimeConfig().public.apiBase as string
}

export type MessageType = 'user' | 'assistant' | 'thinking' | 'tool_call' | 'tool_result'

export interface ChatMessage {
  id: string
  conversationId: string
  type: MessageType
  content: string
  toolName?: string | null
  toolArgs?: Record<string, unknown> | null
  toolResult?: string | null
  agentRole?: string | null
  timestamp: string
}

export interface AIStudioConversation {
  id: string
  title: string
  userId: string
  providerId: string
  model: string | null
  createdAt: string
  updatedAt: string
}

const SELECTED_PROVIDER_KEY = 'aistudio:selectedProviderId'
const SELECTED_MODEL_KEY = 'aistudio:selectedModel'

function readLocalStorage(key: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeLocalStorage(key: string, value: string | null): void {
  if (typeof window === 'undefined') return
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // localStorage unavailable — swallow. The provider will
    // still be selectable for the current session, just not
    // remembered across reloads.
  }
}

export interface AIStudioState {
  currentConversation: AIStudioConversation | null
  messages: ChatMessage[]
  // The in-progress assistant turn. The store keeps a
  // **separate** entry from ``messages`` so a page refresh
  // mid-stream can't lose the already-streamed tokens —
  // but for Phase 1 we only persist on ``message_end``, so
  // the live buffer lives here until the backend confirms.
  streaming: {
    messageId: string | null
    content: string
    isStreaming: boolean
    error: string | null
    abortController: AbortController | null
  }
  selectedProviderId: string | null
  selectedModel: string | null
  isLoadingConversation: boolean
  loadError: string | null
}

export const useAIStudioStore = defineStore('aiStudio', {
  state: (): AIStudioState => ({
    currentConversation: null,
    messages: [],
    streaming: {
      messageId: null,
      content: '',
      isStreaming: false,
      error: null,
      abortController: null,
    },
    selectedProviderId: readLocalStorage(SELECTED_PROVIDER_KEY),
    selectedModel: readLocalStorage(SELECTED_MODEL_KEY),
    isLoadingConversation: false,
    loadError: null,
  }),

  getters: {
    /** True if there is an assistant turn in progress. */
    isStreaming: (state) => state.streaming.isStreaming,
    /** The most-recent user message — used to echo the prompt
     *  next to the streaming reply for a familiar chat feel. */
    lastUserMessage: (state) => {
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        if (state.messages[i].type === 'user') return state.messages[i]
      }
      return null
    },
    /** The full assistant text for the active turn, including
     *  whatever is still streaming. The page binds its input
     *  disabled state to ``isStreaming`` and renders the
     *  reply block from this getter. */
    streamingReply: (state) => state.streaming.content,
    streamingError: (state) => state.streaming.error,
  },

  actions: {
    // ── Selection (provider / model) ──────────────────────────────
    setSelectedProvider(providerId: string | null) {
      this.selectedProviderId = providerId
      writeLocalStorage(SELECTED_PROVIDER_KEY, providerId)
    },
    setSelectedModel(model: string | null) {
      this.selectedModel = model
      writeLocalStorage(SELECTED_MODEL_KEY, model)
    },

    // ── Conversation lifecycle ────────────────────────────────────
    /**
     * Create a brand-new conversation on the backend and adopt it
     * as the active one. Returns the new conversation id so the
     * caller can navigate to ``/ai-studio/c/<id>`` if it wants to
     * deep-link immediately.
     */
    async createConversation(title: string = 'New chat'): Promise<string | null> {
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/ai-studio/conversations`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders(),
          },
          body: JSON.stringify({
            title,
            provider_id: this.selectedProviderId,
            model: this.selectedModel,
          }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const conv: AIStudioConversation = await res.json()
        // Normalise snake_case from the wire to camelCase.
        this.currentConversation = {
          ...conv,
          userId: (conv as any).userId ?? (conv as any).user_id,
          providerId: (conv as any).providerId ?? (conv as any).provider_id,
        }
        this.messages = []
        this.streaming = {
          messageId: null,
          content: '',
          isStreaming: false,
          error: null,
          abortController: null,
        }
        this.loadError = null
        return this.currentConversation.id
      } catch (e: any) {
        this.loadError = e?.message || 'Failed to create conversation'
        return null
      }
    },

    /**
     * Hydrate the active conversation + its message history from
     * the backend. Used when the page mounts with no in-flight
     * stream and when the user picks a past conversation from
     * the history sidebar (Phase 1 sidebar lands with I-MVP-3).
     */
    async loadConversation(conversationId: string): Promise<boolean> {
      this.isLoadingConversation = true
      this.loadError = null
      try {
        const apiBase = useApiBase()
        const res = await fetch(
          `${apiBase}/ai-studio/conversations/${conversationId}`,
          { headers: authHeaders() },
        )
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const conv: any = await res.json()
        this.currentConversation = {
          id: conv.id,
          title: conv.title,
          userId: conv.userId ?? conv.user_id,
          providerId: conv.providerId ?? conv.provider_id,
          model: conv.model ?? null,
          createdAt: conv.createdAt ?? conv.created_at ?? '',
          updatedAt: conv.updatedAt ?? conv.updated_at ?? '',
        }
        this.messages = (conv.messages ?? []).map((m: any) => ({
          id: m.id,
          conversationId: m.conversationId ?? m.conversation_id,
          type: m.type as MessageType,
          content: m.content ?? '',
          toolName: m.toolName ?? m.tool_name ?? null,
          toolArgs: m.toolArgs ?? m.tool_args ?? null,
          toolResult: m.toolResult ?? m.tool_result ?? null,
          agentRole: m.agentRole ?? m.agent_role ?? null,
          timestamp: m.timestamp ?? '',
        }))
        return true
      } catch (e: any) {
        this.loadError = e?.message || 'Failed to load conversation'
        return false
      } finally {
        this.isLoadingConversation = false
      }
    },

    /**
     * Reset the store to the empty state. Used when the user
     * clicks "New chat" without persisting, or when the page
     * is torn down.
     */
    clearConversation() {
      this.abortStream()
      this.currentConversation = null
      this.messages = []
      this.streaming = {
        messageId: null,
        content: '',
        isStreaming: false,
        error: null,
        abortController: null,
      }
      this.loadError = null
    },

    // ── Streaming ─────────────────────────────────────────────────
    /**
     * Abort the in-flight stream, if any. Safe to call when
     * nothing is streaming — it's a no-op.
     */
    abortStream() {
      if (this.streaming.abortController) {
        try {
          this.streaming.abortController.abort()
        } catch {
          // The controller was already used / disposed of.
          // Swallow — the caller's intent ("stop the stream")
          // is satisfied either way.
        }
      }
      this.streaming = {
        messageId: this.streaming.messageId,
        content: this.streaming.content,
        isStreaming: false,
        error: this.streaming.error,
        abortController: null,
      }
    },

    /**
     * Internal helpers used by the composable as it drives the
     * SSE generator. We expose them as actions (rather than letting
     * the composable mutate ``state.streaming`` directly) so the
     * store remains the single point of truth for the UI.
     */
    beginStream() {
      this.streaming = {
        messageId: null,
        content: '',
        isStreaming: true,
        error: null,
        abortController: new AbortController(),
      }
    },
    appendStreamChunk(chunk: string) {
      this.streaming.content += chunk
    },
    setStreamMessageId(messageId: string) {
      this.streaming.messageId = messageId
    },
    setStreamError(detail: string | null) {
      this.streaming.error = detail
    },
    /**
     * Called once the SSE generator returns (either because
     * ``message_end`` fired, the network closed, or the user
     * aborted). If we accumulated any text, fold it into the
     * ``messages`` list so a refresh doesn't lose the reply.
     */
    endStream() {
      const persisted: ChatMessage | null = this.streaming.content
        ? {
            id: this.streaming.messageId ?? `local_${Date.now()}`,
            conversationId: this.currentConversation?.id ?? '',
            type: 'assistant',
            content: this.streaming.content,
            timestamp: new Date().toISOString(),
          }
        : null
      this.streaming = {
        messageId: null,
        content: '',
        isStreaming: false,
        error: null,
        abortController: null,
      }
      if (persisted) this.messages.push(persisted)
    },
  },
})
