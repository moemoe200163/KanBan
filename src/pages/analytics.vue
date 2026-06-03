<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { BarChart3, CheckCircle2, Clock, Eye, Loader2, Target, TrendingUp, XCircle } from 'lucide-vue-next'

const boardStore = useBoardStore()
const config = useRuntimeConfig()
const apiBase = config.public.apiBase

interface AnalyticsData {
  issues: { total: number; byStatus: Record<string, number>; byPriority: Record<string, number>; byProfile: Record<string, number> }
  jobs: { total: number; byStatus: Record<string, number>; byProfile: Record<string, number>; running: number; inReview: number }
  quality: { total: number; passed: number; avgCoverage: number }
  audit: { total: number }
  kpis: { aiSuccessRate: number; throughput: number; avgCycleTimeMin: number; totalIssues: number; totalJobs: number; activeRuns: number; inReview: number }
}

const stats = ref<AnalyticsData | null>(null)

const dateFrom = ref('')
const dateTo = ref('')
const activePreset = ref<string | null>('7d')

const datePresets = [
  { value: '1d', label: 'Last 24h', days: 1 },
  { value: '7d', label: 'Last 7 days', days: 7 },
  { value: '30d', label: 'Last 30 days', days: 30 },
  { value: null, label: 'All time', days: null },
]

function toISOString(local: string): string {
  if (!local) return ''
  return local.length === 16 ? local + ':00Z' : local + 'Z'
}

function applyPreset(preset: { value: string | null; days: number | null }) {
  activePreset.value = preset.value
  if (preset.days == null) {
    dateFrom.value = ''
    dateTo.value = ''
  } else {
    const now = new Date()
    const from = new Date(now)
    from.setDate(from.getDate() - preset.days)
    dateFrom.value = from.toISOString().slice(0, 16)
    dateTo.value = now.toISOString().slice(0, 16)
  }
  fetchStats()
}

function clearAnalyticsFilters() {
  applyPreset(datePresets.find(p => p.value === '7d')!)
}

const currentRangeLabel = computed(() => {
  if (!dateFrom.value && !dateTo.value) return ''
  const fmt = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ', ' +
      d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  }
  const from = dateFrom.value ? fmt(dateFrom.value) : '...'
  const to = dateTo.value ? fmt(dateTo.value) : '...'
  return `${from} \u2014 ${to}`
})

const fetchStats = async () => {
  try {
    const params = new URLSearchParams()
    if (dateFrom.value) params.set('date_from', toISOString(dateFrom.value))
    if (dateTo.value) params.set('date_to', toISOString(dateTo.value))
    const qs = params.toString()
    const url = qs ? `${apiBase}/analytics/stats?${qs}` : `${apiBase}/analytics/stats`
    const res = await fetch(url)
    if (res.ok) stats.value = await res.json()
  } catch {
    // fallback to board store
  }
}

onMounted(() => {
  if (!boardStore.columns.length) boardStore.fetchBoard()
  boardStore.fetchJobs()
  applyPreset(datePresets.find(p => p.value === '7d')!)
})

// Fallback computed values from board store (used if API fails)
const totalIssues = computed(() =>
  stats.value?.issues.total ?? boardStore.columns.reduce((sum, col) => sum + col.issues.length, 0)
)

const columnStats = computed(() => {
  if (stats.value?.issues.byStatus) {
    const byStatus = stats.value.issues.byStatus
    return boardStore.columns.map(col => ({
      id: col.id,
      title: col.title,
      count: byStatus[col.id] ?? col.issues.length,
      pct: totalIssues.value ? Math.round(((byStatus[col.id] ?? 0) / totalIssues.value) * 100) : 0,
      color: col.color,
    }))
  }
  return boardStore.columns.map(col => ({
    id: col.id,
    title: col.title,
    count: col.issues.length,
    pct: totalIssues.value ? Math.round((col.issues.length / totalIssues.value) * 100) : 0,
    color: col.color,
  }))
})

const jobStats = computed(() => {
  if (stats.value?.jobs) {
    const s = stats.value.jobs.byStatus
    return {
      total: stats.value.jobs.total,
      running: s.running ?? 0,
      queued: s.queued ?? 0,
      review: s.review_required ?? 0,
      completed: s.completed ?? 0,
      failed: s.failed ?? 0,
      cancelled: s.cancelled ?? 0,
    }
  }
  const jobs = boardStore.jobs
  return {
    total: jobs.length,
    running: jobs.filter(j => j.status === 'running').length,
    queued: jobs.filter(j => j.status === 'queued').length,
    review: jobs.filter(j => j.status === 'review_required').length,
    completed: jobs.filter(j => j.status === 'completed').length,
    failed: jobs.filter(j => j.status === 'failed').length,
    cancelled: jobs.filter(j => j.status === 'cancelled').length,
  }
})

const kpis = computed(() => stats.value?.kpis ?? {
  aiSuccessRate: 0,
  throughput: 0,
  avgCycleTimeMin: 0,
  totalIssues: totalIssues.value,
  totalJobs: jobStats.value.total,
  activeRuns: jobStats.value.running,
  inReview: jobStats.value.review,
})

