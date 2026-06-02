<script setup lang="ts">
import { computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { X } from 'lucide-vue-next'
import JobTimeline from '~/components/command/JobTimeline.vue'
import LiveLogPanel from '~/components/command/LiveLogPanel.vue'

const boardStore = useBoardStore()
const open = computed({
  get: () => boardStore.selectedJob !== null,
  set: (v) => { if (!v) boardStore.selectedJob = null }
})
const job = computed(() => boardStore.selectedJob)
const issueId = computed(() => job.value?.issue_id)
const close = () => { boardStore.selectedJob = null }
</script>

<template>
  <Teleport to="body">
    <transition name="drawer">
      <aside v-if="open && job" class="job-drawer" data-testid="job-detail-drawer">
        <header class="job-drawer__head">
          <div>
            <h2>{{ job.issue_key }}</h2>
            <p>{{ job.command }}</p>
          </div>
          <button class="job-drawer__close" @click="close">
            <X :size="16" />
          </button>
        </header>
        <section v-if="issueId" class="job-drawer__section">
          <h3>Live logs</h3>
          <LiveLogPanel :issue-id="issueId" />
        </section>
        <section class="job-drawer__section">
          <h3>Timeline</h3>
          <JobTimeline :events="job.events" />
        </section>
      </aside>
    </transition>
  </Teleport>
</template>

<style scoped>
.job-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(420px, 100vw);
  background: var(--surface-card);
  border-left: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: -8px 0 24px rgba(0,0,0,0.08);
}
.job-drawer__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.job-drawer__head h2 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  margin: 0;
}
.job-drawer__head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  word-break: break-word;
}
.job-drawer__close {
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  cursor: pointer;
  color: var(--muted);
}
.job-drawer__section h3 {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}
.drawer-enter-active,
.drawer-leave-active {
  transition: transform 200ms ease-out;
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}
</style>
