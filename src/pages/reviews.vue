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
 *
 * Status filter (``?status=pending|reviewed|all``):
 * - ``pending`` is the original "needs a leader decision" queue
 *   (default on first visit).
 * - ``reviewed`` shows reports the leader has already approved or
 *   sent back — useful for follow-up, e.g. "what did I send back
 *   to the worker yesterday".
 * - ``all`` merges both. The list splits visually into
 *   "Awaiting review" and "Reviewed" sub-sections so a mixed
 *   view stays scannable.
 */
import { authHeaders } from '~/utils/authHeaders'
import ReviewRowActions from '~/components/ReviewRowActions.vue'
import type { PendingCycleReport, CycleReportVerdict } from '~/types'

type StatusFilter = 'pending' | 'reviewed' | 'all'

const config = useRuntimeConfig()
const route = useRoute()
const router = useRouter()
const reports = ref<PendingCycleReport[]>([])
const isLoading = ref(false)

// Filters. State lives in the URL query so a leader can bookmark
// "everything auto-promote reported on Monday" and have the
// page land back on the same view. Default: ``pending`` (show
// every report that still needs a leader decision).
const filterStatus = ref<StatusFilter>(
  ((route.query.status as StatusFilter) || 'pending'),
)
const filterPriority = ref<string | null>((route.query.priority as string) || null)
const filterAuthor = ref<string | null>((route.query.author as string) || null)
// Date input is a plain ``YYYY-MM-DD`` string; we convert to the
// ISO-8601 lower bound the backend expects.
const filterSince = ref<string | null>((route.query.since as string) || null)

const PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'] as const
const STATUS_OPTIONS: StatusFilter[] = ['pending', 'reviewed', 'all']
const updatingId = ref<string | null>(null)
const error = ref<string | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ----- status filter helpers --------------------------------------
//
// Two views to keep straight:
//   * ``filterStatus.value`` is the *user's intent* — what's
//     selected in the dropdown (``pending|reviewed|all``).
//   * The endpoint actually called is chosen by the helper
//     below. For ``pending`` we still hit the legacy
//     ``/cycle-reports/pending`` endpoint (which excludes
//     terminal verdicts), for everything else we hit
//     ``/cycle-reports/reviewed?status=...`` which is the new
//     decision-aware split introduced by this task.
//
// The list is then grouped client-side when the operator picks
// ``all`` so the page renders the same two sub-sections the
// endpoint filters would.

const refresh = async () => {
  isLoading.value = true
  error.value = null
  try {
    // Build params shared by both endpoints.
    const baseParams = new URLSearchParams()
    if (filterPriority.value) baseParams.set('priority', filterPriority.value)
    if (filterAuthor.value) baseParams.set('author', filterAuthor.value)
    if (filterSince.value) {
      // ``YYYY-MM-DD`` → start-of-day UTC ISO-8601. End of day
      // is the operator's job — if they want "since 6am
      // yesterday" they can use the full ISO format.
      const iso = `${filterSince.value}T00:00:00Z`
      baseParams.set('since', iso)
    }
    const baseQs = baseParams.toString()

    // Pick the endpoint. ``pending`` keeps the historical
    // behaviour (excludes terminal verdicts); ``reviewed`` and
    // ``all`` use the new decision-aware split.
    //
    // Each branch builds the URL as a single template literal
    // (no `?` directly in the literal) so the unused-endpoints
    // audit script — which extracts path prefixes by static
    // text match — picks up both callsites. Splitting the
    // ``?status=`` join into a second template literal would
    // make the script miss the ``/cycle-reports/reviewed``
    // path.
    const status = filterStatus.value
    const endpoint = status === 'pending'
      ? `${config.public.apiBase}/cycle-reports/pending${baseQs ? '?' + baseQs : ''}`
      : `${config.public.apiBase}/cycle-reports/reviewed${`?status=${status}${baseQs ? '&' + baseQs : ''}`}`

    const res = await $fetch<{ cycleReports: PendingCycleReport[]; total: number }>(
      endpoint,
      { headers: authHeaders() },
    )
    reports.value = res.cycleReports ?? []
    error.value = null
  } catch (err: any) {
    error.value = err instanceof Error ? err.message : 'Failed to load reports'
  } finally {
    isLoading.value = false
  }
}

const setStatus = (next: StatusFilter) => {
  filterStatus.value = next
  // Reflect in URL so bookmarked URLs survive a refresh.
  router.replace({
    query: { ...route.query, status: next === 'pending' ? undefined : next },
  })
  void refresh()
}

