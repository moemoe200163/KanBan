<script setup lang="ts">
/**
 * AgentRoleMatrix — grid view of agent roles.
 *
 * Shows each role's display name, status, allowed profiles, and
 * whether a handoff is currently active in that role.
 * Supports both AgentRole[] (primary) and WorkerLane[] (fallback).
 */

import type { WorkerLane, Handoff, AgentRole } from '~/types'
import { Lock, Pencil, Eye } from 'lucide-vue-next'

const props = defineProps<{
  lanes?: WorkerLane[]
  roles?: AgentRole[]
  handoffs: Handoff[]
}>()

const emit = defineEmits<{
  'edit': [role: AgentRole]
  'view-detail': [role: AgentRole]
}>()

// Use roles if provided, otherwise map lanes to role-like objects
const displayRoles = computed(() => {
  if (props.roles?.length) return props.roles
  // Fallback: map WorkerLane to a minimal AgentRole-like shape
  return (props.lanes ?? []).map(l => ({
    id: l.key,
    key: l.key,
    displayName: l.displayName,
    description: l.description,
    allowedProfiles: l.allowedProfiles,
    defaultProvider: l.defaultProvider,
    defaultModel: l.defaultModel,
    allowedCommands: l.allowedCommands,
    requiredCompletionFields: l.requiredCompletionFields,
    timeoutSeconds: l.timeoutSeconds,
    retryPolicy: l.retryPolicy,
    retryMax: l.retryMax,
    nextRoles: l.nextLanes,
    humanApprovalRequired: l.humanApprovalRequired,
    enabled: true,
    isSystem: true,
    systemPrompt: '',
    taskPromptTemplate: '',
    reviewPromptTemplate: '',
    createdAt: null,
    updatedAt: null,
  } satisfies AgentRole))
})

const activeHandoffsByLane = computed(() => {
  const map: Record<string, Handoff[]> = {}
  for (const h of props.handoffs) {
    if (h.status !== 'completed' && h.status !== 'cancelled') {
      ;(map[h.toLane] ??= []).push(h)
    }
  }
  return map
})

function roleStatus(role: AgentRole): 'idle' | 'active' | 'blocked' {
  const active = activeHandoffsByLane.value[role.key]
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
      v-for="role in displayRoles"
      :key="role.key"
      class="rounded-md border border-zinc-700 p-3 text-xs transition-colors"
      :class="[
        STATUS_STYLES[roleStatus(role)].bg,
        { 'opacity-50': role.enabled === false },
      ]"
    >
      <div class="flex items-center gap-2 mb-1.5">
        <span
          class="h-2 w-2 rounded-full"
          :class="STATUS_STYLES[roleStatus(role)].dot"
        />
        <span class="font-medium text-zinc-200 truncate">
          {{ role.displayName }}
        </span>
        <Lock
          v-if="role.isSystem"
          :size="12"
          class="text-zinc-500 shrink-0"
          title="System role"
        />
      </div>

      <p class="text-zinc-500 text-[11px] leading-snug mb-2 line-clamp-2">
        {{ role.description }}
      </p>

      <div class="flex flex-wrap gap-1">
        <span
          v-for="profile in role.allowedProfiles"
          :key="profile"
          class="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[10px]"
        >
          {{ profile }}
        </span>
      </div>

      <div
        v-if="role.humanApprovalRequired"
        class="mt-2 text-[10px] text-amber-500/80"
      >
        approval required
      </div>

      <div
        v-if="activeHandoffsByLane[role.key]?.length"
        class="mt-1.5 text-[10px] text-zinc-400"
      >
        {{ activeHandoffsByLane[role.key].length }} handoff(s)
      </div>

      <div class="flex gap-1 mt-2">
        <button
          class="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 transition-colors"
          title="View details"
          @click.stop="emit('view-detail', role)"
        >
          <Eye :size="10" />
          View
        </button>
        <button
          class="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 transition-colors"
          title="Edit role"
          @click.stop="emit('edit', role)"
        >
          <Pencil :size="10" />
          Edit
        </button>
      </div>
    </div>
  </div>
</template>
