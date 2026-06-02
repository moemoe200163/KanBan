<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useRecentJobs } from '~/composables/useRecentJobs'
import type { ECCDispatchJob, ECCJobStatus } from '~/types'
import { Activity, AlertCircle, CheckCircle2, Clock, Eye, Loader2, Square, XCircle } from 'lucide-vue-next'

const boardStore = useBoardStore()
const { jobs: recentJobs, isLoading, start, stop } = useRecentJobs({ refreshMs: 4000, limit: 20 })

onMounted(() => start())
onUnmounted(() => stop())

const activeJobs = computed(() =>
  recentJobs.value.filter(j => j.status === 'running' || j.status === 'queued')
)

const completedJobs = computed(() =>
  recentJobs.value.filter(j => j.status === 'completed' || j.status === 'failed' || j.status === 'review_required')
)

const getStatusIcon = (status: ECCJobStatus) => {
  switch (status) {
    case 'running': return Loader2
    case 'queued': return Clock
    case 'review_required': return Eye
    case 'completed': return CheckCircle2
    case 'failed': return XCircle
    case 'cancelled': return Square
    case 'paused': return AlertCircle
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
    case 'paused': return 'var(--amber)'
    default: return 'var(--muted)'
  }
}

const formatTime = (iso: string) => {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHrs = Math.floor(diffMins / 60)
  if (diffHrs < 24) return `${diffHrs}h ago`
  return `${Math.floor(diffHrs / 24)}d ago`
}

const formatDuration = (job: ECCDispatchJob) => {
  const start = new Date(job.created_at)
  const end = job.status === 'running' ? new Date() : new Date(job.updated_at)
  const ms = end.getTime() - start.getTime()
  const secs = Math.floor(ms / 1000)
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

const handleViewJob = (job: ECCDispatchJob) => {
  boardStore.openJob(job)
}

const handleCancel = async (job: ECCDispatchJob) => {
  await boardStore.cancelJob(job.id)
}

const handleRetry = async (job: ECCDispatchJob) => {
  await boardStore.retryJob(job.id)
}

const canCancel = (status: ECCJobStatus) =>
  status === 'queued' || status === 'running' || status === 'paused'

const canRetry = (status: ECCJobStatus) =>
  status === 'failed' || status === 'cancelled' || status === 'review_required'
</script>

<template>
  <div class="job-monitor">
    <div class="job-monitor__header">
      <Activity :size="18" />
      <h3>Job Monitor</h3>
      <span v-if="activeJobs.length" class="job-monitor__badge">{{ activeJobs.length }}</span>
    </div>

    <!-- Loading -->
    <div v-if="isLoading && recentJobs.length === 0" class="job-monitor__loading">
      <Loader2 :size="18" class="spin" />
      <span>Loading jobs...</span>
    </div>

    <!-- Empty -->
    <div v-else-if="recentJobs.length === 0" class="job-monitor__empty">
      <Activity :size="24" />
      <p>No jobs dispatched yet</p>
      <span>Use the composer to dispatch a command</span>
    </div>

    <template v-else>
      <!-- Active Jobs -->
      <div v-if="activeJobs.length" class="job-monitor__section">
        <h4 class="job-monitor__section-title">Active</h4>
        <div class="job-list">
          <div
            v-for="job in activeJobs"
            :key="job.id"
            class="job-row job-row--active"
            @click="handleViewJob(job)"
          >
            <div class="job-row__status">
              <component
                :is="getStatusIcon(job.status)"
                :size="16"
                :class="{ spin: job.status === 'running' }"
                :style="{ color: getStatusColor(job.status) }"
              />
            </div>
            <div class="job-row__info">
              <span class="job-row__key">{{ job.issue_key }}</span>
              <span class="job-row__command">{{ job.command }}</span>
              <span class="job-row__meta">
                {{ job.profile }} &middot; {{ job.harness }} &middot; {{ formatDuration(job) }}
              </span>
            </div>
            <span class="job-row__status-badge" :style="{ color: getStatusColor(job.status) }">
              {{ job.status }}
            </span>
            <div class="job-row__actions" @click.stop>
              <button
                v-if="canCancel(job.status)"
                class="job-row__action job-row__action--cancel"
                :data-testid="`job-cancel-${job.id}`"
                @click="handleCancel(job)"
              >
                Cancel
              </button>
              <button
                v-if="canRetry(job.status)"
                class="job-row__action job-row__action--retry"
                :data-testid="`job-retry-${job.id}`"
                @click="handleRetry(job)"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Completed / Review Jobs -->
      <div v-if="completedJobs.length" class="job-monitor__section">
        <h4 class="job-monitor__section-title">Recent</h4>
        <div class="job-list">
          <div
            v-for="job in completedJobs"
            :key="job.id"
            class="job-row"
            @click="handleViewJob(job)"
          >
            <div class="job-row__status">
              <component
                :is="getStatusIcon(job.status)"
                :size="16"
                :style="{ color: getStatusColor(job.status) }"
              />
            </div>
            <div class="job-row__info">
              <span class="job-row__key">{{ job.issue_key }}</span>
              <span class="job-row__command">{{ job.command }}</span>
              <span class="job-row__meta">
                {{ formatTime(job.updated_at) }}
                <template v-if="job.message"> &middot; {{ job.message }}</template>
              </span>
            </div>
            <span class="job-row__status-badge" :style="{ color: getStatusColor(job.status) }">
              {{ job.status }}
            </span>
            <div class="job-row__actions" @click.stop>
              <button
                v-if="canCancel(job.status)"
                class="job-row__action job-row__action--cancel"
                :data-testid="`job-cancel-${job.id}`"
                @click="handleCancel(job)"
              >
                Cancel
              </button>
              <button
                v-if="canRetry(job.status)"
                class="job-row__action job-row__action--retry"
                :data-testid="`job-retry-${job.id}`"
                @click="handleRetry(job)"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.job-monitor {
  display: flex;
  flex-direction: column;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  overflow: hidden;
}

.job-monitor__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  color: var(--ink);
  background: var(--surface-soft);
  border-bottom: 1px solid var(--hairline);
}

