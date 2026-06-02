<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useRecentJobs } from '~/composables/useRecentJobs'
import type { ECCJobStatus } from '~/types'
import { Activity, CheckCircle2, Clock, Eye, Loader2, Square, XCircle } from 'lucide-vue-next'

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

    <div v-else-if="!filteredJobs.length" class="runs-page__empty">
      <Activity :size="32" />
      <p>No jobs match this filter</p>
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
  display: flex; flex-direction: column; height: 100vh; min-width: 0;
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
