<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { Activity, Bot, ChevronRight, Columns3, GitPullRequest, Package, Terminal, TrendingUp } from 'lucide-vue-next'

const boardStore = useBoardStore()

onMounted(() => {
  boardStore.fetchBoard()
  boardStore.fetchJobs()
})

// KPI metrics
const activeRuns = computed(() =>
  boardStore.getAllIssues.filter(i => i.aiStatus === 'running').length
)
const reviewCount = computed(() =>
  boardStore.getColumnByStatus('human_review')?.issues.length ?? 0
)
const blockedCount = computed(() =>
  boardStore.getColumnByStatus('blocked')?.issues.length ?? 0
)
const doneCount = computed(() =>
  boardStore.getColumnByStatus('done')?.issues.length ?? 0
)

// Recent jobs (last 5)
const recentJobs = computed(() => boardStore.recentJobs)

// Review queue issues
const reviewQueueIssues = computed(() =>
  boardStore.getColumnByStatus('human_review')?.issues ?? []
)

// Navigation entries
const navCards = [
  {
    to: '/',
    icon: Columns3,
    label: 'Delivery Board',
    description: 'Kanban board with 5 workflow columns',
    meta: 'Board'
  },
  {
    to: '/lanes',
    icon: GitPullRequest,
    label: 'Worker Lanes',
    description: 'Agent roles and handoff routing',
    meta: 'Roles'
  },
  {
    to: '/command-center',
    icon: Terminal,
    label: 'Command Center',
    description: 'ECC jobs, logs, and dispatch',
    meta: 'ECC'
  },
  {
    to: '/runs',
    icon: Activity,
    label: 'Runs',
    description: 'Job history and filter by status',
    meta: 'Logs'
  },
  {
    to: '/deliveries',
    icon: Package,
    label: 'Deliveries',
    description: 'AI / handoff outputs — screenshots, diffs, PR links',
    meta: 'Outputs'
  }
]

const jobStatusColor = (status: string) => {
  switch (status) {
    case 'running': return 'var(--accent)'
    case 'review_required': return 'var(--amber)'
    case 'completed': return 'var(--sage)'
    case 'failed': return 'var(--clay-red)'
    default: return 'var(--muted)'
  }
}
</script>

<template>
  <div class="dashboard">
    <header class="dashboard__header">
      <div class="dashboard__title">
        <span class="dashboard__kicker">Workspace / DevFlow</span>
        <h1>Delivery Dashboard</h1>
        <p>交付總覽 — AI Delivery Board 控制平面</p>
      </div>
    </header>

    <!-- KPI Strip -->
    <div class="dashboard__kpis">
      <div class="kpi-tile">
        <span class="kpi-tile__label">Active Runs</span>
        <strong class="kpi-tile__value">{{ activeRuns }}</strong>
      </div>
      <div class="kpi-tile">
        <span class="kpi-tile__label">Review</span>
        <strong class="kpi-tile__value">{{ reviewCount }}</strong>
      </div>
      <div class="kpi-tile kpi-tile--warn">
        <span class="kpi-tile__label">Blocked</span>
        <strong class="kpi-tile__value">{{ blockedCount }}</strong>
      </div>
      <div class="kpi-tile">
        <span class="kpi-tile__label">Done</span>
        <strong class="kpi-tile__value">{{ doneCount }}</strong>
      </div>
    </div>

    <!-- Navigation cards -->
    <section class="dashboard__nav-cards">
      <RouterLink
        v-for="card in navCards"
        :key="card.to"
        :to="card.to"
        class="nav-card"
      >
        <div class="nav-card__icon">
          <component :is="card.icon" :size="22" />
        </div>
        <div class="nav-card__body">
          <span class="nav-card__meta">{{ card.meta }}</span>
          <strong class="nav-card__label">{{ card.label }}</strong>
          <span class="nav-card__desc">{{ card.description }}</span>
        </div>
        <ChevronRight :size="16" class="nav-card__arrow" />
      </RouterLink>
    </section>

    <!-- Bottom grid: Recent Jobs + Review Queue -->
    <div class="dashboard__bottom">
      <!-- Recent Jobs -->
      <section class="dashboard__jobs">
        <div class="dashboard__section-header">
          <TrendingUp :size="15" />
          <h2>Recent Jobs</h2>
          <RouterLink to="/runs" class="dashboard__section-link">View all</RouterLink>
        </div>
        <div v-if="recentJobs.length === 0" class="dashboard__empty">
          No jobs yet — move an issue to In Progress to trigger a run.
        </div>
        <ul v-else class="job-list">
          <li
            v-for="job in recentJobs"
            :key="job.id"
            class="job-item"
          >
            <span class="job-item__status" :style="{ background: jobStatusColor(job.status) }" />
            <span class="job-item__profile">{{ job.profile }}</span>
            <span class="job-item__harness">{{ job.harness }}</span>
            <span class="job-item__status-text">{{ job.status }}</span>
            <span class="job-item__time">
              {{ new Date(job.updated_at).toLocaleTimeString() }}
            </span>
          </li>
        </ul>
      </section>

      <!-- Review Queue -->
      <section class="dashboard__review">
        <div class="dashboard__section-header">
          <Bot :size="15" />
          <h2>Review Queue</h2>
          <RouterLink to="/" class="dashboard__section-link">Open board</RouterLink>
        </div>
        <div v-if="reviewQueueIssues.length === 0" class="dashboard__empty">
          No items in review queue.
        </div>
        <ul v-else class="review-list">
          <li
            v-for="issue in reviewQueueIssues.slice(0, 5)"
            :key="issue.id"
            class="review-item"
          >
            <span class="review-item__key">{{ issue.key }}</span>
            <span class="review-item__title">{{ issue.title }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 2rem 2.5rem;
  height: 100%;
  overflow-y: auto;
  background: var(--canvas);
}

