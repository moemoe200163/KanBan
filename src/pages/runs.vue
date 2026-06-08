<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useRecentJobs } from '~/composables/useRecentJobs'
import type { ECCJobStatus } from '~/types'
import { Activity, CheckCircle2, Clock, Eye, Loader2, Sparkles, Square, XCircle } from 'lucide-vue-next'

const boardStore = useBoardStore()
const { jobs: recentJobs, isLoading, start, stop } = useRecentJobs({ refreshMs: 4000, limit: 50 })

onMounted(() => {
  start()
  boardStore.fetchJobs()
})
onUnmounted(() => stop())

const statusFilter = ref<ECCJobStatus | 'all'>('all')
const statusOptions: Array<{ value: ECCJobStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'queued', label: 'Queued' },
  { value: 'review_required', label: 'Review' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

const filteredJobs = computed(() => {
  if (statusFilter.value === 'all') return recentJobs.value
  return recentJobs.value.filter(j => j.status === statusFilter.value)
})

const getStatusIcon = (status: ECCJobStatus) => {
  switch (status) {
    case 'running': return Loader2
    case 'queued': return Clock
    case 'review_required': return Eye
    case 'completed': return CheckCircle2
    case 'failed': return XCircle
    case 'cancelled': return Square
    default: return Activity
  }
}

const getStatusColor = (status: ECCJobStatus): string => {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'queued': return 'var(--amber)'
    case 'review_required': return 'var(--dusty-blue)'
    case 'completed': return 'var(--sage)'
    case 'failed': return 'var(--clay-red)'
    case 'cancelled': return 'var(--muted)'
    default: return 'var(--muted)'
  }
}

const handleOpenJob = (job: typeof recentJobs.value[0]) => {
  boardStore.openJob(job)
}

const clearFilter = () => {
  statusFilter.value = 'all'
}
</script>

<template>
  <section class="runs-page">
    <header class="runs-page__topbar">
      <div class="runs-page__title">
        <span class="runs-page__kicker">Workspace / DevFlow</span>
        <h1>Runs</h1>
        <p>{{ filteredJobs.length }} jobs{{ statusFilter !== 'all' ? ` (${statusFilter})` : '' }}</p>
      </div>
    </header>

    <div class="runs-page__toolbar">
      <button
        v-for="opt in statusOptions"
        :key="opt.value"
        class="runs-page__filter"
        :class="{ 'runs-page__filter--active': statusFilter === opt.value }"
        @click="statusFilter = opt.value"
      >
        {{ opt.label }}
      </button>
    </div>

    <div v-if="isLoading && !filteredJobs.length" class="runs-page__empty">
      <Loader2 :size="24" class="spin" />
      <span>Loading jobs...</span>
    </div>

    <div v-else-if="!recentJobs.length" class="runs-page__empty runs-page__empty--guide">
      <Sparkles :size="36" class="runs-page__empty-icon" />
      <p>No runs yet</p>
      <span class="runs-page__empty-hint">
        Dispatch a job from the Command Center to see it appear here.
      </span>
      <NuxtLink to="/command-center" class="runs-page__empty-cta">
        Go to Command Center
      </NuxtLink>
    </div>

    <div v-else-if="!filteredJobs.length" class="runs-page__empty runs-page__empty--guide">
      <Activity :size="32" class="runs-page__empty-icon" />
      <p>No jobs match this filter</p>
      <span class="runs-page__empty-hint">
        Try a different status, or clear the filter to see every run.
      </span>
      <button class="runs-page__empty-cta" @click="clearFilter">
        Show all
      </button>
    </div>

    <div v-else class="runs-page__list">
      <div
        v-for="job in filteredJobs"
        :key="job.id"
        class="run-row"
        data-testid="run-row"
        @click="handleOpenJob(job)"
      >
        <div class="run-row__status">
          <component
            :is="getStatusIcon(job.status)"
            :size="18"
            :style="{ color: getStatusColor(job.status) }"
            :class="{ spin: job.status === 'running' }"
          />
        </div>
        <div class="run-row__info">
          <span class="run-row__key">{{ job.issue_key }}</span>
          <span class="run-row__command">{{ job.command }}</span>
          <span class="run-row__meta">
            {{ job.profile }} · {{ job.harness }} · {{ job.message || 'No message' }}
          </span>
        </div>
        <span class="run-row__badge" :style="{ color: getStatusColor(job.status) }">
          {{ job.status }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.runs-page {
  display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0;
  padding: 22px; gap: 18px; overflow-y: auto;
}
.runs-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.runs-page__title { display: flex; flex-direction: column; gap: 6px; }
.runs-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.runs-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.runs-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }
.runs-page__toolbar { display: flex; gap: 6px; flex-wrap: wrap; }
.runs-page__filter {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--muted); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.runs-page__filter--active { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }
.runs-page__filter:hover:not(.runs-page__filter--active) { border-color: var(--primary); color: var(--ink); }
.runs-page__empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 60px; color: var(--muted); }
.runs-page__empty p { color: var(--ink); font-weight: 600; }
.runs-page__empty--guide { gap: 10px; }
.runs-page__empty-icon { color: var(--muted); opacity: 0.6; }
.runs-page__empty-hint { color: var(--muted); font-size: 0.8125rem; max-width: 360px; text-align: center; line-height: 1.5; }
.runs-page__empty-cta {
  margin-top: 8px; padding: 8px 18px; border-radius: 8px;
  background: var(--primary); color: var(--on-primary);
  font-size: 0.8125rem; font-weight: 600; text-decoration: none;
  border: 1px solid var(--primary); cursor: pointer; transition: opacity 150ms;
}
.runs-page__empty-cta:hover { opacity: 0.88; }
.runs-page__list { display: flex; flex-direction: column; gap: 6px; }
.run-row {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: var(--surface-card); border: 1px solid var(--hairline);
  border-radius: 10px; cursor: pointer; transition: border-color 150ms;
}
.run-row:hover { border-color: var(--primary); }
.run-row__status { flex-shrink: 0; display: grid; place-items: center; width: 28px; height: 28px; }
.run-row__info { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.run-row__key { font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--ink); }
.run-row__command { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-row__meta { color: var(--muted); font-size: 0.75rem; }
.run-row__badge {
  flex-shrink: 0; padding: 3px 10px; font-family: var(--font-mono); font-size: 0.6875rem;
  font-weight: 600; text-transform: uppercase; background: var(--surface-soft);
  border: 1px solid var(--hairline); border-radius: 6px;
}
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
