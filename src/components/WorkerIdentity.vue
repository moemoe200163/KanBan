<script setup lang="ts">
/**
 * WorkerIdentity — IssueDetail Worker tab content.
 *
 * Roadmap P3 延伸 + Plan C 對應：
 * - 顯示當前 worker 身份（profile / harness / role）
 * - 顯示 progress narrative：把 currentJob.events 摘要成 2-3 句的
 *   「目前做什麼 + 為什麼 + 下一步是什麼」
 * - 顯示 ETA 倒數（從 currentJob.created_at + timeout_seconds 算）
 *   timeout 過 80% 顯示黃色警告
 * - Worker 缺席時顯示 CTA + suggested role
 *
 * 純 UI 元件，零 store 變動，零 backend 變動（Plan C-1 範圍）。
 */

import { computed } from 'vue'
import type { ECCJobStatus, Issue, ECCJobEvent } from '~/types'

/** Local minimal job shape — matches the subset of ECCJob that
 *  WorkerIdentity reads. Avoids coupling the component to the
 *  full job interface (which would pull in unrelated fields). */
interface WorkerJob {
  id: string
  status: ECCJobStatus
  created_at: string
  updated_at: string
  profile: string
  harness: string
  execution_mode?: string | null
  message?: string | null
  events: ECCJobEvent[]
}

interface Props {
  issue: Issue | null
  job: WorkerJob | null
  /** timeout_seconds 從 agent_roles.timeout_seconds 來，Plan C-2 後可從 store 注入 */
  roleTimeoutSeconds?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  roleTimeoutSeconds: 1800, // 30 min default — 跟既有 frontend/backend role 一致
})

// ---------------------------------------------------------------------------
// 1. Worker identity
// ---------------------------------------------------------------------------

const profileToRole: Record<string, string> = {
  frontend: 'frontend',
  backend: 'backend',
  security: 'backend',
  refactor: 'backend',
  debug: 'backend',
  general: 'frontend', // general 多數是 triage / 雜項，建議 frontend（最常見 next-role）
}

const workerName = computed(() => {
  if (!props.job) return null
  // Both 'safe-runner' and 'default' represent the in-process
  // deterministic runner (different historical names for the same
  // thing). Treat them as a single human-readable identity.
  const h = props.job.harness
  if (h === 'safe-runner' || h === 'default' || h === '' || h == null) {
    return 'Safe Runner'
  }
  return h
})

const workerSubtitle = computed(() => {
  if (!props.job) return null
  const parts: string[] = []
  if (props.job.profile) parts.push(`profile: ${props.job.profile}`)
  if (props.job.harness) parts.push(`harness: ${props.job.harness}`)
  if (props.job.execution_mode) parts.push(`mode: ${props.job.execution_mode}`)
  return parts.join(' · ')
})

const suggestedRole = computed(() => {
  if (props.job) return null
  const profile = props.issue?.profile ?? 'general'
  return profileToRole[profile] ?? 'backend'
})

const suggestedCommand = computed(() => {
  if (props.job) return null
  const profile = props.issue?.profile ?? 'general'
  return `/loop-start --profile=${profile}`
})

// ---------------------------------------------------------------------------
// 2. Progress narrative
//
// 規則（Plan C-1 v1）：
// - events 為空 → "Worker is preparing the workspace"
// - 有 events → "Currently: <latest event message>" + "Started: <first event message>"
// - > 3 events → 加 "Progress: N events recorded"
// - failed → 加 "Reason: <latest event message>"
// ---------------------------------------------------------------------------

