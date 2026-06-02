<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useDarkMode } from '~/composables/useDarkMode'
import { useRecentJobs } from '~/composables/useRecentJobs'
import {
  Activity,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  Columns3,
  GitPullRequest,
  ListChecks,
  Moon,
  Radio,
  Settings,
  ShieldCheck,
  Square,
  Sun,
  Terminal,
  Webhook
} from 'lucide-vue-next'

const boardStore = useBoardStore()
const { isDark, toggleDark } = useDarkMode()
const router = useRouter()
const route = useRoute()
const isCollapsed = ref(false)

const emit = defineEmits<{ collapsed: [value: boolean] }>()

watch(isCollapsed, (val) => emit('collapsed', val), { immediate: true })

const navItems = [
  { id: 'board', icon: Columns3, label: 'Board', meta: 'Kanban', to: '/' },
  { id: 'command-center', icon: Terminal, label: 'Command Center', meta: 'ECC', to: '/command-center' },
  { id: 'backlog', icon: ListChecks, label: 'Backlog', meta: 'Triage', to: '/backlog' },
  { id: 'agents', icon: Bot, label: 'Agents', meta: 'Runners', to: '/agents' },
  { id: 'runs', icon: Activity, label: 'Runs', meta: 'Logs', to: '/runs' },
  { id: 'analytics', icon: BarChart3, label: 'Analytics', meta: 'Flow', to: '/analytics' },
  { id: 'settings', icon: Settings, label: 'Settings', meta: 'System', to: '/settings' }
]

const activeNav = computed(() => {
  const path = route.path
  if (path === '/') return 'board'
  const match = navItems.find(item => item.to !== '/' && path.startsWith(item.to))
  return match?.id ?? 'board'
})

const navigate = (to: string) => {
  router.push(to)
}

// Recent jobs feed
const { start: startRecentJobs, stop: stopRecentJobs } = useRecentJobs()

onMounted(() => {
  startRecentJobs()
})

onUnmounted(() => {
  stopRecentJobs()
})

// Computed stats
const boardStats = computed(() => {
  const stats: Record<string, number> = {
    backlog: 0,
    in_progress: 0,
    blocked: 0,
    human_review: 0,
    done: 0
  }

  for (const col of boardStore.columns) {
    stats[col.id] = col.issues.length
  }

  return stats
})

const activeRuns = computed(() =>
  boardStore.columns.reduce(
    (count, col) => count + col.issues.filter(issue => issue.aiStatus === 'running').length,
    0
  )
)

const blockedCount = computed(() => boardStore.getColumnByStatus('blocked')?.issues.length ?? 0)
const reviewCount = computed(() => boardStore.getColumnByStatus('human_review')?.issues.length ?? 0)

// Job status display helpers
const getJobStatusIcon = (status: string) => {
  switch (status) {
    case 'running':
      return Circle
    case 'queued':
      return Activity
    case 'review_required':
      return GitPullRequest
    case 'completed':
      return ShieldCheck
    case 'failed':
    case 'cancelled':
      return Square
    default:
      return Circle
  }
}

const getJobStatusColor = (status: string) => {
  switch (status) {
    case 'running':
      return 'var(--primary)'
    case 'queued':
      return 'var(--amber)'
    case 'review_required':
      return 'var(--dusty-blue)'
    case 'completed':
      return 'var(--sage)'
    case 'failed':
    case 'cancelled':
      return 'var(--clay-red)'
    default:
      return 'var(--muted)'
  }
}

