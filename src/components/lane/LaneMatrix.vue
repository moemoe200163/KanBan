<script setup lang="ts">
/**
 * LaneMatrix — grid view of the 8 Kanban Protocol worker lanes.
 *
 * Shows each lane's display name, status, allowed profiles, and
 * whether a handoff is currently active in that lane.
 */

import type { WorkerLane, Handoff } from '~/types'

const props = defineProps<{
  lanes: WorkerLane[]
  handoffs: Handoff[]
}>()

const activeHandoffsByLane = computed(() => {
  const map: Record<string, Handoff[]> = {}
  for (const h of props.handoffs) {
    if (h.status !== 'completed' && h.status !== 'cancelled') {
      ;(map[h.toLane] ??= []).push(h)
    }
  }
  return map
})

function laneStatus(lane: WorkerLane): 'idle' | 'active' | 'blocked' {
  const active = activeHandoffsByLane.value[lane.key]
  if (!active?.length) return 'idle'
  if (active.some(h => h.status === 'blocked')) return 'blocked'
  return 'active'
}

const STATUS_STYLES: Record<string, { dot: string; bg: string }> = {
  idle: { dot: 'bg-zinc-500', bg: 'bg-zinc-900/40' },
  active: { dot: 'bg-emerald-500', bg: 'bg-emerald-900/20' },
  blocked: { dot: 'bg-red-500', bg: 'bg-red-900/20' },
}
</script>

<template>
  <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
    <div
      v-for="lane in lanes"
      :key="lane.key"
      class="rounded-md border border-zinc-700 p-3 text-xs transition-colors"
      :class="STATUS_STYLES[laneStatus(lane)].bg"
    >
      <div class="flex items-center gap-2 mb-1.5">
        <span
          class="h-2 w-2 rounded-full"
          :class="STATUS_STYLES[laneStatus(lane)].dot"
        />
        <span class="font-medium text-zinc-200 truncate">
          {{ lane.displayName }}
        </span>
      </div>

      <p class="text-zinc-500 text-[11px] leading-snug mb-2 line-clamp-2">
        {{ lane.description }}
      </p>

      <div class="flex flex-wrap gap-1">
        <span
          v-for="profile in lane.allowedProfiles"
          :key="profile"
          class="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[10px]"
        >
          {{ profile }}
        </span>
      </div>

      <div
        v-if="lane.humanApprovalRequired"
        class="mt-2 text-[10px] text-amber-500/80"
      >
        approval required
      </div>

      <div
        v-if="activeHandoffsByLane[lane.key]?.length"
        class="mt-1.5 text-[10px] text-zinc-400"
      >
        {{ activeHandoffsByLane[lane.key].length }} handoff(s)
      </div>
    </div>
  </div>
</template>
