<script setup lang="ts">
/**
 * /agents — Runtime execution matrix + Agent role routing.
 *
 * Tabs:
 *   Runtime Matrix (default) — profile × harness execution state
 *   Agent Roles              — Kanban Protocol agent roles (CRUD)
 *
 * Tab state persisted in ?tab= query param.
 */

import { ref, computed, onMounted, watch } from 'vue'
import { useBoardStore } from '~/stores/board'
import { Circle, Loader2, XCircle, Plus, Search } from 'lucide-vue-next'
import type { Handoff, AgentRole } from '~/types'
// Explicit imports: components in `components/lane/` are auto-imported with
// a `Lane` prefix. Without explicit imports, `<AgentRoleMatrix>` renders as
// a literal custom element and never displays.
import AgentRoleMatrix from '~/components/lane/AgentRoleMatrix.vue'
import AgentRoleFormModal from '~/components/lane/AgentRoleFormModal.vue'
import AgentRoleDetailDrawer from '~/components/lane/AgentRoleDetailDrawer.vue'

const boardStore = useBoardStore()
const route = useRoute()
const router = useRouter()

// --- Tab state ---

type TabId = 'matrix' | 'roles'
const validTabs: TabId[] = ['matrix', 'roles']

const activeTab = computed<TabId>({
  get() {
    const q = (route.query.tab as string) || 'matrix'
    return validTabs.includes(q as TabId) ? (q as TabId) : 'matrix'
  },
  set(val) {
    router.replace({ query: { ...route.query, tab: val === 'matrix' ? undefined : val } })
  },
})

// --- Runtime Matrix data ---

const profiles = ['frontend', 'backend', 'security', 'refactor', 'debug', 'general'] as const
const harnesses = ['claude-code', 'codex', 'cursor', 'opencode', 'gemini'] as const

onMounted(() => {
  if (!boardStore.columns.length) boardStore.fetchBoard()
})

const agentMatrix = computed(() => {
  return profiles.map(profile => ({
    profile,
    harnesses: harnesses.map(harness => {
      const jobs = boardStore.jobs.filter(j => j.profile === profile && j.harness === harness)
      const running = jobs.filter(j => j.status === 'running' || j.status === 'queued')
      const completed = jobs.filter(j => j.status === 'completed')
      const failed = jobs.filter(j => j.status === 'failed')
      return {
        harness,
        status: running.length > 0 ? 'running' as const : failed.length > 0 ? 'error' as const : 'idle' as const,
        totalJobs: jobs.length,
        running: running.length,
        completed: completed.length,
        failed: failed.length,
      }
    })
  }))
})

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'running': return Loader2
    case 'error': return XCircle
    default: return Circle
  }
}

const getStatusColor = (status: string) => {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'error': return 'var(--clay-red)'
    default: return 'var(--muted)'
  }
}

// --- Agent Roles data ---

const handoffs = ref<Handoff[]>([])

// Role search / filter state
const roleSearchQuery = ref('')
const roleStatusFilter = ref<'all' | 'active' | 'disabled'>('all')

// Modal / drawer state
const isFormModalVisible = ref(false)
const editingRole = ref<AgentRole | null>(null)
const isDetailDrawerVisible = ref(false)
const viewingRole = ref<AgentRole | null>(null)

