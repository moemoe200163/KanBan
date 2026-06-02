<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { BarChart3, CheckCircle2, Clock, Eye, Loader2, XCircle } from 'lucide-vue-next'

const boardStore = useBoardStore()

onMounted(() => {
  if (!boardStore.columns.length) boardStore.fetchBoard()
  boardStore.fetchJobs()
})

const totalIssues = computed(() =>
  boardStore.columns.reduce((sum, col) => sum + col.issues.length, 0)
)

const columnStats = computed(() =>
  boardStore.columns.map(col => ({
    id: col.id,
    title: col.title,
    count: col.issues.length,
    pct: totalIssues.value ? Math.round((col.issues.length / totalIssues.value) * 100) : 0,
    color: col.color,
  }))
)

const jobStats = computed(() => {
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

const profileStats = computed(() => {
  const map = new Map<string, number>()
  boardStore.jobs.forEach(j => {
    map.set(j.profile, (map.get(j.profile) ?? 0) + 1)
  })
  return Array.from(map.entries()).sort((a, b) => b[1] - a[1])
})
</script>

<template>
  <section class="analytics-page">
    <header class="analytics-page__topbar">
      <div class="analytics-page__title">
        <span class="analytics-page__kicker">Workspace / DevFlow</span>
        <h1>Analytics</h1>
        <p>Board stats and job status distribution</p>
      </div>
    </header>

    <div class="analytics-page__grid">
      <!-- KPI Cards -->
      <div class="kpi-row">
        <div class="kpi-card">
          <span class="kpi-card__value">{{ totalIssues }}</span>
          <span class="kpi-card__label">Total Issues</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value">{{ jobStats.total }}</span>
          <span class="kpi-card__label">Total Jobs</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value" style="color: var(--primary)">{{ jobStats.running }}</span>
          <span class="kpi-card__label">Active Runs</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-card__value" style="color: var(--dusty-blue)">{{ jobStats.review }}</span>
          <span class="kpi-card__label">In Review</span>
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
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
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
</style>
