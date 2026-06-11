<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useToast } from '~/composables/useToast'
import { authHeaders } from '~/utils/authHeaders'
import type { Issue, IssueStatus } from '~/types'
import { COLUMN_CONFIG } from '~/types'
import { Bot, Filter, Plus, Search, SlidersHorizontal, Wifi } from 'lucide-vue-next'

const boardStore = useBoardStore()
const toast = useToast()

const searchQuery = ref('')
const selectedStatus = ref<IssueStatus | 'all'>('all')
const selectedPriority = ref<'all' | 'critical' | 'high' | 'medium' | 'low'>('all')
const reviewQueueOpen = ref(false)

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
  const fromStatus = issue.status
  const key = issue.key
  boardStore.moveIssueWithUnlock(issueId, fromStatus, 'in_progress', 0)
  toast.add(
    `${key} moved to In Progress`,
    () => {
      boardStore.moveIssueWithUnlock(issueId, 'in_progress', fromStatus, 0)
    },
    'Undo'
  )
}

// Card-level archive / unarchive: optimistic, then call the
// backend. The board will re-fetch on its own once the next
// board query lands; we just kick it explicitly here so the
// archived card disappears without a polling delay.
const handleArchiveIssue = async (issueId: string) => {
  const issue = boardStore.getIssueById(issueId)
  if (!issue) return
  const key = issue.key
  try {
    const config = useRuntimeConfig()
    await $fetch(`${config.public.apiBase}/issues/${issueId}/archive`, {
      method: 'POST',
      headers: authHeaders(),
    })
    toast.add(`${key} archived`, undefined, 'OK')
    await boardStore.fetchBoard()
  } catch (err) {
    console.error('[archive] failed:', err)
    toast.add(`Failed to archive ${key}`, undefined, 'Dismiss')
  }
}

const handleUnarchiveIssue = async (issueId: string) => {
  const issue = boardStore.getIssueById(issueId)
  if (!issue) return
  const key = issue.key
  try {
    const config = useRuntimeConfig()
    await $fetch(`${config.public.apiBase}/issues/${issueId}/unarchive`, {
      method: 'POST',
      headers: authHeaders(),
    })
    toast.add(`${key} unarchived`, undefined, 'OK')
    await boardStore.fetchBoard()
  } catch (err) {
    console.error('[unarchive] failed:', err)
    toast.add(`Failed to unarchive ${key}`, undefined, 'Dismiss')
  }
}
</script>

<template>
  <section class="kanban-board">
    <!-- Compact single-row toolbar -->
    <header class="board-topbar">
      <h1 class="board-topbar__title">AI Delivery Board</h1>

      <div class="board-toolbar">
        <div class="board-toolbar__search">
          <Search :size="14" />
          <input v-model="searchQuery" type="search" placeholder="Search key, title, or label" />
        </div>

        <select v-model="selectedStatus" aria-label="Filter by status" class="board-toolbar__select">
          <option value="all">All</option>
          <option v-for="(config, status) in COLUMN_CONFIG" :key="status" :value="status">
            {{ config.title }}
          </option>
        </select>

        <select v-model="selectedPriority" aria-label="Filter by priority" class="board-toolbar__select">
          <option value="all">All priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <button v-if="searchQuery || selectedStatus !== 'all' || selectedPriority !== 'all'" class="ghost-btn" @click="clearFilters">
          <SlidersHorizontal :size="13" />
          Reset
        </button>
      </div>

      <div class="board-topbar__actions">
        <!-- Review Queue floating toggle -->
        <button
          v-if="reviewCount > 0"
          class="review-toggle"
          data-testid="review-queue-toggle"
          @click="reviewQueueOpen = !reviewQueueOpen"
        >
          <Bot :size="14" />
          <span>Review</span>
          <span class="review-badge">{{ reviewCount }}</span>
        </button>

        <button class="primary-action" data-testid="new-issue-open" @click="boardStore.openNewIssueModal()">
          <Plus :size="14" />
          <span>New Issue</span>
        </button>
      </div>
    </header>

    <!-- Review Queue panel (conditional) -->
    <Transition name="slide-down">
      <div v-if="reviewQueueOpen && reviewCount > 0" class="review-panel">
        <ReviewQueue />
      </div>
    </Transition>

    <!-- Board columns fill remaining height -->
    <div class="kanban-board__columns">
      <KanbanColumn
        v-for="column in filteredColumns"
        :key="column.id"
        :column="column"
        @card-click="handleCardClick"
        @drop="handleColumnDrop(column.id)"
        @retry="boardStore.retryMove"
        @start="handleStartIssue"
        @archive="handleArchiveIssue"
        @unarchive="handleUnarchiveIssue"
        @create="boardStore.createIssue($event, column.id)"
      />
    </div>

    <IssueDetail />
    <NewIssueModal />
    <ToastContainer />
  </section>
</template>

<style scoped>
.kanban-board {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 10px 12px;
  gap: 8px;
  overflow: hidden;
}

/* Compact single-row toolbar */
.board-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  min-height: 44px;
}

.board-topbar__title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
  flex-shrink: 0;
}

.board-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.board-toolbar__search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  min-height: 32px;
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
  font-size: 0.8rem;
}

.board-toolbar__select {
  min-height: 32px;
  max-width: 120px;
  color: var(--ink);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  padding: 0 8px;
  font-size: 0.8rem;
  cursor: pointer;
}

.ghost-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 5px 10px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
}

.board-topbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.primary-action {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 6px 12px;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 7px;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
}

.review-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 6px 12px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  border-radius: 7px;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.review-toggle:hover {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
}

.review-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  background: var(--accent);
  color: white;
  border-radius: 9px;
  font-size: 0.7rem;
  font-weight: 700;
}

/* Review panel */
.review-panel {
  flex-shrink: 0;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  overflow: hidden;
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: max-height 0.2s ease, opacity 0.2s ease;
  overflow: hidden;
}
.slide-down-enter-from,
.slide-down-leave-to {
  max-height: 0;
  opacity: 0;
}
.slide-down-enter-to,
.slide-down-leave-from {
  max-height: 300px;
  opacity: 1;
}

/* Board columns fill all remaining height */
.kanban-board__columns {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(260px, 300px);
  gap: 10px;
  flex: 1;
  min-height: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

@media (max-width: 760px) {
  .kanban-board {
    padding: 8px;
    gap: 6px;
  }

  .board-topbar {
    flex-wrap: wrap;
    gap: 6px;
  }

  .board-topbar__title {
    font-size: 0.9rem;
  }

  .board-toolbar {
    flex-wrap: wrap;
    gap: 4px;
  }

  .board-toolbar__select {
    max-width: 100px;
    font-size: 0.75rem;
  }

  .kanban-board__columns {
    flex-direction: column;
    overflow-x: hidden;
    overflow-y: auto;
    min-height: 300px;
    grid-auto-columns: none;
    grid-auto-flow: row;
  }
}
</style>
