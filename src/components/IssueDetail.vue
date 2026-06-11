<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { COLUMN_CONFIG, PRIORITY_CONFIG, PROFILE_CONFIG } from '~/types'
import type { ECCLogEntry } from '~/types'
import { useRuntime } from '~/composables/useRuntime'
import { useToast } from '~/composables/useToast'
import { authHeaders } from '~/utils/authHeaders'
import {
  Bot, FileText, X, Archive, RotateCcw,
  Plus, Pencil, Trash2, GripVertical, Check,
} from 'lucide-vue-next'
import draggable from 'vuedraggable'
import IssueCollaborationTab from './IssueCollaborationTab.vue'
import HandoffSection from './lane/HandoffSection.vue'

const boardStore = useBoardStore()
const { fetchRunsByJobId, fetchRunLogs } = useRuntime()

const issue = computed(() => boardStore.selectedIssue)
const activeTab = computed(() => boardStore.activeDetailTab)
const currentJob = computed(() => {
  if (!issue.value) return null
  if (boardStore.selectedJob?.issue_id === issue.value.id) return boardStore.selectedJob
  if (issue.value.eccJobId) {
    return boardStore.jobs.find(job => job.id === issue.value?.eccJobId) ?? null
  }
  return boardStore.jobs
    .filter(job => job.issue_id === issue.value?.id)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0] ?? null
})

// P4: AgentRun events fetched from the runtime API, merged into timeline
const runEvents = ref<Array<ECCLogEntry>>([])

const selectedRunId = ref<string | null>(null)
const runDetails = ref<Map<string, { status: string; worker: string }>>(new Map())

const timelineLogs = computed<ECCLogEntry[]>(() => {
  const jobLogs = currentJob.value
    ? currentJob.value.events
        .slice()
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
        .map(event => ({
          id: `jobevt_${currentJob.value?.id}_${event.timestamp}_${event.status}`,
          timestamp: event.timestamp,
          phase: _inferPhase(event.message, event.status),
          content: event.message,
          confidence: event.status === 'review_required' ? 0.95 : 0.75
        }))
    : issue.value?.eccLogs ?? []

  // Merge AgentRun events (fetched separately) into the timeline
  if (runEvents.value.length > 0) {
    const merged = [...jobLogs, ...runEvents.value]
    merged.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    return merged
  }
  return jobLogs
})

const statusConfig = computed(() => {
  if (!issue.value) return null
  return COLUMN_CONFIG[issue.value.status]
})

const priorityConfig = computed(() => {
  if (!issue.value) return null
  return PRIORITY_CONFIG[issue.value.priority]
})

const profileConfig = computed(() => {
  if (!issue.value) return null
  return PROFILE_CONFIG[issue.value.profile]
})

const close = () => {
  boardStore.closeDetail()
}

const setTab = (tab: 'overview' | 'ecc-logs' | 'diff' | 'collaboration' | 'handoffs' | 'cycles') => {
  boardStore.setDetailTab(tab)
}

// ---------------------------------------------------------------------------
// Cycle reports — Mavis-style worker handoffs. Each issue has 0..N reports,
// newest first. Auto-written by the backend when an ECC job completes; the
// leader can override the verdict here, which also drives a lane transition
// for ``pass`` -> ``done``.
// ---------------------------------------------------------------------------
interface CycleReport {
  id: string
  issueId: string
  jobId: string | null
  authorId: string | null
  authorName: string | null
  plan: string
  progressLog: Array<{ ts: string; status: string; message: string }>
  deliverableSummary: string | null
  verdict: 'pending' | 'pass' | 'fail' | 'blocked' | 'auto_passed'
  verdictReason: string | null
  createdAt: string | null
  updatedAt: string | null
  // Review fields — populated by POST /cycle-reports/{id}/review
  // (see migration 0020). ``decision IS NULL`` means the report
  // hasn't been reviewed yet; the UI hides the action buttons
  // once a decision is recorded.
  decision: 'approved' | 'changes_requested' | null
  reviewComment: string | null
  reviewedAt: string | null
  reviewedBy: string | null
  reviewedById: string | null
}

const cycleReports = ref<CycleReport[]>([])
const updatingReportId = ref<string | null>(null)
let cycleAbort: AbortController | null = null

const loadCycleReports = async (issueId: string) => {
  // Abort any in-flight request so a fast tab-switch doesn't race two
  // fetches and clobber the list with the older response.
  cycleAbort?.abort()
  const ac = new AbortController()
  cycleAbort = ac
  try {
    const config = useRuntimeConfig()
    const res = await $fetch<{ cycleReports: CycleReport[] }>(
      `${config.public.apiBase}/issues/${issueId}/cycle-reports`,
      { signal: ac.signal, headers: authHeaders() },
    )
    cycleReports.value = res.cycleReports ?? []
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    console.error('[Cycles] failed to load reports:', err)
    cycleReports.value = []
  }
}

// Reload when the user switches to the cycles tab, or when the issue
// changes (board store reuses the drawer across selections).
watch(
  [() => activeTab.value, () => issue.value?.id],
  ([tab, id]) => {
    if (tab === 'cycles' && id) {
      void loadCycleReports(id)
    }
  },
  { immediate: true },
)

const verdictLabel = (v: string) => {
  switch (v) {
    case 'pass': return 'Pass'
    case 'auto_passed': return 'Auto-passed'
    case 'fail': return 'Failed'
    case 'blocked': return 'Blocked'
    case 'pending': return 'Pending review'
    default: return v
  }
}

const verdictClass = (v: string) => {
  if (v === 'pass' || v === 'auto_passed') return 'pass'
  if (v === 'fail') return 'fail'
  if (v === 'blocked') return 'blocked'
  return 'pending'
}

// Only verdicts that the leader can still change are surfaced. Once the
// report is in a terminal state, the override buttons hide to keep the
// card honest about what hasn't been reviewed yet.
const canOverride = (r: CycleReport) => {
  return r.verdict === 'pending' || r.verdict === 'auto_passed'
}