const profileStats = computed(() => {
  if (stats.value?.jobs.byProfile) {
    return Object.entries(stats.value.jobs.byProfile).sort((a, b) => b[1] - a[1])
  }
  const map = new Map<string, number>()
  boardStore.jobs.forEach(j => {
    map.set(j.profile, (map.get(j.profile) ?? 0) + 1)
  })
  return Array.from(map.entries()).sort((a, b) => b[1] - a[1])
})

const priorityStats = computed(() => {
  if (!stats.value?.issues.byPriority) return []
  return Object.entries(stats.value.issues.byPriority).sort((a, b) => b[1] - a[1])
})
</script>

<template>
  <section class="analytics-page">
    <header class="analytics-page__topbar">
      <div class="analytics-page__title">
        <span class="analytics-page__kicker">Workspace / DevFlow</span>
        <h1>Analytics</h1>
        <p>Board stats, job metrics, and AI performance KPIs</p>
      </div>
    </header>

    <!-- Date range toolbar -->
    <div class="analytics-page__toolbar">
      <div class="analytics-page__presets">
        <button
          v-for="p in datePresets"
          :key="p.value ?? 'all'"
          class="filter-btn"
          :class="{ 'filter-btn--active': activePreset === p.value }"
          @click="applyPreset(p)"
        >
          {{ p.label }}
        </button>
      </div>
      <div class="analytics-page__date-inputs">
        <input type="datetime-local" v-model="dateFrom" class="search-input" @change="activePreset = null" />
        <input type="datetime-local" v-model="dateTo" class="search-input" @change="activePreset = null" />
        <button class="filter-btn" @click="clearAnalyticsFilters">Clear</button>
      </div>
      <div v-if="currentRangeLabel" class="analytics-page__range-label">{{ currentRangeLabel }}</div>
    </div>

    <div class="analytics-page__grid">
      <!-- Enhanced KPI Cards -->
      <div class="kpi-row">
        <div class="kpi-card">
          <span class="kpi-card__value">{{ kpis.totalIssues }}</span>
          <span class="kpi-card__label">Total Issues</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value">{{ kpis.totalJobs }}</span>
          <span class="kpi-card__label">Total Jobs</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value" style="color: var(--primary)">{{ kpis.activeRuns }}</span>
          <span class="kpi-card__label">Active Runs</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value" style="color: var(--dusty-blue)">{{ kpis.inReview }}</span>
          <span class="kpi-card__label">In Review</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value" style="color: var(--sage)">{{ kpis.aiSuccessRate }}%</span>
          <span class="kpi-card__label">AI Success Rate</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value">{{ kpis.throughput }}</span>
          <span class="kpi-card__label">Throughput</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value">{{ kpis.avgCycleTimeMin }}m</span>
          <span class="kpi-card__label">Avg Cycle Time</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value">{{ stats?.audit.total ?? 0 }}</span>
          <span class="kpi-card__label">Audit Events</span>
        </div>
      </div>

      <!-- Column Distribution -->
      <div class="analytics-card">
        <h3>Board Distribution</h3>
        <div class="bar-chart">
          <div v-for="col in columnStats" :key="col.id" class="bar-row">
            <span class="bar-row__label">{{ col.title }}</span>
            <div class="bar-row__track">
              <div
                class="bar-row__fill"
                :style="{ width: col.pct + '%', background: col.color }"
              />
            </div>
            <span class="bar-row__count">{{ col.count }}</span>
          </div>
        </div>
      </div>

      <!-- Job Status Distribution -->
      <div class="analytics-card">
        <h3>Job Status</h3>
        <div class="status-grid">
          <div class="status-item">
            <Loader2 :size="16" style="color: var(--primary)" class="spin" />
            <span class="status-item__count">{{ jobStats.running }}</span>
            <span class="status-item__label">Running</span>
          </div>
          <div class="status-item">
            <Clock :size="16" style="color: var(--amber)" />
            <span class="status-item__count">{{ jobStats.queued }}</span>
            <span class="status-item__label">Queued</span>
          </div>
          <div class="status-item">
            <Eye :size="16" style="color: var(--dusty-blue)" />
            <span class="status-item__count">{{ jobStats.review }}</span>
            <span class="status-item__label">Review</span>
          </div>
          <div class="status-item">
            <CheckCircle2 :size="16" style="color: var(--sage)" />
            <span class="status-item__count">{{ jobStats.completed }}</span>
            <span class="status-item__label">Completed</span>
          </div>
          <div class="status-item">
            <XCircle :size="16" style="color: var(--clay-red)" />
            <span class="status-item__count">{{ jobStats.failed }}</span>
            <span class="status-item__label">Failed</span>
          </div>
        </div>
      </div>

      <!-- Priority Breakdown -->
      <div class="analytics-card">
        <h3>Issues by Priority</h3>
        <div v-if="!priorityStats.length" class="analytics-card__empty">No issues yet</div>
        <div v-else class="profile-list">
          <div v-for="[priority, count] in priorityStats" :key="priority" class="profile-row">
            <span class="profile-row__name">{{ priority }}</span>
            <div class="profile-row__bar">
              <div
                class="profile-row__fill"
                :style="{ width: Math.round((count / totalIssues) * 100) + '%', background: priority === 'critical' ? 'var(--clay-red)' : priority === 'high' ? 'var(--amber)' : priority === 'medium' ? 'var(--dusty-blue)' : 'var(--muted)' }"
              />
            </div>
            <span class="profile-row__count">{{ count }}</span>
          </div>
        </div>
      </div>

      <!-- Profile Breakdown -->
      <div class="analytics-card">
        <h3>Jobs by Profile</h3>
        <div v-if="!profileStats.length" class="analytics-card__empty">No jobs yet</div>
        <div v-else class="profile-list">
          <div v-for="[profile, count] in profileStats" :key="profile" class="profile-row">
            <span class="profile-row__name">{{ profile }}</span>
            <div class="profile-row__bar">
              <div
                class="profile-row__fill"
                :style="{ width: Math.round((count / jobStats.total) * 100) + '%' }"
              />
            </div>
            <span class="profile-row__count">{{ count }}</span>
          </div>
        </div>
      </div>

      <!-- Quality Gate Summary -->
      <div v-if="stats?.quality.total" class="analytics-card">
        <h3>Quality Gate</h3>
        <div class="status-grid">
          <div class="status-item">
            <Target :size="16" style="color: var(--primary)" />
            <span class="status-item__count">{{ stats.quality.total }}</span>
            <span class="status-item__label">Total Runs</span>
          </div>
          <div class="status-item">
            <CheckCircle2 :size="16" style="color: var(--sage)" />
            <span class="status-item__count">{{ stats.quality.passed }}</span>
            <span class="status-item__label">Passed</span>
          </div>
          <div class="status-item">
            <TrendingUp :size="16" style="color: var(--dusty-blue)" />
            <span class="status-item__count">{{ stats.quality.avgCoverage }}%</span>
            <span class="status-item__label">Avg Coverage</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.analytics-page {
  display: flex; flex-direction: column; height: 100vh; min-width: 0;
  padding: 22px; gap: 18px; overflow-y: auto;
}
.analytics-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.analytics-page__title { display: flex; flex-direction: column; gap: 6px; }
.analytics-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.analytics-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.analytics-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }
.analytics-page__grid { display: flex; flex-direction: column; gap: 18px; }
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.kpi-card {
  display: flex; flex-direction: column; gap: 4px; padding: 18px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
}
.kpi-card__value { font-family: var(--font-display); font-size: 2rem; font-weight: 700; color: var(--ink); }
.kpi-card__label { color: var(--muted); font-size: 0.8125rem; }
.analytics-card {
  display: flex; flex-direction: column; gap: 14px; padding: 18px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
}
.analytics-card h3 { font-family: var(--font-display); font-size: 0.9375rem; font-weight: 700; color: var(--ink); }
.analytics-card__empty { color: var(--muted); font-size: 0.875rem; }
.bar-chart { display: flex; flex-direction: column; gap: 8px; }
.bar-row { display: flex; align-items: center; gap: 10px; }
.bar-row__label { flex: 0 0 100px; font-size: 0.8125rem; color: var(--ink); font-weight: 500; }
.bar-row__track { flex: 1; height: 20px; background: var(--surface-soft); border-radius: 4px; overflow: hidden; }
.bar-row__fill { height: 100%; border-radius: 4px; transition: width 300ms ease; }
.bar-row__count { flex: 0 0 30px; text-align: right; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--ink); }
.status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 12px; }
.status-item { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px; border-radius: 8px; background: var(--surface-soft); }
.status-item__count { font-family: var(--font-mono); font-size: 1.25rem; font-weight: 700; color: var(--ink); }
.status-item__label { font-size: 0.75rem; color: var(--muted); }
.profile-list { display: flex; flex-direction: column; gap: 8px; }
.profile-row { display: flex; align-items: center; gap: 10px; }
.profile-row__name { flex: 0 0 80px; font-size: 0.8125rem; color: var(--ink); font-weight: 500; text-transform: capitalize; }
.profile-row__bar { flex: 1; height: 16px; background: var(--surface-soft); border-radius: 4px; overflow: hidden; }
.profile-row__fill { height: 100%; background: var(--primary); border-radius: 4px; transition: width 300ms; }
.profile-row__count { flex: 0 0 30px; text-align: right; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.analytics-page__toolbar {
  display: flex; flex-direction: column; gap: 8px;
}
.analytics-page__presets {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.analytics-page__date-inputs {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.filter-btn {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--muted); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.filter-btn:hover { border-color: var(--primary); color: var(--ink); }
.filter-btn--active {
  background: var(--primary); color: var(--on-primary); border-color: var(--primary);
}
.search-input {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--ink); font-size: 0.8125rem;
  font-family: var(--font-mono); transition: border-color 150ms;
}
.search-input:focus { outline: none; border-color: var(--primary); }
.analytics-page__range-label {
  color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono);
}
</style>
