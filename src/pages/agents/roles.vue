<script setup lang="ts">
/**
 * /agents/roles — Kanban Protocol agent role overview page.
 *
 * Displays the AgentRoleMatrix grid showing all 8 agent roles, their
 * status, and active handoff counts.
 */

import { useBoardStore } from '~/stores/board'
import type { WorkerLane, Handoff } from '~/types'

const boardStore = useBoardStore()
const lanes = ref<WorkerLane[]>([])
const handoffs = ref<Handoff[]>([])

onMounted(async () => {
  const config = useRuntimeConfig()

  // Fetch lanes and active handoffs in parallel
  const [lanesRes, boardRes] = await Promise.allSettled([
    $fetch<{ lanes: WorkerLane[] }>(`${config.public.apiBase}/lanes`),
    boardStore.fetchBoard(),
  ])

  if (lanesRes.status === 'fulfilled') {
    lanes.value = lanesRes.value.lanes
  }

  // Collect all non-terminal handoffs from all issues
  const allIssues = boardStore.columns.flatMap(c => c.issues)
  const handoffResults = await Promise.allSettled(
    allIssues.map(async (issue) => {
      const res = await $fetch<{ handoffs: Handoff[] }>(
        `${config.public.apiBase}/boards/board-default/issues/${issue.id}/handoffs`,
      )
      return res.handoffs
    }),
  )

  handoffs.value = handoffResults
    .filter((r): r is PromiseFulfilledResult<Handoff[]> => r.status === 'fulfilled')
    .flatMap(r => r.value)
})
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto space-y-6">
    <div>
      <h1 class="text-lg font-medium text-zinc-200">Agent Roles</h1>
      <p class="text-sm text-zinc-500 mt-1">
        Subagent role definitions. Each role specifies allowed profiles,
        completion requirements, and approval policies.
      </p>
    </div>

    <AgentRoleMatrix
      v-if="lanes.length > 0"
      :lanes="lanes"
      :handoffs="handoffs"
    />

    <p v-else class="text-sm text-zinc-600 italic">
      Loading roles from backend...
    </p>
  </div>
</template>
