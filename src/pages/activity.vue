<script setup lang="ts">
import type { AuditLogEntry } from '~/types'
import { ClipboardList, Filter, RefreshCw } from 'lucide-vue-next'

const config = useRuntimeConfig()
const apiBase = config.public.apiBase

const entries = ref<AuditLogEntry[]>([])
const total = ref(0)
const isLoading = ref(true)
const activeFilter = ref<string | null>(null)
const page = ref(0)
const pageSize = 30

const actionFilters = [
  { value: null, label: 'All' },
  { value: 'dispatch', label: 'Dispatch' },
  { value: 'running', label: 'Running' },
  { value: 'review_required', label: 'Review' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'created', label: 'Created' },
]

const fetchLogs = async () => {
  isLoading.value = true
  try {
    const params = new URLSearchParams()
    params.set('limit', String(pageSize))
    params.set('offset', String(page.value * pageSize))
    if (activeFilter.value) params.set('action', activeFilter.value)

    const res = await fetch(`${apiBase}/audit-logs?${params}`)
    if (res.ok) {
      const data = await res.json()
      entries.value = data.entries
      total.value = data.total
    }
  } catch {
    // silent
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchLogs)

watch(activeFilter, () => {
  page.value = 0
  fetchLogs()
})

const totalPages = computed(() => Math.ceil(total.value / pageSize))

const getActionColor = (action: string) => {
  switch (action) {
    case 'dispatch': return 'var(--primary)'
    case 'running': return 'var(--amber)'
    case 'review_required': return 'var(--dusty-blue)'
    case 'completed': return 'var(--sage)'
    case 'cancelled': return 'var(--clay-red)'
    case 'created': return 'var(--primary)'
    default: return 'var(--muted)'
  }
}

const getResourceIcon = (resource: string) => {
  switch (resource) {
    case 'ecc_job': return 'terminal'
    case 'issue': return 'clipboard'
    default: return 'circle'
  }
}

const formatTime = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const formatDetails = (entry: AuditLogEntry) => {
  const parts: string[] = []
  if (entry.details.issueKey) parts.push(entry.details.issueKey as string)
  if (entry.details.command) parts.push((entry.details.command as string).split(' ')[0])
  if (entry.details.profile) parts.push(entry.details.profile as string)
  if (entry.changes.message) parts.push(String(entry.changes.message).slice(0, 60))
  return parts.join(' · ')
}
</script>

<template>
  <section class="activity-page">
    <header class="activity-page__topbar">
      <div class="activity-page__title">
        <span class="activity-page__kicker">Workspace / DevFlow</span>
        <h1>Activity Log</h1>
        <p>System audit trail — all dispatched jobs, status changes, and issue events</p>
      </div>
      <button class="activity-page__refresh" @click="fetchLogs" :disabled="isLoading">
        <RefreshCw :size="16" :class="{ spin: isLoading }" />
      </button>
    </header>

    <!-- Filters -->
    <div class="activity-page__filters">
      <button
        v-for="f in actionFilters"
        :key="f.value ?? 'all'"
        class="filter-btn"
        :class="{ 'filter-btn--active': activeFilter === f.value }"
        @click="activeFilter = f.value"
      >
        {{ f.label }}
      </button>
      <span class="filter-count">{{ total }} events</span>
    </div>

    <!-- Loading -->
    <div v-if="isLoading && entries.length === 0" class="activity-page__loading">
      <RefreshCw :size="20" class="spin" />
      Loading activity...
    </div>

    <!-- Empty -->
    <div v-else-if="entries.length === 0" class="activity-page__empty">
      <ClipboardList :size="32" />
      <p>No activity events</p>
      <span>Events appear here as jobs are dispatched and issues change status.</span>
    </div>

    <!-- Timeline -->
    <div v-else class="activity-timeline">
      <div
        v-for="entry in entries"
        :key="entry.id"
        class="timeline-item"
      >
        <div class="timeline-item__dot" :style="{ background: getActionColor(entry.action) }" />
        <div class="timeline-item__content">
          <div class="timeline-item__header">
            <span class="timeline-item__action" :style="{ color: getActionColor(entry.action) }">
              {{ entry.action }}
            </span>
            <span class="timeline-item__resource">{{ entry.resource }}</span>
            <span class="timeline-item__time">{{ formatTime(entry.timestamp) }}</span>
          </div>
          <div class="timeline-item__detail">
            {{ formatDetails(entry) }}
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="activity-page__pagination">
      <button
        class="page-btn"
        :disabled="page === 0"
        @click="page--; fetchLogs()"
      >
        Prev
      </button>
      <span class="page-info">{{ page + 1 }} / {{ totalPages }}</span>
      <button
        class="page-btn"
        :disabled="page >= totalPages - 1"
        @click="page++; fetchLogs()"
      >
        Next
      </button>
    </div>
  </section>
</template>

<style scoped>
.activity-page {
  display: flex; flex-direction: column; height: 100vh; min-width: 0;
  padding: 22px; gap: 18px; overflow-y: auto;
}
.activity-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.activity-page__title { display: flex; flex-direction: column; gap: 6px; }
.activity-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.activity-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.activity-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }
.activity-page__refresh {
  padding: 8px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--muted); cursor: pointer; transition: color 150ms;
}
.activity-page__refresh:hover { color: var(--ink); }

.activity-page__filters {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.filter-btn {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--muted); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.filter-btn:hover { border-color: var(--primary); color: var(--ink); }
.filter-btn--active {
  background: var(--primary); color: var(--on-primary); border-color: var(--primary);
}
.filter-count {
  margin-left: auto; color: var(--muted); font-size: 0.8125rem; font-family: var(--font-mono);
}

.activity-page__loading,
.activity-page__empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 60px 18px; color: var(--muted); text-align: center;
}
.activity-page__empty p { color: var(--ink); font-weight: 600; }

.activity-timeline {
  display: flex; flex-direction: column; gap: 2px;
  border-left: 2px solid var(--hairline); margin-left: 8px; padding-left: 20px;
}
.timeline-item {
  display: flex; align-items: flex-start; gap: 14px; position: relative;
  padding: 10px 0;
}
.timeline-item__dot {
  position: absolute; left: -27px; top: 14px;
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
}
.timeline-item__content { flex: 1; min-width: 0; }
.timeline-item__header {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.timeline-item__action {
  font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; text-transform: uppercase;
}
.timeline-item__resource {
  padding: 1px 6px; border-radius: 4px; font-size: 0.6875rem; font-weight: 500;
  background: var(--surface-soft); color: var(--muted);
}
.timeline-item__time {
  margin-left: auto; color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono);
}
.timeline-item__detail {
  margin-top: 4px; color: var(--ink); font-size: 0.875rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.activity-page__pagination {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding: 12px 0; border-top: 1px solid var(--hairline);
}
.page-btn {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--ink); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.page-btn:hover:not(:disabled) { border-color: var(--primary); }
.page-btn:disabled { opacity: 0.4; cursor: default; }
.page-info { color: var(--muted); font-size: 0.8125rem; font-family: var(--font-mono); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
