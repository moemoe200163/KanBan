<script setup lang="ts">
import { onMounted } from 'vue'
import { useBoardStore } from '~/stores/board'
import JobDetailDrawer from '~/components/common/JobDetailDrawer.vue'
import JobMonitor from '~/components/command/JobMonitor.vue'
import ReviewQueuePanel from '~/components/command/ReviewQueuePanel.vue'
import DevStats from '~/components/command/DevStats.vue'

const boardStore = useBoardStore()

onMounted(async () => {
  await boardStore.fetchBoard()
  await boardStore.fetchJobs()
})
</script>

<template>
  <section class="command-center">
    <header class="command-center__topbar">
      <div class="command-center__title">
        <span class="command-center__kicker">Workspace / DevFlow</span>
        <div>
          <h1>Command Center</h1>
          <p>Dispatch ECC commands, monitor runs, and act on review-required jobs</p>
        </div>
      </div>
    </header>

    <div class="command-center__grid">
      <div class="command-center__col command-center__col--left">
        <CommandComposer />
        <ReviewQueuePanel class="command-center__review" />
      </div>
      <div class="command-center__col command-center__col--right">
        <DevStats />
        <JobMonitor />
      </div>
    </div>

    <JobDetailDrawer />
  </section>
</template>

<style scoped>
.command-center {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow: hidden;
}
.command-center__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}
.command-center__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.command-center__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
.command-center__title h1 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.1;
}
.command-center__title p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.9rem;
}
.command-center__grid {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(420px, 1.4fr);
  gap: 18px;
  flex: 1;
  min-height: 0;
}
.command-center__col {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 0;
  overflow-y: auto;
}
@media (max-width: 1024px) {
  .command-center__grid {
    grid-template-columns: 1fr;
  }
}
</style>