const formatTimeAgo = (isoString: string) => {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`

  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`

  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': isCollapsed }">
    <!-- Brand -->
    <div class="sidebar__brand">
      <div class="sidebar__mark">
        <CircleDot :size="22" />
      </div>
      <div class="sidebar__brand-copy" v-show="!isCollapsed">
        <strong>DevFlow</strong>
        <span>AI Control Plane</span>
      </div>
    </div>

    <!-- Collapse toggle -->
    <button class="sidebar__collapse-btn" @click="toggleCollapse" aria-label="Toggle sidebar">
      <component :is="isCollapsed ? ChevronRight : ChevronDown" :size="16" />
    </button>

    <div class="sidebar__content">
      <!-- Navigation -->
      <section class="sidebar__section">
        <p class="sidebar__eyebrow" v-show="!isCollapsed">Workspace</p>
        <nav class="sidebar__nav" aria-label="Primary">
          <button
            v-for="item in navItems"
            :key="item.id"
            class="sidebar__nav-item"
            :class="{ 'sidebar__nav-item--active': activeNav === item.id }"
            :title="item.label"
            @click="navigate(item.to)"
          >
            <component :is="item.icon" :size="18" />
            <span class="sidebar__nav-label" v-show="!isCollapsed">{{ item.label }}</span>
            <span class="sidebar__nav-meta" v-show="!isCollapsed">{{ item.meta }}</span>
          </button>
        </nav>
      </section>

      <!-- Control Plane Status -->
      <section class="sidebar__section">
        <h3 class="sidebar__heading" v-show="!isCollapsed">Control Plane</h3>
        <div class="control-status">
          <div class="control-status__row">
            <Radio :size="15" />
            <span v-show="!isCollapsed">Backend</span>
            <strong>Local</strong>
          </div>
          <div class="control-status__row">
            <Bot :size="15" />
            <span v-show="!isCollapsed">Active runs</span>
            <strong>{{ activeRuns }}</strong>
          </div>
          <div class="control-status__row">
            <ShieldCheck :size="15" />
            <span v-show="!isCollapsed">Review</span>
            <strong>{{ reviewCount }}</strong>
          </div>
          <div class="control-status__row">
            <GitPullRequest :size="15" />
            <span v-show="!isCollapsed">Blocked</span>
            <strong>{{ blockedCount }}</strong>
          </div>
        </div>
      </section>

      <!-- Board Stats -->
      <section class="sidebar__section" v-show="!isCollapsed">
        <h3 class="sidebar__heading">Board Stats</h3>
        <div class="board-stats">
          <div
            v-for="(count, status) in boardStats"
            :key="status"
            class="board-stats__row"
          >
            <span class="board-stats__label">{{ status.replace('_', ' ') }}</span>
            <span class="board-stats__count">{{ count }}</span>
          </div>
        </div>
      </section>

      <!-- Recent Jobs -->
      <section class="sidebar__section sidebar__section--jobs" v-show="!isCollapsed">
        <h3 class="sidebar__heading">Recent Jobs</h3>
        <div v-if="boardStore.isLoadingJobs" class="sidebar__loading">
          Loading...
        </div>
        <div v-else-if="boardStore.recentJobs.length === 0" class="sidebar__empty">
          No recent jobs
        </div>
        <div v-else class="job-list">
          <button
            v-for="job in boardStore.recentJobs"
            :key="job.id"
            class="job-item"
            data-testid="recent-job"
            @click="boardStore.openJob(job)"
          >
            <component
              :is="getJobStatusIcon(job.status)"
              :size="14"
              class="job-item__icon"
              :style="{ color: getJobStatusColor(job.status) }"
            />
            <div class="job-item__info">
              <span class="job-item__key">{{ job.issue_key }}</span>
              <span class="job-item__message">{{ job.message || 'No message yet' }}</span>
              <span class="job-item__time">{{ formatTimeAgo(job.updated_at) }}</span>
            </div>
            <span class="job-item__status">{{ job.status }}</span>
          </button>
        </div>
      </section>
    </div>

    <!-- Footer: Harness + Theme Toggle -->
    <div class="sidebar__footer">
      <div class="harness-card" v-show="!isCollapsed">
        <CheckCircle2 :size="16" />
        <div>
          <span>Harness</span>
          <strong>{{ boardStore.activeHarness }}</strong>
        </div>
      </div>
      <button class="theme-button" :title="isDark ? 'Light mode' : 'Dark mode'" @click="toggleDark">
        <Sun v-if="isDark" :size="18" />
        <Moon v-else :size="18" />
        <span v-show="!isCollapsed">{{ isDark ? 'Light' : 'Dark' }}</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: var(--sidebar-w, 260px);
  padding: 18px 14px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  color: var(--sidebar-text);
  overflow: hidden;
  transition: width var(--duration-normal) var(--ease-out);
}

.sidebar--collapsed .sidebar__content,
.sidebar--collapsed .sidebar__footer {
  display: none;
}

