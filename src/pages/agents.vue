<script setup lang="ts">
/**
 * /agents — Runtime execution matrix + Agent role routing.
 *
 * Tabs:
 *   Runtime Matrix (default) — profile × harness execution state
 *   Agent Roles              — 8 Kanban Protocol agent roles
 *
 * Tab state persisted in ?tab= query param.
 */

import { useBoardStore } from '~/stores/board'
import { Bot, Circle, Loader2, XCircle } from 'lucide-vue-next'
import type { WorkerLane, Handoff } from '~/types'
// Explicit import: AgentRoleMatrix lives in `components/lane/`, so
// Nuxt's auto-import registers it as `LaneAgentRoleMatrix`. Without
// this explicit import, `<AgentRoleMatrix>` is rendered as a literal
// custom element (`<agentrolematrix>`) and the roles matrix never shows.
import AgentRoleMatrix from '~/components/lane/AgentRoleMatrix.vue'

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

const lanes = ref<WorkerLane[]>([])
const handoffs = ref<Handoff[]>([])

// Pre-fetch roles data on mount (lightweight)
onMounted(async () => {
  const config = useRuntimeConfig()
  const [lanesRes, boardRes] = await Promise.allSettled([
    $fetch<{ lanes: WorkerLane[] }>(`${config.public.apiBase}/lanes`),
    boardStore.columns.length ? Promise.resolve() : boardStore.fetchBoard(),
  ])
  if (lanesRes.status === 'fulfilled') {
    lanes.value = lanesRes.value.lanes
  }
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
      <div v-if="lanes.length > 0" class="roles-content">
        <div class="roles-header">
          <p class="roles-desc">
            Subagent role definitions. Each role specifies allowed profiles,
            completion requirements, and approval policies.
          </p>
        </div>
        <AgentRoleMatrix :lanes="lanes" :handoffs="handoffs" />
      </div>
      <p v-else class="roles-loading">Loading roles from backend...</p>
    </div>
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
.agents-page__roles { flex: 1; overflow-x: auto; }
.roles-content { display: flex; flex-direction: column; gap: 16px; }
.roles-desc { color: var(--muted); font-size: 0.875rem; }
.roles-loading { color: var(--muted); font-size: 0.875rem; font-style: italic; }
</style>