.job-monitor__header h3 {
  font-family: var(--font-display);
  font-size: 0.9375rem;
  font-weight: 700;
}

.job-monitor__badge {
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  color: var(--on-primary);
  background: var(--primary);
  border-radius: 10px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
}

.job-monitor__loading,
.job-monitor__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 32px 18px;
  color: var(--muted);
  text-align: center;
}

.job-monitor__empty p {
  color: var(--ink);
  font-weight: 600;
  font-size: 0.875rem;
}

.job-monitor__empty span {
  font-size: 0.8125rem;
}

.job-monitor__section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
}

.job-monitor__section:not(:last-child) {
  border-bottom: 1px solid var(--hairline);
}

.job-monitor__section-title {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.job-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 150ms ease-out, background 150ms ease-out;
}

.job-row:hover {
  border-color: var(--primary);
  background: var(--surface-card);
}

.job-row--active {
  border-left: 3px solid var(--primary);
}

.job-row__status {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
}

.job-row__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.job-row__key {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  font-weight: 600;
}

.job-row__command {
  overflow: hidden;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-row__meta {
  color: var(--muted);
  font-size: 0.6875rem;
}

.job-row__status-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  font-family: var(--font-mono);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 4px;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.job-row__actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.job-row__action {
  min-height: 26px;
  padding: 4px 8px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms ease-out, color 150ms ease-out;
}

.job-row__action--cancel {
  color: var(--clay-red);
  background: transparent;
  border: 1px solid var(--clay-red);
}

.job-row__action--cancel:hover {
  color: var(--on-primary);
  background: var(--clay-red);
}

.job-row__action--retry {
  color: var(--sage);
  background: transparent;
  border: 1px solid var(--sage);
}

.job-row__action--retry:hover {
  color: var(--on-primary);
  background: var(--sage);
}
</style>
