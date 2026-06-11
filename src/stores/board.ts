import { defineStore } from 'pinia'
import type { BoardState, Issue, IssueStatus, Priority, AIAgentStatus, HarnessType, Column, ECCLogEntry, PRDetails, ECCDispatchJob, ECCProfile, Handoff, HandoffCreateRequest, HandoffDispatchRequest, AgentRole } from '~/types'
import { COLUMN_CONFIG, ECC_COMMAND_MAP } from '~/types'
import { useECCStreamSingleton } from '~/composables/useECCStream'
import { useDependencyGraph } from '~/composables/useDependencyGraph'
import { useFeedbackLoop } from '~/composables/useFeedbackLoop'
import { useKanbanProtocol } from '~/composables/useKanbanProtocol'
import { authHeaders } from '~/utils/authHeaders'

// Helper to read cookie directly (works in Pinia actions where useCookie may not)
function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`))
  return match ? decodeURIComponent(match[2]) : null
}


const _inferPhaseFromEvent = (message: string, status: string): ECCLogEntry['phase'] => {
  const m = message.toLowerCase()
  if (m.includes('analyz') || m.includes('started') || m.includes('queued')) return 'observation'
  if (m.includes('prepar') || m.includes('planning') || m.includes('reasoning')) return 'reasoning'
  if (m.includes('running') || m.includes('execut') || m.includes('check') || m.includes('modif')) return 'action'
  if (m.includes('ready') || m.includes('complete') || m.includes('review')) return 'output'
  if (status === 'failed' || status === 'cancelled') return 'error'
  return 'output'
}

interface NewIssuePayload {
  title: string
  description?: string
  status: IssueStatus
  priority: Priority
  profile: ECCProfile
}

const _jobIsTerminal = (status: ECCDispatchJob['status']) =>
  ['review_required', 'completed', 'failed', 'cancelled'].includes(status)

const _normalizeIssue = (issue: Issue): Issue => ({
  ...issue,
  labels: issue.labels ?? [],
  dependencies: issue.dependencies ?? [],
  activityLog: issue.activityLog ?? [],
  eccLogs: issue.eccLogs ?? [],
  assigneeId: issue.assigneeId ?? null,
  assigneeName: issue.assigneeName ?? null,
  assigneeAvatar: issue.assigneeAvatar ?? null,
  storyPoints: issue.storyPoints ?? null,
  prUrl: issue.prUrl ?? null,
  ciStatus: issue.ciStatus ?? null,
  aiStatus: issue.aiStatus ?? (issue.status === 'in_progress' ? 'running' : 'idle'),
  harnessType: issue.harnessType ?? null,
  eccJobId: issue.eccJobId ?? null,
  eccJobStatus: issue.eccJobStatus ?? null,
  eccJobMessage: issue.eccJobMessage ?? null,
  eccJobUpdatedAt: issue.eccJobUpdatedAt ?? null,
  memoryRef: issue.memoryRef ?? null,
  prDetails: issue.prDetails ?? null,
  moveStatus: issue.moveStatus ?? 'idle',
  moveError: issue.moveError ?? null,
  parentId: issue.parentId ?? null,
  acceptanceCriteria: issue.acceptanceCriteria ?? [],
  isArchived: issue.isArchived ?? false,
  archivedAt: issue.archivedAt ?? null,
  createdAt: issue.createdAt ?? (issue as unknown as { created_at?: string }).created_at ?? new Date().toISOString(),
  updatedAt: issue.updatedAt ?? (issue as unknown as { updated_at?: string }).updated_at ?? new Date().toISOString()
})

export const useBoardStore = defineStore('board', {
  state: (): BoardState => ({
    columns: [],
    isLoading: false,
    selectedIssue: null,
    isDetailOpen: false,
    activeDetailTab: 'overview',
    jobs: [],
    selectedJob: null,
    isLoadingJobs: false,
    fetchError: null as string | null,
    isNewIssueModalOpen: false,
    createIssueError: null,
    isCreatingIssue: false,
    aiStatus: 'idle',
    activeAI_task: null,
    activeHarness: 'claude-code',
    streamingIssues: [],
    jobsById: {},
    jobsForIssue: {},
    searchQuery: '',
    profileFilter: 'all',
    harnessFilter: 'all',
    agentRoles: []
  }),

  getters: {
    getColumnByStatus: (state) => (status: IssueStatus): Column | undefined => {
      return state.columns.find(col => col.id === status)
    },

    getIssueById: (state) => (id: string): Issue | undefined => {
      for (const col of state.columns) {
        const issue = col.issues.find(i => i.id === id)
        if (issue) return issue
      }
      return undefined
    },

    getAllIssues: (state): Issue[] => {
      return state.columns.flatMap(col => col.issues)
    },

    totalIssues: (state): number => {
      return state.columns.reduce((sum, col) => sum + col.issues.length, 0)
    },

    inProgressCount: (state): number => {
      const col = state.columns.find(c => c.id === 'in_progress')
      return col ? col.issues.length : 0
    },

    hasPendingMoves: (state): boolean => {
      for (const col of state.columns) {
        if (col.issues.some(i => i.moveStatus === 'pending')) return true
      }
      return false
    },

    filteredIssues(): Issue[] {
      let issues = this.getAllIssues

      // Filter by search query
      if (this.searchQuery.trim()) {
        const query = this.searchQuery.trim().toLowerCase()
        issues = issues.filter(issue =>
          issue.title.toLowerCase().includes(query) ||
          issue.key.toLowerCase().includes(query)
        )
      }

      // Filter by profile
      if (this.profileFilter && this.profileFilter !== 'all') {
        issues = issues.filter(issue => issue.profile === this.profileFilter)
      }

      // Filter by harness
      if (this.harnessFilter && this.harnessFilter !== 'all') {
        issues = issues.filter(issue => issue.harnessType === this.harnessFilter)
      }

      return issues
    },

    recentJobs: (state): ECCDispatchJob[] => {
      return [...state.jobs]
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 5)
    },

    getJobsForIssue: (state) => (issueId: string): ECCDispatchJob[] => {
      return state.jobs
        .filter(job => job.issue_id === issueId)
        .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    },

    getIssueJob: (state) => (issueId: string): ECCDispatchJob | null => {
      const jobIds = state.jobsForIssue[issueId] ?? []
      const jobs = jobIds
        .map(id => state.jobsById[id])
        .filter((j): j is ECCDispatchJob => Boolean(j))
      if (jobs.length === 0) return null
      return jobs.reduce((latest, current) =>
        new Date(current.updated_at).getTime() > new Date(latest.updated_at).getTime()
          ? current
          : latest
      )
    },

    reviewQueueItems(): Issue[] {
      return this.getAllIssues.filter(issue => {
        // Done issues are never awaiting review, even if a stale job
        // row is still flagged ``review_required`` in the registry.
        if (issue.status === 'done') return false
        if (issue.status === 'human_review') return true
        if (issue.eccJobStatus === 'review_required') return true
        return this.jobs.some(
          job => job.issue_id === issue.id && job.status === 'review_required'
        )
      })
    }
  },

  actions: {
    async fetchBoard() {
      this.isLoading = true
      this.fetchError = null

      try {
        const config = useRuntimeConfig()
        // The sidebar's "Show archived" toggle persists its
        // choice to localStorage; the store reads the same key so
        // the two stay in sync without prop-drilling.
        let includeArchived = ''
        if (typeof window !== 'undefined') {
          try {
            if (localStorage.getItem('devflow:showArchived') === '1') {
              includeArchived = '?include_archived=1'
            }
          } catch { /* localStorage unavailable */ }
        }
        const boardData = await $fetch<{ columns: Array<{ id: IssueStatus; title: string; color: string; issues: Issue[] }> }>(`${config.public.apiBase}/board${includeArchived}`)
        this.columns = boardData.columns.map(column => ({
          ...column,
          issues: column.issues.map(_normalizeIssue)
        }))
        await this.fetchJobs()
      } catch (error) {
        // Real backend unavailable or returned an error. Surface it; do
        // NOT fabricate data — that hides outages from the operator.
        console.error('[BoardStore] fetchBoard failed:', error)
        this.fetchError = error instanceof Error ? error.message : 'Failed to load board'
        this.columns = []
      }

      this.isLoading = false
    },

    async fetchJobs(issueId?: string) {
      this.isLoadingJobs = true
      try {
        const config = useRuntimeConfig()
        const query = issueId ? `?issue_id=${encodeURIComponent(issueId)}` : ''
        const response = await $fetch<{ jobs: ECCDispatchJob[]; total: number }>(
          `${config.public.apiBase}/ecc/jobs${query}`
        )
        const incoming = response.jobs

        if (issueId) {
          const remaining = this.jobs.filter(job => job.issue_id !== issueId)
          this.jobs = [...remaining, ...incoming]
        } else {
          this.jobs = incoming
        }

        for (const job of incoming) {
          // Update the index unconditionally — the issue may not be in any
          // column yet (e.g. jobs fetched before the board has loaded), and
          // we still want getIssueJob/getJobsForIssue to be consistent.
          this.jobsById[job.id] = job
          const existingIds = this.jobsForIssue[job.issue_id] ?? []
          if (!existingIds.includes(job.id)) {
            this.jobsForIssue[job.issue_id] = [...existingIds, job.id]
          }
          this.attachJobToIssue(job.issue_id, job)
        }

        return incoming
      } catch (error) {
        console.warn('[BoardStore] fetchJobs failed:', error)
        return []
      } finally {
        this.isLoadingJobs = false
      }
    },

    async fetchJob(jobId: string) {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(`${config.public.apiBase}/ecc/jobs/${jobId}`)
        this.jobs = [job, ...this.jobs.filter(existing => existing.id !== job.id)]
        this.attachJobToIssue(job.issue_id, job)
        return job
      } catch (error) {
        console.warn('[BoardStore] fetchJob failed:', error)
        return null
      }
    },

    async fetchJobsForIssue(issueId: string) {
      return await this.fetchJobs(issueId)
    },

    async moveIssue(issueId: string, fromStatus: IssueStatus, toStatus: IssueStatus, newIndex: number): Promise<boolean> {
      const fromColumn = this.columns.find(col => col.id === fromStatus)
      const toColumn = this.columns.find(col => col.id === toStatus)

      if (!fromColumn || !toColumn) return false

      const issueIndex = fromColumn.issues.findIndex(i => i.id === issueId)
      if (issueIndex === -1) return false

      const issue = fromColumn.issues[issueIndex]

      // Set pending state - UI shows spinner
      issue.moveStatus = 'pending'
      issue.moveError = null

      // Optimistically move to target column visually
      fromColumn.issues.splice(issueIndex, 1)
      issue.status = toStatus
      issue.updatedAt = new Date().toISOString()

      // Add pending activity log entry
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'status_change',
        message: `Pending move to ${COLUMN_CONFIG[toStatus].title}...`,
        actor: 'human',
        timestamp: new Date().toISOString()
      })

      toColumn.issues.splice(newIndex, 0, issue)

      // Fire and forget status update to backend
      const config = useRuntimeConfig()
      $fetch(`${config.public.apiBase}/issues/${issueId}/status`, {
        method: 'PUT',
        body: { status: toStatus }
      }).catch(error => console.warn('[BoardStore] moveIssue status update failed:', error))

      // If moving to in_progress, simulate ECC dispatch confirmation
      if (toStatus === 'in_progress') {
        try {
          const dispatchJob = await this.confirmMoveWithControlPlane(issue, toStatus)
          issue.moveStatus = 'confirmed'
          this.dispatchAI(issue, dispatchJob)
        } catch (error) {
          issue.moveStatus = 'failed'
          issue.moveError = error instanceof Error ? error.message : 'Unknown error'
          // Revert the move
          this.revertMove(issue, fromStatus, fromColumn)
          return false
        }
      } else {
        // For non-AI statuses, confirmation is instant
        await new Promise(resolve => setTimeout(resolve, 300))
        issue.moveStatus = 'confirmed'
        issue.activityLog.push({
          id: `a${Date.now()}`,
          type: 'status_change',
          message: `Moved to ${COLUMN_CONFIG[toStatus].title}`,
          actor: 'human',
          timestamp: new Date().toISOString()
        })
      }

      return true
    },

    async confirmMoveWithControlPlane(issue: Issue, toStatus: IssueStatus): Promise<ECCDispatchJob | null> {
      if (toStatus !== 'in_progress') return null

      try {
        const config = useRuntimeConfig()
        return await $fetch<ECCDispatchJob>(`${config.public.apiBase}/ecc/dispatch`, {
          method: 'POST',
          body: {
            issue_id: issue.id,
            issue_key: issue.key,
            command: `${ECC_COMMAND_MAP[toStatus]} --profile=${issue.profile}`,
            profile: issue.profile,
            harness: this.activeHarness
          },
          headers: authHeaders(),
        })
      } catch (error) {
        console.warn('[BoardStore] ECC dispatch endpoint unavailable, using local run telemetry', error)
        await new Promise(resolve => setTimeout(resolve, 450))
        return null
      }
    },

    applyECCJobToIssue(issue: Issue, job: ECCDispatchJob) {
      this.jobs = [job, ...this.jobs.filter(existing => existing.id !== job.id)]
      this.jobsById[job.id] = job
      const existingIds = this.jobsForIssue[job.issue_id] ?? []
      if (!existingIds.includes(job.id)) {
        this.jobsForIssue[job.issue_id] = [...existingIds, job.id]
      }
      this.selectedJob = this.selectedJob?.id === job.id ? job : this.selectedJob
      issue.eccJobId = job.id
      issue.eccJobStatus = job.status
      issue.eccJobMessage = job.message
      issue.eccJobUpdatedAt = job.updated_at
      issue.harnessType = job.harness
      issue.aiStatus = _jobIsTerminal(job.status)
        ? (job.status === 'failed' || job.status === 'cancelled' ? 'error' : 'idle')
        : 'running'
      issue.eccLogs = job.events.map(e => ({
        id: `jobevt_${job.id}_${e.timestamp}_${e.status}`,
        timestamp: e.timestamp,
        phase: _inferPhaseFromEvent(e.message, e.status),
        content: e.message,
        confidence: e.status === 'review_required' ? 0.95 : 0.75
      }))
      // keep selectedIssue in sync
      if (this.selectedIssue?.id === issue.id) {
        this.selectedIssue = { ...issue }
      }
    },

    attachJobToIssue(issueId: string, job: ECCDispatchJob) {
      const issue = this.getIssueById(issueId)
      if (issue) {
        this.applyECCJobToIssue(issue, job)
      }
    },

    async refreshECCJob(issueId: string) {
      const issue = this.getIssueById(issueId)
      if (!issue?.eccJobId) return

      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(`${config.public.apiBase}/ecc/jobs/${issue.eccJobId}`)
        this.applyECCJobToIssue(issue, job)
        if (_jobIsTerminal(job.status)) {
          this.stopStreaming(issue.id)
          if (this.activeAI_task === issue.key) {
            this.aiStatus = 'idle'
            this.activeAI_task = null
          }
        }
      } catch (error) {
        console.warn('[BoardStore] Unable to refresh ECC job status', error)
      }
    },

    async updateECCJobStatus(issue: Issue, status: Issue['eccJobStatus'], message: string) {
      if (!issue.eccJobId || !status) return

      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(`${config.public.apiBase}/ecc/jobs/${issue.eccJobId}`, {
          method: 'PATCH',
          body: { status, message }
        })
        this.applyECCJobToIssue(issue, job)
      } catch (error) {
        console.warn('[BoardStore] Unable to update ECC job status', error)
      }
    },

    async pollIssueJob(issueId: string): Promise<(() => void) | null> {
      // Resolve a job id for this issue, in priority order.
      const issueJobId = this.getIssueById(issueId)?.eccJobId ?? undefined
      let jobId: string | undefined = issueJobId
      if (!jobId) {
        const existing = this.getIssueJob(issueId)
        if (existing) jobId = existing.id
      }
      if (!jobId) {
        const jobs = await this.fetchJobsForIssue(issueId)
        if (jobs && jobs.length > 0) jobId = jobs[0].id
      }
      if (!jobId) return null

      // Initial fetch so the most recent state lands before polling starts.
      await this.fetchJob(jobId)

      // Poll window: ~2.5s at 250ms while the job is still in flight.
      const POLL_DURATION_MS = 2500
      const POLL_INTERVAL_MS = 250
      const deadline = Date.now() + POLL_DURATION_MS
      let timerId: ReturnType<typeof setTimeout> | null = null
      let cancelled = false

      const tick = async () => {
        if (cancelled) return

        const currentIssue = this.getIssueById(issueId)
        if (!currentIssue) return

        // The live job id may differ from what we started polling.
        // If a new dispatch has taken over (or our captured job has been
        // removed), stop polling — the live state is already what we wanted.
        if (!currentIssue.eccJobId || currentIssue.eccJobId !== jobId) {
          return
        }

        const status = currentIssue.eccJobStatus
        if (status && _jobIsTerminal(status)) return
        if (Date.now() > deadline) return
        await this.fetchJob(jobId!)
        if (cancelled) return
        timerId = setTimeout(tick, POLL_INTERVAL_MS)
      }

      timerId = setTimeout(tick, POLL_INTERVAL_MS)

      return () => {
        cancelled = true
        if (timerId) {
          clearTimeout(timerId)
          timerId = null
        }
      }
    },

    revertMove(issue: Issue, originalStatus: IssueStatus, originalColumn: Column) {
      // Remove from current column
      for (const col of this.columns) {
        const idx = col.issues.findIndex(i => i.id === issue.id)
        if (idx !== -1) {
          col.issues.splice(idx, 1)
          break
        }
      }

      // Add back to original column
      issue.status = originalStatus
      issue.moveStatus = 'idle'
      issue.updatedAt = new Date().toISOString()
      originalColumn.issues.push(issue)

      // Update activity log
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'status_change',
        message: `Move failed, reverted to ${COLUMN_CONFIG[originalStatus].title}`,
        actor: 'system',
        timestamp: new Date().toISOString()
      })
    },

    async retryMove(issueId: string) {
      const issue = this.getIssueById(issueId)
      if (!issue) return

      const toStatus = issue.status
      issue.moveStatus = 'pending'
      issue.moveError = null

      try {
        const dispatchJob = await this.confirmMoveWithControlPlane(issue, toStatus)
        issue.moveStatus = 'confirmed'
        this.dispatchAI(issue, dispatchJob)
      } catch (error) {
        issue.moveStatus = 'failed'
        issue.moveError = error instanceof Error ? error.message : 'Retry failed'
      }
    },

    dispatchAI(issue: Issue, dispatchJob?: ECCDispatchJob | null) {
      issue.aiStatus = 'running'
      issue.harnessType = this.activeHarness
      if (dispatchJob) {
        this.applyECCJobToIssue(issue, dispatchJob)
      }
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'ai_started',
        message: dispatchJob?.id
          ? `Agent dispatched via ${dispatchJob.id}: /loop-start --profile=${issue.profile}`
          : `Agent dispatched locally: /loop-start --profile=${issue.profile}`,
        actor: 'system',
        timestamp: new Date().toISOString()
      })

      this.aiStatus = 'running'
      this.activeAI_task = issue.key

      if (dispatchJob?.id) {
        this.fetchJobs()
        setTimeout(() => this.refreshECCJob(issue.id), 250)
        setTimeout(() => this.refreshECCJob(issue.id), 900)
        setTimeout(() => this.fetchJobs(), 1400)
        return
      }

      this.startStreaming(issue.id, issue.profile)

      setTimeout(() => {
        this.completeAI(issue.id)
      }, 3000 + Math.random() * 2000)
    },

    async dispatchCommand(payload: {
      issueId: string
      issueKey: string
      command: string
      profile: ECCProfile
      harness: HarnessType
      provider?: string
      model?: string
      execution_mode?: string
    }): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(`${config.public.apiBase}/ecc/dispatch`, {
          method: 'POST',
          body: {
            issue_id: payload.issueId,
            issue_key: payload.issueKey,
            command: payload.command,
            profile: payload.profile,
            harness: payload.harness,
            provider: payload.provider || null,
            model: payload.model || null,
            execution_mode: payload.execution_mode || null
          },
          headers: authHeaders(),
        })
        await this.fetchJobs()
        return job
      } catch (error) {
        console.warn('[BoardStore] dispatchCommand failed:', error)
        return null
      }
    },

    startStreaming(issueId: string, profile: string) {
      // Register this issue as streaming
      if (!this.streamingIssues.includes(issueId)) {
        this.streamingIssues.push(issueId)
      }

      const issue = this.getIssueById(issueId)
      if (!issue) return

      const phases: Array<{ phase: ECCLogEntry['phase']; content: string; toolUsed?: string }> = [
        { phase: 'observation', content: `Analyzing ${profile} codebase structure...` },
        { phase: 'reasoning', content: `Planning implementation approach based on ECC patterns...` },
        { phase: 'action', content: `Modifying source files with precision...`, toolUsed: 'edit' },
        { phase: 'action', content: `Running tests to validate changes...`, toolUsed: 'bash' },
        { phase: 'output', content: `Implementation complete. Running quality gates...` }
      ]

      let phaseIndex = 0
      const streamInterval = setInterval(() => {
        const currentIssue = this.getIssueById(issueId)
        if (!currentIssue || currentIssue.aiStatus !== 'running') {
          clearInterval(streamInterval)
          return
        }

        if (phaseIndex < phases.length) {
          const p = phases[phaseIndex]
          const log: ECCLogEntry = {
            id: `stream_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            timestamp: new Date().toISOString(),
            phase: p.phase,
            content: p.content,
            confidence: 0.75 + Math.random() * 0.2,
            toolUsed: p.toolUsed,
            duration: p.phase === 'action' ? 200 + Math.random() * 400 : undefined
          }

          // Find the issue in columns and append log
          for (const col of this.columns) {
            const idx = col.issues.findIndex(i => i.id === issueId)
            if (idx !== -1) {
              col.issues[idx].eccLogs.push(log)
              break
            }
          }

          phaseIndex++
        } else {
          clearInterval(streamInterval)
        }
      }, 1000 + Math.random() * 800)
    },

    stopStreaming(issueId: string) {
      this.streamingIssues = this.streamingIssues.filter(id => id !== issueId)
    },

    async completeAI(issueId: string) {
      const issue = this.getIssueById(issueId)
      if (!issue) return

      issue.aiStatus = 'idle'
      issue.eccJobStatus = 'review_required'
      issue.eccJobMessage = 'Agent completed local run; human review required'
      issue.eccJobUpdatedAt = new Date().toISOString()
      issue.prUrl = `https://github.com/org/repo/pull/${Math.floor(Math.random() * 100) + 40}`
      issue.ciStatus = 'pending'
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'ai_completed',
        message: 'AI task completed, PR created',
        actor: 'ai',
        timestamp: new Date().toISOString()
      })

      // Stop streaming
      this.stopStreaming(issueId)

      this.aiStatus = 'idle'
      this.activeAI_task = null

      // Await the PATCH call to properly update ECC job status on backend
      await this.updateECCJobStatus(issue, 'review_required', 'Agent completed local run; human review required')
    },

    // Task #6: Feedback Loop - Reject & Loop Back
    async rejectAndLoopBack(issueId: string, comments: string[]): Promise<boolean> {
      const issue = this.getIssueById(issueId)
      if (!issue || issue.status !== 'human_review') return false

      console.log(`[Feedback Loop] Processing reject for ${issue.key}`)
      console.log(`[Feedback Loop] Comments: ${comments.join('; ')}`)

      // Build context injection from comments
      const contextInjection = this.buildFeedbackContext(issue, comments)

      // Add activity log entry
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'status_change',
        message: `Rejected: ${comments.length} comment(s) received. Re-triggering AI with feedback context.`,
        actor: 'human',
        timestamp: new Date().toISOString()
      })

      // Move back to In Progress
      const fromColumn = this.columns.find(col => col.id === 'human_review')
      const toColumn = this.columns.find(col => col.id === 'in_progress')

      if (!fromColumn || !toColumn) return false

      const idx = fromColumn.issues.findIndex(i => i.id === issueId)
      if (idx === -1) return false

      fromColumn.issues.splice(idx, 1)
      issue.status = 'in_progress'
      issue.updatedAt = new Date().toISOString()
      issue.moveStatus = 'confirmed'

      toColumn.issues.unshift(issue)

      // Re-dispatch AI with feedback context
      setTimeout(() => {
        this.dispatchAIWithContext(issue, contextInjection)
      }, 500)

      return true
    },

    buildFeedbackContext(issue: Issue, comments: string[]): string {
      const focusAreas = comments.map(c => {
        const lower = c.toLowerCase()
        if (lower.includes('security')) return 'security'
        if (lower.includes('performance')) return 'performance'
        if (lower.includes('test')) return 'testing'
        if (lower.includes('logic') || lower.includes('bug')) return 'logic-fix'
        return 'general-fix'
      })

      return `=== REJECTION FEEDBACK FOR ${issue.key} ===
Issue: ${issue.title}
Profile: ${issue.profile}

--- Review Comments ---
${comments.map((c, i) => `${i + 1}. ${c}`).join('\n')}

--- Instructions ---
Please address each comment above. Focus on: ${[...new Set(focusAreas)].join(', ')}

=== END FEEDBACK ===`
    },

    dispatchAIWithContext(issue: Issue, context: string) {
      issue.aiStatus = 'running'
      issue.harnessType = this.activeHarness
      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'ai_started',
        message: `Agent re-dispatched with feedback context: ${context.substring(0, 50)}...`,
        actor: 'system',
        timestamp: new Date().toISOString()
      })

      this.aiStatus = 'running'
      this.activeAI_task = issue.key

      this.startStreaming(issue.id, issue.profile)

      // Simulate AI working with context
      setTimeout(() => {
        this.completeAI(issue.id)
      }, 4000 + Math.random() * 2000)
    },

    // Task #6: Approve & Merge
    async approveReview(issueId: string): Promise<boolean> {
      const issue = this.getIssueById(issueId)
      if (!issue) return false

      console.log(`[Feedback Loop] Processing approve for ${issue.key}`)

      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'status_change',
        message: 'PR approved. Merging via /release-ready --merge',
        actor: 'human',
        timestamp: new Date().toISOString()
      })

      return await this.moveIssueWithUnlock(issueId, issue.status, 'done', 0)
    },

    async requestChanges(issueId: string, reason = 'Review requested changes'): Promise<boolean> {
      const issue = this.getIssueById(issueId)
      if (!issue) return false

      issue.activityLog.push({
        id: `a${Date.now()}`,
        type: 'status_change',
        message: reason,
        actor: 'human',
        timestamp: new Date().toISOString()
      })

      const wasInProgress = issue.status === 'in_progress'
      const moved = wasInProgress
        ? true
        : await this.moveIssueWithUnlock(issueId, issue.status, 'in_progress', 0)

      if (moved && wasInProgress) {
        const freshIssue = this.getIssueById(issueId)
        if (freshIssue) {
          const dispatchJob = await this.confirmMoveWithControlPlane(freshIssue, 'in_progress')
          this.dispatchAI(freshIssue, dispatchJob)
        }
      }

      return moved
    },

    // Task #7: Dependency Graph Auto-Unlock
    processDependencyUnlock(completedIssueKey: string) {
      const allIssues = this.getAllIssues
      const unlocked: string[] = []

      // Find all blocked issues that depend on the completed issue
      const dependentIssues = allIssues.filter(issue =>
        issue.dependencies.includes(completedIssueKey) && issue.status === 'blocked'
      )

      console.log(`[Dependency Graph] ${completedIssueKey} completed. Found ${dependentIssues.length} dependent(s)`)

      for (const issue of dependentIssues) {
        // Check if ALL dependencies are now resolved
        const doneKeys = new Set(
          allIssues
            .filter(i => i.status === 'done')
            .map(i => i.key)
        )

        const blockers = issue.dependencies.filter(dep => !doneKeys.has(dep))

        if (blockers.length === 0) {
          console.log(`[Dependency Graph] Unblocking ${issue.key} (all dependencies resolved)`)

          // Move from blocked to backlog
          const fromColumn = this.columns.find(col => col.id === 'blocked')
          const toColumn = this.columns.find(col => col.id === 'backlog')

          if (fromColumn && toColumn) {
            const idx = fromColumn.issues.findIndex(i => i.id === issue.id)
            if (idx !== -1) {
              fromColumn.issues.splice(idx, 1)
              issue.status = 'backlog'
              issue.updatedAt = new Date().toISOString()

              toColumn.issues.unshift(issue)

              issue.activityLog.push({
                id: `a${Date.now()}`,
                type: 'status_change',
                message: `Unblocked: ${completedIssueKey} completed. All dependencies resolved.`,
                actor: 'system',
                timestamp: new Date().toISOString()
              })

              unlocked.push(issue.key)
              console.log(`[Dependency Graph] ${issue.key} moved to Backlog`)
            }
          }
        }
      }

      return unlocked
    },

    // Wrapper for moveIssue that triggers dependency unlock when moving to Done
    async moveIssueWithUnlock(issueId: string, fromStatus: IssueStatus, toStatus: IssueStatus, newIndex: number): Promise<boolean> {
      // Get issue before move to capture key for unlock
      const issue = this.getIssueById(issueId)
      const completedKey = issue?.key

      const result = await this.moveIssue(issueId, fromStatus, toStatus, newIndex)

      // If moved to Done, trigger dependency unlock
      if (result && toStatus === 'done' && completedKey) {
        setTimeout(() => {
          this.processDependencyUnlock(completedKey)
        }, 500)
      }

      return result
    },

    selectIssue(issue: Issue | null) {
      this.selectedIssue = issue
      this.isDetailOpen = issue !== null
      // Reset to overview tab when opening new issue
      if (issue) {
        this.activeDetailTab = 'overview'
      }
    },

    closeDetail() {
      this.isDetailOpen = false
      this.selectedIssue = null
      this.selectedJob = null
    },

    setDetailTab(tab: 'overview' | 'ecc-logs' | 'diff' | 'collaboration' | 'handoffs' | 'cycles') {
      this.activeDetailTab = tab
    },

    setSearch(query: string) {
      this.searchQuery = query
    },

    setProfileFilter(profile: string) {
      this.profileFilter = profile
    },

    setHarnessFilter(harness: string) {
      this.harnessFilter = harness
    },

    clearFilters() {
      this.searchQuery = ''
      this.profileFilter = 'all'
      this.harnessFilter = 'all'
    },

    setHarness(harness: HarnessType) {
      this.activeHarness = harness
    },

    openNewIssueModal() {
      this.createIssueError = null
      this.isNewIssueModalOpen = true
    },

    closeNewIssueModal() {
      this.isNewIssueModalOpen = false
      this.createIssueError = null
    },

    async createIssueFromModal(payload: NewIssuePayload) {
      this.isCreatingIssue = true
      this.createIssueError = null

      try {
        const config = useRuntimeConfig()
        const token = getCookie('auth_token')
        const res = await fetch(`${config.public.apiBase}/issues`, {
          method: 'POST',
          body: JSON.stringify(payload),
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          credentials: 'include',
        })
        if (!res.ok) {
          let errMsg = `HTTP ${res.status}`
          try {
            const errData = await res.json()
            errMsg = errData.detail || errMsg
          } catch {
            errMsg = await res.text() || errMsg
          }
          throw new Error(errMsg)
        }
        await this.fetchBoard()
        this.closeNewIssueModal()
        return true
      } catch (error) {
        this.createIssueError = error instanceof Error ? error.message : 'Unable to create issue'
        return false
      } finally {
        this.isCreatingIssue = false
      }
    },

    async openJob(job: ECCDispatchJob) {
      this.selectedJob = job
      let issue = this.getIssueById(job.issue_id)
      if (!issue) {
        await this.fetchBoard()
        issue = this.getIssueById(job.issue_id)
      }

      if (issue) {
        this.applyECCJobToIssue(issue, job)
        this.selectIssue(issue)
        this.setDetailTab('ecc-logs')
      } else {
        const fallbackIssue: Issue = _normalizeIssue({
          id: job.issue_id,
          key: job.issue_key,
          title: `Job ${job.id}`,
          description: job.message ?? 'Execution job is not linked to a visible board issue.',
          status: 'in_progress',
          priority: 'medium',
          profile: job.profile,
          labels: [],
          assigneeId: null,
          assigneeName: null,
          assigneeAvatar: null,
          storyPoints: null,
          dependencies: [],
          prUrl: null,
          ciStatus: null,
          aiStatus: _jobIsTerminal(job.status) ? 'idle' : 'running',
          harnessType: job.harness,
          eccJobId: job.id,
          eccJobStatus: job.status,
          eccJobMessage: job.message,
          eccJobUpdatedAt: job.updated_at,
          memoryRef: null,
          activityLog: [],
          eccLogs: [],
          prDetails: null,
          moveStatus: 'idle',
          moveError: null,
          handoffs: [],
          parentId: null,
          acceptanceCriteria: [],
          createdAt: job.created_at,
          updatedAt: job.updated_at
        })
        this.applyECCJobToIssue(fallbackIssue, job)
        this.selectedIssue = fallbackIssue
        this.isDetailOpen = true
        this.activeDetailTab = 'ecc-logs'
      }
    },

    async createIssue(title: string, columnId: IssueStatus) {
      let newIssue: Issue

      try {
        const config = useRuntimeConfig()
        const created = await $fetch<Issue>(`${config.public.apiBase}/issues`, {
          method: 'POST',
          body: { title, status: columnId },
          headers: authHeaders(),
        })
        // Normalize: ensure all required fields exist
        newIssue = {
          ...created,
          dependencies: created.dependencies ?? [],
          labels: created.labels ?? [],
          activityLog: created.activityLog ?? [],
          eccLogs: created.eccLogs ?? [],
          prDetails: created.prDetails ?? null,
          moveStatus: created.moveStatus ?? 'idle',
          moveError: created.moveError ?? null,
          aiStatus: created.aiStatus ?? 'idle',
          eccJobId: created.eccJobId ?? null,
          eccJobStatus: created.eccJobStatus ?? null,
          eccJobMessage: created.eccJobMessage ?? null,
          eccJobUpdatedAt: created.eccJobUpdatedAt ?? null,
          harnessType: created.harnessType ?? null,
          prUrl: created.prUrl ?? null,
          ciStatus: created.ciStatus ?? null,
          storyPoints: created.storyPoints ?? 0,
          memoryRef: created.memoryRef ?? null,
          assigneeId: created.assigneeId ?? null,
          assigneeName: created.assigneeName ?? null,
          assigneeAvatar: created.assigneeAvatar ?? null,
        }
      } catch (error) {
        console.warn('[BoardStore] createIssue failed, creating local-only issue:', error)
        const allIssues = this.getAllIssues
        const maxNumber = allIssues.reduce((max, issue) => {
          const match = issue.key.match(/^DEV-(\d+)$/)
          return match ? Math.max(max, parseInt(match[1])) : max
        }, 0)

        newIssue = {
          id: `new_${Date.now()}`,
          key: `DEV-${String(maxNumber + 1).padStart(3, '0')}`,
          title,
          description: '',
          status: columnId,
          priority: 'medium',
          profile: 'general',
          labels: [],
          assigneeId: null,
          assigneeName: null,
          assigneeAvatar: null,
          storyPoints: 0,
          dependencies: [],
          prUrl: null,
          ciStatus: null,
          aiStatus: 'idle',
          harnessType: null,
          eccJobId: null,
          eccJobStatus: null,
          eccJobMessage: null,
          eccJobUpdatedAt: null,
          memoryRef: null,
          activityLog: [
            {
              id: `a${Date.now()}`,
              type: 'status_change',
              message: `Created in ${COLUMN_CONFIG[columnId].title}`,
              actor: 'human',
              timestamp: new Date().toISOString()
            }
          ],
          eccLogs: [],
          prDetails: null,
          moveStatus: 'idle',
          moveError: null,
          handoffs: [],
          parentId: null,
          acceptanceCriteria: [],
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString()
        }
      }

      const column = this.columns.find(col => col.id === columnId)
      if (column) {
        column.issues.push(newIssue)
      }

      return newIssue
    },

    // Task #8: WebSocket Real-time Updates
    handleIssueUpdate(payload: {
      issueId: string
      changes: Partial<{
        title: string
        description: string
        status: IssueStatus
        priority: Priority
        assigneeId: string | null
        assigneeName: string | null
        labels: Array<{ id: string; name: string; color: string }>
      }>
    }) {
      const issue = this.getIssueById(payload.issueId)
      if (!issue) {
        console.warn('[BoardStore] handleIssueUpdate: Issue not found', payload.issueId)
        return
      }

      console.log('[BoardStore] Handling issue update:', payload.issueId, payload.changes)

      // Apply status change if present
      if (payload.changes.status && payload.changes.status !== issue.status) {
        const fromColumn = this.columns.find(col => col.id === issue.status)
        const toColumn = this.columns.find(col => col.id === payload.changes.status)

        if (fromColumn && toColumn) {
          const idx = fromColumn.issues.findIndex(i => i.id === payload.issueId)
          if (idx !== -1) {
            fromColumn.issues.splice(idx, 1)
            issue.status = payload.changes.status
            issue.updatedAt = new Date().toISOString()
            toColumn.issues.push(issue)

            issue.activityLog.push({
              id: `a${Date.now()}`,
              type: 'status_change',
              message: `Status changed via WebSocket to ${COLUMN_CONFIG[payload.changes.status].title}`,
              actor: 'system',
              timestamp: new Date().toISOString()
            })
          }
        }
      }

      // Apply other changes
      if (payload.changes.title !== undefined) issue.title = payload.changes.title
      if (payload.changes.description !== undefined) issue.description = payload.changes.description
      if (payload.changes.priority !== undefined) issue.priority = payload.changes.priority
      if (payload.changes.assigneeId !== undefined) issue.assigneeId = payload.changes.assigneeId
      if (payload.changes.assigneeName !== undefined) issue.assigneeName = payload.changes.assigneeName
      if (payload.changes.labels !== undefined) issue.labels = payload.changes.labels

      issue.updatedAt = new Date().toISOString()

      // Update selected issue if it's the one being updated
      if (this.selectedIssue?.id === payload.issueId) {
        this.selectedIssue = { ...issue }
      }
    },

    handleAgentStatusUpdate(payload: {
      agentId: string
      status: 'idle' | 'running' | 'error'
      taskId?: string
    }) {
      console.log('[BoardStore] Handling agent status update:', payload)

      // Update global AI status
      this.aiStatus = payload.status

      // If there's a taskId, find the associated issue
      if (payload.taskId) {
        const issue = this.getIssueById(payload.taskId)
        if (issue) {
          issue.aiStatus = payload.status

          issue.activityLog.push({
            id: `a${Date.now()}`,
            type: payload.status === 'running' ? 'ai_started' : payload.status === 'error' ? 'error' : 'ai_completed',
            message: `Agent status changed to ${payload.status} via WebSocket`,
            actor: payload.status === 'error' ? 'system' : 'ai',
            timestamp: new Date().toISOString()
          })

          if (payload.status === 'idle') {
            this.stopStreaming(issue.id)
          } else if (payload.status === 'running') {
            if (!this.streamingIssues.includes(issue.id)) {
              this.streamingIssues.push(issue.id)
            }
          }
        }
      }

      // Update active task reference
      if (payload.status === 'idle') {
        this.activeAI_task = null
      } else if (payload.taskId) {
        this.activeAI_task = this.getIssueById(payload.taskId)?.key ?? null
      }
    },

    handleJobUpdate(job: ECCDispatchJob) {
      // Used by the WS path. Same shape as applyECCJobToIssue but
      // driven by an external push rather than a REST fetch.

      // Once a job is cancelled or completed, ignore stale updates that
      // would revert its status (e.g. a late-arriving WS push from a
      // safe-runner that was not stopped promptly).
      const current = this.jobsById[job.id]
      if (current && (current.status === 'cancelled' || current.status === 'completed')) {
        return
      }

      this.jobsById[job.id] = job
      const existing = this.jobs.find(j => j.id === job.id)
      if (existing) {
        Object.assign(existing, job)
      } else {
        this.jobs = [job, ...this.jobs]
      }
      const ids = this.jobsForIssue[job.issue_id] ?? []
      if (!ids.includes(job.id)) {
        this.jobsForIssue[job.issue_id] = [...ids, job.id]
      }
      this.applyECCJobToIssue(
        this.getIssueById(job.issue_id) ?? this._synthIssue(job),
        job
      )
    },

    _synthIssue(job: ECCDispatchJob): Issue {
      // When WS pushes a job whose issue has not been loaded yet, we
      // synthesise a minimal Issue so the rest of the store logic can
      // run. The real issue will overwrite this once the board loads.
      return {
        id: job.issue_id,
        key: job.issue_key,
        title: job.issue_key,
        description: '',
        status: 'backlog',
        priority: 'medium',
        profile: job.profile,
        labels: [],
        assigneeId: null,
        assigneeName: null,
        assigneeAvatar: null,
        storyPoints: null,
        dependencies: [],
        prUrl: null,
        ciStatus: null,
        aiStatus: 'idle',
        harnessType: job.harness,
        eccJobId: job.id,
        eccJobStatus: job.status,
        eccJobMessage: job.message,
        eccJobUpdatedAt: job.updated_at,
        memoryRef: null,
        activityLog: [],
        eccLogs: [],
        prDetails: null,
        moveStatus: 'idle',
        moveError: null,
        handoffs: [],
        parentId: null,
        acceptanceCriteria: [],
        createdAt: job.created_at,
        updatedAt: job.updated_at
      }
    },

    async cancelJob(jobId: string): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(
          `${config.public.apiBase}/ecc/jobs/${jobId}/cancel`,
          { method: 'POST', headers: authHeaders() }
        )
        this.handleJobUpdate(job)
        return job
      } catch (error) {
        console.warn('[BoardStore] cancelJob failed:', error)
        return null
      }
    },

    async retryJob(jobId: string): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(
          `${config.public.apiBase}/ecc/jobs/${jobId}/retry`,
          { method: 'POST', headers: authHeaders() }
        )
        this.handleJobUpdate(job)
        // Kick a fetch so the new job shows up in the global list
        // immediately (we only mutated the in-place entry above).
        await this.fetchJobs()
        return job
      } catch (error) {
        console.warn('[BoardStore] retryJob failed:', error)
        return null
      }
    },

    // ------------------------------------------------------------------
    // Kanban Protocol — Handoff actions
    // ------------------------------------------------------------------

    /** Find the in-memory issue by ID and return its composable handle. */
    _handoffCtx(issueId: string) {
      const issue = this.columns
        .flatMap(c => c.issues)
        .find(i => i.id === issueId)
      if (!issue) return null
      return { issue, api: useKanbanProtocol(issueId) }
    },

    async fetchHandoffs(issueId: string): Promise<Handoff[]> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return []
      try {
        const { handoffs } = await ctx.api.listHandoffs()
        ctx.issue.handoffs = handoffs
        return handoffs
      } catch (e) {
        console.warn('[BoardStore] fetchHandoffs failed:', e)
        return []
      }
    },

    async createHandoff(issueId: string, req: HandoffCreateRequest): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.createHandoff(req)
        ctx.issue.handoffs = [...ctx.issue.handoffs, h]
        return h
      } catch (e) {
        console.warn('[BoardStore] createHandoff failed:', e)
        return null
      }
    },

    async acceptHandoff(issueId: string, handoffId: string, actor?: string): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.acceptHandoff(handoffId, actor)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        return h
      } catch (e) {
        console.warn('[BoardStore] acceptHandoff failed:', e)
        return null
      }
    },

    async dispatchHandoff(issueId: string, handoffId: string, req: HandoffDispatchRequest): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const { handoff } = await ctx.api.dispatchHandoff(handoffId, req)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? handoff : x)
        return handoff
      } catch (e) {
        console.warn('[BoardStore] dispatchHandoff failed:', e)
        return null
      }
    },

    async completeHandoff(issueId: string, handoffId: string, payload?: Record<string, unknown>, actor?: string): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.completeHandoff(handoffId, payload, actor)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        return h
      } catch (e) {
        console.warn('[BoardStore] completeHandoff failed:', e)
        return null
      }
    },

    async reviewHandoff(issueId: string, handoffId: string, req: { decision: 'approve' | 'reject' | 'request_changes'; actor?: string; comment?: string }): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const resp = await ctx.api.reviewHandoff(handoffId, req) as any
        // Backend returns { handoff, routing }. Extract the updated handoff.
        const h: Handoff = resp.handoff ?? resp
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        // If routing created a new handoff (rework/reject/approve), append it.
        if (resp.routing?.next_handoff) {
          ctx.issue.handoffs.push(resp.routing.next_handoff)
        }
        return h
      } catch (e) {
        console.warn('[BoardStore] reviewHandoff failed:', e)
        return null
      }
    },

    async blockHandoff(issueId: string, handoffId: string, reason: string, actor?: string): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.blockHandoff(handoffId, reason, actor)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        return h
      } catch (e) {
        console.warn('[BoardStore] blockHandoff failed:', e)
        return null
      }
    },

    async unblockHandoff(issueId: string, handoffId: string, actor?: string): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.unblockHandoff(handoffId, actor)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        return h
      } catch (e) {
        console.warn('[BoardStore] unblockHandoff failed:', e)
        return null
      }
    },

    async cancelHandoff(issueId: string, handoffId: string, actor?: string): Promise<Handoff | null> {
      const ctx = this._handoffCtx(issueId)
      if (!ctx) return null
      try {
        const h = await ctx.api.cancelHandoff(handoffId, actor)
        ctx.issue.handoffs = ctx.issue.handoffs.map(x => x.id === handoffId ? h : x)
        return h
      } catch (e) {
        console.warn('[BoardStore] cancelHandoff failed:', e)
        return null
      }
    },

    // ------------------------------------------------------------------
    // Agent Role CRUD actions
    // ------------------------------------------------------------------

    async fetchAgentRoles() {
      const config = useRuntimeConfig()
      const token = getCookie('auth_token')

      // No token → read-only from public /lanes, skip protected /agent-roles
      if (!token) {
        try {
          const lanesRes = await $fetch<{ lanes: any[] }>(`${config.public.apiBase}/lanes`)
          this.agentRoles = (lanesRes.lanes ?? []).map((l: any) => ({
            ...l,
            id: l.key,
            nextRoles: l.nextLanes ?? [],
            enabled: true,
          }))
        } catch {
          this.agentRoles = []
        }
        return
      }

      // Has token → try /agent-roles, fallback to /lanes on 401/403
      try {
        const res = await $fetch<{ roles: AgentRole[] }>(`${config.public.apiBase}/agent-roles`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        this.agentRoles = res.roles
      } catch (e: any) {
        if (e?.status === 401 || e?.status === 403) {
          try {
            const lanesRes = await $fetch<{ lanes: any[] }>(`${config.public.apiBase}/lanes`)
            this.agentRoles = (lanesRes.lanes ?? []).map((l: any) => ({
              ...l,
              id: l.key,
              nextRoles: l.nextLanes ?? [],
              enabled: true,
            }))
          } catch {
            this.agentRoles = []
          }
        } else {
          console.error('Failed to fetch agent roles:', e)
        }
      }
    },

    async createAgentRole(data: Record<string, unknown>) {
      const config = useRuntimeConfig()
      const token = getCookie('auth_token')
      const headers: Record<string, string> = {}
      if (token) headers.Authorization = `Bearer ${token}`
      const res = await $fetch<AgentRole>(`${config.public.apiBase}/agent-roles`, {
        method: 'POST',
        body: data,
        headers,
      })
      await this.fetchAgentRoles()
      return res
    },

    async updateAgentRole(key: string, data: Record<string, unknown>) {
      const config = useRuntimeConfig()
      const token = getCookie('auth_token')
      const headers: Record<string, string> = {}
      if (token) headers.Authorization = `Bearer ${token}`
      const res = await $fetch<AgentRole>(`${config.public.apiBase}/agent-roles/${key}`, {
        method: 'PUT',
        body: data,
        headers,
      })
      await this.fetchAgentRoles()
      return res
    },

    async toggleAgentRoleEnabled(key: string, enabled: boolean) {
      const config = useRuntimeConfig()
      const token = getCookie('auth_token')
      const headers: Record<string, string> = {}
      if (token) headers.Authorization = `Bearer ${token}`
      const res = await $fetch<AgentRole>(`${config.public.apiBase}/agent-roles/${key}/enabled`, {
        method: 'PATCH',
        body: { enabled },
        headers,
      })
      await this.fetchAgentRoles()
      return res
    }
  }
})