const overrideVerdict = async (report: CycleReport, verdict: 'pass' | 'fail' | 'blocked') => {
  if (!issue.value) return
  updatingReportId.value = report.id
  try {
    const config = useRuntimeConfig()
    const updated = await $fetch<CycleReport>(
      `${config.public.apiBase}/issues/${issue.value.id}/cycle-reports/${report.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: {
          verdict,
          verdict_reason:
            verdict === 'pass' ? 'Leader accepted the cycle report' :
            verdict === 'fail' ? 'Leader rejected the cycle report' :
            'Leader marked the cycle as blocked',
        },
        headers,
      },
    )
    // Patch in place; the leader override on ``pass`` triggers a
    // server-side issue auto-promote + WebSocket broadcast so the
    // board moves the card to ``done`` without a second click.
    const idx = cycleReports.value.findIndex(r => r.id === updated.id)
    if (idx >= 0) cycleReports.value[idx] = updated
  } catch (err) {
    console.error('[Cycles] override failed:', err)
  } finally {
    updatingReportId.value = null
  }
}

const formatCycleTime = (ts: string | null) => {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString()
  } catch { return ts }
}

// ---------------------------------------------------------------------------
// Review flow (POST /cycle-reports/{id}/review)
//
// Distinct from ``overrideVerdict``: a *verdict* override
// (pass/fail/blocked) is the leader's accept/reject of the
// work product, a *review* is the leader's accept/reject of
// the report itself (approve, or send the worker back with
// feedback). Both can coexist on the same report. The
// backend writes the review fields on cycle_reports and emits
// a ``cycle_report.review`` audit-log entry — see migration
// 0020 + the endpoint in cycle_reports.py.
// ---------------------------------------------------------------------------

// Per-report comment input — a Map keyed by report id so
// different reports on the same issue don't clobber each
// other when the user types in one card then switches focus.
const reviewComments = ref<Map<string, string>>(new Map())
const reviewingReportId = ref<string | null>(null)
const reviewErrors = ref<Map<string, string>>(new Map())

const setReviewComment = (reportId: string, value: string) => {
  const m = new Map(reviewComments.value)
  m.set(reportId, value)
  reviewComments.value = m
}

const setReviewError = (reportId: string, message: string | null) => {
  const m = new Map(reviewErrors.value)
  if (message === null) {
    m.delete(reportId)
  } else {
    m.set(reportId, message)
  }
  reviewErrors.value = m
}

// Self-review guard client-side: the backend also rejects with
// 403, but hiding the buttons up-front prevents the user from
// spending time on a comment only to see the error after submit.
const { authUser } = useAuth()
const currentUserId = computed<string | null>(() => authUser.value?.id ?? null)

const isSelfReview = (report: CycleReport) => {
  return !!(report.authorId && currentUserId.value && report.authorId === currentUserId.value)
}

const isReviewed = (report: CycleReport) => {
  return report.decision === 'approved' || report.decision === 'changes_requested'
}

const reviewDecisionLabel = (decision: 'approved' | 'changes_requested') => {
  return decision === 'approved' ? 'Approved' : 'Changes requested'
}

const reviewDecisionClass = (decision: 'approved' | 'changes_requested') => {
  return decision === 'approved' ? 'approved' : 'changes'
}

const submitReview = async (report: CycleReport, decision: 'approved' | 'changes_requested') => {
  reviewingReportId.value = report.id
  setReviewError(report.id, null)
  const comment = (reviewComments.value.get(report.id) ?? '').trim() || null
  try {
    const config = useRuntimeConfig()
    const updated = await $fetch<CycleReport>(
      `${config.public.apiBase}/cycle-reports/${report.id}/review`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: { decision, comment },
      },
    )
    // Optimistic patch + a server-of-truth refetch — same
    // pattern as the verdict override above. The two together
    // make the row animate to the new state immediately while
    // the next poll (or WS broadcast) reconciles any drift.
    const idx = cycleReports.value.findIndex(r => r.id === updated.id)
    if (idx >= 0) cycleReports.value[idx] = updated
    setReviewComment(report.id, '')
    if (issue.value?.id) {
      void loadCycleReports(issue.value.id)
    }
  } catch (err: any) {
    // Surface 4xx with a clear inline message; for 5xx
    // fall back to the raw error string so the operator can
    // at least copy it into a bug report.
    const detail = err?.data?.detail ?? err?.message ?? 'Failed to submit review'
    setReviewError(report.id, typeof detail === 'string' ? detail : 'Failed to submit review')
  } finally {
    reviewingReportId.value = null
  }
}

const formatLogTime = (ts: string) => {
  if (!ts) return ''
  try {
    // The backend timestamps carry timezone offset; trim to HH:MM:SS
    // so the progress log stays compact.
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return ts }
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatTimestamp = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const activityIcon = (type: string) => {
  const icons: Record<string, string> = {
    status_change: '→',
    ai_started: 'AI',
    ai_completed: '✓',
    pr_created: 'PR',
    quality_gate: 'QG',
    error: '!'
  }
  return icons[type] || '•'
}

const getPhaseIcon = (phase: string) => {
  const icons: Record<string, string> = {
    observation: 'OBS',
    reasoning: 'PLAN',
    action: 'RUN',
    output: 'OUT',
    error: 'ERR'
  }
  return icons[phase] || '•'
}

const getPhaseColor = (phase: string) => {
  const colors: Record<string, string> = {
    observation: 'var(--dusty-blue)',
    reasoning: 'var(--amber)',
    action: 'var(--primary)',
    output: 'var(--sage)',
    error: 'var(--clay-red)'
  }
  return colors[phase] || 'var(--muted)'
}

const _inferPhase = (message: string, status: string): ECCLogEntry['phase'] => {
  const value = message.toLowerCase()
  if (status === 'failed' || status === 'cancelled') return 'error'
  if (value.includes('analyz') || value.includes('started') || value.includes('queued')) return 'observation'
  if (value.includes('prepar') || value.includes('planning')) return 'reasoning'
  if (value.includes('running') || value.includes('check') || value.includes('execut')) return 'action'
  return 'output'
}

const handleApprove = async () => {
  if (!issue.value) return
  const success = await boardStore.approveReview(issue.value.id)
  if (success) {
    boardStore.closeDetail()
  }
}

const handleReject = () => {
  const commentsText = prompt('Enter review comments (one per line):')
  if (!commentsText) return

  const comments = commentsText.split('\n').filter(c => c.trim())
  if (comments.length === 0) return

  if (issue.value) {
    boardStore.rejectAndLoopBack(issue.value.id, comments)
    boardStore.closeDetail()
  }
}

const handleRetryMove = () => {
  if (issue.value) {
    boardStore.retryMove(issue.value.id)
  }
}

// C1+C2: catch up to server-side job state when the ECC Logs tab is opened
// for an issue that does not yet have an `eccJobId` on the client.
let stopPolling: (() => void) | null = null

const stopActivePolling = () => {
  if (stopPolling) {
    stopPolling()
    stopPolling = null
  }
}

watch(
  [activeTab, () => issue.value?.eccJobId],
  async ([tab, jobId]) => {
    // Always cancel any prior poll before deciding whether to start a new one.
    // Otherwise switching tabs or having a job land would leave the previous
    // poll running and firing redundant fetchJob calls.
    stopActivePolling()
    if (tab !== 'ecc-logs' || !issue.value || jobId) {
      // Tab is not active, no issue, or job already attached — nothing to do.
      return
    }
    const handle = await boardStore.pollIssueJob(issue.value.id)
    if (handle) {
      stopPolling = handle
    } else {
      // pollIssueJob returned null (no job on the server) — nothing to stop later.
      stopPolling = null
    }
  },
  { immediate: true }
)

// P4: Fetch AgentRun events when ecc-logs tab is active and a job is linked
watch(
  [activeTab, currentJob],
  async ([tab, job]) => {
    if (tab !== 'ecc-logs' || !job) {
      runEvents.value = []
      return
    }
    try {
      const linkedRuns = await fetchRunsByJobId(job.id)
      if (linkedRuns.length === 0) {
        runEvents.value = []
        runDetails.value = new Map()
        return
      }
      // Store run metadata for the detail panel
      const detailsMap = new Map<string, { status: string; worker: string }>()
      for (const run of linkedRuns) {
        detailsMap.set(run.id, { status: run.status, worker: run.workerId ?? 'unknown' })
      }
      runDetails.value = detailsMap
      // Fetch events for all linked runs and merge
      const allEvents = await Promise.all(
        linkedRuns.map(async (run) => {
          const logs = await fetchRunLogs(run.id)
          return logs.map(log => ({
            id: `runevt_${log.id}`,
            timestamp: log.createdAt ?? new Date().toISOString(),
            phase: (['observation', 'reasoning', 'action', 'output', 'error'].includes(log.eventType)
              ? log.eventType
              : 'observation') as ECCLogEntry['phase'],
            content: log.message ?? '',
            confidence: 0.85,
            runId: run.id,
          }))
        })
      )
      runEvents.value = allEvents.flat()
    } catch {
      runEvents.value = []
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  stopActivePolling()
})

// ---------------------------------------------------------------------------
// Acceptance Criteria — operator-driven AC management.
//
// Two flows live here:
//   1. AI Suggest AC:  the existing "Suggest AC" button calls the backend
//      /suggest-ac endpoint, which uses the active LLM provider if
//      configured and falls back to a deterministic heuristic. The
//      operator commits via "Apply all" (PATCH /acceptance-criteria).
//   2. Inline editor:  the operator can add / edit / delete / toggle /
//      reorder AC entries directly. Every action does an *optimistic*
//      update against the local mirror first, then calls PATCH
//      /acceptance-criteria with the full array. On error we roll back
//      the local mirror and surface a toast.
//
// We keep a local ref (`acLocal`) rather than mutating
// `issue.value.acceptanceCriteria` directly so the rollback path is
// obvious and so the AI-Suggest-apply can replace the mirror without
// touching anything else.
// ---------------------------------------------------------------------------
interface AcItem { id: string; text: string; done: boolean }
interface SuggestResponse {
  source: 'llm' | 'cache' | 'heuristic'
  provider: string | null
  model: string | null
  criteria: AcItem[]
}

const acSuggestion = ref<SuggestResponse | null>(null)
const acSuggesting = ref(false)
const acApplying = ref(false)

// Local mirror of acceptanceCriteria on the current issue. We re-sync
// from the issue when the issue id changes (board reuses the drawer
// across selections), and after the AI-Suggest apply.
const acLocal = ref<AcItem[]>([])
let lastSyncedIssueId: string | null = null

const syncAcFromIssue = () => {
  if (!issue.value) {
    acLocal.value = []
    lastSyncedIssueId = null
    return
  }
  // Deep clone the AC entries so optimistic edits don't mutate the
  // board store's shared issue object.
  acLocal.value = (issue.value.acceptanceCriteria ?? []).map(c => ({ ...c }))
  lastSyncedIssueId = issue.value.id
}

// --- Inline editor state ---------------------------------------------------

// Declared BEFORE the watcher below: the watcher runs
// ``immediate: true`` so it fires during setup, and the TDZ would
// bite us if the refs lived further down the file. Keep all editor
// state above any watcher that touches it.
const showAddRow = ref(false)
const newAcText = ref('')
const editingId = ref<string | null>(null)
const editingText = ref('')
const acSaving = ref(false)
const acError = ref<string | null>(null)
const { add: addToast } = useToast()

watch(
  () => issue.value?.id,
  () => {
    // Switching to a different issue: drop any open editor state and
    // pull a fresh copy of the AC list.
    editingId.value = null
    newAcText.value = ''
    showAddRow.value = false
    syncAcFromIssue()
  },
  { immediate: true },
)

const suggestAcceptanceCriteria = async () => {
  if (!issue.value) return
  acSuggesting.value = true
  try {
    const config = useRuntimeConfig()
    const res = await $fetch<SuggestResponse>(
      `${config.public.apiBase}/issues/${issue.value.id}/suggest-ac`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: {},
      },
    )
    acSuggestion.value = res
  } catch (err) {
    console.error('[AC] suggest failed:', err)
  } finally {
    acSuggesting.value = false
  }
}

const applySuggestion = async () => {
  if (!issue.value || !acSuggestion.value) return
  acApplying.value = true
  try {
    // Merge: append the suggested criteria to whatever's already
    // on the issue. The operator can re-edit / drop dupes after.
    // We don't dedupe on text here because re-suggesting the same
    // issue with a tweaked description is a legit workflow.
    const merged: AcItem[] = [...acLocal.value, ...acSuggestion.value.criteria]
    await persistAcceptanceCriteria(merged, 'apply suggestion')
    acSuggestion.value = null
  } catch (err) {
    console.error('[AC] apply failed:', err)
  } finally {
    acApplying.value = false
  }
}

// --- Inline editor state ---------------------------------------------------

// (refs are declared above so the immediate watcher doesn't hit the
// TDZ — the rest of the editor logic lives down here.)

// Build a stable client-side id for new entries. The backend fills
// any missing id with a uuid on save, but we keep the local one so
// the optimistic render doesn't flicker if the server rewrites it.
const makeAcId = () => `ac_local_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`

const beginAdd = () => {
  showAddRow.value = true
  newAcText.value = ''
  editingId.value = null
  editingText.value = ''
}

const cancelAdd = () => {
  showAddRow.value = false
  newAcText.value = ''
}

const commitAdd = async () => {
  const text = newAcText.value.trim()
  if (!text || !issue.value) return
  const newItem: AcItem = { id: makeAcId(), text, done: false }
  const previous = [...acLocal.value]
  const next = [...acLocal.value, newItem]
  // Optimistic: render immediately, close the input row, clear text.
  acLocal.value = next
  showAddRow.value = false
  newAcText.value = ''
  try {
    await persistAcceptanceCriteria(next, 'add criterion')
  } catch {
    // persistAcceptanceCriteria already rolled back + toasted.
    void previous
  }
}

const beginEdit = (ac: AcItem) => {
  editingId.value = ac.id
  editingText.value = ac.text
  // Close any open add row so the drawer doesn't grow two inputs.
  showAddRow.value = false
  newAcText.value = ''
}

const cancelEdit = () => {
  editingId.value = null
  editingText.value = ''
}

const commitEdit = async (ac: AcItem) => {
  const text = editingText.value.trim()
  if (!text || !issue.value) {
    cancelEdit()
    return
  }
  if (text === ac.text) {
    // No change — don't fire an API call.
    cancelEdit()
    return
  }
  const next = acLocal.value.map(c => c.id === ac.id ? { ...c, text } : c)
  acLocal.value = next
  cancelEdit()
  try {
    await persistAcceptanceCriteria(next, 'edit criterion')
  } catch {
    // rolled back already
  }
}

const removeAcceptanceCriterion = async (ac: AcItem) => {
  if (!issue.value) return
  // Use window.confirm so the prompt feels native to the existing
  // archive flow. The operator can also cancel and keep the row.
  // We don't want a fancy modal for one-click destructive ops.
  const ok = window.confirm(
    `Delete this acceptance criterion?\n\n"${ac.text}"`,
  )
  if (!ok) return
  const next = acLocal.value.filter(c => c.id !== ac.id)
  const previous = acLocal.value
  acLocal.value = next
  try {
    await persistAcceptanceCriteria(next, 'delete criterion')
  } catch {
    // rolled back already
    void previous
  }
}

const toggleAcceptanceCriterion = async (ac: AcItem) => {
  if (!issue.value) return
  // Optimistic — flip locally first, then sync. The checkbox binds to
  // acLocal via the render path so the visual update is instant; we
  // don't wait for the API round-trip.
  const next = acLocal.value.map(c => c.id === ac.id ? { ...c, done: !c.done } : c)
  acLocal.value = next
  try {
    await persistAcceptanceCriteria(next, 'toggle criterion')
  } catch {
    // rolled back already
  }
}

// --- Persist (with rollback + toast on error) -----------------------------

async function persistAcceptanceCriteria(
  next: AcItem[],
  reason: string,
): Promise<void> {
  if (!issue.value) return
  const previous = acLocal.value
  const target = issue.value.id
  acSaving.value = true
  acError.value = null
  try {
    const config = useRuntimeConfig()
    const res = await $fetch<{ acceptanceCriteria: AcItem[] } | null>(
      `${config.public.apiBase}/issues/${target}/acceptance-criteria`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: { criteria: next },
      },
    )
    // The endpoint returns the updated issue (with the cleaned AC
    // list including server-assigned ids). We update both the
    // mirror and the board store's selectedIssue so the next
    // external refresh sees the same shape. Only mutate if we're
    // still on the same issue — switching issues mid-flight would
    // stomp the new selection.
    if (issue.value && issue.value.id === target) {
      const fresh: AcItem[] = ((res as any)?.acceptanceCriteria ?? next) as AcItem[]
      acLocal.value = fresh.map((c: AcItem) => ({ ...c }))
      issue.value.acceptanceCriteria = fresh
    }
  } catch (err: any) {
    // Roll back the optimistic update.
    if (issue.value && issue.value.id === target) {
      acLocal.value = previous
    }
    const detail = err?.data?.detail ?? err?.message ?? 'Network error'
    acError.value = `Failed to ${reason}: ${detail}`
    addToast(acError.value)
    console.error('[AC] persist failed:', err)
    throw err
  } finally {
    acSaving.value = false
  }
}

// --- Drag-to-reorder -------------------------------------------------------

// vuedraggable mutates the bound array in place when the user drops.
// We hand it a v-model on acLocal and call persistAcceptanceCriteria
// when the array length is unchanged (a real reorder, not an add/remove).
const onAcReorder = async () => {
  if (!issue.value) return
  // No real length change — it's a pure reorder, push the new order.
  try {
    await persistAcceptanceCriteria([...acLocal.value], 'reorder')
  } catch {
    // rollback will restore the previous order; vuedraggable has
    // already mutated the array, so we set acLocal back to the
    // previous snapshot taken inside persistAcceptanceCriteria.
  }
}

// ---------------------------------------------------------------------------
// Archive / unarchive (soft delete).
//
// The board endpoint filters archived issues out by default, so as
// soon as the archive call lands the issue disappears from the
// main view. We close the drawer after archiving so the operator
// doesn't have to stare at an empty drawer; unarchive keeps it
// open since the issue is now back in the live set.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Link to epic (set parent).
//
// We don't expose every issue as a candidate parent — only root
// epics (issues with no parent) on the same board. The board store
// already holds them in `boardStore.issues`; we filter client-side
// and exclude the current issue plus its descendants. A descendant
// can't be set as parent because that would create a cycle in the
// parent graph (the backend rejects it with 400 too, but the UI
// should hint at this *before* the user picks one).
// ---------------------------------------------------------------------------
const showParentPicker = ref(false)
const parentPickerLoading = ref(false)
const parentPickerError = ref<string | null>(null)
const linkingParent = ref(false)

const parentIssue = computed(() => {
  if (!issue.value?.parentId) return null
  return boardStore.getAllIssues.find(i => i.id === issue.value?.parentId) ?? null
})

// Walk the current issue's descendants using whatever we know
// about the local board state. This is best-effort: if the tree is
// paged out we fall back to the empty set, and the backend's
// `get_epic_chain` does the authoritative cycle check at PATCH
// time.
const descendantIds = computed(() => {
  const all = boardStore.getAllIssues
  if (!issue.value || !all.length) return new Set<string>()
  const out = new Set<string>()
  const queue = [issue.value.id]
  while (queue.length) {
    const cur = queue.shift()!
    for (const cand of all) {
      if (cand.parentId === cur && !out.has(cand.id)) {
        out.add(cand.id)
        queue.push(cand.id)
      }
    }
  }
  return out
})

const parentCandidates = computed(() => {
  const all = boardStore.getAllIssues
  if (!issue.value || !all.length) return []
  const selfId = issue.value.id
  const excluded = descendantIds.value
  excluded.add(selfId)
  return all
    .filter(i => i.id !== selfId && i.parentId == null && !excluded.has(i.id))
    .sort((a, b) => a.key.localeCompare(b.key))
})

const linkToEpic = async (parentId: string) => {
  if (!issue.value) return
  linkingParent.value = true
  parentPickerError.value = null
  try {
    const config = useRuntimeConfig()
    const updated = await $fetch<{ parentId: string | null }>(
      `${config.public.apiBase}/issues/${issue.value.id}/parent`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: { parentId },
      },
    )
    issue.value.parentId = updated.parentId ?? null
    showParentPicker.value = false
  } catch (err: any) {
    const detail = err?.data?.detail ?? err?.message ?? 'Failed to link to epic'
    parentPickerError.value = detail
  } finally {
    linkingParent.value = false
  }
}

const unlinkFromEpic = async () => {
  if (!issue.value) return
  linkingParent.value = true
  parentPickerError.value = null
  try {
    const config = useRuntimeConfig()
    const updated = await $fetch<{ parentId: string | null }>(
      `${config.public.apiBase}/issues/${issue.value.id}/parent`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: { parentId: null },
      },
    )
    issue.value.parentId = updated.parentId ?? null
  } catch (err: any) {
    const detail = err?.data?.detail ?? err?.message ?? 'Failed to unlink from epic'
    parentPickerError.value = detail
  } finally {
    linkingParent.value = false
  }
}

const archiving = ref(false)

const archiveIssue = async () => {
  if (!issue.value) return
  if (!confirm(`Archive ${issue.value.key}? It will be hidden from the board view but kept in the database.`)) {
    return
  }
  archiving.value = true
  try {
    const config = useRuntimeConfig()
    await $fetch(
      `${config.public.apiBase}/issues/${issue.value.id}/archive`,
      { method: 'POST', headers: authHeaders() },
    )
    if (issue.value) {
      issue.value.isArchived = true
    }
    // Close the drawer so the operator doesn't see a "ghost" card;
    // the board re-fetch is the source of truth for what's visible.
    close()
  } catch (err) {
    console.error('[archive] failed:', err)
  } finally {
    archiving.value = false
  }
}

const unarchiveIssue = async () => {
  if (!issue.value) return
  archiving.value = true
  try {
    const config = useRuntimeConfig()
    await $fetch(
      `${config.public.apiBase}/issues/${issue.value.id}/unarchive`,
      { method: 'POST', headers: authHeaders() },
    )
    if (issue.value) {
      issue.value.isArchived = false
    }
  } catch (err) {
    console.error('[unarchive] failed:', err)
  } finally {
    archiving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="slide">
      <div v-if="boardStore.isDetailOpen && issue" class="issue-detail">
        <!-- Backdrop -->
        <div class="issue-detail__backdrop" @click="close" />

        <!-- Panel -->
        <div class="issue-detail__panel">
          <!-- Header -->
          <div class="issue-detail__header">
            <div class="issue-detail__header-left">
              <span class="issue-detail__key">{{ issue.key }}</span>
              <span
                class="issue-detail__status"
                :style="{
                  backgroundColor: `${statusConfig?.color}15`,
                  color: statusConfig?.color
                }"
              >
                {{ statusConfig?.title }}
              </span>
              <span
                v-if="issue.isArchived"
                class="issue-detail__archived-pill"
                title="This issue is archived and hidden from the main board"
              >
                <Archive :size="13" /> Archived
              </span>
            </div>
            <div class="issue-detail__header-actions">
              <span
                v-if="parentIssue"
                class="issue-detail__parent-chip"
                :title="`Linked to epic ${parentIssue.key} — ${parentIssue.title}`"
              >
                <NuxtLink
                  :to="`/board/epic/${parentIssue.id}`"
                  class="issue-detail__parent-link"
                >
                  ↑ {{ parentIssue.key }}
                </NuxtLink>
                <button
                  class="issue-detail__parent-unlink"
                  :disabled="linkingParent"
                  title="Unlink from this epic"
                  @click="unlinkFromEpic"
                >
                  <X :size="12" />
                </button>
              </span>
              <button
                v-if="!issue.isArchived && !parentIssue"
                class="issue-detail__link-epic-btn"
                :disabled="parentPickerLoading"
                @click="showParentPicker = true"
              >
                Link to epic
              </button>
              <span
                v-if="parentPickerError"
                class="issue-detail__parent-error"
                :title="parentPickerError"
              >
                {{ parentPickerError }}
              </span>
              <button
                v-if="!issue.isArchived"
                class="issue-detail__archive-btn"
                :disabled="archiving"
                @click="archiveIssue"
              >
                <Archive :size="14" /> {{ archiving ? 'Archiving…' : 'Archive' }}
              </button>
              <button
                v-else
                class="issue-detail__unarchive-btn"
                :disabled="archiving"
                @click="unarchiveIssue"
              >
                <RotateCcw :size="14" /> {{ archiving ? 'Restoring…' : 'Unarchive' }}
              </button>
              <button class="issue-detail__close" @click="close">
                <X :size="18" />
              </button>
            </div>
          </div>

          <!-- Tabs -->
          <div class="issue-detail__tabs">
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'overview' }]"
              @click="setTab('overview')"
            >
              Overview
            </button>
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'ecc-logs' }]"
              @click="setTab('ecc-logs')"
            >
              <Bot :size="15" />
              ECC Logs
              <span v-if="timelineLogs.length > 0" class="issue-detail__tab-badge">
                {{ timelineLogs.length }}
              </span>
            </button>
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'diff' }]"
              @click="setTab('diff')"
            >
              <FileText :size="15" />
              Diff / PR
              <span v-if="issue.prDetails" class="issue-detail__tab-badge issue-detail__tab-badge--accent">
                PR #{{ issue.prDetails.number }}
              </span>
            </button>
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'collaboration' }]"
              @click="setTab('collaboration')"
            >
              Notes
            </button>
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'handoffs' }]"
              @click="setTab('handoffs')"
            >
              Handoffs
              <span v-if="issue.handoffs?.length" class="issue-detail__tab-badge">
                {{ issue.handoffs.length }}
              </span>
            </button>
            <button
              :class="['issue-detail__tab', { 'issue-detail__tab--active': activeTab === 'cycles' }]"
              @click="setTab('cycles')"
            >
              Cycles
              <span v-if="cycleReports.length > 0" class="issue-detail__tab-badge">
                {{ cycleReports.length }}
              </span>
            </button>
          </div>

          <!-- Tab Content -->
          <div class="issue-detail__content">
            <!-- Overview Tab -->
            <div v-if="activeTab === 'overview'" class="issue-detail__tab-pane">
              <!-- Move Error Banner -->
              <div v-if="issue.moveStatus === 'failed'" class="issue-detail__error-banner">
                <svg class="issue-detail__error-banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <div class="issue-detail__error-banner-content">
                  <span class="issue-detail__error-banner-title">Move operation failed</span>
                  <span class="issue-detail__error-banner-message">{{ issue.moveError }}</span>
                </div>
                <button class="issue-detail__error-banner-btn" @click="handleRetryMove">
                  Retry
                </button>
              </div>

              <!-- Title -->
              <h2 class="issue-detail__title">{{ issue.title }}</h2>

              <!-- Meta Row -->
              <div class="issue-detail__meta-row">
                <div class="issue-detail__meta-item">
                  <span class="issue-detail__meta-label">Priority</span>
                  <span class="issue-detail__meta-value" :style="{ color: priorityConfig?.color }">
                    {{ priorityConfig?.label }}
                  </span>
                </div>
                <div class="issue-detail__meta-item">
                  <span class="issue-detail__meta-label">Profile</span>
                  <span
                    class="issue-detail__meta-value"
                    :style="{ color: profileConfig?.color }"
                  >
                    {{ profileConfig?.label }}
                  </span>
                </div>
                <div v-if="issue.storyPoints" class="issue-detail__meta-item">
                  <span class="issue-detail__meta-label">Points</span>
                  <span class="issue-detail__meta-value">{{ issue.storyPoints }}</span>
                </div>
                <div v-if="issue.harnessType" class="issue-detail__meta-item">
                  <span class="issue-detail__meta-label">Harness</span>
                  <span class="issue-detail__meta-value issue-detail__meta-value--mono">
                    {{ issue.harnessType }}
                  </span>
                </div>
                <div v-if="issue.eccJobStatus" class="issue-detail__meta-item">
                  <span class="issue-detail__meta-label">ECC Job</span>
                  <span class="issue-detail__meta-value issue-detail__meta-value--mono">
                    {{ issue.eccJobStatus }}
                  </span>
                </div>
              </div>

              <div v-if="issue.eccJobId" class="issue-detail__section issue-detail__job">
                <h3 class="issue-detail__section-title">Control Plane Job</h3>
                <div class="issue-detail__job-row">
                  <span>ID</span>
                  <strong>{{ issue.eccJobId }}</strong>
                </div>
                <div v-if="issue.eccJobMessage" class="issue-detail__job-row">
                  <span>Last event</span>
                  <strong>{{ issue.eccJobMessage }}</strong>
                </div>
                <div v-if="issue.eccJobUpdatedAt" class="issue-detail__job-row">
                  <span>Updated</span>
                  <strong>{{ formatTimestamp(issue.eccJobUpdatedAt) }}</strong>
                </div>
              </div>

              <!-- Assignee -->
              <div v-if="issue.assigneeName" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Assignee</h3>
                <div class="issue-detail__assignee">
                  <AvatarStack
                    :name="issue.assigneeName"
                    :avatar-url="issue.assigneeAvatar"
                    size="md"
                  />
                  <span class="issue-detail__assignee-name">{{ issue.assigneeName }}</span>
                </div>
              </div>

              <!-- Description -->
              <div v-if="issue.description" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Description</h3>
                <p class="issue-detail__description">{{ issue.description }}</p>
              </div>

              <!-- Acceptance Criteria (Mavis collab) — rendered as a
                   checklist so the operator can flip items as they
                   pass. The "Suggest AC" button calls the backend
                   endpoint, which falls back to a heuristic when no
                   LLM provider is configured; either way the
                   result is the same shape and committed via the
                   existing PATCH /acceptance-criteria endpoint. -->
              <div class="issue-detail__section">
                <div class="issue-detail__ac-header">
                  <h3 class="issue-detail__section-title">
                    Acceptance Criteria
                    <span
                      v-if="(issue.acceptanceCriteria?.length ?? 0) > 0"
                      class="issue-detail__ac-count"
                    >
                      {{ issue.acceptanceCriteria?.filter(ac => ac.done).length ?? 0 }} / {{ issue.acceptanceCriteria?.length ?? 0 }}
                    </span>
                  </h3>
                  <div class="issue-detail__ac-actions">
                    <button
                      class="issue-detail__suggest-btn"
                      :disabled="acSuggesting"
                      @click="suggestAcceptanceCriteria"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        width="14"
                        height="14"
                      >
                        <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2" />
                        <path d="M14 4.5a2.5 2.5 0 0 0-2.5 2.5v.5" />
                      </svg>
                      {{ acSuggesting ? 'Thinking…' : 'Suggest AC' }}
                    </button>
                  </div>
                </div>
                <div v-if="acSuggestion" class="issue-detail__ac-suggestion">
                  <div class="issue-detail__ac-suggestion-meta">
                    <span :class="['issue-detail__ac-source', `issue-detail__ac-source--${acSuggestion.source}`]">
                      {{ acSuggestion.source === 'llm' ? 'AI' : acSuggestion.source === 'cache' ? 'cached' : 'heuristic' }}
                    </span>
                    <span v-if="acSuggestion.provider" class="issue-detail__ac-provider">
                      via {{ acSuggestion.provider }}
                    </span>
                    <button class="issue-detail__ac-discard" @click="acSuggestion = null">
                      Discard
                    </button>
                    <button
                      v-if="!acApplying"
                      class="issue-detail__ac-apply"
                      @click="applySuggestion"
                    >
                      Apply all
                    </button>
                  </div>
                  <ul class="issue-detail__ac-suggestion-list">
                    <li
                      v-for="(c, idx) in acSuggestion.criteria"
                      :key="c.id || idx"
                    >
                      {{ c.text }}
                    </li>
                  </ul>
                </div>
                <!--
                  Inline editor: every entry is a row. The default
                  state shows checkbox + text + edit / delete / drag
                  handle. Tapping edit swaps the text for an input;
                  tapping the + at the bottom of the list reveals a
                  new-row input. vuedraggable wraps the <ul> so a
                  pure-reorder drop fires ``onAcReorder`` and saves
                  the new order to the backend.
                -->
                <ul
                  v-if="acLocal.length > 0"
                  class="issue-detail__ac-list"
                  data-testid="ac-list"
                >
                  <draggable
                    v-model="acLocal"
                    :animation="160"
                    handle=".issue-detail__ac-drag"
                    item-key="id"
                    tag="div"
                    class="issue-detail__ac-drag-root"
                    @end="onAcReorder"
                  >
                    <template #item="{ element: ac }">
                      <li
                        :key="ac.id"
                        :class="['issue-detail__ac-item', ac.done && 'issue-detail__ac-item--done', editingId === ac.id && 'issue-detail__ac-item--editing']"
                        :data-testid="`ac-item-${ac.id}`"
                      >
                        <span
                          class="issue-detail__ac-drag"
                          :title="acSaving ? 'Saving…' : 'Drag to reorder'"
                          aria-label="Drag to reorder"
                        >
                          <GripVertical :size="14" />
                        </span>
                        <input
                          type="checkbox"
                          :checked="ac.done"
                          :disabled="acSaving"
                          :data-testid="`ac-toggle-${ac.id}`"
                          @change="toggleAcceptanceCriterion(ac)"
                        />
                        <template v-if="editingId === ac.id">
                          <input
                            v-model="editingText"
                            type="text"
                            class="issue-detail__ac-edit-input"
                            :data-testid="`ac-edit-input-${ac.id}`"
                            autofocus
                            @keydown.enter.prevent="commitEdit(ac)"
                            @keydown.esc.prevent="cancelEdit"
                            @blur="commitEdit(ac)"
                          />
                          <button
                            type="button"
                            class="issue-detail__ac-icon-btn"
                            title="Save"
                            :data-testid="`ac-save-${ac.id}`"
                            @mousedown.prevent
                            @click="commitEdit(ac)"
                          >
                            <Check :size="14" />
                          </button>
                          <button
                            type="button"
                            class="issue-detail__ac-icon-btn"
                            title="Cancel"
                            @mousedown.prevent
                            @click="cancelEdit"
                          >
                            <X :size="14" />
                          </button>
                        </template>
                        <template v-else>
                          <span class="issue-detail__ac-text">{{ ac.text }}</span>
                          <button
                            type="button"
                            class="issue-detail__ac-icon-btn"
                            title="Edit"
                            :data-testid="`ac-edit-${ac.id}`"
                            @click="beginEdit(ac)"
                          >
                            <Pencil :size="13" />
                          </button>
                          <button
                            type="button"
                            class="issue-detail__ac-icon-btn issue-detail__ac-icon-btn--danger"
                            title="Delete"
                            :data-testid="`ac-delete-${ac.id}`"
                            @click="removeAcceptanceCriterion(ac)"
                          >
                            <Trash2 :size="13" />
                          </button>
                        </template>
                      </li>
                    </template>
                  </draggable>
                </ul>
                <p
                  v-else
                  class="issue-detail__ac-empty"
                  data-testid="ac-empty-state"
                >
                  No acceptance criteria yet — add one or use <strong>AI Suggest</strong>.
                </p>

                <div
                  v-if="showAddRow"
                  class="issue-detail__ac-add-row"
                  data-testid="ac-add-row"
                >
                  <input
                    v-model="newAcText"
                    type="text"
                    class="issue-detail__ac-edit-input"
                    placeholder="New criterion…"
                    data-testid="ac-add-input"
                    autofocus
                    @keydown.enter.prevent="commitAdd"
                    @keydown.esc.prevent="cancelAdd"
                  />
                  <button
                    type="button"
                    class="issue-detail__ac-icon-btn"
                    title="Save"
                    :disabled="!newAcText.trim() || acSaving"
                    data-testid="ac-add-save"
                    @click="commitAdd"
                  >
                    <Check :size="14" />
                  </button>
                  <button
                    type="button"
                    class="issue-detail__ac-icon-btn"
                    title="Cancel"
                    @click="cancelAdd"
                  >
                    <X :size="14" />
                  </button>
                </div>

                <button
                  v-if="!showAddRow"
                  type="button"
                  class="issue-detail__ac-add-btn"
                  data-testid="ac-add-button"
                  @click="beginAdd"
                >
                  <Plus :size="14" /> Add criterion
                </button>
              </div>

              <!-- Labels -->
              <div v-if="issue.labels.length > 0" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Labels</h3>
                <div class="issue-detail__labels">
                  <LabelChip
                    v-for="label in issue.labels"
                    :key="label.id"
                    :label="label"
                    size="md"
                  />
                </div>
              </div>

              <!-- Dependencies -->
              <div v-if="issue.dependencies.length > 0" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Dependencies ({{ issue.dependencies.length }})</h3>
                <div class="issue-detail__dependencies">
                  <span
                    v-for="dep in issue.dependencies"
                    :key="dep"
                    class="issue-detail__dep-chip"
                  >
                    {{ dep }}
                  </span>
                </div>
              </div>

              <!-- PR Link -->
              <div v-if="issue.prUrl" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Pull Request</h3>
                <a :href="issue.prUrl" target="_blank" class="issue-detail__pr-link">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                    <path d="M15 3h6v6M10 14L21 3" />
                  </svg>
                  Open PR
                </a>
              </div>

              <!-- Activity Log -->
              <div v-if="issue.activityLog.length > 0" class="issue-detail__section">
                <h3 class="issue-detail__section-title">Activity</h3>
                <div class="issue-detail__activity">
                  <div
                    v-for="entry in issue.activityLog"
                    :key="entry.id"
                    class="issue-detail__activity-entry"
                  >
                    <span class="issue-detail__activity-icon">{{ activityIcon(entry.type) }}</span>
                    <div class="issue-detail__activity-content">
                      <span class="issue-detail__activity-message">{{ entry.message }}</span>
                      <div class="issue-detail__activity-meta">
                        <span class="issue-detail__activity-actor">{{ entry.actor }}</span>
                        <span class="issue-detail__activity-time">{{ formatDate(entry.timestamp) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- ECC Logs Tab -->
            <div v-if="activeTab === 'ecc-logs'" class="issue-detail__tab-pane">
              <div v-if="!currentJob && timelineLogs.length === 0" class="issue-detail__empty-state">
                <svg class="issue-detail__empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                <span class="issue-detail__empty-state-text">No execution jobs yet</span>
                <span class="issue-detail__empty-state-hint">Move the card to In Progress to dispatch an ECC job.</span>
              </div>
              <div v-else class="issue-detail__ecc-logs">
                <div v-if="currentJob" class="issue-detail__job-card" data-testid="ecc-job-summary">
                  <div class="issue-detail__job-card-row">
                    <span>Job ID</span>
                    <strong>{{ currentJob.id }}</strong>
                  </div>
                  <div class="issue-detail__job-card-row">
                    <span>Command</span>
                    <strong>{{ currentJob.command }}</strong>
                  </div>
                  <div class="issue-detail__job-card-grid">
                    <div>
                      <span>Profile</span>
                      <strong>{{ currentJob.profile }}</strong>
                    </div>
                    <div>
                      <span>Harness</span>
                      <strong>{{ currentJob.harness }}</strong>
                    </div>
                    <div>
                      <span>Status</span>
                      <strong>{{ currentJob.status }}</strong>
                    </div>
                  </div>
                  <div class="issue-detail__job-card-grid">
                    <div>
                      <span>Created</span>
                      <strong>{{ formatTimestamp(currentJob.created_at) }}</strong>
                    </div>
                    <div>
                      <span>Updated</span>
                      <strong>{{ formatTimestamp(currentJob.updated_at) }}</strong>
                    </div>
                  </div>
                </div>
                <div
                  v-for="log in timelineLogs"
                  :key="log.id"
                  class="issue-detail__ecc-log-entry"
                  data-testid="ecc-log-entry"
                >
                  <div class="issue-detail__ecc-log-header">
                    <span
                      class="issue-detail__ecc-log-phase"
                      :style="{ backgroundColor: `${getPhaseColor(log.phase)}15`, color: getPhaseColor(log.phase) }"
                    >
                      {{ getPhaseIcon(log.phase) }} {{ log.phase }}
                    </span>
                    <span class="issue-detail__ecc-log-time">{{ formatTimestamp(log.timestamp) }}</span>
                    <span v-if="log.toolUsed" class="issue-detail__ecc-log-tool">{{ log.toolUsed }}</span>
                    <span v-if="log.duration" class="issue-detail__ecc-log-duration">{{ log.duration }}ms</span>
                    <button
                      v-if="log.runId"
                      class="issue-detail__run-link"
                      @click="selectedRunId = selectedRunId === log.runId ? null : log.runId"
                    >
                      {{ selectedRunId === log.runId ? 'Hide' : 'View' }} Run
                    </button>
                  </div>
                  <div class="issue-detail__ecc-log-content">
                    {{ log.content }}
                  </div>
                  <div v-if="log.confidence !== undefined" class="issue-detail__ecc-log-confidence">
                    <div class="issue-detail__ecc-log-confidence-bar">
                      <div
                        class="issue-detail__ecc-log-confidence-fill"
                        :style="{ width: `${log.confidence * 100}%` }"
                      />
                    </div>
                    <span class="issue-detail__ecc-log-confidence-label">
                      {{ Math.round(log.confidence * 100) }}% confidence
                    </span>
                  </div>
                  <div v-if="selectedRunId === log.runId" class="issue-detail__run-detail" data-testid="run-detail-panel">
                    <div class="issue-detail__run-meta">
                      <span>Run: {{ selectedRunId }}</span>
                      <span>Status: {{ runDetails.get(selectedRunId ?? '')?.status ?? 'unknown' }}</span>
                      <span>Worker: {{ runDetails.get(selectedRunId ?? '')?.worker ?? 'unknown' }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Diff / PR Tab -->
            <div v-if="activeTab === 'diff'" class="issue-detail__tab-pane">
              <div v-if="!issue.prDetails" class="issue-detail__empty-state">
                <svg class="issue-detail__empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22" />
                </svg>
                <span class="issue-detail__empty-state-text">No PR yet</span>
                <span class="issue-detail__empty-state-hint">PR details appear after AI completes task</span>
              </div>
              <div v-else class="issue-detail__diff">
                <!-- PR Summary -->
                <div class="issue-detail__pr-summary">
                  <div class="issue-detail__pr-summary-header">
                    <span class="issue-detail__pr-number">#{{ issue.prDetails.number }}</span>
                    <span
                      class="issue-detail__pr-state"
                      :class="`issue-detail__pr-state--${issue.prDetails.state}`"
                    >
                      {{ issue.prDetails.state }}
                    </span>
                  </div>
                  <h3 class="issue-detail__pr-title">{{ issue.prDetails.title }}</h3>
                  <div class="issue-detail__pr-meta">
                    <span class="issue-detail__pr-author">{{ issue.prDetails.author }}</span>
                    <span class="issue-detail__pr-stats">
                      <span class="issue-detail__pr-additions">+{{ issue.prDetails.additions }}</span>
                      <span class="issue-detail__pr-deletions">-{{ issue.prDetails.deletions }}</span>
                      <span class="issue-detail__pr-files">{{ issue.prDetails.changedFiles }} files</span>
                    </span>
                  </div>
                  <div v-if="issue.prDetails.reviewDecision" class="issue-detail__pr-review">
                    <span
                      class="issue-detail__pr-review-badge"
                      :class="`issue-detail__pr-review-badge--${issue.prDetails.reviewDecision}`"
                    >
                      {{ issue.prDetails.reviewDecision === 'approved' ? '✓ Approved' : issue.prDetails.reviewDecision === 'changes_requested' ? '✗ Changes Requested' : '○ Pending Review' }}
                    </span>
                  </div>
                </div>

                <!-- PR Actions -->
                <div class="issue-detail__pr-actions">
                  <button class="issue-detail__pr-btn issue-detail__pr-btn--approve" @click="handleApprove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    Approve & Merge
                  </button>
                  <button class="issue-detail__pr-btn issue-detail__pr-btn--reject" @click="handleReject">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                    Reject & Loop Back
                  </button>
                </div>

                <!-- File Diffs -->
                <div class="issue-detail__diff-files">
                  <div
                    v-for="file in issue.prDetails.files"
                    :key="file.filename"
                    class="issue-detail__diff-file"
                  >
                    <div class="issue-detail__diff-file-header">
                      <span
                        class="issue-detail__diff-file-status"
                        :class="`issue-detail__diff-file-status--${file.status}`"
                      >
                        {{ file.status }}
                      </span>
                      <span class="issue-detail__diff-file-name">{{ file.filename }}</span>
                      <span class="issue-detail__diff-file-stats">
                        <span class="issue-detail__diff-file-additions">+{{ file.additions }}</span>
                        <span class="issue-detail__diff-file-deletions">-{{ file.deletions }}</span>
                      </span>
                    </div>
                    <div v-if="file.patch" class="issue-detail__diff-file-patch">
                      <pre>{{ file.patch }}</pre>
                    </div>
                  </div>
                </div>

                <!-- Comments -->
                <div v-if="issue.prDetails.comments.length > 0" class="issue-detail__pr-comments">
                  <h4 class="issue-detail__pr-comments-title">Comments ({{ issue.prDetails.comments.length }})</h4>
                  <div
                    v-for="comment in issue.prDetails.comments"
                    :key="comment.id"
                    class="issue-detail__pr-comment"
                  >
                    <AvatarStack :name="comment.author" :avatar-url="comment.avatarUrl" size="sm" />
                    <div class="issue-detail__pr-comment-content">
                      <div class="issue-detail__pr-comment-header">
                        <span class="issue-detail__pr-comment-author">{{ comment.author }}</span>
                        <span class="issue-detail__pr-comment-time">{{ formatDate(comment.createdAt) }}</span>
                      </div>
                      <p class="issue-detail__pr-comment-body">{{ comment.body }}</p>
                      <span v-if="comment.path" class="issue-detail__pr-comment-location">
                        {{ comment.path }}:{{ comment.line }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Collaboration Tab -->
            <div v-if="activeTab === 'collaboration'" class="issue-detail__tab-pane">
              <IssueCollaborationTab :issue-id="issue.id" />
            </div>
            <div v-if="activeTab === 'handoffs'" class="issue-detail__tab-pane">
              <HandoffSection />
            </div>
            <div v-if="activeTab === 'cycles'" class="issue-detail__tab-pane">
              <!-- Mavis collaboration: each cycle is plan + progress + verdict.
                   Workers (incl. auto-promote) write a report when they finish
                   a pass; the leader reviews the report here and flips the
                   verdict to drive the next lane transition. -->
              <div class="cycles-tab">
                <div v-if="cycleReports.length === 0" class="cycles-tab__empty">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
                    <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
                    <rect x="9" y="3" width="6" height="4" rx="1" />
                    <path d="M9 13h6M9 17h4" />
                  </svg>
                  <p>No cycle reports yet.</p>
                  <p class="cycles-tab__empty-hint">
                    Cycle reports appear here automatically when an ECC job completes,
                    or when the leader writes a manual handoff.
                  </p>
                </div>
                <template v-else>
                  <NuxtLink to="/reviews" class="cycles-tab__queue-link">
                    Open in review queue →
                  </NuxtLink>
                </template>
                <div v-if="cycleReports.length > 0" class="cycles-tab__list">
                  <article
                    v-for="report in cycleReports"
                    :key="report.id"
                    class="cycle-card"
                  >
                    <header class="cycle-card__header">
                      <div class="cycle-card__author">
                        <span class="cycle-card__avatar">{{ (report.authorName || '?').slice(0,1).toUpperCase() }}</span>
                        <div>
                          <div class="cycle-card__name">{{ report.authorName || 'unknown' }}</div>
                          <div class="cycle-card__meta">
                            {{ formatCycleTime(report.createdAt) }}
                            <span v-if="report.jobId" class="cycle-card__job-pill">job: {{ report.jobId.slice(0, 12) }}</span>
                          </div>
                        </div>
                      </div>
                      <span :class="['cycle-card__verdict', `cycle-card__verdict--${verdictClass(report.verdict)}`]">
                        {{ verdictLabel(report.verdict) }}
                      </span>
                    </header>

                    <section class="cycle-card__section">
                      <h4 class="cycle-card__section-title">Plan</h4>
                      <p class="cycle-card__plan">{{ report.plan }}</p>
                    </section>

                    <section v-if="report.progressLog?.length" class="cycle-card__section">
                      <h4 class="cycle-card__section-title">
                        Progress
                        <span class="cycle-card__section-count">{{ report.progressLog.length }}</span>
                      </h4>
                      <ol class="cycle-card__log">
                        <li
                          v-for="(ev, idx) in report.progressLog"
                          :key="idx"
                          :class="['cycle-card__log-item', `cycle-card__log-item--${(ev.status || 'info').toLowerCase()}`]"
                        >
                          <span class="cycle-card__log-ts">{{ formatLogTime(ev.ts) }}</span>
                          <span class="cycle-card__log-status">{{ ev.status }}</span>
                          <span class="cycle-card__log-msg">{{ ev.message }}</span>
                        </li>
                      </ol>
                    </section>

                    <section v-if="report.deliverableSummary" class="cycle-card__section">
                      <h4 class="cycle-card__section-title">Deliverable</h4>
                      <p class="cycle-card__deliverable">{{ report.deliverableSummary }}</p>
                    </section>

                    <section v-if="report.verdictReason" class="cycle-card__section">
                      <h4 class="cycle-card__section-title">Reason</h4>
                      <p class="cycle-card__reason">{{ report.verdictReason }}</p>
                    </section>

                    <footer v-if="canOverride(report)" class="cycle-card__actions">
                      <button
                        class="cycle-card__btn cycle-card__btn--pass"
                        :disabled="updatingReportId === report.id || report.verdict === 'pass'"
                        @click="overrideVerdict(report, 'pass')"
                      >
                        Mark as pass
                      </button>
                      <button
                        class="cycle-card__btn cycle-card__btn--fail"
                        :disabled="updatingReportId === report.id || report.verdict === 'fail'"
                        @click="overrideVerdict(report, 'fail')"
                      >
                        Fail
                      </button>
                      <button
                        class="cycle-card__btn cycle-card__btn--blocked"
                        :disabled="updatingReportId === report.id || report.verdict === 'blocked'"
                        @click="overrideVerdict(report, 'blocked')"
                      >
                        Block
                      </button>
                    </footer>

                    <!-- Review section (POST /cycle-reports/{id}/review).
                         Distinct from the verdict override above: this
                         captures the leader's *review* of the report
                         itself — approve, or send the worker back with
                         a comment. The buttons hide once a decision is
                         recorded, and the backend self-review guard
                         also blocks the worker who wrote the report
                         from signing off on their own work. -->
                    <section class="cycle-card__review" data-testid="cycle-review-section">
                      <header class="cycle-card__review-header">
                        <h4 class="cycle-card__section-title">Leader review</h4>
                        <span
                          v-if="isReviewed(report)"
                          :class="['cycle-card__review-pill', `cycle-card__review-pill--${reviewDecisionClass(report.decision as 'approved' | 'changes_requested')}`]"
                          data-testid="cycle-review-pill"
                        >
                          {{ reviewDecisionLabel(report.decision as 'approved' | 'changes_requested') }}
                        </span>
                      </header>

                      <p
                        v-if="isReviewed(report)"
                        class="cycle-card__review-summary"
                        data-testid="cycle-review-summary"
                      >
                        Reviewed by <strong>{{ report.reviewedBy || 'unknown' }}</strong>
                        on {{ formatCycleTime(report.reviewedAt) }}
                        — decision: {{ reviewDecisionLabel(report.decision as 'approved' | 'changes_requested') }}
                      </p>

                      <p
                        v-if="isReviewed(report) && report.reviewComment"
                        class="cycle-card__review-comment"
                      >
                        {{ report.reviewComment }}
                      </p>

                      <div
                        v-if="!isReviewed(report) && isSelfReview(report)"
                        class="cycle-card__review-self-hint"
                      >
                        You authored this cycle report — another reviewer must sign off.
                      </div>

                      <template v-if="!isReviewed(report) && !isSelfReview(report)">
                        <textarea
                          class="cycle-card__review-input"
                          rows="2"
                          placeholder="Optional comment for the worker (visible in the audit trail)…"
                          :value="reviewComments.get(report.id) ?? ''"
                          :disabled="reviewingReportId === report.id"
                          :data-testid="`cycle-review-comment-${report.id}`"
                          @input="setReviewComment(report.id, ($event.target as HTMLTextAreaElement).value)"
                        />
                        <div class="cycle-card__review-buttons">
                          <button
                            class="cycle-card__btn cycle-card__btn--approve"
                            :disabled="reviewingReportId === report.id"
                            :data-testid="`cycle-review-approve-${report.id}`"
                            @click="submitReview(report, 'approved')"
                          >
                            Approve
                          </button>
                          <button
                            class="cycle-card__btn cycle-card__btn--changes"
                            :disabled="reviewingReportId === report.id"
                            :data-testid="`cycle-review-changes-${report.id}`"
                            @click="submitReview(report, 'changes_requested')"
                          >
                            Request changes
                          </button>
                        </div>
                        <p
                          v-if="reviewErrors.get(report.id)"
                          class="cycle-card__review-error"
                          :data-testid="`cycle-review-error-${report.id}`"
                        >
                          {{ reviewErrors.get(report.id) }}
                        </p>
                      </template>
                    </section>
                   </article>
                 </div>
               </div>
             </div>
           </div>
         </div>
       </div>
     </Transition>

     <!-- Link-to-epic picker (modal). Lists root epics on the
          same board, excludes the current issue and its
          descendants to prevent cycle-creation. The backend
          enforces the same rule, but the UI hints *before* a
          request is fired so the operator doesn't have to wait
          for a round-trip to see why something failed. -->
     <Teleport to="body">
       <Transition name="fade">
         <div
           v-if="showParentPicker && issue"
           class="parent-picker__backdrop"
           @click.self="showParentPicker = false"
         >
           <div class="parent-picker" role="dialog" aria-label="Link this issue to an epic">
             <div class="parent-picker__header">
               <h3>Link {{ issue.key }} to an epic</h3>
              <button class="parent-picker__close" @click="showParentPicker = false">
                <X :size="16" />
              </button>
            </div>
            <p class="parent-picker__hint">
              Pick a root epic on this board. Cycles are blocked
              (you can't pick this issue or any of its descendants).
            </p>
            <div v-if="parentCandidates.length === 0" class="parent-picker__empty">
              No eligible epic on this board. Create a root epic first.
            </div>
            <ul v-else class="parent-picker__list">
              <li
                v-for="cand in parentCandidates"
                :key="cand.id"
                class="parent-picker__item"
              >
                <div class="parent-picker__item-main">
                  <span class="parent-picker__key">{{ cand.key }}</span>
                  <span class="parent-picker__title">{{ cand.title }}</span>
                </div>
                <button
                  class="parent-picker__pick"
                  :disabled="linkingParent"
                  @click="linkToEpic(cand.id)"
                >
                  {{ linkingParent ? 'Linking…' : 'Link' }}
                </button>
              </li>
            </ul>
            <p
              v-if="parentPickerError"
              class="parent-picker__error"
            >
              {{ parentPickerError }}
            </p>
          </div>
        </div>
      </Transition>
    </Teleport>
  </Teleport>
</template>

<style scoped>
.issue-detail {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.issue-detail__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 19, 0.4);
  backdrop-filter: blur(4px);
}

.issue-detail__panel {
  position: relative;
  width: 100%;
  max-width: 520px;
  height: 100%;
  background: var(--canvas);
  border-left: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-xl);
}

/* Slide Transition */
.slide-enter-active,
.slide-leave-active {
  transition: all var(--duration-slow) var(--ease-out);
}

.slide-enter-active .issue-detail__panel,
.slide-leave-active .issue-detail__panel {
  transition: transform var(--duration-slow) var(--ease-out);
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
}

.slide-enter-from .issue-detail__panel,
.slide-leave-to .issue-detail__panel {
  transform: translateX(100%);
}

/* Header */
.issue-detail__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--hairline);
  flex-shrink: 0;
  background: var(--canvas);
}

.issue-detail__header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.issue-detail__key {
  font-family: var(--font-mono);
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--ink);
}

.issue-detail__status {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.issue-detail__close {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  color: var(--muted);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.issue-detail__close:hover {
  background: var(--surface-soft);
  color: var(--ink);
}

.issue-detail__close svg {
  width: 18px;
  height: 18px;
}

/* Tabs */
.issue-detail__tabs {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--hairline);
  flex-shrink: 0;
  background: var(--canvas);
}

.issue-detail__tab {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.issue-detail__tab:hover {
  background: var(--surface-soft);
  color: var(--ink);
}

.issue-detail__tab--active {
  background: var(--surface-card);
  border-color: var(--hairline);
  color: var(--ink);
}

.issue-detail__tab-icon {
  font-size: var(--text-xs);
}

.issue-detail__tab-badge {
  padding: 0 var(--space-2);
  background: var(--surface-soft);
  border-radius: var(--radius-sm);
  font-size: 0.625rem;
  font-weight: 600;
  color: var(--muted);
}

.issue-detail__tab-badge--accent {
  background: var(--primary);
  color: var(--on-primary);
}

/* Content */
.issue-detail__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
  background: var(--canvas);
}

.issue-detail__tab-pane {
  animation: fadeIn var(--duration-fast) var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ---------- Cycles tab (Mavis collab) ---------- */
.cycles-tab {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.cycles-tab__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--ink-muted);
  gap: var(--space-2);
}
.cycles-tab__empty p { margin: 0; }
.cycles-tab__empty-hint {
  font-size: var(--text-sm);
  color: var(--ink-faint);
  max-width: 30ch;
}

.cycles-tab__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.cycles-tab__queue-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--accent, #7D9E7D);
  text-decoration: none;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  background: rgba(125, 158, 125, 0.08);
  transition: background var(--duration-fast);
}
.cycles-tab__queue-link:hover { background: rgba(125, 158, 125, 0.18); }

.cycle-card {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background: var(--canvas-elevated);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.cycle-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
}

.cycle-card__author {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
.cycle-card__avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft, rgba(125, 158, 125, 0.18));
  color: var(--accent, #7D9E7D);
  font-weight: 600;
  font-size: var(--text-sm);
}
.cycle-card__name { font-weight: 600; font-size: var(--text-sm); }
.cycle-card__meta {
  font-size: var(--text-xs);
  color: var(--ink-muted);
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin-top: 2px;
}
.cycle-card__job-pill {
  font-family: var(--font-mono, monospace);
  background: var(--canvas-subtle, rgba(0,0,0,0.04));
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: 10px;
}

.cycle-card__verdict {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}
.cycle-card__verdict--pass    { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.cycle-card__verdict--fail    { background: rgba(184, 92, 77, 0.18); color: #B85C4D; }
.cycle-card__verdict--blocked { background: rgba(212, 168, 75, 0.18); color: #8A6B22; }
.cycle-card__verdict--pending { background: rgba(140, 130, 121, 0.18); color: #6B6660; }

.cycle-card__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cycle-card__section-title {
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-muted);
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.cycle-card__section-count {
  font-size: 10px;
  background: var(--canvas-subtle, rgba(0,0,0,0.04));
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
}

.cycle-card__plan,
.cycle-card__deliverable,
.cycle-card__reason {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.5;
  color: var(--ink);
}

.cycle-card__log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-sm);
}
.cycle-card__log-item {
  display: grid;
  grid-template-columns: 80px 90px 1fr;
  gap: var(--space-3);
  align-items: baseline;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
}
.cycle-card__log-item--running { background: rgba(107, 139, 164, 0.08); }
.cycle-card__log-item--queued  { background: rgba(140, 130, 121, 0.08); }
.cycle-card__log-item--review_required,
.cycle-card__log-item--completed { background: rgba(125, 158, 125, 0.08); }
.cycle-card__log-item--failed,
.cycle-card__log-item--cancelled { background: rgba(184, 92, 77, 0.08); }
.cycle-card__log-ts { color: var(--ink-faint); }
.cycle-card__log-status {
  font-weight: 600;
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.04em;
}
.cycle-card__log-msg { color: var(--ink); font-family: var(--font-sans, sans-serif); }

.cycle-card__actions {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--hairline);
  margin-top: var(--space-2);
}
.cycle-card__btn {
  font-size: var(--text-sm);
  font-weight: 500;
  padding: 6px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas);
  cursor: pointer;
  transition: opacity var(--duration-fast);
}
.cycle-card__btn:hover:not(:disabled) { opacity: 0.8; }
.cycle-card__btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cycle-card__btn--pass    { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; border-color: rgba(125, 158, 125, 0.4); }
.cycle-card__btn--fail    { background: rgba(184, 92, 77, 0.18);  color: #B85C4D; border-color: rgba(184, 92, 77, 0.4); }
.cycle-card__btn--blocked { background: rgba(212, 168, 75, 0.18); color: #8A6B22; border-color: rgba(212, 168, 75, 0.4); }

/* Review section — sits below the verdict override block, same
   .cycle-card__section visual rhythm so the card reads as
   plan → progress → deliverable → reason → verdict → review. */
.cycle-card__review {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border-top: 1px dashed var(--hairline);
  padding-top: var(--space-3);
  margin-top: var(--space-2);
}
.cycle-card__review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}
.cycle-card__review-pill {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  border-radius: 999px;
}
.cycle-card__review-pill--approved { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.cycle-card__review-pill--changes  { background: rgba(212, 168, 75, 0.18); color: #8A6B22; }

.cycle-card__review-summary {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink);
}
.cycle-card__review-comment {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink-muted);
  font-style: italic;
  border-left: 2px solid var(--hairline);
  padding-left: var(--space-3);
}
.cycle-card__review-self-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: #8A6B22;
  background: rgba(212, 168, 75, 0.1);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
}
.cycle-card__review-input {
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
.cycle-card__review-input:focus {
  outline: none;
  border-color: rgba(107, 139, 164, 0.6);
}
.cycle-card__review-buttons {
  display: flex;
  gap: var(--space-2);
}
.cycle-card__btn--approve {
  background: rgba(125, 158, 125, 0.22);
  color: #4F6F4F;
  border-color: rgba(125, 158, 125, 0.5);
}
.cycle-card__btn--changes {
  background: rgba(212, 168, 75, 0.22);
  color: #8A6B22;
  border-color: rgba(212, 168, 75, 0.5);
}
.cycle-card__review-error {
  margin: 0;
  font-size: var(--text-xs);
  color: #B85C4D;
  background: rgba(184, 92, 77, 0.1);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
}

/* Error Banner */
.issue-detail__error-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid var(--clay-red);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}

.issue-detail__error-banner-icon {
  width: 20px;
  height: 20px;
  color: var(--clay-red);
  flex-shrink: 0;
}

.issue-detail__error-banner-content {
  flex: 1;
}

.issue-detail__error-banner-title {
  display: block;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--clay-red);
}

.issue-detail__error-banner-message {
  display: block;
  font-size: var(--text-xs);
  color: var(--muted);
  margin-top: var(--space-1);
}

.issue-detail__error-banner-btn {
  padding: var(--space-1) var(--space-3);
  background: var(--clay-red);
  color: var(--on-primary);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.issue-detail__error-banner-btn:hover {
  background: var(--clay-red-muted);
}

/* Title */
.issue-detail__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ink);
  line-height: 1.4;
  margin-bottom: var(--space-4);
}

/* Meta Row */
.issue-detail__meta-row {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--hairline);
  border-bottom: 1px solid var(--hairline);
  margin-bottom: var(--space-5);
}

.issue-detail__meta-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.issue-detail__meta-label {
  font-size: var(--text-xs);
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.issue-detail__meta-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
}

.issue-detail__meta-value--mono {
  font-family: var(--font-mono);
  font-size: 0.78rem;
}

/* Sections */
.issue-detail__section {
  margin-bottom: var(--space-5);
}

.issue-detail__section-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-3);
}

.issue-detail__job {
  padding: var(--space-4);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
}

.issue-detail__job-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: var(--space-3);
  padding: var(--space-2) 0;
  color: var(--muted);
  font-size: var(--text-sm);
}

.issue-detail__job-row strong {
  overflow-wrap: anywhere;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  font-weight: 600;
}

/* Assignee */
.issue-detail__assignee {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.issue-detail__assignee-name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
}

/* Description */
.issue-detail__description {
  font-size: var(--text-sm);
  color: var(--body);
  line-height: 1.6;
}

/* Acceptance Criteria (Mavis collab) */
.issue-detail__ac-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.issue-detail__ac-count {
  font-size: 10px;
  font-weight: 600;
  background: var(--canvas-subtle, rgba(0,0,0,0.04));
  color: var(--ink-muted);
  padding: 2px 8px;
  border-radius: 999px;
  margin-left: var(--space-2);
  text-transform: none;
  letter-spacing: 0;
}
.issue-detail__ac-actions { display: flex; gap: var(--space-2); }
.issue-detail__suggest-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  font-weight: 500;
  padding: 5px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas-elevated);
  cursor: pointer;
  color: var(--ink);
  transition: background var(--duration-fast), opacity var(--duration-fast);
}
.issue-detail__suggest-btn:hover:not(:disabled) {
  background: rgba(125, 158, 125, 0.12);
  color: #4F6F4F;
}
.issue-detail__suggest-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.issue-detail__ac-suggestion {
  border: 1px solid rgba(125, 158, 125, 0.4);
  background: rgba(125, 158, 125, 0.06);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  margin-bottom: var(--space-3);
}
.issue-detail__ac-suggestion-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-muted);
  margin-bottom: var(--space-2);
}
.issue-detail__ac-source {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 999px;
}
.issue-detail__ac-source--llm       { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.issue-detail__ac-source--cache    { background: rgba(140, 130, 121, 0.18); color: #6B6660; }
.issue-detail__ac-source--heuristic{ background: rgba(107, 139, 164, 0.18); color: #4A6680; }
.issue-detail__ac-provider { color: var(--ink-faint); }
.issue-detail__ac-discard {
  margin-left: auto;
  font-size: var(--text-xs);
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  cursor: pointer;
  color: var(--ink-muted);
}
.issue-detail__ac-apply {
  font-size: var(--text-xs);
  background: rgba(125, 158, 125, 0.18);
  color: #4F6F4F;
  border: 1px solid rgba(125, 158, 125, 0.4);
  border-radius: var(--radius-sm);
  padding: 3px 10px;
  cursor: pointer;
  font-weight: 500;
}
.issue-detail__ac-suggestion-list {
  list-style: decimal;
  margin: 0 0 0 var(--space-4);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-sm);
  line-height: 1.5;
}

.issue-detail__ac-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.issue-detail__ac-drag-root {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.issue-detail__ac-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}
.issue-detail__ac-item:hover {
  background: var(--surface-soft);
  border-color: var(--hairline);
}
.issue-detail__ac-item--done .issue-detail__ac-text {
  text-decoration: line-through;
  color: var(--ink-muted);
}
.issue-detail__ac-item--editing {
  background: var(--surface-soft);
  border-color: var(--hairline);
}
.issue-detail__ac-item input[type="checkbox"] { margin: 0; cursor: pointer; }
.issue-detail__ac-text {
  flex: 1;
  min-width: 0;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.issue-detail__ac-drag {
  color: var(--muted-soft);
  cursor: grab;
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  user-select: none;
}
.issue-detail__ac-drag:hover { color: var(--ink-muted); }
.issue-detail__ac-drag:active { cursor: grabbing; }

.issue-detail__ac-icon-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--ink-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}
.issue-detail__ac-icon-btn:hover {
  background: var(--surface-card);
  color: var(--ink);
  border-color: var(--hairline);
}
.issue-detail__ac-icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.issue-detail__ac-icon-btn--danger:hover {
  color: var(--clay-red);
  border-color: rgba(184, 92, 77, 0.4);
}
.issue-detail__ac-icon-btn--danger {
  /* Make the danger glyph fade in only on hover so the row stays
     calm in the default state. */
  opacity: 0.55;
}
.issue-detail__ac-item:hover .issue-detail__ac-icon-btn--danger { opacity: 1; }

.issue-detail__ac-edit-input {
  flex: 1;
  min-width: 0;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font: inherit;
  padding: 4px 8px;
  outline: none;
}
.issue-detail__ac-edit-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(204, 120, 92, 0.18);
}

.issue-detail__ac-add-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 6px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  margin-top: 6px;
}

.issue-detail__ac-add-btn {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--ink-muted);
  background: transparent;
  border: 1px dashed var(--hairline);
  border-radius: var(--radius-sm);
  padding: 5px 10px;
  cursor: pointer;
  font-weight: 500;
  transition: background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}
.issue-detail__ac-add-btn:hover {
  background: var(--surface-soft);
  color: var(--ink);
  border-color: var(--muted-soft);
}

/* vuedraggable sort classes — light visual feedback while dragging. */
.issue-detail__ac-drag-root:has(.sortable-ghost) {
  background: rgba(204, 120, 92, 0.06);
  border-radius: var(--radius-sm);
}
.issue-detail__ac-drag-root .sortable-ghost {
  opacity: 0.4;
}
.issue-detail__ac-drag-root .sortable-chosen {
  background: var(--surface-card);
  border-color: var(--primary);
}

.issue-detail__ac-empty {
  font-size: var(--text-sm);
  color: var(--ink-muted);
  font-style: italic;
  margin: 0;
}

/* Labels */
.issue-detail__labels {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

/* Dependencies */
.issue-detail__dependencies {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.issue-detail__dep-chip {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted);
  padding: var(--space-1) var(--space-2);
  background: var(--surface-soft);
  border-radius: var(--radius-sm);
}

/* PR Link */
.issue-detail__pr-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--primary);
  text-decoration: none;
  padding: var(--space-2) var(--space-3);
  background: rgba(204, 120, 92, 0.08);
  border-radius: var(--radius-md);
  transition: all var(--duration-fast) var(--ease-out);
}

.issue-detail__pr-link:hover {
  background: var(--primary);
  color: var(--on-primary);
}

.issue-detail__pr-link svg {
  width: 16px;
  height: 16px;
}

/* Activity */
.issue-detail__activity {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.issue-detail__activity-entry {
  display: flex;
  gap: var(--space-3);
}

.issue-detail__activity-icon {
  font-size: var(--text-sm);
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-soft);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.issue-detail__activity-content {
  flex: 1;
  min-width: 0;
}

.issue-detail__activity-message {
  font-size: var(--text-sm);
  color: var(--ink);
  display: block;
  margin-bottom: var(--space-1);
}

.issue-detail__activity-meta {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--muted);
}

.issue-detail__activity-actor {
  text-transform: capitalize;
}

/* Empty State */
.issue-detail__empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12);
  text-align: center;
}

.issue-detail__empty-state-icon {
  width: 48px;
  height: 48px;
  color: var(--muted-soft);
  opacity: 0.5;
  margin-bottom: var(--space-4);
}

.issue-detail__empty-state-text {
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--muted);
}

.issue-detail__empty-state-hint {
  font-size: var(--text-sm);
  color: var(--muted-soft);
  margin-top: var(--space-2);
}

/* ECC Logs */
.issue-detail__ecc-logs {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.issue-detail__job-card {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
}

.issue-detail__job-card-row,
.issue-detail__job-card-grid {
  display: grid;
  gap: var(--space-2);
}

.issue-detail__job-card-row {
  grid-template-columns: 82px minmax(0, 1fr);
}

.issue-detail__job-card-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.issue-detail__job-card span {
  color: var(--muted);
  font-size: var(--text-xs);
  text-transform: uppercase;
}

.issue-detail__job-card strong {
  overflow-wrap: anywhere;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.77rem;
}

.issue-detail__ecc-log-entry {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.issue-detail__ecc-log-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.issue-detail__ecc-log-phase {
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.issue-detail__ecc-log-time {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted-soft);
}

.issue-detail__ecc-log-tool {
  font-family: var(--font-mono);
  font-size: 0.625rem;
  color: var(--primary);
  padding: 2px var(--space-2);
  background: rgba(204, 120, 92, 0.08);
  border-radius: var(--radius-sm);
}

.issue-detail__ecc-log-duration {
  font-family: var(--font-mono);
  font-size: 0.625rem;
  color: var(--muted-soft);
  margin-left: auto;
}

.issue-detail__ecc-log-content {
  font-size: var(--text-sm);
  color: var(--ink);
  line-height: 1.5;
}

.issue-detail__ecc-log-confidence {
  margin-top: var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.issue-detail__ecc-log-confidence-bar {
  flex: 1;
  height: 4px;
  background: var(--surface-soft);
  border-radius: 2px;
  overflow: hidden;
}

.issue-detail__ecc-log-confidence-fill {
  height: 100%;
  background: var(--sage);
  transition: width var(--duration-normal) var(--ease-out);
}

.issue-detail__ecc-log-confidence-label {
  font-size: 0.625rem;
  color: var(--muted-soft);
}

/* PR/Diff */
.issue-detail__diff {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.issue-detail__pr-summary {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.issue-detail__pr-summary-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.issue-detail__pr-number {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--muted);
}

.issue-detail__pr-state {
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
}

.issue-detail__pr-state--open {
  background: rgba(125, 158, 125, 0.15);
  color: var(--sage-muted);
}

.issue-detail__pr-state--merged {
  background: rgba(107, 139, 164, 0.15);
  color: var(--dusty-blue-muted);
}

.issue-detail__pr-state--closed {
  background: rgba(184, 92, 77, 0.15);
  color: var(--clay-red);
}

.issue-detail__pr-title {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
  margin-bottom: var(--space-2);
}

.issue-detail__pr-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.issue-detail__pr-author {
  font-size: var(--text-sm);
  color: var(--muted);
}

.issue-detail__pr-stats {
  display: flex;
  gap: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.issue-detail__pr-additions {
  color: var(--sage-muted);
}

.issue-detail__pr-deletions {
  color: var(--clay-red);
}

.issue-detail__pr-files {
  color: var(--muted-soft);
}

.issue-detail__pr-review-badge {
  display: inline-flex;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
}

.issue-detail__pr-review-badge--approved {
  background: rgba(125, 158, 125, 0.12);
  color: var(--sage-muted);
}

.issue-detail__pr-review-badge--changes_requested {
  background: rgba(184, 92, 77, 0.12);
  color: var(--clay-red);
}

.issue-detail__pr-review-badge--pending {
  background: rgba(212, 168, 75, 0.12);
  color: var(--amber-muted);
}

/* PR Actions */
.issue-detail__pr-actions {
  display: flex;
  gap: var(--space-3);
}

.issue-detail__pr-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.issue-detail__pr-btn svg {
  width: 16px;
  height: 16px;
}

.issue-detail__pr-btn--approve {
  background: var(--sage);
  color: var(--ink);
}

.issue-detail__pr-btn--approve:hover {
  background: var(--sage-muted);
}

.issue-detail__pr-btn--reject {
  background: var(--surface-card);
  color: var(--ink);
  border: 1px solid var(--hairline);
}

.issue-detail__pr-btn--reject:hover {
  background: var(--surface-soft);
  border-color: var(--clay-red);
}

/* Diff Files */
.issue-detail__diff-files {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.issue-detail__diff-file {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.issue-detail__diff-file-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-soft);
  border-bottom: 1px solid var(--hairline);
}

.issue-detail__diff-file-status {
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
}

.issue-detail__diff-file-status--added {
  background: rgba(125, 158, 125, 0.12);
  color: var(--sage-muted);
}

.issue-detail__diff-file-status--modified {
  background: rgba(212, 168, 75, 0.12);
  color: var(--amber-muted);
}

.issue-detail__diff-file-status--deleted {
  background: rgba(184, 92, 77, 0.12);
  color: var(--clay-red);
}

.issue-detail__diff-file-name {
  flex: 1;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-detail__diff-file-stats {
  display: flex;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: 0.625rem;
}

.issue-detail__diff-file-additions {
  color: var(--sage-muted);
}

.issue-detail__diff-file-deletions {
  color: var(--clay-red);
}

.issue-detail__diff-file-patch {
  padding: var(--space-3);
  overflow-x: auto;
}

.issue-detail__diff-file-patch pre {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--body);
  white-space: pre;
  margin: 0;
}

/* PR Comments */
.issue-detail__pr-comments {
  margin-top: var(--space-4);
}

.issue-detail__pr-comments-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-3);
}

.issue-detail__pr-comment {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-2);
}

.issue-detail__pr-comment-content {
  flex: 1;
}

.issue-detail__pr-comment-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.issue-detail__pr-comment-author {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.issue-detail__pr-comment-time {
  font-size: var(--text-xs);
  color: var(--muted-soft);
}

.issue-detail__pr-comment-body {
  font-size: var(--text-sm);
  color: var(--body);
  line-height: 1.5;
  margin-bottom: var(--space-2);
}

.issue-detail__pr-comment-location {
  font-family: var(--font-mono);
  font-size: 0.625rem;
  color: var(--primary);
  padding: 2px var(--space-2);
  background: rgba(204, 120, 92, 0.08);
  border-radius: var(--radius-sm);
}

.issue-detail__run-link {
  font-size: 0.75rem;
  color: var(--primary);
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: underline;
  margin-left: auto;
}

.issue-detail__run-detail {
  margin: 8px 0;
  padding: 10px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.82rem;
}

.issue-detail__run-meta {
  display: flex;
  gap: 12px;
  color: var(--muted);
}

/* Archive / unarchive controls in the drawer header */
.issue-detail__header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.issue-detail__archive-btn,
.issue-detail__unarchive-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  padding: 4px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas-elevated);
  cursor: pointer;
  color: var(--ink-muted);
  transition: background var(--duration-fast), color var(--duration-fast);
}
.issue-detail__archive-btn:hover:not(:disabled) {
  background: rgba(184, 92, 77, 0.12);
  color: #B85C4D;
  border-color: rgba(184, 92, 77, 0.4);
}
.issue-detail__unarchive-btn:hover:not(:disabled) {
  background: rgba(125, 158, 125, 0.12);
  color: #4F6F4F;
  border-color: rgba(125, 158, 125, 0.4);
}
.issue-detail__archive-btn:disabled,
.issue-detail__unarchive-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.issue-detail__archived-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(140, 130, 121, 0.18);
  color: #6B6660;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* Parent (epic) linkage — chip in header + link button. The chip
   shows the parent key and title on hover; the X unlinks. The
   "Link to epic" button is hidden when an epic is already
   linked, and on archived issues (the parent chain is still
   readable but mutable, hence no chip unlink). */
.issue-detail__parent-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 4px 3px 8px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  color: #4F46E5;
  border: 1px solid rgba(99, 102, 241, 0.25);
}
.issue-detail__parent-link {
  color: inherit;
  text-decoration: none;
}
.issue-detail__parent-link:hover {
  text-decoration: underline;
}
.issue-detail__parent-unlink {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity var(--duration-fast), background var(--duration-fast);
}
.issue-detail__parent-unlink:hover:not(:disabled) {
  opacity: 1;
  background: rgba(99, 102, 241, 0.18);
}
.issue-detail__parent-unlink:disabled {
  cursor: not-allowed;
}
.issue-detail__link-epic-btn {
  display: inline-flex;
  align-items: center;
  font-size: var(--text-sm);
  padding: 4px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--hairline);
  background: var(--canvas-elevated);
  cursor: pointer;
  color: var(--ink-muted);
  transition: background var(--duration-fast), color var(--duration-fast);
}
.issue-detail__link-epic-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.08);
  color: #4F46E5;
  border-color: rgba(99, 102, 241, 0.3);
}
.issue-detail__link-epic-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.issue-detail__parent-error {
  font-size: var(--text-xs);
  color: #B85C4D;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Picker modal — same fade as the rest of the app, but small
   panel (max 480px) because the candidate list rarely exceeds a
   few rows. The empty state appears when the board has no root
   epics, or when the only roots are the current issue or its
   descendants. */
.parent-picker__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 15, 18, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
  padding: 16px;
}
.parent-picker {
  background: var(--canvas-elevated);
  border-radius: var(--radius-lg);
  border: 1px solid var(--hairline);
  padding: 20px;
  width: 100%;
  max-width: 480px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4);
}
.parent-picker__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.parent-picker__header h3 {
  margin: 0;
  font-size: var(--text-lg);
}
.parent-picker__close {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--ink-muted);
  padding: 4px;
  border-radius: var(--radius-md);
}
.parent-picker__close:hover {
  background: var(--canvas-muted);
}
.parent-picker__hint {
  font-size: var(--text-sm);
  color: var(--ink-muted);
  margin: 0 0 12px;
}
.parent-picker__empty {
  font-size: var(--text-sm);
  color: var(--ink-muted);
  padding: 16px;
  border: 1px dashed var(--hairline);
  border-radius: var(--radius-md);
  text-align: center;
}
.parent-picker__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.parent-picker__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--canvas);
}
.parent-picker__item-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.parent-picker__key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-muted);
  flex-shrink: 0;
}
.parent-picker__title {
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.parent-picker__pick {
  display: inline-flex;
  align-items: center;
  font-size: var(--text-sm);
  padding: 4px 10px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(99, 102, 241, 0.3);
  background: rgba(99, 102, 241, 0.08);
  color: #4F46E5;
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--duration-fast);
}
.parent-picker__pick:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.16);
}
.parent-picker__pick:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.parent-picker__error {
  margin: 12px 0 0;
  font-size: var(--text-sm);
  color: #B85C4D;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--duration-fast);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Mobile: full-width panel, no border, adjusted padding */
@media (max-width: 640px) {
  .issue-detail__panel {
    max-width: 100%;
    border-left: none;
  }

  .issue-detail__header {
    padding: var(--space-3) var(--space-4);
  }

  .issue-detail__tabs {
    padding: var(--space-2) var(--space-3);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .issue-detail__tab {
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-xs);
    white-space: nowrap;
  }

  .issue-detail__content {
    padding: var(--space-4);
  }

  .issue-detail__title {
    font-size: var(--text-lg);
  }

  .issue-detail__meta-row {
    flex-wrap: wrap;
    gap: var(--space-3);
  }

  .issue-detail__pr-actions {
    flex-direction: column;
  }

  .issue-detail__run-meta {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