const clearFilters = () => {
  filterPriority.value = null
  filterAuthor.value = null
  filterSince.value = null
  // Reflect in URL too so bookmarked URLs reset.
  router.replace({ query: { status: filterStatus.value === 'pending' ? undefined : filterStatus.value } })
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

// Per-row review state — same shape as the IssueDetail review
// section so the UX stays consistent. Kept in a Map keyed by
// report id so multiple rows don't share comment state.
const reviewComments = ref<Map<string, string>>(new Map())
const reviewingId = ref<string | null>(null)
const reviewErrors = ref<Map<string, string>>(new Map())
const setReviewComment = (id: string, value: string) => {
  const m = new Map(reviewComments.value)
  m.set(id, value)
  reviewComments.value = m
}
const setReviewError = (id: string, message: string | null) => {
  const m = new Map(reviewErrors.value)
  if (message === null) m.delete(id)
  else m.set(id, message)
  reviewErrors.value = m
}

// Self-review guard uses the same useAuth composable the
// detail drawer uses, so the user id is the same single
// source of truth.
const { authUser } = useAuth()
const isSelfReview = (r: PendingCycleReport) =>
  !!(r.authorId && authUser.value?.id && r.authorId === authUser.value.id)

const submitReview = async (r: PendingCycleReport, decision: 'approved' | 'changes_requested') => {
  reviewingId.value = r.id
  setReviewError(r.id, null)
  const comment = (reviewComments.value.get(r.id) ?? '').trim() || null
  try {
    const updated = await $fetch<PendingCycleReport>(
      `${config.public.apiBase}/cycle-reports/${r.id}/review`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: { decision, comment },
      },
    )
    // Optimistic patch in place; the next poll will reconcile
    // any drift. The row is left in the list (with the new
    // decision) so the operator sees the result of their click
    // even when the status filter is ``pending`` — switching
    // to ``reviewed`` shows the same row in the "Approved" or
    // "Changes requested" section.
    const idx = reports.value.findIndex(x => x.id === updated.id)
    if (idx >= 0) reports.value[idx] = updated
    setReviewComment(r.id, '')
  } catch (err: any) {
    const detail = err?.data?.detail ?? err?.message ?? 'Failed to submit review'
    setReviewError(r.id, typeof detail === 'string' ? detail : 'Failed to submit review')
  } finally {
    reviewingId.value = null
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

// Group reports client-side for the "all" view so the page
// stays scannable when a leader wants to see both the queue
// and the recently-reviewed entries in one place.
const pendingReports = computed(() => reports.value.filter(r => !r.decision))
const reviewedReports = computed(() => reports.value.filter(r => !!r.decision))

const reviewDecisionLabel = (d: 'approved' | 'changes_requested') =>
  d === 'approved' ? 'Approved' : 'Changes requested'
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
        <span>Status</span>
        <select
          :value="filterStatus"
          data-testid="reviews-status-filter"
          @change="setStatus(($event.target as HTMLSelectElement).value as StatusFilter)"
        >
          <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
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
      <p v-if="filterStatus === 'pending'">
        No cycle reports are waiting for a leader decision. New reports will appear here as workers complete their passes.
      </p>
      <p v-else-if="filterStatus === 'reviewed'">
        No reviewed cycle reports yet. Approve or request changes on a pending report to see it here.
      </p>
      <p v-else>
        No cycle reports match the current filters.
      </p>
    </div>

    <!-- Awaiting review sub-section. Rendered when the
         ``all`` filter merges pending and reviewed in one
         list, so the operator can scan the queue without
         losing track of what they already decided. -->
    <template v-if="filterStatus === 'all' && pendingReports.length > 0">
      <h2 class="reviews-page__section-title" data-testid="reviews-section-pending">
        Awaiting review ({{ pendingReports.length }})
      </h2>
      <ul class="reviews-list">
        <li
          v-for="report in pendingReports"
          :key="report.id"
          class="review-row"
          :data-testid="`review-row-${report.id}`"
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

          <ReviewRowActions
            :report="report"
            :review-comment="reviewComments.get(report.id) ?? ''"
            :review-error="reviewErrors.get(report.id) ?? null"
            :is-self-review="isSelfReview(report)"
            :is-reviewing="reviewingId === report.id"
            :is-overriding="updatingId === report.id"
            @update-review-comment="setReviewComment(report.id, $event)"
            @submit-review="(decision) => submitReview(report, decision)"
            @override="(verdict) => override(report, verdict)"
          />
        </li>
      </ul>
    </template>

    <template v-if="filterStatus === 'all' && reviewedReports.length > 0">
      <h2 class="reviews-page__section-title" data-testid="reviews-section-reviewed">
        Reviewed ({{ reviewedReports.length }})
      </h2>
    </template>

    <ul v-if="filterStatus === 'all' && reviewedReports.length > 0" class="reviews-list">
      <li
        v-for="report in reviewedReports"
        :key="report.id"
        class="review-row review-row--reviewed"
        :data-testid="`review-row-reviewed-${report.id}`"
      >
        <header class="review-row__header">
          <div class="review-row__meta">
            <span class="review-row__key">{{ report.issueKey }}</span>
            <span :class="['review-row__status', `review-row__status--${report.issueStatus}`]">
              {{ report.issueStatus.replace('_', ' ') }}
            </span>
          </div>
          <span :class="['review-row__decision', `review-row__decision--${report.decision}`]" data-testid="review-row-decision-pill">
            {{ reviewDecisionLabel(report.decision as 'approved' | 'changes_requested') }}
          </span>
        </header>

        <h3 class="review-row__title">{{ report.issueTitle }}</h3>

        <section class="review-row__section">
          <h4>Plan</h4>
          <p>{{ report.plan }}</p>
        </section>

        <p class="review-row__review-summary">
          Reviewed by <strong>{{ report.reviewedBy || 'unknown' }}</strong>
          · {{ formatTime(report.reviewedAt) }}
        </p>
        <p v-if="report.reviewComment" class="review-row__review-comment">
          “{{ report.reviewComment }}”
        </p>
      </li>
    </ul>

    <ul v-if="filterStatus !== 'all' && reports.length > 0" class="reviews-list">
      <li
        v-for="report in reports"
        :key="report.id"
        class="review-row"
        :class="{ 'review-row--reviewed': report.decision }"
        :data-testid="`review-row-${report.id}`"
      >
        <header class="review-row__header">
          <div class="review-row__meta">
            <span class="review-row__key">{{ report.issueKey }}</span>
            <span :class="['review-row__status', `review-row__status--${report.issueStatus}`]">
              {{ report.issueStatus.replace('_', ' ') }}
            </span>
          </div>
          <span
            v-if="report.decision"
            :class="['review-row__decision', `review-row__decision--${report.decision}`]"
            data-testid="review-row-decision-pill"
          >
            {{ reviewDecisionLabel(report.decision as 'approved' | 'changes_requested') }}
          </span>
          <span
            v-else
            :class="['review-row__verdict', `review-row__verdict--${report.verdict}`]"
          >
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

        <!-- Reviewed rows: readonly summary only — no
             review/verdict buttons so a leader can't accidentally
             re-decide. -->
        <template v-if="report.decision">
          <p class="review-row__review-summary">
            Reviewed by <strong>{{ report.reviewedBy || 'unknown' }}</strong>
            · {{ formatTime(report.reviewedAt) }}
          </p>
          <p v-if="report.reviewComment" class="review-row__review-comment">
            “{{ report.reviewComment }}”
          </p>
        </template>

        <!-- Pending rows: same per-row review block the queue
             page has always had, plus the new review controls. -->
        <ReviewRowActions
          v-else
          :report="report"
          :review-comment="reviewComments.get(report.id) ?? ''"
          :review-error="reviewErrors.get(report.id) ?? null"
          :is-self-review="isSelfReview(report)"
          :is-reviewing="reviewingId === report.id"
          :is-overriding="updatingId === report.id"
          @update-review-comment="setReviewComment(report.id, $event)"
          @submit-review="(decision) => submitReview(report, decision)"
          @override="(verdict) => override(report, verdict)"
        />
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

/* Status filter — sits at the front of the filter bar so the
   split between "still to do" and "already done" is the first
   control a leader reaches for. */
.reviews-page__section-title {
  font-size: var(--text-md);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-muted);
  margin: var(--space-2) 0 0 0;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--hairline);
}

