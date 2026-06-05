<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { COLUMN_CONFIG, PRIORITY_CONFIG, PROFILE_CONFIG } from '~/types'
import type { ECCLogEntry } from '~/types'
import { useRuntime } from '~/composables/useRuntime'
import { Bot, FileText, X } from 'lucide-vue-next'
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

const setTab = (tab: 'overview' | 'ecc-logs' | 'diff' | 'collaboration' | 'handoffs') => {
  boardStore.setDetailTab(tab)
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
        return
      }
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
            </div>
            <button class="issue-detail__close" @click="close">
              <X :size="18" />
            </button>
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
          </div>
        </div>
      </div>
    </Transition>
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
</style>
