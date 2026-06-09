<script setup lang="ts">
import { useBoardStore } from '~/stores/board'

const boardStore = useBoardStore()

// Fetch on mount (client-side)
onMounted(() => {
  boardStore.fetchBoard()
})
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