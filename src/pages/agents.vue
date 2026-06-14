<script setup lang="ts">
/**
 * /agents — Runtime execution matrix.
 *
 * Shows profile × harness execution state. Role management lives at /lanes.
 */

import { computed, onMounted } from 'vue'
import { useBoardStore } from '~/stores/board'
import { Circle, Loader2, XCircle } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

// Redirect legacy /agents?tab=roles to /lanes
if (route.query.tab === 'roles') {
  router.replace('/lanes')
}

const boardStore = useBoardStore()

// --- Runtime Matrix data ---

const profiles = ['frontend', 'backend', 'security', 'refactor', 'debug', 'general'] as const
const harnesses = ['claude-code', 'codex', 'cursor', 'opencode', 'gemini'] as const

onMounted(() => {
  if (!boardStore.columns.length) boardStore.fetchBoard()
})

const agentMatrix = computed(() => {
  return profiles.map(profile => ({
    profile,
    harnesses: harnesses.map(harness => {
      const jobs = boardStore.jobs.filter(j => j.profile === profile && j.harness === harness)
      const running = jobs.filter(j => j.status === 'running' || j.status === 'queued')
      const completed = jobs.filter(j => j.status === 'completed')
      const failed = jobs.filter(j => j.status === 'failed')
      return {
        harness,
        status: running.length > 0 ? 'running' as const : failed.length > 0 ? 'error' as const : 'idle' as const,
        totalJobs: jobs.length,
        running: running.length,
        completed: completed.length,
        failed: failed.length,
      }
    })
  }))
})

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'running': return Loader2
    case 'error': return XCircle
    default: return Circle
  }
}

const getStatusColor = (status: string) => {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'error': return 'var(--clay-red)'
    default: return 'var(--muted)'
  }
}
</script>

<template>
  <section class="agents-page">
    <header class="agents-page__topbar">
      <div class="agents-page__title">
        <span class="agents-page__kicker">Workspace / DevFlow</span>
        <h1>Agents</h1>
        <p>Profile × harness execution state</p>
      </div>
    </header>

    <!-- Runtime Matrix -->
    <div class="agents-page__matrix">
      <div class="agents-matrix">
        <div class="agents-matrix__header">
          <div class="agents-matrix__cell agents-matrix__cell--label"></div>
          <div v-for="harness in harnesses" :key="harness" class="agents-matrix__cell agents-matrix__cell--header">
            {{ harness }}
          </div>
        </div>
        <div v-for="row in agentMatrix" :key="row.profile" class="agents-matrix__row">
          <div class="agents-matrix__cell agents-matrix__cell--label">{{ row.profile }}</div>
          <div v-for="cell in row.harnesses" :key="cell.harness" class="agents-matrix__cell">
            <div class="agent-card" :class="{ 'agent-card--active': cell.status === 'running' }">
              <component
                :is="getStatusIcon(cell.status)"
                :size="16"
                :style="{ color: getStatusColor(cell.status) }"
                :class="{ spin: cell.status === 'running' }"
              />
              <span class="agent-card__count">{{ cell.totalJobs }}</span>
              <span v-if="cell.running" class="agent-card__running">{{ cell.running }} active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agents-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}

.agents-page__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.agents-page__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.agents-page__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.agents-page__title h1 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
}

.agents-page__title p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.9rem;
}

/* Matrix */
.agents-page__matrix {
  flex: 1;
  overflow-x: auto;
}

.agents-matrix {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  overflow: hidden;
}

.agents-matrix__header,
.agents-matrix__row {
  display: flex;
}

.agents-matrix__cell {
  flex: 1;
  min-width: 120px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--hairline);
  display: flex;
  align-items: center;
  justify-content: center;
}

.agents-matrix__cell--label {
  justify-content: flex-start;
  min-width: 100px;
  flex: 0 0 100px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink);
  text-transform: capitalize;
}

.agents-matrix__cell--header {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  background: var(--surface-soft);
}

.agents-matrix__row:last-child .agents-matrix__cell {
  border-bottom: none;
}

.agent-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-radius: 8px;
  min-width: 80px;
  transition: background 150ms;
}

.agent-card--active {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}

.agent-card__count {
  font-family: var(--font-mono);
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--ink);
}

.agent-card__running {
  font-size: 0.6875rem;
  color: var(--primary);
  font-weight: 600;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>