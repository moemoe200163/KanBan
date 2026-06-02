<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import type { Issue, IssueStatus } from '~/types'
import { COLUMN_CONFIG } from '~/types'
import { Bot, Filter, Plus, Search, SlidersHorizontal, Wifi } from 'lucide-vue-next'

const boardStore = useBoardStore()

const searchQuery = ref('')
const selectedStatus = ref<IssueStatus | 'all'>('all')
const selectedPriority = ref<'all' | 'critical' | 'high' | 'medium' | 'low'>('all')

const filteredColumns = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  return boardStore.columns.map(col => ({
    ...col,
    issues: col.issues.filter(issue => {
      const matchesSearch = !query ||
        issue.title.toLowerCase().includes(query) ||
        issue.key.toLowerCase().includes(query) ||
        issue.labels.some(label => label.name.toLowerCase().includes(query))

      const matchesStatus = selectedStatus.value === 'all' || issue.status === selectedStatus.value
      const matchesPriority = selectedPriority.value === 'all' || issue.priority === selectedPriority.value

      return matchesSearch && matchesStatus && matchesPriority
    })
  }))
})

const totalFiltered = computed(() => filteredColumns.value.reduce((sum, col) => sum + col.issues.length, 0))
const activeRuns = computed(() => boardStore.getAllIssues.filter(issue => issue.aiStatus === 'running').length)
const reviewCount = computed(() => boardStore.getColumnByStatus('human_review')?.issues.length ?? 0)
const blockedCount = computed(() => boardStore.getColumnByStatus('blocked')?.issues.length ?? 0)

const clearFilters = () => {
  searchQuery.value = ''
  selectedStatus.value = 'all'
  selectedPriority.value = 'all'
}

const handleCardClick = (issue: Issue) => {
  boardStore.selectIssue(issue)
}

const handleDrop = (columnId: IssueStatus, issueId: string, newIndex: number) => {
  const fromColumn = boardStore.columns.find(col => col.issues.some(issue => issue.id === issueId))
  if (!fromColumn) return
  boardStore.moveIssueWithUnlock(issueId, fromColumn.id, columnId, newIndex)
}

const handleColumnDrop = (columnId: IssueStatus) => (issueId: string, newIndex: number) => {
  handleDrop(columnId, issueId, newIndex)
}

const handleStartIssue = (issueId: string) => {
  const issue = boardStore.getIssueById(issueId)
  if (!issue) return
  boardStore.moveIssueWithUnlock(issueId, issue.status, 'in_progress', 0)
}
</script>

<template>
  <section class="kanban-board">
    <header class="board-topbar">
      <div class="board-topbar__title">
        <span class="board-topbar__kicker">Workspace / DevFlow</span>
        <div>
          <h1>AI Delivery Board</h1>
          <p>{{ totalFiltered }} visible issues across {{ boardStore.columns.length }} workflow lanes</p>
        </div>
      </div>

      <div class="board-topbar__actions">
        <div class="connection-pill">
          <Wifi :size="15" />
          <span>Local control plane</span>
        </div>
        <button class="primary-action" data-testid="new-issue-open" @click="boardStore.openNewIssueModal()">
          <Plus :size="16" />
          <span>New Issue</span>
        </button>
      </div>
    </header>

    <div class="board-metrics">
      <div class="metric-tile">
        <span>Active Runs</span>
        <strong>{{ activeRuns }}</strong>
        <small>Agents currently executing</small>
      </div>
      <div class="metric-tile">
        <span>Human Review</span>
        <strong>{{ reviewCount }}</strong>
        <small>Waiting on decision</small>
      </div>
      <div class="metric-tile metric-tile--warn">
        <span>Blocked</span>
        <strong>{{ blockedCount }}</strong>
        <small>Dependency or runtime stop</small>
      </div>
      <div class="metric-tile">
        <span>Harness</span>
        <strong>{{ boardStore.activeHarness }}</strong>
        <small>Selected execution target</small>
      </div>
    </div>

    <div class="board-toolbar">
      <div class="board-toolbar__search">
        <Search :size="16" />
        <input v-model="searchQuery" type="search" placeholder="Search key, title, or label" />
      </div>

      <div class="board-toolbar__filters">
        <Filter :size="16" />
        <select v-model="selectedStatus" aria-label="Filter by status">
          <option value="all">All statuses</option>
          <option v-for="(config, status) in COLUMN_CONFIG" :key="status" :value="status">
            {{ config.title }}
          </option>
        </select>
        <select v-model="selectedPriority" aria-label="Filter by priority">
          <option value="all">All priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button class="ghost-action" @click="clearFilters">
          <SlidersHorizontal :size="15" />
          <span>Reset</span>
        </button>
      </div>

      <div class="board-toolbar__agent">
        <Bot :size="16" />
        <span>{{ boardStore.aiStatus === 'running' ? 'Agent running' : 'Agents ready' }}</span>
      </div>
    </div>

    <ReviewQueue />

    <div class="kanban-board__columns">
      <KanbanColumn
        v-for="column in filteredColumns"
        :key="column.id"
        :column="column"
        @card-click="handleCardClick"
        @drop="handleColumnDrop(column.id)"
        @retry="boardStore.retryMove"
        @start="handleStartIssue"
        @create="boardStore.createIssue($event, column.id)"
      />
    </div>

    <IssueDetail />
    <NewIssueModal />
  </section>