.dashboard__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.dashboard__kicker {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-weight: 500;
}

.dashboard__title h1 {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--ink);
  margin: 0.25rem 0 0;
  letter-spacing: -0.02em;
}

.dashboard__title p {
  font-size: 0.85rem;
  color: var(--muted);
  margin: 0;
}

/* KPI Strip */
.dashboard__kpis {
  display: flex;
  gap: 1px;
  background: var(--hairline);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--hairline);
}

.kpi-tile {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 1rem 1.25rem;
  background: var(--surface-card);
}

.kpi-tile--warn {
  background: color-mix(in srgb, var(--clay-red) 8%, var(--surface-card));
}

.kpi-tile__label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  font-weight: 500;
}

.kpi-tile__value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.03em;
  line-height: 1;
}

/* Navigation cards */
.dashboard__nav-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

.nav-card {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
  cursor: pointer;
}

.nav-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
}

.nav-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  flex-shrink: 0;
}

.nav-card__body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.nav-card__meta {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  font-weight: 500;
}

.nav-card__label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--ink);
}

.nav-card__desc {
  font-size: 0.75rem;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-card__arrow {
  color: var(--muted);
  margin-left: auto;
  flex-shrink: 0;
}

/* Bottom grid */
.dashboard__bottom {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.dashboard__section-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  color: var(--muted);
}

.dashboard__section-header h2 {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--body);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.dashboard__section-link {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}

.dashboard__empty {
  font-size: 0.8rem;
  color: var(--muted);
  padding: 1rem 0;
}

.dashboard__jobs,
.dashboard__review {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}

/* Job list */
.job-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.job-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
}

.job-item__status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.job-item__profile {
  font-weight: 600;
  color: var(--ink);
  font-size: 0.75rem;
}

.job-item__harness {
  color: var(--muted);
  font-size: 0.75rem;
}

.job-item__status-text {
  color: var(--body);
  font-size: 0.75rem;
  margin-left: auto;
}

.job-item__time {
  color: var(--muted);
  font-size: 0.7rem;
}

/* Review list */
.review-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.review-item {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.8rem;
}

.review-item__key {
  font-weight: 600;
  color: var(--accent);
  font-size: 0.75rem;
  flex-shrink: 0;
}

.review-item__title {
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>