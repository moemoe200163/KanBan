<script setup lang="ts">
/**
 * DevStats — compact record-count display for the Command Center.
 * Fetches from GET /api/v1/stats on mount and refreshes periodically.
 */

const config = useRuntimeConfig()
const counts = ref<Record<string, number>>({})
const error = ref<string | null>(null)

async function fetchStats() {
  try {
    const data = await $fetch<{ counts: Record<string, number> }>(
      `${config.public.apiBase}/stats`
    )
    counts.value = data.counts
    error.value = null
  } catch (err) {
    error.value = (err as Error)?.message || 'Failed to load stats'
  }
}

onMounted(fetchStats)
// Refresh every 30s
const interval = setInterval(fetchStats, 30_000)
onUnmounted(() => clearInterval(interval))

const items = computed(() => [
  { label: 'Issues', key: 'issues' },
  { label: 'Jobs', key: 'ecc_jobs' },
  { label: 'Handoffs', key: 'issue_handoffs' },
  { label: 'Audit', key: 'audit_logs' },
])
</script>

<template>
  <section class="dev-stats" data-testid="dev-stats">
    <header class="dev-stats__header">
      <span class="dev-stats__kicker">Database</span>
    </header>
    <p v-if="error" class="dev-stats__error">{{ error }}</p>
    <div v-else class="dev-stats__grid">
      <div v-for="item in items" :key="item.key" class="dev-stats__cell">
        <span class="dev-stats__value">{{ counts[item.key] ?? '—' }}</span>
        <span class="dev-stats__label">{{ item.label }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dev-stats {
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  padding: 12px 14px;
}
.dev-stats__header {
  margin-bottom: 8px;
}
.dev-stats__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
}
.dev-stats__grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.dev-stats__cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.dev-stats__value {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 1.1rem;
  font-weight: 700;
}
.dev-stats__label {
  color: var(--muted);
  font-size: 0.6875rem;
}
.dev-stats__error {
  color: var(--clay-red);
  font-size: 0.75rem;
}
</style>