/* Decision pill — replaces the verdict pill on rows that have
   been reviewed, so the leader can spot a "Approved" / "Changes
   requested" row at a glance. */
.review-row__decision {
  font-size: var(--text-xs);
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.review-row__decision--approved       { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.review-row__decision--changes_requested { background: rgba(212, 168, 75, 0.18); color: #8A6B22; }

.review-row--reviewed {
  opacity: 0.85;
  border-style: dashed;
}

.review-row__review-summary {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ink-muted);
}
.review-row__review-comment {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink);
  font-style: italic;
  border-left: 2px solid var(--hairline);
  padding-left: var(--space-3);
}

/* Review action block (textarea + Approve / Request changes). */
.review-row__review {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border-top: 1px dashed var(--hairline);
  padding-top: var(--space-3);
  margin-top: var(--space-2);
}
.review-row__review-input {
  font-size: var(--text-sm);
  font-family: var(--font-sans, sans-serif);
  padding: 6px 8px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--canvas);
  color: var(--ink);
  resize: vertical;
  min-height: 44px;
}
.review-row__review-input:focus {
  outline: none;
  border-color: rgba(107, 139, 164, 0.6);
}
.review-row__review-buttons {
  display: flex;
  gap: var(--space-2);
}
.review-row__review-error {
  margin: 0;
  font-size: var(--text-xs);
  color: #B85C4D;
  background: rgba(184, 92, 77, 0.1);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
}
.review-row__self-hint {
  font-size: var(--text-xs);
  color: #8A6B22;
  background: rgba(212, 168, 75, 0.1);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
}
.review-btn--approve {
  background: rgba(125, 158, 125, 0.22);
  color: #4F6F4F;
  border-color: rgba(125, 158, 125, 0.5);
}
.review-btn--changes {
  background: rgba(212, 168, 75, 0.22);
  color: #8A6B22;
  border-color: rgba(212, 168, 75, 0.5);
}
</style>
