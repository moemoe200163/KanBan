/**
 * useSSE — fetch-based Server-Sent Events client.
 *
 * Why fetch + ReadableStream, not the platform ``EventSource``:
 * ``EventSource`` is hard-coded to send cookies / use the global
 * ``withCredentials`` setting, but in this app the auth token lives
 * in a ``document.cookie`` and we want to attach it as a regular
 * ``Authorization: Bearer <token>`` header. ``EventSource`` does
 * not let you set request headers at all. ``fetch`` does, and a
 * chunked ``text/event-stream`` response is just a normal HTTP body
 * we can ``.getReader()`` ourselves.
 *
 * Event wire format (matches what the AI Studio SSE driver in
 * ``backend/core/execution/ai_studio_runner.py`` yields):
 *
 *   event: message_start
 *   data: {"conversationId": "aiconv_..."}
 *
 *   event: content
 *   data: {"content": "Hello "}
 *
 *   event: error
 *   data: {"detail": "..."}
 *
 *   event: message_end
 *   data: {"messageId": "aimsg_..."}
 *
 * Frames are delimited by a blank line (``\n\n``). The spec allows
 * multi-line ``data:`` values (each line prefixed ``data: ``) — we
 * concatenate them with ``\n`` between, which is what the consumer
 * expects.
 */

export type SSEEventType =
  | 'message_start'
  | 'content'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_handoff'
  | 'message_end'
  | 'error'

export interface SSEEvent {
  event: SSEEventType
  // Parsed JSON payload. Always an object on the AI Studio wire —
  // we widen the type to ``Record<string, unknown>`` so the caller
  // can destructure the fields they need.
  data: Record<string, unknown>
  // The raw ``data:`` text — useful for debugging or for events
  // that don't parse as JSON (server quirks).
  rawData: string
}

/**
 * Parse a single SSE frame (the text between two ``\n\n`` boundaries)
 * into an ``SSEEvent`` or ``null`` if the frame is empty / a comment.
 *
 * Exported so the unit tests (and the manual debug page) can re-use
 * it without round-tripping through ``fetch``.
 */
export function parseSSEFrame(frame: string): SSEEvent | null {
  // Comments (``line starting with ``:``) and empty frames are
  // legal SSE keep-alives — drop them on the floor.
  if (!frame || frame.startsWith(':')) return null

  let eventName: SSEEventType | null = null
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (!line) continue
    if (line.startsWith(':')) continue // comment
    const colon = line.indexOf(':')
    if (colon === -1) continue // malformed; skip
    const field = line.slice(0, colon)
    // The spec lets the producer add a single leading space after
    // the colon — strip it so the value doesn't carry whitespace.
    let value = line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') {
      eventName = value as SSEEventType
    } else if (field === 'data') {
      dataLines.push(value)
    }
    // ``id:`` and ``retry:`` are intentionally ignored — the AI
    // Studio backend doesn't emit them and a chat client has no
    // use for reconnection hints when each stream is one-shot.
  }

  if (!eventName || dataLines.length === 0) {
    // No ``event:`` line or no ``data:`` line — the frame is not
    // actionable. Returning ``null`` is the same as dropping it.
    return null
  }

  const rawData = dataLines.join('\n')
  let parsed: Record<string, unknown> = {}
  try {
    const json: unknown = JSON.parse(rawData)
    if (json && typeof json === 'object' && !Array.isArray(json)) {
      parsed = json as Record<string, unknown>
    } else {
      // The server emitted a scalar — keep it under ``raw`` so the
      // caller can still see it, but treat the structured ``data``
      // as empty.
      parsed = { raw: json }
    }
  } catch {
    // Not JSON. The AI Studio endpoint always sends JSON, but a
    // future proxy in front of it might not. Stash the raw text
    // so the UI can display the error verbatim.
    parsed = { raw: rawData }
  }

  return { event: eventName, data: parsed, rawData }
}

export interface StreamSSEOptions {
  url: string
  body: unknown
  token: string
  signal?: AbortSignal
  // Called for every successfully parsed event. The async iterator
  // still yields the same event — this is a convenience for callers
  // that want to log / count without driving the loop themselves.
  onEvent?: (evt: SSEEvent) => void
}

/**
 * Drive a POST against an SSE endpoint and yield parsed events.
 *
 * Throws if the HTTP response is non-2xx (so the caller can render
 * a clear error message — SSE bodies after a 4xx/5xx are usually
 * not actually a stream). Network errors propagate as the fetch
 * promise rejects.
 */
export async function* streamSSE(opts: StreamSSEOptions): AsyncGenerator<SSEEvent> {
  const { url, body, token, signal, onEvent } = opts
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => '')
    throw new Error(
      `SSE HTTP ${resp.status} ${resp.statusText}: ${text.slice(0, 200) || '(empty body)'}`,
    )
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  // Track the current event name across frames — the SSE spec lets
  // a producer omit ``event:`` on continuation frames and re-uses
  // the previous one. The AI Studio backend always sends ``event:``
  // on every frame, so this is mostly belt-and-braces.
  let currentEvent: SSEEventType | null = null

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Frames are delimited by a blank line (\n\n). Split
      // greedily until we run out of complete frames; the tail
      // stays in the buffer for the next read.
      let frameEnd = buffer.indexOf('\n\n')
      while (frameEnd !== -1) {
        const frame = buffer.slice(0, frameEnd)
        buffer = buffer.slice(frameEnd + 2)

        // Track event name across lines within a single frame —
        // the spec lets a producer write ``event: foo`` once at
        // the top, then several ``data:`` lines. The frame
        // parser already handles this; the cross-frame
        // continuation is the part that needs ``currentEvent``.
        if (frame.startsWith('event:')) {
          currentEvent = frame.slice(6).trim() as SSEEventType
        }

        const evt = parseSSEFrame(frame)
        if (evt) {
          if (onEvent) onEvent(evt)
          yield evt
        }
        frameEnd = buffer.indexOf('\n\n')
      }
    }

    // Flush any trailing frame that wasn't followed by a blank
    // line (some servers skip the final \n\n). Only emit if it
    // has a recognizable shape.
    const tail = buffer.trim()
    if (tail) {
      const evt = parseSSEFrame(tail)
      if (evt) {
        if (onEvent) onEvent(evt)
        yield evt
      }
      // Keep the reference alive so TS doesn't flag it as
      // unused in a future refactor.
      void currentEvent
    }
  } finally {
    // Always release the reader so the underlying socket can
    // close. ``cancel()`` is the right call regardless of
    // whether we exited via ``done`` or via a thrown error.
    try {
      reader.releaseLock()
    } catch {
      // Already released — ignore.
    }
  }
}

/**
 * Composable wrapper that returns a stable function reference plus
 * helpers for the most common call sites.
 *
 * We don't keep a long-lived connection (each ``streamSSE`` call is
 * a one-shot POST → SSE), so the composable is just a thin factory
 * over the free function. It exists so callers can do
 * ``const { stream } = useSSE()`` and stay symmetric with the other
 * composables in the project (``useWebSocket``, ``useECCStream``).
 */
export function useSSE() {
  return {
    stream: streamSSE,
    parseFrame: parseSSEFrame,
  }
}
