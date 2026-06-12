<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useBoardListStore } from '~/stores/boardList'
import { useNotificationsStore } from '~/stores/notifications'
import { useDarkMode } from '~/composables/useDarkMode'
import { useRecentJobs } from '~/composables/useRecentJobs'
import {
  Activity,
  Archive,
  BarChart3,
  Bell,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleDot,
  ClipboardList,
  Columns3,
  GitPullRequest,
  LayoutDashboard,
  ListChecks,
  Moon,
  Package,
  Radio,
  Settings,
  ShieldCheck,
  Square,
  Sun,
  Terminal,
  Webhook,
  ClipboardCheck
} from 'lucide-vue-next'

const boardStore = useBoardStore()
const boardListStore = useBoardListStore()
const notificationsStore = useNotificationsStore()
const { isDark, toggleDark } = useDarkMode()
const router = useRouter()
const route = useRoute()
const isCollapsed = ref(false)

const emit = defineEmits<{ collapsed: [value: boolean]; navigate: [] }>()

watch(isCollapsed, (val) => emit('collapsed', val), { immediate: true })

// -------------------------------------------------------------------------
// Board selector
//
// The list of boards comes from /api/v1/boards (Issue.distinct(board_id)
// on the backend). We hydrate on mount and on every login change. The
// selector only renders when we actually have something to choose from,
// so logged-out visitors and single-board deployments keep the old,
// single-board sidebar untouched.
// -------------------------------------------------------------------------
onMounted(() => {
  void boardListStore.fetchBoards()
})

const onSelectBoard = (event: Event) => {
  const target = event.target as HTMLSelectElement | null
  if (!target) return
  const nextId = boardListStore.setActive(target.value)
  target.value = nextId
  // Refetch the board so the columns refresh. The board store reads
  // activeBoardId from boardListStore inside fetchBoard, so we don't
  // have to thread the id through.
  void boardStore.fetchBoard()
}

// Auto-collapse to icon rail on tablet widths
onMounted(() => {
  const mq = window.matchMedia('(max-width: 920px)')
  const handleMQ = (e: MediaQueryListEvent | MediaQueryList) => {
    if (e.matches) isCollapsed.value = true
  }
  handleMQ(mq)
  mq.addEventListener('change', handleMQ)
})