/* Mobile: hide sidebar completely */
@media (max-width: 640px) {
  .sidebar {
    display: none;
  }
}

/* Brand */
.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  margin-bottom: 22px;
}

.sidebar__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  color: var(--primary);
  background: rgba(204, 120, 92, 0.12);
  border: 1px solid rgba(204, 120, 92, 0.24);
  border-radius: 8px;
}

.sidebar__brand-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sidebar__brand-copy strong {
  font-family: var(--font-display);
  font-size: 1rem;
  line-height: 1.2;
}

.sidebar__brand-copy span {
  color: var(--sidebar-muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
}

/* Collapse button */
.sidebar__collapse-btn {
  position: absolute;
  top: 18px;
  right: -12px;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  color: var(--sidebar-muted);
  background: var(--sidebar-surface);
  border: 1px solid var(--sidebar-border);
  border-radius: 50%;
  cursor: pointer;
  z-index: 10;
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.sidebar__collapse-btn:hover {
  color: var(--sidebar-text);
  background: var(--sidebar-panel);
}

/* Content */
.sidebar__content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

.sidebar__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar__section--jobs {
  flex: 1;
  min-height: 0;
}

.sidebar__heading,
.sidebar__eyebrow {
  padding: 0 8px;
  color: var(--sidebar-muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Navigation */
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebar__nav-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 8px;
  color: var(--sidebar-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.sidebar__nav-item:hover,
.sidebar__nav-item--active {
  color: var(--sidebar-text);
  background: var(--sidebar-surface);
  border-color: var(--sidebar-border);
}

.sidebar__nav-item--active {
  box-shadow: inset 3px 0 0 var(--primary);
}

.sidebar__nav-label {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__nav-meta {
  color: var(--sidebar-subtle);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}

/* Control Status */
.control-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: var(--sidebar-panel);
  border: 1px solid var(--sidebar-border);
  border-radius: 8px;
}

.control-status__row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  color: var(--sidebar-muted);
  font-size: 0.8125rem;
}

.control-status__row strong {
  color: var(--sidebar-text);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
}

/* Board Stats */
.board-stats {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--sidebar-panel);
  border: 1px solid var(--sidebar-border);
  border-radius: 8px;
}

.board-stats__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 26px;
  padding: 0 4px;
}

.board-stats__label {
  color: var(--sidebar-muted);
  font-size: 0.8125rem;
  text-transform: capitalize;
}

.board-stats__count {
  color: var(--sidebar-text);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
}

/* Recent Jobs */
.job-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
}

.job-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px;
  text-align: left;
  background: var(--sidebar-surface);
  border: 1px solid var(--sidebar-border);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 150ms ease-out, background 150ms ease-out;
}

.job-item:hover {
  background: var(--sidebar-panel);
  border-color: var(--sidebar-muted);
}

.job-item__icon {
  flex-shrink: 0;
}

.job-item__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.job-item__key {
  color: var(--sidebar-text);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-item__time {
  color: var(--sidebar-subtle);
  font-size: 0.6875rem;
}

.job-item__message {
  overflow: hidden;
  color: var(--sidebar-muted);
  font-size: 0.6875rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-item__status {
  flex-shrink: 0;
  padding: 2px 6px;
  color: var(--sidebar-muted);
  background: var(--sidebar-panel);
  border-radius: 4px;
  font-size: 0.625rem;
  font-weight: 500;
  text-transform: uppercase;
}

.sidebar__loading,
.sidebar__empty {
  padding: 12px;
  color: var(--sidebar-muted);
  font-size: 0.8125rem;
  text-align: center;
  background: var(--sidebar-panel);
  border: 1px solid var(--sidebar-border);
  border-radius: 8px;
}

/* Footer */
.sidebar__footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
  padding-top: 12px;
}

.harness-card,
.theme-button {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 9px 10px;
  color: var(--sidebar-text);
  background: var(--sidebar-surface);
  border: 1px solid var(--sidebar-border);
  border-radius: 8px;
}

.harness-card div {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.harness-card span {
  color: var(--sidebar-muted);
  font-size: 0.6875rem;
}

.harness-card strong {
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.theme-button {
  justify-content: flex-start;
  cursor: pointer;
}
</style>