</template>

<style scoped>
.kanban-board {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-width: 0;
  padding: 22px;
  gap: 14px;
  overflow: hidden;
}

.board-topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.board-topbar__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.board-topbar__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.board-topbar h1 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.1;
}

.board-topbar p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.9rem;
}

.board-topbar__actions,
.board-toolbar__filters,
.board-toolbar__agent,
.connection-pill,
.primary-action,
.ghost-action {
  display: flex;
  align-items: center;
}

.board-topbar__actions {
  gap: 10px;
  flex-shrink: 0;
}

.connection-pill,
.primary-action,
.ghost-action,
.board-toolbar__agent {
  gap: 8px;
  min-height: 36px;
  padding: 8px 11px;
  border-radius: 8px;
  font-weight: 600;
}

.connection-pill {
  color: var(--sage-muted);
  background: rgba(125, 158, 125, 0.12);
  border: 1px solid rgba(125, 158, 125, 0.24);
}

.primary-action {
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  cursor: pointer;
}

.ghost-action {
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  cursor: pointer;
}

.board-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-tile {
  min-width: 0;
  padding: 10px 12px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.metric-tile span,
.metric-tile small {
  display: block;
  overflow: hidden;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-tile span {
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.metric-tile strong {
  display: block;
  margin: 2px 0;
  overflow: hidden;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 1.125rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-tile small {
  font-size: 0.6875rem;
}

.metric-tile--warn {
  border-color: rgba(212, 168, 75, 0.3);
}

.metric-tile--warn strong {
  color: var(--amber);
}

.board-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.board-toolbar__search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 200px;
  min-width: 0;
  min-height: 34px;
  padding: 0 10px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  color: var(--muted);
}

.board-toolbar__search input {
  width: 100%;
  min-width: 0;
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 0.8125rem;
}

.board-toolbar__filters {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
}

.board-toolbar select {
  min-height: 32px;
  max-width: 130px;
  color: var(--ink);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  padding: 0 8px;
  font-size: 0.8125rem;
}

.board-toolbar__agent {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 6px 10px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.8125rem;
}

.kanban-board__columns {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(280px, 320px);
  gap: 12px;
  min-height: 0;
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 8px;
}

@media (max-width: 1180px) {
  .board-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .kanban-board {
    height: 100vh;
    padding: 12px;
    gap: 10px;
    overflow-y: auto;
  }

  .board-topbar {
    flex-direction: column;
    gap: 8px;
  }

  .board-topbar h1 {
    font-size: 1.25rem;
  }

  .board-topbar p {
    display: none;
  }

  .board-topbar__actions {
    width: 100%;
    justify-content: flex-end;
  }

  .board-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }

  .metric-tile {
    padding: 8px 10px;
  }

  .metric-tile strong {
    font-size: 1rem;
  }

  .metric-tile small {
    display: none;
  }

  .board-toolbar {
    flex-wrap: nowrap;
    gap: 6px;
    padding: 6px 8px;
  }

  .board-toolbar__filters {
    display: none;
  }

  .board-toolbar__agent {
    display: none;
  }

  .kanban-board__columns {
    flex: none;
    min-height: 400px;
  }
}
</style>