const navItems = computed(() => [
  { id: 'board', icon: Columns3, label: 'Board', meta: 'Issues', to: '/' },
  { id: 'command-center', icon: Terminal, label: 'Command Center', meta: 'ECC', to: '/command-center' },
  { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard', meta: 'Delivery', to: '/dashboard' },
  { id: 'agents', icon: Bot, label: 'Agents', meta: 'Runners', to: '/agents' },
  { id: 'lanes', icon: GitPullRequest, label: 'Lanes', meta: 'Roles', to: '/lanes' },
  { id: 'runtime', icon: Radio, label: 'Runtime', meta: 'Workers', to: '/runtime' },
  { id: 'backlog', icon: ListChecks, label: 'Backlog', meta: 'Triage', to: '/backlog' },
  { id: 'runs', icon: Activity, label: 'Runs', meta: 'Logs', to: '/runs' },
  {
    id: 'reviews',
    icon: ClipboardCheck,
    label: 'Cycle Reviews',
    meta: pendingCycleCount.value > 0 ? `${pendingCycleCount.value} pending` : 'Pending',
    to: '/reviews'
  },
  { id: 'uploads', icon: Archive, label: 'Uploads', meta: 'Files', to: '/artifacts' },
  { id: 'deliveries', icon: Package, label: 'Deliveries', meta: 'Outputs', to: '/deliveries' },
  { id: 'webhooks', icon: Webhook, label: 'Webhooks', meta: 'Events', to: '/settings/webhooks' },
  { id: 'analytics', icon: BarChart3, label: 'Analytics', meta: 'Flow', to: '/analytics' },
  { id: 'activity', icon: ClipboardList, label: 'Activity Log', meta: 'Audit', to: '/activity' },
  { id: 'settings', icon: Settings, label: 'Settings', meta: 'System', to: '/settings' }
])

const activeNav = computed(() => {
  const path = route.path
  if (path === '/') return 'board'
  if (path === '/dashboard') return 'dashboard'
  const match = navItems.value.find(item => item.to !== '/' && path.startsWith(item.to))
  return match?.id ?? 'board'
})

const navigate = (to: string) => {
  router.push(to)
  emit('navigate')
}

// Bell → /notifications. We deliberately do NOT open a drawer (per
// task spec: drawer would crowd the sidebar). Click goes straight to
// the inbox page. A `markAllRead` on navigate is tempting but
// erases the "needs review" signal — leave that to the page.
const unreadCount = computed(() => notificationsStore.unreadCount)
const goToNotifications = () => {
  router.push('/notifications')
  emit('navigate')
}

// Recent jobs feed
const { start: startRecentJobs, stop: stopRecentJobs } = useRecentJobs()

onMounted(() => {
  startRecentJobs()
})

onUnmounted(() => {
  stopRecentJobs()
})

// "Show archived" toggle. Persisted to localStorage so the operator
// doesn't have to flip it every page load. The store's fetchBoard
// reads the same localStorage key, so the two stay in sync.
const SHOW_ARCHIVED_KEY = 'devflow:showArchived'
const showArchived = ref(false)
try {
  if (typeof window !== 'undefined') {
    showArchived.value = localStorage.getItem(SHOW_ARCHIVED_KEY) === '1'
  }
} catch {
  // localStorage unavailable (SSR, sandboxed) — default to off.
}
watch(showArchived, (val) => {
  try {
    if (typeof window !== 'undefined') {
      localStorage.setItem(SHOW_ARCHIVED_KEY, val ? '1' : '0')
      // Tell the board store to re-fetch so the toggle takes
      // effect without a full page reload.
      const store = useBoardStore()
      void store.fetchBoard()
    }
  } catch {
    // ignore
  }
})

// Cycle-review pending count. Polled separately from the board
// store so the sidebar can keep its number fresh even when the
// operator is on a page that doesn't otherwise watch the board.
const pendingCycleCount = ref(0)
let pendingCountTimer: ReturnType<typeof setInterval> | null = null

// Bell badge: shows the unread count. The store hydrates from
// localStorage lazily, but we want the bell to render with the
// persisted value on the first paint — kick hydrate() in onMounted.
onMounted(() => {
  notificationsStore.hydrate()
})

const refreshPendingCount = async () => {
  try {
    const config = useRuntimeConfig()
    const res = await $fetch<{ count: number }>(
      `${config.public.apiBase}/cycle-reports/pending/count`,
      { headers: authHeaders() },
    )
    pendingCycleCount.value = res.count
  } catch {
    // Silently swallow — the badge is non-critical, and the
    // endpoint requires auth which a logged-out visitor won't have.
  }
}

onMounted(() => {
  void refreshPendingCount()
  // Light polling: the board endpoint already broadcasts issue
  // changes; the count drifts slowly (only when a worker cycle
  // finishes), so 30 s is enough to feel live.
  pendingCountTimer = setInterval(refreshPendingCount, 30_000)
})

onUnmounted(() => {
  if (pendingCountTimer) clearInterval(pendingCountTimer)
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
      <button
        class="sidebar__bell"
        :class="{ 'sidebar__bell--has-unread': unreadCount > 0 }"
        :aria-label="unreadCount > 0 ? `Notifications (${unreadCount} unread)` : 'Notifications'"
        :title="unreadCount > 0 ? `${unreadCount} unread notification${unreadCount === 1 ? '' : 's'}` : 'Notifications'"
        data-testid="sidebar-bell"
        @click="goToNotifications"
      >
        <Bell :size="18" />
        <span
          v-if="unreadCount > 0"
          class="sidebar__bell-badge"
          data-testid="sidebar-bell-badge"
        >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
      </button>
    </div>

    <!-- Collapse toggle -->
    <button class="sidebar__collapse-btn" @click="toggleCollapse" aria-label="Toggle sidebar">
      <component :is="isCollapsed ? ChevronRight : ChevronDown" :size="16" />
    </button>

    <!-- Board selector — hidden when there's nothing to pick. Single
         boards, logged-out visitors, and a not-yet-hydrated list all
         keep the old single-board sidebar. -->
    <div
      v-show="boardListStore.boards.length > 1"
      class="sidebar__board-selector"
      :class="{ 'sidebar__board-selector--collapsed': isCollapsed }"
      data-testid="sidebar-board-selector"
    >
      <label
        v-show="!isCollapsed"
        class="sidebar__board-selector-label"
        for="sidebar-board-select"
      >
        Board
      </label>
      <select
        id="sidebar-board-select"
        class="sidebar__board-select"
        :class="{ 'sidebar__board-select--collapsed': isCollapsed }"
        :value="boardListStore.activeBoardId"
        :disabled="boardListStore.isLoading"
        :title="isCollapsed
          ? boardListStore.boards.find(b => b.id === boardListStore.activeBoardId)?.name ?? 'Board'
          : undefined"
        aria-label="Select board"
        data-testid="sidebar-board-select"
        @change="onSelectBoard"
      >
        <option
          v-for="board in boardListStore.boards"
          :key="board.id"
          :value="board.id"
        >
          {{ board.name }} ({{ board.issueCount }})
        </option>
      </select>
    </div>

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
            <strong>{{ pendingCycleCount }}</strong>
          </div>
          <div class="control-status__row">
            <GitPullRequest :size="15" />
            <span v-show="!isCollapsed">Blocked</span>
            <strong>{{ blockedCount }}</strong>
          </div>
          <label class="control-status__toggle" v-show="!isCollapsed">
            <input
              type="checkbox"
              v-model="showArchived"
            />
            <span>Show archived</span>
          </label>
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
  height: 100dvh;
  min-height: 0;
  width: var(--sidebar-w, 260px);
  padding: 18px 14px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  color: var(--sidebar-text);
  overflow: hidden;
  transition: width var(--duration-normal) var(--ease-out);
}

/* Icon rail mode: collapsed sidebar shows icons only */
.sidebar--collapsed .sidebar__content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.sidebar--collapsed .sidebar__section {
  align-items: center;
}

.sidebar--collapsed .sidebar__eyebrow,
.sidebar--collapsed .sidebar__heading {
  display: none;
}

.sidebar--collapsed .sidebar__nav {
  align-items: center;
}

.sidebar--collapsed .sidebar__nav-item {
  grid-template-columns: 1fr;
  justify-items: center;
  padding: 8px;
  min-height: 38px;
  width: 36px;
}

.sidebar--collapsed .sidebar__nav-label,
.sidebar--collapsed .sidebar__nav-meta {
  display: none;
}

.sidebar--collapsed .control-status {
  padding: 8px;
  align-items: center;
}

.sidebar--collapsed .control-status__row {
  grid-template-columns: 1fr;
  justify-items: center;
  min-height: 28px;
}

.sidebar--collapsed .control-status__row span {
  display: none;
}

.sidebar--collapsed .sidebar__footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  margin-top: auto;
  padding-top: 12px;
}

.sidebar--collapsed .harness-card {
  display: none;
}

.sidebar--collapsed .theme-button {
  justify-content: center;
  padding: 8px;
  min-height: 36px;
  width: 36px;
}

.sidebar--collapsed .theme-button span {
  display: none;
}

/* In collapsed (icon-rail) mode the bell still shows — it lives
   in the brand row, not the nav. Pull it center so the column
   stays balanced when the brand copy is hidden. */
.sidebar--collapsed .sidebar__bell {
  margin-left: 0;
}

/* Mobile: sidebar is shown via wrapper drawer — no hide needed */
@media (max-width: 640px) {
  .sidebar {
    width: 260px;
    display: flex;
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

.sidebar__bell {
  position: relative;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  margin-left: auto;
  color: var(--sidebar-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.sidebar__bell:hover {
  color: var(--sidebar-text);
  background: var(--sidebar-surface);
  border-color: var(--sidebar-border);
}

.sidebar__bell--has-unread {
  color: var(--sidebar-text);
}

.sidebar__bell-badge {
  position: absolute;
  top: -2px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--clay-red, #d04a3a);
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 0.625rem;
  font-weight: 600;
  line-height: 1;
  pointer-events: none;
  box-shadow: 0 0 0 2px var(--sidebar-bg);
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

/* Board selector — sits between the brand and the navigation so it
   reads as "which workspace am I in?" before the operator chooses
   where to go. */
.sidebar__board-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 18px;
  padding: 8px 10px;
  background: var(--sidebar-panel);
  border: 1px solid var(--sidebar-border);
  border-radius: 8px;
}

.sidebar__board-selector--collapsed {
  gap: 0;
  align-items: center;
  padding: 6px;
  margin-bottom: 12px;
}

.sidebar__board-selector-label {
  color: var(--sidebar-muted);
  font-family: var(--font-mono);
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sidebar__board-select {
  appearance: none;
  width: 100%;
  padding: 6px 28px 6px 8px;
  color: var(--sidebar-text);
  background: var(--sidebar-surface);
  background-image: linear-gradient(45deg, transparent 50%, var(--sidebar-muted) 50%),
                    linear-gradient(135deg, var(--sidebar-muted) 50%, transparent 50%);
  background-position: calc(100% - 14px) 50%, calc(100% - 9px) 50%;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
  border: 1px solid var(--sidebar-border);
  border-radius: 6px;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              background-color var(--duration-fast) var(--ease-out);
}

.sidebar__board-select:hover {
  border-color: var(--sidebar-muted);
}

.sidebar__board-select:focus {
  outline: none;
  border-color: var(--primary);
}

.sidebar__board-select:disabled {
  opacity: 0.5;
  cursor: wait;
}

/* In collapsed (icon-rail) mode the select only needs the icon
   affordance — strip the padding and let the background match the
   surrounding rail. */
.sidebar__board-select--collapsed {
  width: 36px;
  height: 32px;
  padding: 0;
  background-image: none;
  text-indent: -9999px;
  text-overflow: clip;
}

.sidebar__board-select option {
  color: var(--sidebar-text);
  background: var(--sidebar-bg);
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

.control-status__toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--sidebar-border);
  color: var(--sidebar-muted);
  font-size: 0.8125rem;
  cursor: pointer;
  user-select: none;
}
.control-status__toggle input {
  margin: 0;
  cursor: pointer;
}
.control-status__toggle:hover { color: var(--sidebar-text); }

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
