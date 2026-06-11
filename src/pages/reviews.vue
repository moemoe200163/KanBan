<script setup lang="ts">
/**
 * /reviews — leader's batch review queue for Mavis-style cycle reports.
 *
 * The board already exposes a Cycles tab on each issue, but the
 * leader needs a single surface to triage N pending reports without
 * opening one drawer at a time. This page pulls from
 * ``GET /api/v1/cycle-reports/pending`` and lets the leader flip the
 * verdict inline.
 *
 * Why this matters for the Mavis collab model:
 * - Workers (incl. auto-promote) write cycle reports as they finish.
 * - The reports live in two states that block progress: ``pending``
 *   (review_required) and ``auto_passed`` (waiting for the leader to
 *   acknowledge). Both need a leader decision before the issue
 *   transitions to ``done``.
 * - Without this page, the leader has to remember which issues need
 *   attention — a job that always loses to whatever the operator is
 *   doing in the moment.
 */
import { authHeaders } from '~/utils/authHeaders'

interface PendingCycleReport {
  id: string
  issueId: string
  issueKey: string
  issueTitle: string
  issueStatus: string
  jobId: string | null
  authorName: string | null
  plan: string
  progressLog: Array<{ ts: string; status: string; message: string }>
  deliverableSummary: string | null
  verdict: 'pending' | 'auto_passed'
  createdAt: string | null
}

const config = useRuntimeConfig()
const route = useRoute()
const router = useRouter()
const reports = ref<PendingCycleReport[]>([])
const isLoading = ref(false)

// Filters. State lives in the URL query so a leader can bookmark
// "everything auto-promote reported on Monday" and have the
// page land back on the same view. Default: no filter (show
// every pending report).
const filterPriority = ref<string | null>((route.query.priority as string) || null)
const filterAuthor = ref<string | null>((route.query.author as string) || null)
// Date input is a plain ``YYYY-MM-DD`` string; we convert to the
// ISO-8601 lower bound the backend expects.
const filterSince = ref<string | null>((route.query.since as string) || null)

const PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'] as const
const updatingId = ref<string | null>(null)
const error = ref<string | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const refresh = async () => {
  isLoading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    if (filterPriority.value) params.set('priority', filterPriority.value)
    if (filterAuthor.value) params.set('author', filterAuthor.value)
    if (filterSince.value) {
      // ``YYYY-MM-DD`` → start-of-day UTC ISO-8601. End of day
      // is the operator's job — if they want "since 6am
      // yesterday" they can use the full ISO format.
      const iso = `${filterSince.value}T00:00:00Z`
      params.set('since', iso)
    }
    const qs = params.toString()
    const url = `${config.public.apiBase}/cycle-reports/pending${qs ? '?' + qs : ''}`
    const res = await $fetch<{ cycleReports: PendingCycleReport[]; total: number }>(
      url,
      { headers: authHeaders() },
    )
    reports.value = res.cycleReports ?? []
    error.value = null
  } catch (err: any) {
    error.value = err instanceof Error ? err.message : 'Failed to load pending reports'
  } finally {
    isLoading.value = false
  }
}

const clearFilters = () => {
  filterPriority.value = null
  filterAuthor.value = null
  filterSince.value = null
  // Reflect in URL too so bookmarked URLs reset.
  router.replace({ query: {} })
  void refresh()
}