const narrativeLines = computed<Array<{ kind: 'status' | 'history' | 'progress' | 'reason'; text: string }>>(() => {
  if (!props.job) return []
  if (props.job.events.length === 0) {
    return [{ kind: 'status', text: 'Worker is preparing the workspace…' }]
  }
  const sorted = props.job.events
    .slice()
    .sort((a: ECCJobEvent, b: ECCJobEvent) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
  const latest = sorted[sorted.length - 1]
  const first = sorted[0]
  const lines: Array<{ kind: 'status' | 'history' | 'progress' | 'reason'; text: string }> = [
    { kind: 'status', text: `Currently: ${latest.message ?? '…'}` },
  ]
  if (sorted.length > 1 && first !== latest) {
    lines.push({ kind: 'history', text: `Started: ${first.message ?? '…'}` })
  }
  if (sorted.length > 3) {
    lines.push({ kind: 'progress', text: `Progress: ${sorted.length} events recorded` })
  }
  if (latest.status === 'failed' || latest.status === 'cancelled') {
    lines.push({ kind: 'reason', text: `Reason: ${latest.message ?? 'unknown'}` })
  }
  return lines
})

// ---------------------------------------------------------------------------
// 3. ETA / heartbeat
// ---------------------------------------------------------------------------

interface EtaInfo {
  label: string
  percent: number
  state: 'fresh' | 'halfway' | 'warning' | 'overdue' | 'done'
  remainingSeconds: number | null
}

const eta = computed<EtaInfo | null>(() => {
  if (!props.job) return null
  if (props.job.status === 'completed' || props.job.status === 'cancelled' || props.job.status === 'review_required') {
    return {
      label: 'Done',
      percent: 100,
      state: 'done',
      remainingSeconds: 0,
    }
  }
  const created = new Date(props.job.created_at).getTime()
  if (Number.isNaN(created)) return null
  const now = Date.now()
  const elapsedSec = Math.max(0, Math.floor((now - created) / 1000))
  const timeoutSec = props.roleTimeoutSeconds ?? 1800
  const percent = Math.min(100, Math.floor((elapsedSec / timeoutSec) * 100))
  const remaining = Math.max(0, timeoutSec - elapsedSec)
  let state: EtaInfo['state'] = 'fresh'
  if (percent >= 100) state = 'overdue'
  else if (percent >= 80) state = 'warning'
  else if (percent >= 50) state = 'halfway'
  return {
    label: humanizeRemaining(remaining),
    percent,
    state,
    remainingSeconds: remaining,
  }
})

function humanizeRemaining(sec: number): string {
  if (sec <= 0) return 'overdue'
  if (sec < 60) return `${sec}s remaining`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s remaining`
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${h}h ${m}m remaining`
}

// ---------------------------------------------------------------------------
// 4. Status pill (mirror DeliveryStageBar for visual consistency)
// ---------------------------------------------------------------------------

const statusLabel = computed<string | null>(() => {
  if (!props.job) return null
  return statusToLabel(props.job.status)
})

function statusToLabel(s: ECCJobStatus): string {
  switch (s) {
    case 'queued': return 'Dispatched'
    case 'running': return 'Executing'
    case 'paused': return 'Paused at Quality Gate'
    case 'failed': return 'Failed'
    case 'review_required': return 'Awaiting Review'
    case 'completed': return 'Completed'
    case 'cancelled': return 'Cancelled'
  }
}
</script>

<template>
  <div class="worker-identity" data-testid="worker-identity">
    <!-- 1. Worker identity card -->
    <section v-if="job" class="worker-identity__card">
      <header class="worker-identity__head">
        <div class="worker-identity__avatar" :data-state="job.status">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M12 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM4 21a8 8 0 0 1 16 0" />
          </svg>
        </div>
        <div class="worker-identity__heading">
          <h3 class="worker-identity__name">{{ workerName }}</h3>
          <p class="worker-identity__sub">{{ workerSubtitle }}</p>
        </div>
        <span
          v-if="statusLabel"
          class="worker-identity__status"
          :data-state="job.status"
        >
          {{ statusLabel }}
        </span>
      </header>
    </section>

    <!-- 2. Progress narrative -->
    <section v-if="job" class="worker-identity__narrative">
      <h4 class="worker-identity__section-title">Progress</h4>
      <ul v-if="narrativeLines.length > 0" class="worker-identity__narrative-list">
        <li
          v-for="(line, idx) in narrativeLines"
          :key="idx"
          :class="['worker-identity__narrative-line', `worker-identity__narrative-line--${line.kind}`]"
          :data-testid="`worker-narrative-${line.kind}`"
        >
          {{ line.text }}
        </li>
      </ul>
      <p v-else class="worker-identity__narrative-empty">No events recorded yet.</p>
    </section>

    <!-- 3. ETA / heartbeat -->
    <section v-if="job && eta" class="worker-identity__eta" :data-state="eta.state">
      <h4 class="worker-identity__section-title">Heartbeat</h4>
      <div class="worker-identity__eta-bar">
        <div
          class="worker-identity__eta-fill"
          :style="{ width: `${eta.percent}%` }"
          :data-state="eta.state"
        />
      </div>
      <div class="worker-identity__eta-meta">
        <span>{{ eta.label }}</span>
        <span v-if="eta.remainingSeconds !== null && eta.state !== 'done'">
          {{ Math.floor(eta.percent) }}% of budget
        </span>
      </div>
    </section>

    <!-- 4. No-worker CTA -->
    <section v-if="!job" class="worker-identity__empty" data-testid="worker-empty">
      <svg class="worker-identity__empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
      </svg>
      <h4 class="worker-identity__empty-title">No worker assigned</h4>
      <p class="worker-identity__empty-hint">
        Suggested role: <strong>{{ suggestedRole }}</strong>.
        Run <code>{{ suggestedCommand }}</code> to dispatch.
      </p>
    </section>
  </div>
</template>

<style scoped>
.worker-identity {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding: 1.25rem;
}

.worker-identity__card,
.worker-identity__narrative,
.worker-identity__eta,
.worker-identity__empty {
  background: var(--panel, #1f2937);
  border: 1px solid var(--border, #374151);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}

.worker-identity__head {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.worker-identity__avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft, #1e3a8a);
  color: var(--accent, #60a5fa);
  flex-shrink: 0;
}
.worker-identity__avatar[data-state='failed'],
.worker-identity__avatar[data-state='cancelled'] {
  background: var(--danger-soft, #7f1d1d);
  color: var(--danger, #f87171);
}
.worker-identity__avatar[data-state='completed'] {
  background: var(--success-soft, #14532d);
  color: var(--success, #4ade80);
}
.worker-identity__avatar svg {
  width: 22px;
  height: 22px;
}

.worker-identity__heading {
  flex: 1;
  min-width: 0;
}

.worker-identity__name {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
  color: var(--text, #f3f4f6);
}

.worker-identity__sub {
  font-size: 0.8125rem;
  color: var(--text-muted, #9ca3af);
  margin: 0.125rem 0 0;
}

.worker-identity__status {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.625rem;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--surface-2, #374151);
  color: var(--text, #f3f4f6);
  white-space: nowrap;
}
.worker-identity__status[data-state='running'] {
  background: var(--warning-soft, #78350f);
  color: var(--warning, #fbbf24);
}
.worker-identity__status[data-state='paused'] {
  background: var(--accent-soft, #1e3a8a);
  color: var(--accent, #60a5fa);
}
.worker-identity__status[data-state='failed'],
.worker-identity__status[data-state='cancelled'] {
  background: var(--danger-soft, #7f1d1d);
  color: var(--danger, #f87171);
}
.worker-identity__status[data-state='completed'] {
  background: var(--success-soft, #14532d);
  color: var(--success, #4ade80);
}

.worker-identity__section-title {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #9ca3af);
  margin: 0 0 0.625rem;
}

.worker-identity__narrative-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.worker-identity__narrative-line {
  font-size: 0.875rem;
  color: var(--text, #f3f4f6);
  line-height: 1.5;
  padding-left: 0.875rem;
  border-left: 2px solid var(--border, #374151);
}
.worker-identity__narrative-line--status {
  border-color: var(--accent, #60a5fa);
}
.worker-identity__narrative-line--history {
  color: var(--text-muted, #9ca3af);
  border-color: var(--border, #374151);
}
.worker-identity__narrative-line--progress {
  color: var(--text-muted, #9ca3af);
  font-style: italic;
  border-color: transparent;
}
.worker-identity__narrative-line--reason {
  border-color: var(--danger, #f87171);
  color: var(--danger, #f87171);
}

.worker-identity__narrative-empty {
  font-size: 0.875rem;
  color: var(--text-muted, #9ca3af);
  font-style: italic;
  margin: 0;
}

.worker-identity__eta-bar {
  width: 100%;
  height: 6px;
  background: var(--surface-2, #374151);
  border-radius: 999px;
  overflow: hidden;
}
.worker-identity__eta-fill {
  height: 100%;
  background: var(--accent, #60a5fa);
  transition: width 0.3s ease;
}
.worker-identity__eta-fill[data-state='halfway'] {
  background: var(--warning, #fbbf24);
}
.worker-identity__eta-fill[data-state='warning'] {
  background: var(--warning, #fbbf24);
}
.worker-identity__eta-fill[data-state='overdue'] {
  background: var(--danger, #f87171);
}
.worker-identity__eta-fill[data-state='done'] {
  background: var(--success, #4ade80);
}

.worker-identity__eta-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-muted, #9ca3af);
  margin-top: 0.5rem;
}
.worker-identity__eta[data-state='warning'] .worker-identity__eta-meta,
.worker-identity__eta[data-state='overdue'] .worker-identity__eta-meta {
  color: var(--warning, #fbbf24);
}
.worker-identity__eta[data-state='overdue'] .worker-identity__eta-meta {
  color: var(--danger, #f87171);
}

.worker-identity__empty {
  text-align: center;
  padding: 2rem 1.25rem;
}
.worker-identity__empty-icon {
  width: 40px;
  height: 40px;
  color: var(--text-muted, #6b7280);
  margin: 0 auto 0.75rem;
}
.worker-identity__empty-title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 0.5rem;
  color: var(--text, #f3f4f6);
}
.worker-identity__empty-hint {
  font-size: 0.875rem;
  color: var(--text-muted, #9ca3af);
  margin: 0;
}
.worker-identity__empty code {
  font-family: var(--font-mono, 'Menlo', monospace);
  background: var(--surface-2, #374151);
  padding: 0.125rem 0.375rem;
  border-radius: 3px;
  font-size: 0.8125rem;
  color: var(--accent, #60a5fa);
}
</style>
