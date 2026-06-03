<script setup lang="ts">
/**
 * HandoffSection — lists handoffs for the selected issue and provides
 * the "Create Handoff" action.  Embedded inside IssueDetail.
 */

import { useBoardStore } from '~/stores/board'
import type { Handoff, WorkerLane } from '~/types'

const boardStore = useBoardStore()
const issue = computed(() => boardStore.selectedIssue)

const showCreateForm = ref(false)
const targetLane = ref('')
const isSubmitting = ref(false)

// Load worker lanes from the backend on mount
const lanes = ref<WorkerLane[]>([])
onMounted(async () => {
  try {
    const config = useRuntimeConfig()
    const data = await $fetch<{ lanes: WorkerLane[] }>(`${config.public.apiBase}/lanes`)
    lanes.value = data.lanes
  } catch {
    // Lanes endpoint may not be available yet; fallback to empty
  }
})

// Fetch handoffs when issue changes
watch(
  () => issue.value?.id,
  async (id) => {
    if (id) await boardStore.fetchHandoffs(id)
  },
  { immediate: true },
)

const handoffs = computed(() => issue.value?.handoffs ?? [])

async function handleCreate() {
  if (!issue.value || !targetLane.value) return
  isSubmitting.value = true
  try {
    await boardStore.createHandoff(issue.value.id, {
      toLane: targetLane.value,
      fromLane: null,
      createdBy: 'user',
    })
    showCreateForm.value = false
    targetLane.value = ''
  } finally {
    isSubmitting.value = false
  }
}

async function handleAccept(handoffId: string) {
  if (!issue.value) return
  await boardStore.acceptHandoff(issue.value.id, handoffId, 'user')
}

async function handleDispatch(handoffId: string) {
  if (!issue.value) return
  await boardStore.dispatchHandoff(issue.value.id, handoffId, {
    issueKey: issue.value.key,
    profile: issue.value.profile,
    actor: 'user',
  })
}

async function handleComplete(handoffId: string) {
  if (!issue.value) return
  await boardStore.completeHandoff(issue.value.id, handoffId, {}, 'user')
}

async function handleBlock(handoffId: string) {
  if (!issue.value) return
  const reason = prompt('Block reason:')
  if (!reason) return
  await boardStore.blockHandoff(issue.value.id, handoffId, reason, 'user')
}

async function handleUnblock(handoffId: string) {
  if (!issue.value) return
  await boardStore.unblockHandoff(issue.value.id, handoffId, 'user')
}

async function handleCancel(handoffId: string) {
  if (!issue.value) return
  await boardStore.cancelHandoff(issue.value.id, handoffId, 'user')
}
</script>

<template>
  <div v-if="issue" class="space-y-3">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h4 class="text-xs font-medium text-zinc-400 uppercase tracking-wider">
        Handoffs
      </h4>
      <button
        class="px-2 py-1 rounded text-[11px] bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200 transition-colors"
        @click="showCreateForm = !showCreateForm"
      >
        {{ showCreateForm ? 'Cancel' : '+ Handoff' }}
      </button>
    </div>

    <!-- Create form -->
    <div
      v-if="showCreateForm"
      class="rounded-md border border-zinc-700 p-3 space-y-2"
    >
      <select
        v-model="targetLane"
        class="w-full bg-zinc-800 border border-zinc-600 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
      >
        <option value="" disabled>Select target lane</option>
        <option
          v-for="lane in lanes"
          :key="lane.key"
          :value="lane.key"
        >
          {{ lane.displayName }}
        </option>
      </select>
      <button
        :disabled="!targetLane || isSubmitting"
        class="w-full px-2 py-1.5 rounded text-[11px] bg-emerald-900/40 text-emerald-400 hover:bg-emerald-900/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        @click="handleCreate"
      >
        {{ isSubmitting ? 'Creating...' : 'Create Handoff' }}
      </button>
    </div>

    <!-- Handoff list -->
    <div v-if="handoffs.length > 0" class="space-y-2">
      <HandoffCard
        v-for="h in handoffs"
        :key="h.id"
        :handoff="h"
        @accept="handleAccept"
        @dispatch="handleDispatch"
        @complete="handleComplete"
        @block="handleBlock"
        @unblock="handleUnblock"
        @cancel="handleCancel"
      />
    </div>

    <p
      v-else-if="!showCreateForm"
      class="text-[11px] text-zinc-600 italic"
    >
      No handoffs yet.
    </p>
  </div>
</template>