const override = async (report: PendingCycleReport, verdict: 'pass' | 'fail' | 'blocked') => {
  updatingId.value = report.id
  try {
    await $fetch(
      `${config.public.apiBase}/issues/${report.issueId}/cycle-reports/${report.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: {
          verdict,
          verdict_reason:
            verdict === 'pass' ? 'Accepted from /reviews queue' :
            verdict === 'fail' ? 'Rejected from /reviews queue' :
            'Blocked from /reviews queue',
        },
      },
    )
    // Optimistic remove: once the leader decides, the row leaves the
    // queue. The next poll will catch any drift if the API disagrees.
    reports.value = reports.value.filter(r => r.id !== report.id)
  } catch (err: any) {
    error.value = err instanceof Error ? err.message : 'Failed to update verdict'
  } finally {
    updatingId.value = null
  }
}

onMounted(() => {
  void refresh()
  // Same cadence as the sidebar — every 30 s is enough since cycle
  // reports only land when a worker (or auto-promote) finishes a
  // pass. We don't want to spam the API on every render.
  pollTimer = setInterval(refresh, 30_000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

const formatTime = (ts: string | null) => {
  if (!ts) return ''
  try { return new Date(ts).toLocaleString() } catch { return ts }
}

const verdictLabel = (v: string) => v === 'auto_passed' ? 'Auto-passed' : 'Pending review'
</script>

<template>
  <div class="reviews-page">
    <header class="reviews-page__header">
      <div>
        <h1 class="reviews-page__title">Cycle Reviews</h1>
        <p class="reviews-page__subtitle">
          {{ isLoading ? 'Loading…' : `${reports.length} report(s) awaiting leader decision` }}
        </p>
      </div>
      <button
        class="reviews-page__refresh"
        :disabled="isLoading"
        @click="refresh"
      >
        Refresh
      </button>
    </header>

    <section class="reviews-page__filters">
      <label class="reviews-page__filter">
        <span>Priority</span>
        <select v-model="filterPriority" @change="refresh">
          <option :value="null">All</option>
          <option v-for="p in PRIORITY_OPTIONS" :key="p" :value="p">{{ p }}</option>
        </select>
      </label>
      <label class="reviews-page__filter">
        <span>Author</span>
        <input
          v-model="filterAuthor"
          type="text"
          placeholder="auto-promote, ..."
          @change="refresh"
        />
      </label>
      <label class="reviews-page__filter">
        <span>Since</span>
        <input
          v-model="filterSince"
          type="date"
          @change="refresh"
        />
      </label>
      <button
        v-if="filterPriority || filterAuthor || filterSince"
        class="reviews-page__filter-clear"
        @click="clearFilters"
      >
        Clear
      </button>
    </section>

    <div v-if="error" class="reviews-page__error">
      {{ error }}
    </div>

    <div v-if="!isLoading && reports.length === 0 && !error" class="reviews-page__empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="56" height="56">
        <path d="M9 12l2 2 4-4" />
        <circle cx="12" cy="12" r="10" />
      </svg>
      <h2>All caught up</h2>
      <p>No cycle reports are waiting for a leader decision. New reports will appear here as workers complete their passes.</p>
    </div>

    <ul v-else class="reviews-list">
      <li
        v-for="report in reports"
        :key="report.id"
        class="review-row"
      >
        <header class="review-row__header">
          <div class="review-row__meta">
            <span class="review-row__key">{{ report.issueKey }}</span>
            <span :class="['review-row__status', `review-row__status--${report.issueStatus}`]">
              {{ report.issueStatus.replace('_', ' ') }}
            </span>
          </div>
          <span :class="['review-row__verdict', `review-row__verdict--${report.verdict}`]">
            {{ verdictLabel(report.verdict) }}
          </span>
        </header>

        <h3 class="review-row__title">{{ report.issueTitle }}</h3>

        <section class="review-row__section">
          <h4>Plan</h4>
          <p>{{ report.plan }}</p>
        </section>

        <section v-if="report.progressLog?.length" class="review-row__section">
          <h4>
            Progress
            <span class="review-row__count">{{ report.progressLog.length }}</span>
          </h4>
          <ol class="review-row__log">
            <li
              v-for="(ev, idx) in report.progressLog"
              :key="idx"
              :class="['review-row__log-item', `review-row__log-item--${(ev.status || 'info').toLowerCase()}`]"
            >
              <span class="review-row__log-status">{{ ev.status }}</span>
              <span class="review-row__log-msg">{{ ev.message }}</span>
            </li>
          </ol>
        </section>

        <section v-if="report.deliverableSummary" class="review-row__section">
          <h4>Deliverable</h4>
          <p>{{ report.deliverableSummary }}</p>
        </section>

        <footer class="review-row__actions">
          <span class="review-row__author">
            by <strong>{{ report.authorName || 'unknown' }}</strong>
            · {{ formatTime(report.createdAt) }}
          </span>
          <div class="review-row__buttons">
            <button
              class="review-btn review-btn--pass"
              :disabled="updatingId === report.id"
              @click="override(report, 'pass')"
            >
              Mark as pass
            </button>
            <button
              class="review-btn review-btn--fail"
              :disabled="updatingId === report.id"
              @click="override(report, 'fail')"
            >
              Fail
            </button>
            <button
              class="review-btn review-btn--block"
              :disabled="updatingId === report.id"
              @click="override(report, 'blocked')"
            >
              Block
            </button>
          </div>
        </footer>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.reviews-page {
  padding: var(--space-5);
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.reviews-page__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-4);
  border-bottom: 1px solid var(--hairline);
  padding-bottom: var(--space-4);
}

.reviews-page__title { font-size: var(--text-2xl); margin: 0; }
.reviews-page__subtitle { font-size: var(--text-sm); color: var(--ink-muted); margin: 4px 0 0 0; }

.reviews-page__refresh {
  font-size: var(--text-sm);
  padding: 6px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas-elevated);
  cursor: pointer;
}
.reviews-page__refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* Filter bar — sits below the header so a leader can narrow
   the queue without leaving the page. */
.reviews-page__filters {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--canvas-elevated);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  flex-wrap: wrap;
}
.reviews-page__filter {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--ink-muted);
}
.reviews-page__filter span {
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}
.reviews-page__filter select,
.reviews-page__filter input {
  font-size: var(--text-sm);
  padding: 5px 8px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--canvas);
  color: var(--ink);
  min-width: 140px;
}
.reviews-page__filter-clear {
  font-size: var(--text-sm);
  padding: 5px 12px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--canvas);
  color: var(--ink-muted);
  cursor: pointer;
  align-self: flex-end;
}
.reviews-page__filter-clear:hover { color: var(--ink); }

.reviews-page__error {
  background: rgba(184, 92, 77, 0.1);
  color: #B85C4D;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

.reviews-page__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-9) var(--space-4);
  color: var(--ink-muted);
  gap: var(--space-3);
}
.reviews-page__empty h2 { margin: 0; font-size: var(--text-xl); }
.reviews-page__empty p { margin: 0; max-width: 50ch; }

.reviews-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.review-row {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background: var(--canvas-elevated);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.review-row__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}
.review-row__meta { display: flex; align-items: center; gap: var(--space-3); }
.review-row__key {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--ink);
}
.review-row__status {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.review-row__status--human_review { background: rgba(212, 168, 75, 0.18); color: #8A6B22; }
.review-row__status--in_progress { background: rgba(107, 139, 164, 0.18); color: #4A6680; }
.review-row__status--done { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.review-row__status--blocked { background: rgba(184, 92, 77, 0.18); color: #B85C4D; }

.review-row__verdict {
  font-size: var(--text-xs);
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.review-row__verdict--pending     { background: rgba(140, 130, 121, 0.18); color: #6B6660; }
.review-row__verdict--auto_passed { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }

.review-row__title { font-size: var(--text-lg); font-weight: 600; margin: 0; }

.review-row__section { display: flex; flex-direction: column; gap: var(--space-2); }
.review-row__section h4 {
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-muted);
  margin: 0;
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
.review-row__count {
  font-size: 10px;
  background: var(--canvas-subtle, rgba(0,0,0,0.04));
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
}
.review-row__section p { margin: 0; font-size: var(--text-sm); line-height: 1.5; }

.review-row__log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-xs);
}
.review-row__log-item {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: var(--space-2);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
}
.review-row__log-item--running    { background: rgba(107, 139, 164, 0.08); }
.review-row__log-item--queued     { background: rgba(140, 130, 121, 0.08); }
.review-row__log-item--review_required,
.review-row__log-item--completed  { background: rgba(125, 158, 125, 0.08); }
.review-row__log-item--failed,
.review-row__log-item--cancelled  { background: rgba(184, 92, 77, 0.08); }
.review-row__log-status {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  text-transform: uppercase;
  font-size: 10px;
}

.review-row__actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--hairline);
  padding-top: var(--space-3);
  margin-top: var(--space-2);
  gap: var(--space-3);
}
.review-row__author { font-size: var(--text-xs); color: var(--ink-muted); }
.review-row__buttons { display: flex; gap: var(--space-2); }
.review-btn {
  font-size: var(--text-sm);
  font-weight: 500;
  padding: 6px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas);
  cursor: pointer;
  transition: opacity var(--duration-fast);
}
.review-btn:hover:not(:disabled) { opacity: 0.85; }
.review-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.review-btn--pass  { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; border-color: rgba(125, 158, 125, 0.4); }
.review-btn--fail  { background: rgba(184, 92, 77, 0.18);  color: #B85C4D; border-color: rgba(184, 92, 77, 0.4); }
.review-btn--block { background: rgba(212, 168, 75, 0.18); color: #8A6B22; border-color: rgba(212, 168, 75, 0.4); }
</style>
