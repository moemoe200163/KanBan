/**
 * useAIStudio — façade composable that wires the Pinia store
 * to the AI Studio HTTP + SSE backend.
 *
 * The page layer should never call ``fetch`` directly for
 * AI Studio operations — go through this composable instead.
 * It owns:
 *
 *  - Picking up the auth token from the cookie set by
 *    ``useAuth`` and forwarding it to ``streamSSE``.
 *  - Driving the SSE generator: turning ``content`` events
 *    into ``appendStreamChunk`` calls, ``message_end`` into
 *    ``setStreamMessageId``, and errors into a user-visible
 *    string the chat bubble can render.
 *  - Idempotency: a page that calls ``sendMessage`` twice
 *    before the first stream begins should not produce two
 *    streams. The composable guards on ``store.isStreaming``
 *    and on the store-owned ``AbortController``.
 */

import { useAIStudioStore } from '~/stores/aiStudio'
import { streamSSE, type SSEEvent } from '~/composables/useSSE'
import { authHeaders } from '~/utils/authHeaders'

function useApiBase() {
  return useRuntimeConfig().public.apiBase as string
}

function readAuthToken(): string {
  // The login flow stores the JWT in a cookie named ``auth_token``
  // — the same cookie ``authHeaders()`` reads. We duplicate the
  // logic here because ``streamSSE`` wants the token in the
  // header, not a Record<string,string> object.
  if (typeof document === 'undefined') return ''
  const match = document.cookie.match(new RegExp('(^| )auth_token=([^;]+)'))
  if (!match) return ''
  try {
    return decodeURIComponent(match[2])
  } catch {
    return match[2]
  }
}

export function useAIStudio() {
  const store = useAIStudioStore()

  /**
   * Make sure there is an active conversation. If the store
   * already has one, return its id. Otherwise create a new
   * one and return that id.
   *
   * The caller doesn't need to await this — it just needs
   * the id before calling ``sendMessage``. We return the
   * promise so the caller can chain.
   */
  async function ensureConversation(title: string = 'New chat'): Promise<string | null> {
    if (store.currentConversation?.id) return store.currentConversation.id
    return store.createConversation(title)
  }

  /**
   * Send a user message and stream the assistant reply.
   *
   * The promise resolves when the SSE stream ends (success,
   * error, or abort). The store picks up the streaming state
   * along the way, so the UI just has to bind to
   * ``store.isStreaming`` and ``store.streamingReply``.
   */
  async function sendMessage(content: string): Promise<void> {
    if (store.isStreaming) return // already streaming; ignore double-submit
    const trimmed = content.trim()
    if (!trimmed) return

    const convId = await ensureConversation()
    if (!convId) {
      store.setStreamError('Could not start a conversation. Try again.')
      return
    }

    // Echo the user message into the local list immediately so
    // the bubble appears before the model even responds.
    const userMsg = {
      id: `local_user_${Date.now()}`,
      conversationId: convId,
      type: 'user' as const,
      content: trimmed,
      timestamp: new Date().toISOString(),
    }
    store.messages.push(userMsg)

    const token = readAuthToken()
    if (!token) {
      store.setStreamError('Not signed in. Please log in to chat.')
      return
    }

    store.beginStream()

    try {
      const url = `${useApiBase()}/ai-studio/conversations/${convId}/messages`
      const events = streamSSE({
        url,
        body: {
          content: trimmed,
          provider_id: store.selectedProviderId,
        },
        token,
        signal: store.streaming.abortController?.signal,
      })

      for await (const evt of events) {
        handleEvent(evt)
      }
    } catch (err: any) {
      // The most common cause here is the user hitting Escape,
      // which fires ``AbortError`` from the underlying ``fetch``.
      // That's not a real error to surface — the store already
      // flipped ``isStreaming`` to false via ``abortStream``.
      if (err?.name === 'AbortError') {
        // No-op; the abort action is the user's intent.
      } else {
        store.setStreamError(
          err?.message ? String(err.message) : 'Streaming failed unexpectedly',
        )
      }
    } finally {
      store.endStream()
    }
  }

  function handleEvent(evt: SSEEvent) {
    switch (evt.event) {
      case 'message_start': {
        // ``message_start`` carries the conversationId — for the
        // chat UI the most useful field is the id we already
        // hold. We treat it as a heartbeat: the response is alive.
        break
      }
      case 'content': {
        const chunk = typeof evt.data.content === 'string' ? evt.data.content : ''
        if (chunk) store.appendStreamChunk(chunk)
        break
      }
      case 'thinking': {
        // Phase 1 doesn't have native thinking emissions from the
        // backend, but if a future provider / phase emits one,
        // fold the chunk into the streamed text so the user can
        // still see something happen. A real thinking bubble
        // arrives with Phase 2.
        const chunk = typeof evt.data.content === 'string' ? evt.data.content : ''
        if (chunk) store.appendStreamChunk(chunk)
        break
      }
      case 'message_end': {
        const messageId =
          typeof evt.data.messageId === 'string' ? evt.data.messageId : null
        if (messageId) store.setStreamMessageId(messageId)
        break
      }
      case 'error': {
        const detail =
          typeof evt.data.detail === 'string'
            ? evt.data.detail
            : 'The model returned an error.'
        store.setStreamError(detail)
        break
      }
      case 'tool_call':
      case 'tool_result':
      case 'agent_handoff': {
        // Phase 1 doesn't render these event types, but we
        // deliberately don't throw — a future Phase 2 bubble
        // can subscribe to them without us changing the
        // transport.
        break
      }
      default: {
        // Unknown event — log and continue. We don't want
        // a forward-compat server event to break the chat.
        // eslint-disable-next-line no-console
        console.warn('[ai-studio] unknown SSE event:', evt.event, evt.data)
      }
    }
  }

  /**
   * Best-effort cancel: fire the cancel endpoint so the
   * backend can release resources, then abort the in-flight
   * ``fetch`` so the SSE generator stops yielding.
   */
  async function cancelStream(): Promise<void> {
    const convId = store.currentConversation?.id
    if (convId) {
      try {
        await fetch(
          `${useApiBase()}/ai-studio/conversations/${convId}/cancel`,
          { method: 'POST', headers: authHeaders() },
        )
      } catch {
        // The cancel endpoint is best-effort — the abort
        // is what actually stops the UI from streaming.
      }
    }
    store.abortStream()
  }

  return {
    store,
    ensureConversation,
    sendMessage,
    cancelStream,
  }
}
