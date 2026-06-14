<script setup lang="ts">
/**
 * ChatMessage — renders a single message in the AI Studio chat
 * stream.
 *
 * Five visual variants (mapped from ``type``):
 *   - user         — right-aligned blue bubble
 *   - assistant    — left-aligned green bubble with markdown
 *   - thinking     — left-aligned grey italic bubble
 *   - tool_call    — left-aligned tool chip with name + args preview
 *   - tool_result  — left-aligned dim bubble with the result body
 *
 * Markdown rendering is intentionally light: fenced code blocks
 * get syntax highlighting (via highlight.js) and a copy button;
 * the rest of the body uses a small hand-rolled renderer that
 * handles paragraphs, inline code, bold/italic, and links. We
 * keep the parser tiny because the AI Studio chat only ever
 * renders model output (trusted server-rendered markdown), not
 * arbitrary user HTML — escaping the rest of the input is
 * sufficient.
 */

import { computed, ref } from 'vue'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import {
  Bot,
  Check,
  Copy,
  Sparkles,
  User,
  Wrench,
} from 'lucide-vue-next'
import type { ChatMessage } from '~/stores/aiStudio'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('vue', xml)
hljs.registerLanguage('css', css)

interface Props {
  message: ChatMessage
  // Show a blinking caret at the end of the text. The page
  // sets this true for the in-flight streaming turn and
  // false for everything in the persisted history.
  isStreaming?: boolean
}
const props = defineProps<Props>()

// ---------------------------------------------------------------------------
// HTML escape — every interpolation goes through this before the
// per-line markdown pass. We do NOT use ``v-html`` to inject
// unescaped content anywhere in this component.
// ---------------------------------------------------------------------------
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// ---------------------------------------------------------------------------
// Tiny inline-aware markdown renderer. Order matters: code spans
// have to be protected before we touch bold/italic markers,
// otherwise an ``*`` inside a backtick would get bolded.
// ---------------------------------------------------------------------------
function renderInline(text: string): string {
  let out = escapeHtml(text)
  // Inline code (protect with placeholders so subsequent
  // passes don't mangle their contents).
  const codeStore: string[] = []
  out = out.replace(/`([^`\n]+)`/g, (_m, code: string) => {
    codeStore.push(`<code class="cm-inline-code">${code}</code>`)
    return `\u0000CODE${codeStore.length - 1}\u0000`
  })
  // Bold ( **x** ) before italic ( *x* ) — order matters so
  // the bold regex eats its own asterisks first.
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  // [text](url) — accept http(s) and relative paths
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  )
  // Restore inline code
  out = out.replace(/\u0000CODE(\d+)\u0000/g, (_m, idx: string) => codeStore[Number(idx)])
  return out
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  // Split on fenced code blocks first. Anything between ```lang
  // and ``` becomes a <pre><code class="hljs"> with language
  // class. Everything else is paragraph + inline.
  const parts: string[] = []
  const re = /```(\w+)?\n([\s\S]*?)```/g
  let lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const before = text.slice(lastIndex, m.index)
    if (before.trim()) {
      parts.push(`<p>${renderInline(before).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br/>')}</p>`)
    }
    const lang = (m[1] || '').trim()
    const body = m[2].replace(/\n$/, '')
    let highlighted: string
    try {
      if (lang && hljs.getLanguage(lang)) {
        highlighted = hljs.highlight(body, { language: lang, ignoreIllegals: true }).value
      } else {
        highlighted = hljs.highlightAuto(body).value
      }
    } catch {
      highlighted = escapeHtml(body)
    }
    parts.push(
      `<pre class="cm-codeblock"><code class="hljs language-${lang || 'plaintext'}">${highlighted}</code></pre>`,
    )
    lastIndex = m.index + m[0].length
  }
  const tail = text.slice(lastIndex)
  if (tail.trim()) {
    parts.push(`<p>${renderInline(tail).replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br/>')}</p>`)
  }
  return parts.join('')
}

const renderedHtml = computed(() => renderMarkdown(props.message.content || ''))

// Pull the raw text of every code block (for the copy button)
const codeBlockSources = computed<string[]>(() => {
  const out: string[] = []
  const re = /```(\w+)?\n([\s\S]*?)```/g
  let m: RegExpExecArray | null
  while ((m = re.exec(props.message.content || '')) !== null) {
    out.push(m[2].replace(/\n$/, ''))
  }
  return out
})

const copiedIndex = ref<number | null>(null)
async function copyCodeBlock(index: number) {
  const source = codeBlockSources.value[index]
  if (!source) return
  try {
    await navigator.clipboard.writeText(source)
    copiedIndex.value = index
    setTimeout(() => {
      if (copiedIndex.value === index) copiedIndex.value = null
    }, 1500)
  } catch {
    // Clipboard API not available (insecure context, etc.).
    // The button is purely a convenience — silently no-op
    // rather than confusing the user with a JS error.
  }
}

const variant = computed(() => {
  switch (props.message.type) {
    case 'user':
      return { icon: User, label: 'You', cls: 'cm-msg--user' }
    case 'thinking':
      return { icon: Sparkles, label: 'Thinking', cls: 'cm-msg--thinking' }
    case 'tool_call':
      return { icon: Wrench, label: props.message.toolName || 'Tool', cls: 'cm-msg--tool' }
    case 'tool_result':
      return { icon: Check, label: 'Tool result', cls: 'cm-msg--tool-result' }
    case 'assistant':
    default:
      return { icon: Bot, label: 'AI Studio', cls: 'cm-msg--assistant' }
  }
})

