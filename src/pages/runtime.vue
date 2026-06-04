<script setup lang="ts">
/**
 * /runtime — Agent Runtime Control Plane
 *
 * Three-panel view:
 *   Workers  — registered agent workers with status and capabilities
 *   Runs     — execution runs with status, role, and log access
 *   Logs     — real-time log streaming for selected run
 *
 * Tab state persisted in ?tab= query param.
 */
import { useRuntime, type RuntimeRun } from '~/composables/useRuntime'
import WorkerCard from '~/components/runtime/WorkerCard.vue'
import RunLogViewer from '~/components/runtime/RunLogViewer.vue'
import {
  Activity,
  Bot,
  Circle,
  Clock,
  RefreshCw,
  ScrollText,
  Users,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

// --- Tab state ---

type TabId = 'workers' | 'runs'
const validTabs: TabId[] = ['workers', 'runs']

const activeTab = computed<TabId>({
  get() {
    const q = (route.query.tab as string) || 'workers'
    return validTabs.includes(q as TabId) ? (q as TabId) : 'workers'
  },
  set(val) {
    router.replace({ query: { ...route.query, tab: val === 'workers' ? undefined : val } })
  },
})

// --- Runtime data ---

const {
  workers,
  runs,
  isLoading,
  error,
  lastUpdated,
  fetchRunLogs,
  refresh,
  startPolling,
  stopPolling,
} = useRuntime({ refreshMs: 4000 })

// --- Selected run for log viewer ---

const selectedRunId = ref<string | null>(null)
const selectedRunLogs = ref<any[]>([])

const selectRun = async (run: RuntimeRun) => {
  if (selectedRunId.value === run.id) {
    selectedRunId.value = null
    selectedRunLogs.value = []
    return
  }
  selectedRunId.value = run.id
  selectedRunLogs.value = await fetchRunLogs(run.id)
}

// --- Status helpers ---

const runStatusColor = (status: string): string => {
  switch (status) {
    case 'pending': return 'var(--muted)'
    case 'claimed': return 'var(--amber)'
    case 'running': return 'var(--dusty-blue)'
    case 'completed': return 'var(--sage)'
    case 'failed': return 'var(--clay-red)'
    case 'cancelled': return 'var(--muted)'
    default: return 'var(--muted)'
  }
}

const formatTime = (iso: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// --- Lifecycle ---

onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})

// --- Computed stats ---

const workerStats = computed(() => {
  const total = workers.value.length
  const idle = workers.value.filter(w => w.status === 'idle').length
  const active = workers.value.filter(w => w.status === 'running' || w.status === 'claimed').length
  const stopped = workers.value.filter(w => w.status === 'stopped' || w.status === 'error').length
  return { total, idle, active, stopped }
})

const runStats = computed(() => {
  const total = runs.value.length
  const pending = runs.value.filter(r => r.status === 'pending').length
  const running = runs.value.filter(r => r.status === 'running' || r.status === 'claimed').length
  const completed = runs.value.filter(r => r.status === 'completed').length
  const failed = runs.value.filter(r => r.status === 'failed').length
  return { total, pending, running, completed, failed }
})
</script>

