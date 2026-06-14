<script setup lang="ts">
import { useBoardStore } from '~/stores/board'

const boardStore = useBoardStore()
const route = useRoute()

onMounted(() => {
  boardStore.fetchBoard()
})

// Deep-link support: /?issue=<id> opens the IssueDetail panel.
// fetchBoard() is async, so we wait for isLoading to flip false before
// resolving the id → Issue mapping. Without this watcher, arriving from
// deliveries.vue's "open on board" link would land on a blank home page
// because the store has no issues yet at navigation time.
watch(
  () => boardStore.isLoading,
  (loading) => {
    if (loading) return
    const id = route.query.issue
    if (typeof id !== 'string' || !id) return
    const issue = boardStore.getIssueById(id)
    if (issue) boardStore.selectIssue(issue)
  },
  { immediate: true },
)
</script>

<template>
  <div class="board-page">
    <KanbanBoard />
  </div>
</template>

<style scoped>
.board-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--canvas);
}
</style>