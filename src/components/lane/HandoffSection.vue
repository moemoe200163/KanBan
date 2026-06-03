<script setup lang="ts">
/**
 * HandoffSection — lists handoffs for the selected issue and provides
 * the "Create Handoff" action.  Embedded inside IssueDetail.
 */

import { useBoardStore } from '~/stores/board'
import type { Handoff, HandoffPreview, WorkerLane } from '~/types'

const boardStore = useBoardStore()
const issue = computed(() => boardStore.selectedIssue)
const config = useRuntimeConfig()

const showCreateForm = ref(false)
const targetLane = ref('')
const isSubmitting = ref(false)

// Completion-with-details form state. When the user clicks Complete on a
// handoff whose lane requires fields the existing payload doesn't carry,
// we open an inline form so they can fill them in. See backend
// core/kanban_protocol/lanes.py:required_completion_fields and
// handoff.py::HandoffService.complete — the backend rejects with 422
// if any required field is missing, which was the P4 PARTIAL gap.
const completingHandoffId = ref<string | null>(null)
const completionPreview = ref<HandoffPreview | null>(null)
const completionValues = ref<Record<string, string>>({})
const completionError = ref<string | null>(null)
const isCompleting = ref(false)

// Load worker lanes from the backend on mount
const lanes = ref<WorkerLane[]>([])
onMounted(async () => {
  try {
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
  completionError.value = null
  // Probe the lane's required completion fields. The backend will
  // 422 on missing fields, so we pre-flight via /preview and either
  // submit directly (already-satisfied) or open the form.
  try {
    const preview = await $fetch<HandoffPreview>(
      `${config.public.apiBase}/boards/board-default/issues/${issue.value.id}/handoffs/${handoffId}/preview`
    )
    if (preview.missingFields.length === 0) {
      await boardStore.completeHandoff(issue.value.id, handoffId, {}, 'user')
      return
    }
    completionPreview.value = preview
    completionValues.value = Object.fromEntries(
      preview.missingFields.map((f) => [f, ''])
    )
    completingHandoffId.value = handoffId
  } catch (err) {
    completionError.value = (err as Error)?.message || 'Failed to load handoff preview'
  }
}

async function submitCompletion() {
  if (!issue.value || !completingHandoffId.value || !completionPreview.value) return
  isCompleting.value = true
  completionError.value = null
  try {
    // Send only the fields the user actually filled in. Backend
    // merges with the existing payload, so partial submissions are
    // fine — but the user must cover all required fields, otherwise
    // the service will 422 again.
    const payload: Record<string, unknown> = {}
    for (const field of completionPreview.value.missingFields) {
      const v = completionValues.value[field]?.trim()
      if (v) payload[field] = v
    }
    await boardStore.completeHandoff(
      issue.value.id,
      completingHandoffId.value,
      payload,
      'user'
    )
    cancelCompletion()
  } catch (err) {
    completionError.value = (err as Error)?.message || 'Failed to complete handoff'
  } finally {
    isCompleting.value = false
  }
}

function cancelCompletion() {
  completingHandoffId.value = null
  completionPreview.value = null
  completionValues.value = {}
  completionError.value = null
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
        data-testid="handoff-lane-select"
        class="w-full bg-zinc-800 border border-zinc-600 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
      >
        <option value="" disabled>Select target role</option>
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

    <!-- Completion form (shown when lane requires fields) -->
    <div
      v-if="completingHandoffId && completionPreview"
      class="rounded-md border border-zinc-700 p-3 space-y-2"
    >
      <p class="text-[11px] text-zinc-400">
        This lane requires additional fields to complete the handoff.
      </p>
      <div
        v-for="field in completionPreview.missingFields"
        :key="field"
        class="space-y-1"
      >
        <label class="text-[11px] text-zinc-500 uppercase tracking-wider">
          {{ field.replace(/_/g, ' ') }}
        </label>
        <input
          :data-testid="`completion-field-${field}`"
          v-model="completionValues[field]"
          class="w-full bg-zinc-800 border border-zinc-600 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
          :placeholder="`Enter ${field.replace(/_/g, ' ')}`"
        />
      </div>
      <p v-if="completionError" class="text-[11px] text-red-400">
        {{ completionError }}
      </p>
      <div class="flex gap-2">
        <button
          :disabled="isCompleting"
          data-testid="submit-completion"
          class="flex-1 px-2 py-1.5 rounded text-[11px] bg-emerald-900/40 text-emerald-400 hover:bg-emerald-900/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          @click="submitCompletion"
        >
          {{ isCompleting ? 'Submitting...' : 'Complete Handoff' }}
        </button>
        <button
          class="px-2 py-1.5 rounded text-[11px] bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200 transition-colors"
          @click="cancelCompletion"
        >
          Cancel
        </button>
      </div>
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
      v-else-if="!showCreateForm && !completingHandoffId"
      class="text-[11px] text-zinc-600 italic"
    >
      No handoffs yet.
    </p>
  </div>
</template>
