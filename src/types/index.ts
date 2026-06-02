// Issue Status — maps to ECC commands
export type IssueStatus = 'backlog' | 'in_progress' | 'blocked' | 'human_review' | 'done'

// Priority Levels
export type Priority = 'critical' | 'high' | 'medium' | 'low'

// ECC Profile — skill profile mapping
export type ECCProfile = 'frontend' | 'backend' | 'security' | 'refactor' | 'debug' | 'general'

// Harness Types
export type HarnessType = 'claude-code' | 'codex' | 'cursor' | 'opencode' | 'gemini'

// AI Agent Status
export type AIAgentStatus = 'idle' | 'running' | 'error' | 'paused'

// Move Operation Status (for async confirmation)
export type MoveStatus = 'idle' | 'pending' | 'confirmed' | 'failed'

// ECC Job Status — backend control-plane lifecycle
export type ECCJobStatus = 'queued' | 'running' | 'paused' | 'failed' | 'review_required' | 'completed' | 'cancelled'

export interface ECCJobEvent {
  timestamp: string
  status: ECCJobStatus
  message: string
}

export type ExecutionMode = 'safe-runner' | 'api-agent' | 'cli-agent'

export interface ECCDispatchJob {
  id: string
  issue_id: string
  issue_key: string
  command: string
  profile: ECCProfile
  harness: HarnessType
  status: ECCJobStatus
  created_at: string
  updated_at: string
  message: string | null
  events: ECCJobEvent[]
  // MVP 2: Provider/Model execution config
  provider?: string | null
  model?: string | null
  execution_mode?: ExecutionMode | null
}

export interface ECCCommandDraft {
  issueId: string
  command: string
  profile: ECCProfile
  harness: HarnessType
  provider?: string
  model?: string
  execution_mode?: ExecutionMode
  note?: string
}

// ECC Log Entry (structured agent output)
export interface ECCLogEntry {
  id: string
  timestamp: string
  phase: 'observation' | 'reasoning' | 'action' | 'output' | 'error'
  content: string
  confidence?: number  // 0-1, agent's confidence in the action
  toolUsed?: string    // e.g., "bash", "edit", "read"
  duration?: number    // ms, execution time
}

// PR Diff View
export interface PRDiffFile {
  filename: string
  status: 'added' | 'modified' | 'deleted'
  additions: number
  deletions: number
  patch?: string       // unified diff patch
  comments?: PRComment[]
}

export interface PRComment {
  id: string
  author: string
  avatarUrl: string | null
  body: string
  line: number | null
  path: string
  createdAt: string
}

export interface PRDetails {
  number: number
  title: string
  body: string
  author: string
  avatarUrl: string | null
  state: 'open' | 'merged' | 'closed'
  additions: number
  deletions: number
  changedFiles: number
  headRef: string
  baseRef: string
  files: PRDiffFile[]
  comments: PRComment[]
  reviewDecision: 'approved' | 'changes_requested' | 'pending' | null
}

// Label Interface
export interface Label {
  id: string
  name: string
  color: string
}

// Activity Log Entry
export interface ActivityEntry {
  id: string
  type: 'status_change' | 'ai_started' | 'ai_completed' | 'pr_created' | 'quality_gate' | 'error'
  message: string
  actor: 'human' | 'ai' | 'system'
  timestamp: string
}

// Audit Log Entry (from backend audit_logs table)
export interface AuditLogEntry {
  id: string
  agentId: string | null
  agentName: string | null
  action: string
  resource: string
  resourceId: string | null
  details: Record<string, unknown>
  changes: Record<string, unknown>
  ipAddress: string | null
  userAgent: string | null
  timestamp: string
}

// Issue Interface
export interface Issue {
  id: string
  key: string
  title: string
  description: string
  status: IssueStatus
  priority: Priority
  profile: ECCProfile
  labels: Label[]
  assigneeId: string | null
  assigneeName: string | null
  assigneeAvatar: string | null
  storyPoints: number | null
  dependencies: string[]
  prUrl: string | null
  ciStatus: 'pending' | 'passed' | 'failed' | null
  aiStatus: AIAgentStatus
  harnessType: HarnessType | null
  eccJobId: string | null
  eccJobStatus: ECCJobStatus | null
  eccJobMessage: string | null
  eccJobUpdatedAt: string | null
  memoryRef: string | null
  activityLog: ActivityEntry[]
  eccLogs: ECCLogEntry[]
  prDetails: PRDetails | null
  moveStatus: MoveStatus
  moveError: string | null
  createdAt: string
  updatedAt: string
}

// Column Interface
export interface Column {
  id: IssueStatus
  title: string
  color: string
  issues: Issue[]
}

