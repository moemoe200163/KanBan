import { defineStore } from 'pinia'
import type { BoardState, Issue, IssueStatus, Priority, AIAgentStatus, HarnessType, Column, ECCLogEntry, PRDetails, ECCDispatchJob, ECCProfile } from '~/types'
import { COLUMN_CONFIG, ECC_COMMAND_MAP } from '~/types'
import { useECCStreamSingleton } from '~/composables/useECCStream'
import { useDependencyGraph } from '~/composables/useDependencyGraph'
import { useFeedbackLoop } from '~/composables/useFeedbackLoop'

// Generate edge-case rich mock data
const generateMockIssues = (): Issue[] => ([
  {
    id: '1',
    key: 'DEV-001',
    title: 'Implement user authentication flow',
    description: 'Set up OAuth 2.0 with Google and GitHub providers. Include session management and secure token storage.',
    status: 'done',
    priority: 'high',
    profile: 'backend',
    labels: [
      { id: 'l1', name: 'auth', color: '#7D9E7D' },
      { id: 'l2', name: 'security', color: '#B85C4D' }
    ],
    assigneeId: 'u1',
    assigneeName: 'Alex Chen',
    assigneeAvatar: 'https://i.pravatar.cc/150?u=alex',
    storyPoints: 5,
    dependencies: [],
    prUrl: 'https://github.com/org/repo/pull/42',
    ciStatus: 'passed',
    harnessType: 'claude-code',
    memoryRef: 'mem_001',
    activityLog: [
      { id: 'a1', type: 'ai_started', message: 'Agent started: claude-code', actor: 'ai', timestamp: '2026-05-28T09:00:00Z' },
      { id: 'a2', type: 'status_change', message: 'Moved to In Progress', actor: 'human', timestamp: '2026-05-28T09:05:00Z' },
      { id: 'a3', type: 'pr_created', message: 'PR #42 created', actor: 'ai', timestamp: '2026-05-28T11:30:00Z' },
      { id: 'a4', type: 'quality_gate', message: 'Quality gate passed', actor: 'system', timestamp: '2026-05-28T11:45:00Z' },
      { id: 'a5', type: 'status_change', message: 'Moved to Done', actor: 'human', timestamp: '2026-05-28T14:00:00Z' }
    ],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-20T08:00:00Z',
    updatedAt: '2026-05-28T14:00:00Z'
  },
  {
    id: '2',
    key: 'DEV-002',
    title: 'Build Kanban board drag-and-drop with keyboard navigation and accessibility support for screen readers',
    description: 'Implement interactive Kanban with vuedraggable. Support cross-column dragging, visual feedback, and keyboard navigation. Ensure ARIA labels and focus management for accessibility.',
    status: 'in_progress',
    priority: 'high',
    profile: 'frontend',
    labels: [
      { id: 'l3', name: 'ui', color: '#6B8BA4' },
      { id: 'l4', name: 'ux', color: '#C67B4E' },
      { id: 'l4a', name: 'accessibility', color: '#7D9E7D' },
      { id: 'l4b', name: 'a11y', color: '#7D9E7D' }
    ],
    assigneeId: 'u2',
    assigneeName: 'Jamie Rivera',
    assigneeAvatar: 'https://i.pravatar.cc/150?u=jamie',
    storyPoints: 8,
    dependencies: [],
    prUrl: 'https://github.com/org/repo/pull/46',
    ciStatus: 'pending',
    harnessType: 'claude-code',
    memoryRef: null,
    activityLog: [
      { id: 'a6', type: 'status_change', message: 'Moved to In Progress', actor: 'human', timestamp: '2026-05-30T10:00:00Z' },
      { id: 'a7', type: 'ai_started', message: 'Agent dispatched: /loop-start --profile=frontend', actor: 'system', timestamp: '2026-05-30T10:00:05Z' }
    ],
    eccLogs: [
      { id: 'e1', timestamp: '2026-05-30T10:00:05Z', phase: 'observation', content: 'Analyzing Vue component structure...', confidence: 0.9, toolUsed: 'read' },
      { id: 'e2', timestamp: '2026-05-30T10:00:15Z', phase: 'reasoning', content: 'Need to integrate vuedraggable with existing Pinia store for state synchronization', confidence: 0.85 },
      { id: 'e3', timestamp: '2026-05-30T10:00:20Z', phase: 'action', content: 'Modifying IssueCard.vue to add draggable attributes and ARIA labels', confidence: 0.9, toolUsed: 'edit', duration: 450 },
      { id: 'e4', timestamp: '2026-05-30T10:00:35Z', phase: 'action', content: 'Updating board store to handle cross-column move logic', confidence: 0.95, toolUsed: 'edit', duration: 320 },
      { id: 'e5', timestamp: '2026-05-30T10:00:40Z', phase: 'output', content: 'Drag-and-drop implementation complete. Running accessibility audit...', confidence: 0.88 }
    ],
    prDetails: {
      number: 46,
      title: 'feat: implement kanban drag-and-drop with accessibility',
      body: 'This PR adds drag-and-drop functionality to the Kanban board with full keyboard navigation and screen reader support.',
      author: 'Jamie Rivera',
      avatarUrl: 'https://i.pravatar.cc/150?u=jamie',
      state: 'open',
      additions: 247,
      deletions: 32,
      changedFiles: 5,
      headRef: 'feature/kanban-dnd',
      baseRef: 'main',
      files: [
        { filename: 'src/components/IssueCard.vue', status: 'modified', additions: 89, deletions: 12, patch: '@@ -12,7 +12,15 @@ export default {\n   ...\n+  draggable: true,\n+  ariaLabel: "Drag issue card to reorder",' },
        { filename: 'src/stores/board.ts', status: 'modified', additions: 156, deletions: 18, patch: '@@ -45,8 +45,15 @@ export const useBoardStore...' }
      ],
      comments: [
        { id: 'c1', author: 'Alex Chen', avatarUrl: 'https://i.pravatar.cc/150?u=alex', body: 'LGTM! Consider adding keyboard hints in the tooltip.', line: 24, path: 'src/components/IssueCard.vue', createdAt: '2026-05-30T11:00:00Z' }
      ],
      reviewDecision: 'approved'
    },
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-25T08:00:00Z',
    updatedAt: '2026-05-30T10:00:05Z'
  },
  {
    id: '3',
    key: 'DEV-003',
    title: 'Database schema for issue tracking',
    description: 'Design PostgreSQL schema with Prisma. Include issues, labels, activity logs, and user assignments.',
    status: 'in_progress',
    priority: 'medium',
    profile: 'backend',
    labels: [
      { id: 'l5', name: 'database', color: '#6B8BA4' },
      { id: 'l6', name: 'prisma', color: '#D4A84B' }
    ],
    assigneeId: 'u1',
    assigneeName: 'Alex Chen',
    assigneeAvatar: 'https://i.pravatar.cc/150?u=alex',
    storyPoints: 5,
    dependencies: [],
    prUrl: null,
    ciStatus: 'pending',
    harnessType: 'claude-code',
    memoryRef: null,
    activityLog: [
      { id: 'a8', type: 'status_change', message: 'Moved to In Progress', actor: 'human', timestamp: '2026-05-29T14:00:00Z' }
    ],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-26T08:00:00Z',
    updatedAt: '2026-05-29T14:00:00Z'
  },
  {
    id: '4',
    key: 'DEV-004',
    title: 'ECC memory layer integration',
    description: 'Bridge DevFlow with ECC Observer memory. Implement persistent context sharing and throttled state updates.',
    status: 'blocked',
    priority: 'high',
    profile: 'backend',
    labels: [
      { id: 'l7', name: 'ecc', color: '#C67B4E' },
      { id: 'l8', name: 'memory', color: '#7D9E7D' },
      { id: 'l9', name: 'observer', color: '#6B8BA4' },
      { id: 'l10', name: 'throttle', color: '#D4A84B' }
    ],
    assigneeId: null,
    assigneeName: null,
    assigneeAvatar: null,
    storyPoints: 8,
    dependencies: ['DEV-003', 'DEV-006', 'DEV-007', 'DEV-009'],
    prUrl: null,
    ciStatus: null,
    harnessType: null,
    memoryRef: null,
    activityLog: [
      { id: 'a9', type: 'status_change', message: 'Blocked: depends on DEV-003, DEV-006, DEV-007, DEV-009', actor: 'system', timestamp: '2026-05-29T14:05:00Z' }
    ],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-26T08:00:00Z',
    updatedAt: '2026-05-29T14:05:00Z'
  },
  {
    id: '5',
    key: 'DEV-005',
    title: 'CI/CD pipeline configuration',
    description: 'Set up GitHub Actions with test, lint, and deploy stages. Integrate quality gate checks before merge.',
    status: 'human_review',
    priority: 'medium',
    profile: 'general',
    labels: [
      { id: 'l11', name: 'ci/cd', color: '#D4A84B' },
      { id: 'l12', name: 'github', color: '#8C8279' }
    ],
    assigneeId: 'u3',
    assigneeName: 'Sam Taylor',
    assigneeAvatar: 'https://i.pravatar.cc/150?u=sam',
    storyPoints: 3,
    dependencies: [],
    prUrl: 'https://github.com/org/repo/pull/45',
    ciStatus: 'passed',
    harnessType: 'claude-code',
    memoryRef: 'mem_005',
    activityLog: [
      { id: 'a10', type: 'status_change', message: 'Moved to Human Review', actor: 'ai', timestamp: '2026-05-29T16:00:00Z' },
      { id: 'a11', type: 'quality_gate', message: 'All gates passed: security, tests, coverage', actor: 'system', timestamp: '2026-05-29T16:01:00Z' }
    ],
    eccLogs: [
      { id: 'e6', timestamp: '2026-05-29T15:30:00Z', phase: 'action', content: 'Running npm run lint...', confidence: 1.0, toolUsed: 'bash', duration: 1200 },
      { id: 'e7', timestamp: '2026-05-29T15:30:15Z', phase: 'output', content: '✓ Lint passed (0 errors, 0 warnings)', confidence: 1.0 },
      { id: 'e8', timestamp: '2026-05-29T15:30:20Z', phase: 'action', content: 'Running npm run test...', confidence: 1.0, toolUsed: 'bash', duration: 8500 },
      { id: 'e9', timestamp: '2026-05-29T15:30:45Z', phase: 'output', content: '✓ Tests passed (42 tests, 0 failures)', confidence: 1.0 },
      { id: 'e10', timestamp: '2026-05-29T15:30:50Z', phase: 'action', content: 'Running security scan with AgentShield...', confidence: 0.95, toolUsed: 'bash', duration: 3200 },
      { id: 'e11', timestamp: '2026-05-29T15:31:00Z', phase: 'output', content: '✓ Security scan passed. No vulnerabilities found.', confidence: 0.95 }
    ],
    prDetails: {
      number: 45,
      title: 'ci: add github actions pipeline with quality gates',
      body: 'This PR adds a GitHub Actions workflow with automated linting, testing, and security scanning.',
      author: 'Sam Taylor',
      avatarUrl: 'https://i.pravatar.cc/150?u=sam',
      state: 'open',
      additions: 156,
      deletions: 12,
      changedFiles: 8,
      headRef: 'feature/cicd-pipeline',
      baseRef: 'main',
      files: [
        { filename: '.github/workflows/ci.yml', status: 'added', additions: 120, deletions: 0 },
        { filename: 'package.json', status: 'modified', additions: 36, deletions: 12 }
      ],
      comments: [],
      reviewDecision: 'approved'
    },
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-27T08:00:00Z',
    updatedAt: '2026-05-29T16:01:00Z'
  },
  {
    id: '6',
    key: 'DEV-006',
    title: 'Quality gate automation with ECC quality-gate --verify and benchmark-optimization-loop integration for automated performance regression detection',
    description: 'Implement ECC quality-gate checks: static analysis, test coverage thresholds, and security scanning. Integration with benchmark-optimization-loop for performance regression detection.',
    status: 'backlog',
    priority: 'high',
    profile: 'security',
    labels: [
      { id: 'l13', name: 'security', color: '#B85C4D' },
      { id: 'l14', name: 'quality', color: '#7D9E7D' },
      { id: 'l15', name: 'benchmark', color: '#6B8BA4' },
      { id: 'l16', name: 'automation', color: '#C67B4E' },
      { id: 'l17', name: 'performance', color: '#D4A84B' }
    ],
    assigneeId: null,
    assigneeName: null,
    assigneeAvatar: null,
    storyPoints: 5,
    dependencies: [],
    prUrl: null,
    ciStatus: null,
    harnessType: null,
    memoryRef: null,
    activityLog: [],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-28T08:00:00Z',
    updatedAt: '2026-05-28T08:00:00Z'
  },
  {
    id: '7',
    key: 'DEV-007',
    title: 'Error state: AI agent failed to complete task due to merge conflict in worktree. Need human intervention to resolve.',
    description: 'The AI agent encountered a merge conflict while trying to merge feature/responsive-branch into main. Manual resolution required.',
    status: 'blocked',
    priority: 'critical',
    profile: 'debug',
    labels: [
      { id: 'l18', name: 'error', color: '#B85C4D' },
      { id: 'l19', name: 'merge-conflict', color: '#D4A84B' },
      { id: 'l20', name: 'needs-review', color: '#B85C4D' }
    ],
    assigneeId: 'u2',
    assigneeName: 'Jamie Rivera',
    assigneeAvatar: 'https://i.pravatar.cc/150?u=jamie',
    storyPoints: 3,
    dependencies: ['DEV-002'],
    prUrl: 'https://github.com/org/repo/pull/48',
    ciStatus: 'failed',
    harnessType: 'claude-code',
    memoryRef: 'mem_007',
    activityLog: [
      { id: 'a12', type: 'status_change', message: 'Moved to In Progress', actor: 'ai', timestamp: '2026-05-29T09:00:00Z' },
      { id: 'a13', type: 'error', message: 'Merge conflict detected. AI agent failed to auto-resolve.', actor: 'ai', timestamp: '2026-05-29T09:15:00Z' },
      { id: 'a14', type: 'status_change', message: 'Moved to Blocked', actor: 'system', timestamp: '2026-05-29T09:15:05Z' }
    ],
    eccLogs: [
      { id: 'e12', timestamp: '2026-05-29T09:00:00Z', phase: 'action', content: 'Attempting to merge feature/responsive-branch into main...', confidence: 0.9, toolUsed: 'bash' },
      { id: 'e13', timestamp: '2026-05-29T09:00:30Z', phase: 'error', content: 'Merge conflict in src/components/IssueCard.vue:20-45. Auto-resolve failed.', confidence: 0.95, toolUsed: 'bash', duration: 30000 },
      { id: 'e14', timestamp: '2026-05-29T09:00:35Z', phase: 'reasoning', content: 'Conflict involves conflicting changes to drag-drop handlers. Need human review.', confidence: 0.8 }
    ],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-28T08:00:00Z',
    updatedAt: '2026-05-29T09:15:05Z'
  },
  {
    id: '8',
    key: 'DEV-008',
    title: 'Error tracking and logging with structured log levels and error aggregation',
    description: 'Integrate structured logging with log levels. Set up error aggregation for AI agent runs.',
    status: 'backlog',
    priority: 'low',
    profile: 'debug',
    labels: [
      { id: 'l21', name: 'logging', color: '#D4A84B' },
      { id: 'l22', name: 'monitoring', color: '#8C8279' }
    ],
    assigneeId: null,
    assigneeName: null,
    assigneeAvatar: null,
    storyPoints: 2,
    dependencies: [],
    prUrl: null,
    ciStatus: null,
    harnessType: null,
    memoryRef: null,
    activityLog: [],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-28T08:00:00Z',
    updatedAt: '2026-05-28T08:00:00Z'
  },
  {
    id: '9',
    key: 'DEV-009',
    title: 'Multi-harness support for Codex and alternative AI coding agents',
    description: 'Add support for OpenAI Codex as alternative harness. Test cross-harness parity for basic operations.',
    status: 'backlog',
    priority: 'low',
    profile: 'general',
    labels: [
      { id: 'l23', name: 'harness', color: '#C67B4E' },
      { id: 'l24', name: 'codex', color: '#7D9E7D' }
    ],
    assigneeId: null,
    assigneeName: null,
    assigneeAvatar: null,
    storyPoints: 5,
    dependencies: [],
    prUrl: null,
    ciStatus: null,
    harnessType: null,
    memoryRef: null,
    activityLog: [],
    eccLogs: [],
    prDetails: null,
    moveStatus: 'idle',
    moveError: null,
    createdAt: '2026-05-28T08:00:00Z',
    updatedAt: '2026-05-28T08:00:00Z'
  }
] as Array<Omit<Issue, 'aiStatus' | 'eccJobId' | 'eccJobStatus' | 'eccJobMessage' | 'eccJobUpdatedAt'> & {
  aiStatus?: AIAgentStatus
  eccJobId?: string | null
  eccJobStatus?: Issue['eccJobStatus']
  eccJobMessage?: string | null
  eccJobUpdatedAt?: string | null
}>).map(issue => ({
  aiStatus: issue.status === 'in_progress' ? 'running' : 'idle',
  eccJobId: null,
  eccJobStatus: null,
  eccJobMessage: null,
  eccJobUpdatedAt: null,
  ...issue
}))

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
    harnessFilter: 'all'
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
      return this.getAllIssues.filter(issue =>
        issue.status === 'human_review' ||
        issue.eccJobStatus === 'review_required' ||
        this.jobs.some(job => job.issue_id === issue.id && job.status === 'review_required')
      )
    }
  },

  actions: {
    async fetchBoard() {
      this.isLoading = true

      try {
        const config = useRuntimeConfig()
        const boardData = await $fetch<{ columns: Array<{ id: IssueStatus; title: string; color: string; issues: Issue[] }> }>(`${config.public.apiBase}/board`)
        this.columns = boardData.columns.map(column => ({
          ...column,
          issues: column.issues.map(_normalizeIssue)
        }))
        await this.fetchJobs()
      } catch (error) {
        console.warn('[BoardStore] fetchBoard failed, falling back to mock data:', error)
        const issues = generateMockIssues()
        const statuses: IssueStatus[] = ['backlog', 'in_progress', 'blocked', 'human_review', 'done']
        this.columns = statuses.map(status => ({
          id: status,
          title: COLUMN_CONFIG[status].title,
          color: COLUMN_CONFIG[status].color,
          issues: issues.filter(issue => issue.status === status)
        }))
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
          }
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
            harness: payload.harness
          }
        })
        this.fetchJobs()
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

    setDetailTab(tab: 'overview' | 'ecc-logs' | 'diff') {
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
        await $fetch<Issue>(`${config.public.apiBase}/issues`, {
          method: 'POST',
          body: payload
        })
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
          body: { title, status: columnId }
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
        createdAt: job.created_at,
        updatedAt: job.updated_at
      }
    },

    async cancelJob(jobId: string): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(
          `${config.public.apiBase}/ecc/jobs/${jobId}/cancel`,
          { method: 'POST' }
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
          { method: 'POST' }
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
    }
  }
})