// Fetch roles from store + handoffs from issues
onMounted(async () => {
  const config = useRuntimeConfig()
  await Promise.allSettled([
    boardStore.fetchAgentRoles(),
    boardStore.columns.length ? Promise.resolve() : boardStore.fetchBoard(),
  ])
  // Collect non-terminal handoffs
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

// Filtered roles for the matrix
const filteredRoles = computed(() => {
  let roles = boardStore.agentRoles

  // Status filter
  if (roleStatusFilter.value === 'active') {
    roles = roles.filter(r => r.enabled)
  } else if (roleStatusFilter.value === 'disabled') {
    roles = roles.filter(r => !r.enabled)
  }

  // Search filter
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
  // Store action already refreshes the list
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
  <section class="agents-page">
    <header class="agents-page__topbar">
      <div class="agents-page__title">
        <span class="agents-page__kicker">Workspace / DevFlow</span>
        <h1>Agents</h1>
        <p>Runtime execution and agent role routing</p>
      </div>
    </header>

    <!-- Tabs -->
    <nav class="agents-tabs" role="tablist">
      <button
        role="tab"
        :aria-selected="activeTab === 'matrix'"
        class="agents-tabs__tab"
        :class="{ 'agents-tabs__tab--active': activeTab === 'matrix' }"
        @click="activeTab = 'matrix'"
      >
        Runtime Matrix
      </button>
      <button
        role="tab"
        :aria-selected="activeTab === 'roles'"
        class="agents-tabs__tab"
        :class="{ 'agents-tabs__tab--active': activeTab === 'roles' }"
        @click="activeTab = 'roles'"
      >
        Agent Roles
      </button>
    </nav>

    <!-- Runtime Matrix -->
    <div v-show="activeTab === 'matrix'" class="agents-page__matrix">
      <div class="agents-matrix">
        <div class="agents-matrix__header">
          <div class="agents-matrix__cell agents-matrix__cell--label"></div>
          <div v-for="harness in harnesses" :key="harness" class="agents-matrix__cell agents-matrix__cell--header">
            {{ harness }}
          </div>
        </div>
        <div v-for="row in agentMatrix" :key="row.profile" class="agents-matrix__row">
          <div class="agents-matrix__cell agents-matrix__cell--label">{{ row.profile }}</div>
          <div v-for="cell in row.harnesses" :key="cell.harness" class="agents-matrix__cell">
            <div class="agent-card" :class="{ 'agent-card--active': cell.status === 'running' }">
              <component
                :is="getStatusIcon(cell.status)"
                :size="16"
                :style="{ color: getStatusColor(cell.status) }"
                :class="{ spin: cell.status === 'running' }"
              />
              <span class="agent-card__count">{{ cell.totalJobs }}</span>
              <span v-if="cell.running" class="agent-card__running">{{ cell.running }} active</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Agent Roles -->
    <div v-show="activeTab === 'roles'" class="agents-page__roles">
      <!-- Sticky header with search, filter, and New Role button -->
      <div class="roles-toolbar">
        <div class="roles-toolbar__left">
          <h2 class="roles-toolbar__title">Agent Roles</h2>
          <span class="roles-toolbar__count">{{ filteredRoles.length }} roles</span>
        </div>
        <div class="roles-toolbar__right">
          <div class="roles-toolbar__search">
            <Search :size="14" class="roles-toolbar__search-icon" />
            <input
              v-model="roleSearchQuery"
              type="text"
              placeholder="Search roles..."
              class="roles-toolbar__search-input"
              data-testid="role-search-input"
            />
          </div>
          <select
            v-model="roleStatusFilter"
            class="roles-toolbar__filter"
            data-testid="role-status-filter"
          >
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </select>
          <button
            class="roles-toolbar__new-btn"
            data-testid="new-role-btn"
            @click="openCreateRoleModal"
          >
            <Plus :size="14" />
            New Role
          </button>
        </div>
      </div>

      <div v-if="boardStore.agentRoles.length > 0" class="roles-content">
        <p class="roles-desc">
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
      <p v-else class="roles-loading">Loading roles from backend...</p>
    </div>

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
.agents-page {
  display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0;
  padding: 22px; gap: 18px; overflow-y: auto;
}
.agents-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.agents-page__title { display: flex; flex-direction: column; gap: 6px; }
.agents-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.agents-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.agents-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }

/* Tabs */
.agents-tabs {
  display: flex; gap: 2px; border-bottom: 1px solid var(--hairline);
}
.agents-tabs__tab {
  padding: 10px 18px; font-size: 0.8125rem; font-weight: 600;
  color: var(--muted); background: transparent; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
  transition: color 150ms, border-color 150ms;
}
.agents-tabs__tab:hover { color: var(--ink); }
.agents-tabs__tab--active {
  color: var(--primary); border-bottom-color: var(--primary);
}

/* Matrix */
.agents-page__matrix { flex: 1; overflow-x: auto; }
.agents-matrix {
  display: flex; flex-direction: column; gap: 2px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
  overflow: hidden;
}
.agents-matrix__header, .agents-matrix__row { display: flex; }
.agents-matrix__cell {
  flex: 1; min-width: 120px; padding: 12px 14px;
  border-bottom: 1px solid var(--hairline);
  display: flex; align-items: center; justify-content: center;
}
.agents-matrix__cell--label {
  justify-content: flex-start; min-width: 100px; flex: 0 0 100px;
  font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600;
  color: var(--ink); text-transform: capitalize;
}
.agents-matrix__cell--header {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 600;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em;
  background: var(--surface-soft);
}
.agents-matrix__row:last-child .agents-matrix__cell { border-bottom: none; }
.agent-card {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 8px 12px; border-radius: 8px; min-width: 80px;
  transition: background 150ms;
}
.agent-card--active { background: color-mix(in srgb, var(--primary) 10%, transparent); }
.agent-card__count { font-family: var(--font-mono); font-size: 1.125rem; font-weight: 700; color: var(--ink); }
.agent-card__running { font-size: 0.6875rem; color: var(--primary); font-weight: 600; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Roles */
.agents-page__roles { flex: 1; overflow-x: auto; display: flex; flex-direction: column; gap: 16px; }

/* Roles toolbar */
.roles-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  flex-wrap: wrap; position: sticky; top: 0; z-index: 10;
  padding: 12px 0; background: var(--canvas);
  border-bottom: 1px solid var(--hairline);
}
.roles-toolbar__left { display: flex; align-items: baseline; gap: 8px; }
.roles-toolbar__title {
  margin: 0; font-family: var(--font-display); font-size: 1.1rem;
  font-weight: 700; color: var(--ink);
}
.roles-toolbar__count {
  font-size: 0.8125rem; color: var(--muted);
}
.roles-toolbar__right {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.roles-toolbar__search {
  position: relative; display: flex; align-items: center;
}
.roles-toolbar__search-icon {
  position: absolute; left: 8px; color: var(--muted); pointer-events: none;
}
.roles-toolbar__search-input {
  padding: 7px 10px 7px 28px; font-size: 0.8125rem;
  color: var(--ink); background: var(--surface-card);
  border: 1px solid var(--hairline); border-radius: 8px;
  width: 200px; outline: none;
}
.roles-toolbar__search-input:focus {
  border-color: var(--primary);
}
.roles-toolbar__filter {
  padding: 7px 10px; font-size: 0.8125rem;
  color: var(--ink); background: var(--surface-card);
  border: 1px solid var(--hairline); border-radius: 8px;
  cursor: pointer;
}
.roles-toolbar__new-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 7px 12px; font-size: 0.8125rem; font-weight: 700;
  color: var(--on-primary); background: var(--primary);
  border: 1px solid var(--primary); border-radius: 8px;
  cursor: pointer; white-space: nowrap;
}
.roles-toolbar__new-btn:hover { opacity: 0.9; }

.roles-content { display: flex; flex-direction: column; gap: 16px; }
.roles-desc { color: var(--muted); font-size: 0.875rem; }
.roles-loading { color: var(--muted); font-size: 0.875rem; font-style: italic; }
</style>