<template>
  <section class="runtime-page">
    <header class="runtime-page__topbar">
      <div class="runtime-page__title">
        <span class="runtime-page__kicker">Workspace / DevFlow</span>
        <h1>Runtime Control Plane</h1>
        <p>Monitor agent workers, execution runs, and real-time logs.</p>
      </div>
      <div class="runtime-page__actions">
        <button class="runtime-page__refresh" @click="refresh" :disabled="isLoading">
          <RefreshCw :size="14" :class="{ 'spin': isLoading }" />
          Refresh
        </button>
      </div>
    </header>

    <!-- Stats row -->
    <div class="runtime-page__stats">
      <div class="runtime-page__stat">
        <Users :size="16" />
        <span class="runtime-page__stat-value">{{ workerStats.total }}</span>
        <span class="runtime-page__stat-label">Workers</span>
        <span class="runtime-page__stat-detail" v-if="workerStats.active">{{ workerStats.active }} active</span>
      </div>
      <div class="runtime-page__stat">
        <Activity :size="16" />
        <span class="runtime-page__stat-value">{{ runStats.total }}</span>
        <span class="runtime-page__stat-label">Runs</span>
        <span class="runtime-page__stat-detail" v-if="runStats.running">{{ runStats.running }} running</span>
      </div>
      <div class="runtime-page__stat">
        <Circle :size="16" style="color: var(--sage)" />
        <span class="runtime-page__stat-value">{{ runStats.completed }}</span>
        <span class="runtime-page__stat-label">Completed</span>
      </div>
      <div class="runtime-page__stat">
        <Circle :size="16" style="color: var(--clay-red)" />
        <span class="runtime-page__stat-value">{{ runStats.failed }}</span>
        <span class="runtime-page__stat-label">Failed</span>
      </div>
    </div>

    <!-- Tab bar -->
    <div class="runtime-page__tabs">
      <button
        class="runtime-page__tab"
        :class="{ 'runtime-page__tab--active': activeTab === 'workers' }"
        @click="activeTab = 'workers'"
      >
        <Bot :size="14" />
        Workers
      </button>
      <button
        class="runtime-page__tab"
        :class="{ 'runtime-page__tab--active': activeTab === 'runs' }"
        @click="activeTab = 'runs'"
      >
        <Activity :size="14" />
        Runs
      </button>
    </div>

    <!-- Content area -->
    <div class="runtime-page__content">
      <!-- Workers tab -->
      <div v-if="activeTab === 'workers'" class="runtime-page__workers">
        <div v-if="!workers.length && !isLoading" class="runtime-page__empty">
          <Bot :size="32" />
          <p>No workers registered yet.</p>
          <p class="runtime-page__empty-hint">
            Workers register automatically when <code>ALLOW_REAL_LLM_EXECUTION=true</code>.
          </p>
        </div>
        <div v-else class="runtime-page__worker-grid">
          <WorkerCard
            v-for="worker in workers"
            :key="worker.id"
            :worker="worker"
          />
        </div>
      </div>

      <!-- Runs tab -->
      <div v-if="activeTab === 'runs'" class="runtime-page__runs">
        <div class="runtime-page__runs-layout">
          <!-- Run list -->
          <div class="runtime-page__run-list">
            <div v-if="!runs.length && !isLoading" class="runtime-page__empty">
              <Activity :size="32" />
              <p>No runs yet.</p>
            </div>
            <div
              v-for="run in runs"
              :key="run.id"
              class="runtime-page__run-item"
              :class="{ 'runtime-page__run-item--selected': selectedRunId === run.id }"
              @click="selectRun(run)"
            >
              <div class="runtime-page__run-header">
                <span class="runtime-page__run-id">{{ run.id.slice(0, 16) }}...</span>
                <span
                  class="runtime-page__run-status"
                  :style="{ color: runStatusColor(run.status) }"
                >
                  {{ run.status }}
                </span>
              </div>
              <div class="runtime-page__run-meta">
                <span v-if="run.issueKey">{{ run.issueKey }}</span>
                <span v-if="run.requiredRole" class="runtime-page__run-role">{{ run.requiredRole }}</span>
                <span class="runtime-page__run-time">{{ formatTime(run.createdAt) }}</span>
              </div>
            </div>
          </div>

          <!-- Log viewer -->
          <div class="runtime-page__log-panel">
            <RunLogViewer :runId="selectedRunId" :initialLogs="selectedRunLogs" />
          </div>
        </div>
      </div>
    </div>

    <!-- Error toast -->
    <div v-if="error" class="runtime-page__error">
      {{ error }}
    </div>
  </section>
</template>

<style scoped>
.runtime-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: var(--space-6);
  gap: var(--space-4);
  overflow-y: auto;
}

.runtime-page__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.runtime-page__kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.runtime-page__title h1 {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  color: var(--ink);
  margin: var(--space-1) 0;
}

.runtime-page__title p {
  font-size: 14px;
  color: var(--muted);
}

.runtime-page__actions {
  display: flex;
  gap: var(--space-2);
}

.runtime-page__refresh {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  color: var(--body);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.runtime-page__refresh:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.runtime-page__refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Stats */
.runtime-page__stats {
  display: flex;
  gap: var(--space-4);
}

.runtime-page__stat {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
}

.runtime-page__stat-value {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--ink);
}

.runtime-page__stat-label {
  font-size: 13px;
  color: var(--muted);
}

.runtime-page__stat-detail {
  font-size: 12px;
  color: var(--sage);
  margin-left: var(--space-1);
}

/* Tabs */
.runtime-page__tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--hairline);
  padding-bottom: 0;
}

.runtime-page__tab {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  border: none;
  background: none;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.15s ease;
}

.runtime-page__tab:hover {
  color: var(--body);
}

.runtime-page__tab--active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

/* Content */
.runtime-page__content {
  flex: 1;
  min-height: 0;
}

.runtime-page__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-12) 0;
  color: var(--muted);
}

.runtime-page__empty-hint {
  font-size: 13px;
  color: var(--muted-soft);
}

.runtime-page__empty-hint code {
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--surface-soft);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}

/* Workers grid */
.runtime-page__worker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-3);
}

/* Runs layout */
.runtime-page__runs-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: var(--space-4);
  height: calc(100vh - 280px);
}

.runtime-page__run-list {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.runtime-page__run-item {
  padding: var(--space-3);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--surface-card);
  cursor: pointer;
  transition: all 0.15s ease;
}

.runtime-page__run-item:hover {
  border-color: var(--primary);
}

.runtime-page__run-item--selected {
  border-color: var(--primary);
  background: rgba(204, 120, 92, 0.04);
}

.runtime-page__run-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-1);
}

.runtime-page__run-id {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
}

.runtime-page__run-status {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  text-transform: capitalize;
}

.runtime-page__run-meta {
  display: flex;
  gap: var(--space-2);
  font-size: 12px;
  color: var(--muted);
}

.runtime-page__run-role {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 0 6px;
  background: var(--surface-soft);
  border-radius: var(--radius-sm);
  text-transform: capitalize;
}

.runtime-page__run-time {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
}

.runtime-page__log-panel {
  min-height: 0;
}

/* Error */
.runtime-page__error {
  position: fixed;
  bottom: var(--space-4);
  right: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--clay-red);
  color: var(--on-primary);
  border-radius: var(--radius-md);
  font-size: 13px;
  z-index: 100;
}
</style>