// Board State
export interface BoardState {
  columns: Column[]
  isLoading: boolean
  selectedIssue: Issue | null
  isDetailOpen: boolean
  activeDetailTab: 'overview' | 'ecc-logs' | 'diff'
  jobs: ECCDispatchJob[]
  selectedJob: ECCDispatchJob | null
  isLoadingJobs: boolean
  isNewIssueModalOpen: boolean
  createIssueError: string | null
  isCreatingIssue: boolean
  aiStatus: AIAgentStatus
  activeAI_task: string | null
  activeHarness: HarnessType
  streamingIssues: string[]  // Issue IDs currently streaming ECC logs
  // Job index (P1 — C1)
  jobsById: Record<string, ECCDispatchJob>
  jobsForIssue: Record<string, string[]>
  // Filter state
  searchQuery: string
  profileFilter: string
  harnessFilter: string
}

// ECC Command Mapping
export const ECC_COMMAND_MAP: Record<IssueStatus, string> = {
  backlog: '/loop-reset',
  in_progress: '/loop-start',
  blocked: '/harness-pause',
  human_review: '/quality-gate --verify',
  done: '/release-ready --merge'
}

// Column Configuration
export const COLUMN_CONFIG: Record<IssueStatus, { title: string; color: string; eccCmd: string }> = {
  backlog: { title: 'Backlog', color: '#8e8b82', eccCmd: '/loop-reset' },
  in_progress: { title: 'In Progress', color: '#cc785c', eccCmd: '/loop-start' },
  blocked: { title: 'Blocked', color: '#d4a84b', eccCmd: '/harness-pause' },
  human_review: { title: 'Human Review', color: '#6b8ba4', eccCmd: '/quality-gate --verify' },
  done: { title: 'Done', color: '#7d9e7d', eccCmd: '/release-ready --merge' }
}

// Priority Configuration
export const PRIORITY_CONFIG: Record<Priority, { label: string; color: string; icon: string }> = {
  critical: { label: 'Critical', color: '#b85c4d', icon: 'flame' },
  high: { label: 'High', color: '#d4a84b', icon: 'chevrons-up' },
  medium: { label: 'Medium', color: '#6b8ba4', icon: 'minus' },
  low: { label: 'Low', color: '#8e8b82', icon: 'chevron-down' }
}

// ECC Profile Configuration
export const PROFILE_CONFIG: Record<ECCProfile, { label: string; color: string; skills: string[] }> = {
  frontend: { label: 'Frontend', color: '#7d9e7d', skills: ['vue', 'nuxt', 'css', 'testing', 'a11y'] },
  backend: { label: 'Backend', color: '#6b8ba4', skills: ['fastapi', 'prisma', 'docker', 'postgresql'] },
  security: { label: 'Security', color: '#b85c4d', skills: ['agent-shield', 'vuln-scan', 'auth-aaudit'] },
  refactor: { label: 'Refactor', color: '#cc785c', skills: ['ast-parser', 'complexity-check', 'test-coverage'] },
  debug: { label: 'Debug', color: '#d4a84b', skills: ['error-trace', 'log-analysis', 'reproduce'] },
  general: { label: 'General', color: '#8e8b82', skills: [] }
}

// Harness Configuration
export interface HarnessConfig {
  type: HarnessType
  name: string
  icon: string
  color: string
  available: boolean
}

export const HARNESS_CONFIGS: HarnessConfig[] = [
  { type: 'claude-code', name: 'Claude Code', icon: 'anthropic', color: '#D4A84B', available: true },
  { type: 'codex', name: 'Codex', icon: 'openai', color: '#7D9E7D', available: true },
  { type: 'cursor', name: 'Cursor', icon: 'cursor', color: '#6B8BA4', available: true },
  { type: 'opencode', name: 'OpenCode', icon: 'opencode', color: '#8C8279', available: false },
  { type: 'gemini', name: 'Gemini', icon: 'google', color: '#C67B4E', available: false }
]

// ============================================================================
// LLM Provider System
// ============================================================================

export type LLMAdapterType = 'api-chat' | 'api-responses' | 'cli' | 'local-safe-runner'
export type LLMCapability = 'chat' | 'code' | 'tool-use' | 'streaming' | 'vision' | 'cli'
export type LLMProviderStatus = 'configured' | 'missing_key' | 'unhealthy' | 'disabled' | 'unknown'

export interface LLMProvider {
  id: string
  name: string
  adapter: LLMAdapterType
  enabled: boolean
  configured: boolean
  status: LLMProviderStatus
  defaultModel: string | null
  capabilities: LLMCapability[]
  authType: 'api_key' | 'oauth' | 'cli_path' | 'none'
  authEnvVar: string | null
  maskedSecret: string | null
  healthStatus: 'healthy' | 'unhealthy' | 'unknown'
  lastChecked: string | null
  errorSummary: string | null
}

export interface LLMProviderConfig {
  enabled: boolean
  defaultModel: string | null
}

export interface LLMDefaults {
  providerId: string
  modelId: string
  harness: HarnessType
  maxRuntimeSeconds: number
  tokenBudget: number | null
  costBudget: number | null
  streamingLogs: boolean
}

export interface LLMModelsResponse {
  providerId: string
  models: string[]
}