const formattedTime = computed(() => {
  const ts = props.message.timestamp
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
})
</script>

<template>
  <div
    class="cm-msg"
    :class="[variant.cls, { 'cm-msg--streaming': isStreaming }]"
    :data-type="message.type"
  >
    <div class="cm-msg__avatar" :title="variant.label">
      <component :is="variant.icon" :size="14" />
    </div>
    <div class="cm-msg__body">
      <div class="cm-msg__header">
        <span class="cm-msg__author">{{ variant.label }}</span>
        <span v-if="formattedTime" class="cm-msg__time">{{ formattedTime }}</span>
      </div>
      <!--
        ``renderedHtml`` is fed through escapeHtml() for every
        interpolated segment, and the markdown rules themselves
        only emit a fixed whitelist of tags (``p``, ``strong``,
        ``em``, ``code``, ``pre``, ``a``, ``br``). The ``rel``
        and ``target`` attributes are always set on anchors.
        This is the only ``v-html`` in the file; everything else
        uses text bindings.
      -->
      <div class="cm-msg__content" v-html="renderedHtml" />
      <div
        v-if="codeBlockSources.length > 0"
        class="cm-msg__code-actions"
      >
        <button
          v-for="(_, idx) in codeBlockSources"
          :key="idx"
          class="cm-msg__copy-btn"
          :title="copiedIndex === idx ? 'Copied' : 'Copy code block'"
          @click="copyCodeBlock(idx)"
        >
          <component :is="copiedIndex === idx ? Check : Copy" :size="12" />
          <span>{{ copiedIndex === idx ? 'Copied' : 'Copy' }}</span>
        </button>
      </div>
      <p v-if="message.type === 'tool_call' && message.toolArgs" class="cm-msg__tool-args">
        <span class="cm-msg__tool-label">Args:</span>
        <code>{{ JSON.stringify(message.toolArgs) }}</code>
      </p>
      <p v-else-if="message.type === 'tool_result' && message.toolResult" class="cm-msg__tool-args">
        <span class="cm-msg__tool-label">Result:</span>
        <code>{{ message.toolResult }}</code>
      </p>
      <span v-if="isStreaming" class="cm-msg__caret" aria-hidden="true">▍</span>
    </div>
  </div>
</template>

<style scoped>
.cm-msg {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 8px;
  transition: background var(--duration-fast) var(--ease-out);
}
.cm-msg + .cm-msg {
  margin-top: 2px;
}

.cm-msg__avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--surface-cream-strong);
  color: var(--muted);
}

.cm-msg__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.cm-msg__header {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.cm-msg__author {
  font-family: var(--font-display);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink);
}

.cm-msg__time {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}

.cm-msg__content {
  color: var(--body);
  font-size: 0.9375rem;
  line-height: 1.5;
  word-break: break-word;
}
.cm-msg__content :deep(p) {
  margin: 0 0 8px 0;
}
.cm-msg__content :deep(p:last-child) {
  margin-bottom: 0;
}
.cm-msg__content :deep(strong) {
  color: var(--ink);
  font-weight: 600;
}
.cm-msg__content :deep(em) {
  color: var(--muted);
  font-style: italic;
}
.cm-msg__content :deep(a) {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.cm-msg__content :deep(.cm-inline-code) {
  padding: 1px 6px;
  color: var(--ink);
  background: var(--surface-soft);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85em;
}
.cm-msg__content :deep(.cm-codeblock) {
  position: relative;
  margin: 8px 0;
  padding: 12px 14px;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  line-height: 1.5;
  overflow-x: auto;
}
.cm-msg__content :deep(.cm-codeblock code) {
  background: transparent;
  padding: 0;
}

.cm-msg__code-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.cm-msg__copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline-soft);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}
.cm-msg__copy-btn:hover {
  color: var(--ink);
  background: var(--surface-cream-strong);
}

.cm-msg__tool-args {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
  margin: 4px 0 0 0;
  padding: 6px 8px;
  color: var(--body);
  background: var(--surface-soft);
  border-radius: 6px;
  font-size: 0.8125rem;
}
.cm-msg__tool-args code {
  word-break: break-all;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
.cm-msg__tool-label {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
}

.cm-msg__caret {
  display: inline-block;
  margin-left: 2px;
  color: var(--primary);
  font-weight: 600;
  animation: cm-caret-blink 1s steps(1) infinite;
}
@keyframes cm-caret-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.cm-msg__error-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 2px 8px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}

/* Variants */
.cm-msg--user {
  background: rgba(204, 120, 92, 0.08);
}
.cm-msg--user .cm-msg__avatar {
  background: var(--primary);
  color: var(--on-primary);
}
.cm-msg--user .cm-msg__content {
  white-space: pre-wrap;
}

.cm-msg--assistant .cm-msg__avatar {
  color: var(--sage);
  background: rgba(125, 158, 125, 0.16);
}

.cm-msg--thinking {
  background: var(--surface-soft);
}
.cm-msg--thinking .cm-msg__avatar {
  color: var(--muted);
  background: var(--surface-cream-strong);
}
.cm-msg--thinking .cm-msg__content {
  color: var(--muted);
  font-style: italic;
}

.cm-msg--tool,
.cm-msg--tool-result {
  background: rgba(107, 139, 164, 0.08);
}
.cm-msg--tool .cm-msg__avatar,
.cm-msg--tool-result .cm-msg__avatar {
  color: var(--dusty-blue);
  background: rgba(107, 139, 164, 0.16);
}
</style>
