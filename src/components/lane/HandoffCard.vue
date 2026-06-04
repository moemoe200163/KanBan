<script setup lang="ts">
/**
 * HandoffCard — compact card for a single handoff in the issue detail panel.
 *
 * Shows status badge, lane info, timestamps, and action buttons
 * relevant to the current status.
 */

import type { Handoff } from '~/types'

const props = defineProps<{
  handoff: Handoff
}>()

const emit = defineEmits<{
  accept: [handoffId: string]
  dispatch: [handoffId: string]
  complete: [handoffId: string]
  block: [handoffId: string]
  unblock: [handoffId: string]
  cancel: [handoffId: string]
}>()

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'text-zinc-400 bg-zinc-800' },
  accepted: { label: 'Accepted', color: 'text-blue-400 bg-blue-900/30' },
  in_progress: { label: 'In Progress', color: 'text-emerald-400 bg-emerald-900/30' },
  completed: { label: 'Completed', color: 'text-zinc-300 bg-zinc-700' },
  blocked: { label: 'Blocked', color: 'text-red-400 bg-red-900/30' },
  cancelled: { label: 'Cancelled', color: 'text-zinc-500 bg-zinc-800/50' },
}

const cfg = computed(() => STATUS_CONFIG[props.handoff.status] ?? STATUS_CONFIG.pending)

const relativeTime = computed(() => {
  const d = new Date(props.handoff.createdAt)
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return d.toLocaleDateString()
})

// Evidence display — collapsed by default, completed handoffs only.
// Component-local state; never read by parent. Refreshes on prop change
// so a re-fetched Handoff with a populated payload updates the count.
const expanded = ref(false)

const payloadKeyCount = computed(
  () => Object.keys(props.handoff.payload ?? {}).length
)

// accepted / in_progress / blocked / cancelled / pending are
// intentionally NOT eligible — they have no "evidence" to show.
const showEvidenceToggle = computed(
  () => props.handoff.status === 'completed' && payloadKeyCount.value > 0
)
</script>

<template>
  <div
    class="rounded-md border border-zinc-700/50 p-3 text-xs transition-colors hover:border-zinc-600"
    :class="{ 'opacity-60': handoff.status === 'completed' || handoff.status === 'cancelled' }"
  >
    <!-- Header -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <span class="px-1.5 py-0.5 rounded text-[10px] font-medium" :class="cfg.color">
          {{ cfg.label }}
        </span>
        <span class="text-zinc-500">
          {{ handoff.fromLane ? `${handoff.fromLane} →` : '' }} {{ handoff.toLane }}
        </span>
      </div>
      <span class="text-zinc-600 text-[10px]">{{ relativeTime }}</span>
    </div>

    <!-- Block reason -->
    <div
      v-if="handoff.blockReason"
      class="mb-2 px-2 py-1 rounded bg-red-900/20 text-red-400 text-[11px]"
    >
      {{ handoff.blockReason }}
    </div>

    <!-- Payload summary -->
    <div
      v-if="handoff.payload && Object.keys(handoff.payload).length > 0"
      class="mb-2 flex flex-wrap gap-1"
    >
      <span
        v-for="key in Object.keys(handoff.payload)"
        :key="key"
        class="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[10px]"
      >
        {{ key }}
      </span>
    </div>

    <!-- Evidence toggle (completed handoffs with non-empty payload only) -->
    <button
      v-if="showEvidenceToggle"
      type="button"
      data-testid="handoff-evidence-toggle"
      class="w-full mb-2 flex items-center justify-between px-2 py-1 rounded
             bg-zinc-800/60 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200
             text-[11px] transition-colors"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <span>{{ expanded ? 'Hide evidence' : `View evidence (${payloadKeyCount} fields)` }}</span>
      <span aria-hidden="true">{{ expanded ? '−' : '+' }}</span>
    </button>

    <!-- Actions -->
    <div class="flex flex-wrap gap-1.5 mt-2">
      <button
        v-if="handoff.status === 'pending'"
        class="px-2 py-1 rounded bg-blue-900/40 text-blue-400 hover:bg-blue-900/60 text-[11px] transition-colors"
        @click="emit('accept', handoff.id)"
      >
        Accept
      </button>
      <button
        v-if="handoff.status === 'accepted'"
        class="px-2 py-1 rounded bg-emerald-900/40 text-emerald-400 hover:bg-emerald-900/60 text-[11px] transition-colors"
        @click="emit('dispatch', handoff.id)"
      >
        Dispatch
      </button>
      <button
        v-if="handoff.status === 'in_progress' || handoff.status === 'accepted'"
        data-testid="handoff-complete-btn"
        class="px-2 py-1 rounded bg-zinc-700 text-zinc-300 hover:bg-zinc-600 text-[11px] transition-colors"
        @click="emit('complete', handoff.id)"
      >
        Complete
      </button>
      <button
        v-if="handoff.status !== 'completed' && handoff.status !== 'cancelled' && handoff.status !== 'blocked'"
        class="px-2 py-1 rounded bg-amber-900/30 text-amber-400 hover:bg-amber-900/50 text-[11px] transition-colors"
        @click="emit('block', handoff.id)"
      >
        Block
      </button>
      <button
        v-if="handoff.status === 'blocked'"
        class="px-2 py-1 rounded bg-zinc-700 text-zinc-300 hover:bg-zinc-600 text-[11px] transition-colors"
        @click="emit('unblock', handoff.id)"
      >
        Unblock
      </button>
      <button
        v-if="handoff.status !== 'completed' && handoff.status !== 'cancelled'"
        class="px-2 py-1 rounded bg-red-900/20 text-red-400/70 hover:bg-red-900/40 text-[11px] transition-colors"
        @click="emit('cancel', handoff.id)"
      >
        Cancel
      </button>
    </div>
  </div>
</template>
