<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { ListChecks, Play } from 'lucide-vue-next'

const boardStore = useBoardStore()

onMounted(() => {
  if (!boardStore.columns.length) boardStore.fetchBoard()
})

const backlogIssues = computed(() =>
  boardStore.getColumnByStatus('backlog')?.issues ?? []
)

const handleQuickStart = (issueId: string) => {
  const issue = boardStore.getIssueById(issueId)
  if (issue) {
    boardStore.moveIssueWithUnlock(issueId, issue.status, 'in_progress', 0)
  }
}
</script>

<template>
  <section class="backlog-page">
    <header class="backlog-page__topbar">
      <div class="backlog-page__title">
        <span class="backlog-page__kicker">Workspace / DevFlow</span>
        <h1>Backlog</h1>
        <p>{{ backlogIssues.length }} issues ready to start</p>
      </div>
    </header>

    <div v-if="backlogIssues.length === 0" class="backlog-page__empty">
      <ListChecks :size="32" />
      <p>No backlog issues</p>
      <span>All issues have been picked up or the board is empty.</span>
    </div>

    <div v-else class="backlog-page__list">
      <div
        v-for="issue in backlogIssues"
        :key="issue.id"
        class="backlog-card"
      >
        <div class="backlog-card__header">
          <span class="backlog-card__key">{{ issue.key }}</span>
          <PriorityIndicator :priority="issue.priority" />
        </div>
        <h3 class="backlog-card__title">{{ issue.title }}</h3>
        <div class="backlog-card__meta">
          <span class="backlog-card__profile">{{ issue.profile || 'general' }}</span>
          <span v-if="issue.labels?.length" class="backlog-card__labels">
            {{ issue.labels.map((l: { name: string }) => l.name).join(', ') }}
          </span>
        </div>
        <button
          class="backlog-card__start"
          data-testid="start-issue"
          @click="handleQuickStart(issue.id)"
        >
          <Play :size="14" />
          Start
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.backlog-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
.backlog-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.backlog-page__title { display: flex; flex-direction: column; gap: 6px; }
.backlog-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.backlog-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.backlog-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }
.backlog-page__empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 60px 18px; color: var(--muted); text-align: center; }
.backlog-page__empty p { color: var(--ink); font-weight: 600; }
.backlog-page__list { display: flex; flex-direction: column; gap: 10px; }
.backlog-card {
  display: flex; flex-direction: column; gap: 8px;
  padding: 14px 16px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 10px;
  transition: border-color 150ms;
}
.backlog-card:hover { border-color: var(--primary); }
.backlog-card__header { display: flex; align-items: center; justify-content: space-between; }
.backlog-card__key { font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--primary); }
.backlog-card__title { color: var(--ink); font-size: 0.9375rem; font-weight: 600; }
.backlog-card__meta { display: flex; gap: 8px; color: var(--muted); font-size: 0.8125rem; }
.backlog-card__profile { font-family: var(--font-mono); text-transform: capitalize; }
.backlog-card__start {
  align-self: flex-start; display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--primary);
  color: var(--primary); background: transparent; font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: background 150ms, color 150ms;
}
.backlog-card__start:hover { background: var(--primary); color: var(--on-primary); }
</style>
