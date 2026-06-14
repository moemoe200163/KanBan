<script setup lang="ts">
/**
 * /lanes — Worker Lanes / Agent Role management.
 *
 * The primary hub for managing Kanban Protocol agent roles:
 * - Role matrix with search/filter
 * - Create / edit / detail drawer
 * - Active handoff counts per role
 *
 * This page is the canonical destination for role management.
 * The legacy /agents?tab=roles path redirects here.
 */

import { ref, computed, onMounted } from 'vue'
import { useBoardStore } from '~/stores/board'
import { Circle, Loader2, Plus, Search, XCircle } from 'lucide-vue-next'
import type { Handoff, AgentRole } from '~/types'
// Explicit imports: components in `components/lane/` are auto-imported with
// a `Lane` prefix. Without explicit imports, `<AgentRoleMatrix>` renders as
// a literal custom element and never displays.
import AgentRoleMatrix from '~/components/lane/AgentRoleMatrix.vue'
import AgentRoleFormModal from '~/components/lane/AgentRoleFormModal.vue'
import AgentRoleDetailDrawer from '~/components/lane/AgentRoleDetailDrawer.vue'

const boardStore = useBoardStore()

// --- Role search / filter state ---

const roleSearchQuery = ref('')
const roleStatusFilter = ref<'all' | 'active' | 'disabled'>('all')

// --- Modal / drawer state ---

const isFormModalVisible = ref(false)
const editingRole = ref<AgentRole | null>(null)
const isDetailDrawerVisible = ref(false)
const viewingRole = ref<AgentRole | null>(null)

// --- Data fetching ---

const handoffs = ref<Handoff[]>([])

onMounted(async () => {
  const config = useRuntimeConfig()
  await Promise.allSettled([
    boardStore.fetchAgentRoles(),
    boardStore.columns.length ? Promise.resolve() : boardStore.fetchBoard(),
  ])
  // Collect non-terminal handoffs from all issues
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

// --- Filtered roles for the matrix ---

const filteredRoles = computed(() => {
  let roles = boardStore.agentRoles

  if (roleStatusFilter.value === 'active') {
    roles = roles.filter(r => r.enabled)
  } else if (roleStatusFilter.value === 'disabled') {
    roles = roles.filter(r => !r.enabled)
  }

  const q = roleSearchQuery.value.toLowerCase().trim()
  if (q) {
    roles = roles.filter(r =>
      r.displayName.toLowerCase().includes(q)
      || r.key.toLowerCase().includes(q)
      || r.description.toLowerCase().includes(q)
    )
  }

  return roles
})

// --- Form modal handlers ---

function openCreateRoleModal() {
  editingRole.value = null
  isFormModalVisible.value = true
}

function openEditRoleModal(role: AgentRole) {
  editingRole.value = role
  isFormModalVisible.value = true
}

function closeFormModal() {
  isFormModalVisible.value = false
  editingRole.value = null
}

function onRoleSaved(_role: AgentRole) {
  closeFormModal()
}

// --- Detail drawer handlers ---

function openDetailDrawer(role: AgentRole) {
  viewingRole.value = role
  isDetailDrawerVisible.value = true
}

function closeDetailDrawer() {
  isDetailDrawerVisible.value = false
  viewingRole.value = null
}

function onEditFromDrawer(role: AgentRole) {
  closeDetailDrawer()
  openEditRoleModal(role)
}
</script>

<template>
  <section class="lanes-page">
    <header class="lanes-page__topbar">
      <div class="lanes-page__title">
        <span class="lanes-page__kicker">Workspace / DevFlow</span>
        <h1>Worker Lanes</h1>
        <p>Agent role definitions and routing configuration</p>
      </div>
    </header>

    <!-- Sticky toolbar -->
    <div class="lanes-toolbar">
      <div class="lanes-toolbar__left">
        <h2 class="lanes-toolbar__title">Agent Roles</h2>
        <span class="lanes-toolbar__count">{{ filteredRoles.length }} roles</span>
      </div>
      <div class="lanes-toolbar__right">
        <div class="lanes-toolbar__search">
          <Search :size="14" class="lanes-toolbar__search-icon" />
          <input
            v-model="roleSearchQuery"
            type="text"
            placeholder="Search roles..."
            class="lanes-toolbar__search-input"
            data-testid="role-search-input"
          />
        </div>
        <select
          v-model="roleStatusFilter"
          class="lanes-toolbar__filter"
          data-testid="role-status-filter"
        >
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
        <button
          class="lanes-toolbar__new-btn"
          data-testid="new-role-btn"
          @click="openCreateRoleModal"
        >
          <Plus :size="14" />
          New Role
        </button>
      </div>
    </div>

    <!-- Role matrix -->
    <div v-if="boardStore.agentRoles.length > 0" class="lanes-content">
      <p class="lanes-desc">
        Subagent role definitions. Each role specifies allowed profiles,
        completion requirements, and approval policies.
      </p>
      <AgentRoleMatrix
        :roles="filteredRoles"
        :handoffs="handoffs"
        @edit="openEditRoleModal"
        @view-detail="openDetailDrawer"
      />
    </div>
    <p v-else class="lanes-loading">Loading roles from backend...</p>

    <!-- Form Modal -->
    <AgentRoleFormModal
      :role="editingRole"
      :visible="isFormModalVisible"
      @close="closeFormModal"
      @saved="onRoleSaved"
    />

    <!-- Detail Drawer -->
    <AgentRoleDetailDrawer
      :role="viewingRole"
      :visible="isDetailDrawerVisible"
      @close="closeDetailDrawer"
      @edit="onEditFromDrawer"
    />
  </section>
</template>

<style scoped>
.lanes-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}

.lanes-page__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.lanes-page__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lanes-page__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.lanes-page__title h1 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
}

.lanes-page__title p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.9rem;
}

/* Toolbar */
.lanes-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 12px 0;
  background: var(--canvas);
  border-bottom: 1px solid var(--hairline);
}

.lanes-toolbar__left {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.lanes-toolbar__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--ink);
}

.lanes-toolbar__count {
  font-size: 0.8125rem;
  color: var(--muted);
}

.lanes-toolbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.lanes-toolbar__search {
  position: relative;
  display: flex;
  align-items: center;
}

.lanes-toolbar__search-icon {
  position: absolute;
  left: 8px;
  color: var(--muted);
  pointer-events: none;
}

.lanes-toolbar__search-input {
  padding: 7px 10px 7px 28px;
  font-size: 0.8125rem;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  width: 200px;
  outline: none;
}

.lanes-toolbar__search-input:focus {
  border-color: var(--primary);
}

.lanes-toolbar__filter {
  padding: 7px 10px;
  font-size: 0.8125rem;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  cursor: pointer;
}

.lanes-toolbar__new-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 7px 12px;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
}

.lanes-toolbar__new-btn:hover {
  opacity: 0.9;
}

/* Content */
.lanes-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.lanes-desc {
  color: var(--muted);
  font-size: 0.875rem;
}

.lanes-loading {
  color: var(--muted);
  font-size: 0.875rem;
  font-style: italic;
}
</style>