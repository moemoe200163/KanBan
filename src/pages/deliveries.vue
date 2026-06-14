<script setup lang="ts">
import { onMounted, watch } from 'vue'
import {
  Box,
  ExternalLink,
  FileText,
  Filter,
  Image as ImageIcon,
  Package,
  RefreshCw,
  Search,
  Tag,
  X,
} from 'lucide-vue-next'
import { useDeliveries } from '~/composables/useDeliveries'

const {
  items,
  types,
  sources,
  isLoading,
  error,
  query,
  selectedType,
  selectedSource,
  filtered,
  refresh,
} = useDeliveries()

onMounted(refresh)
watch([selectedType, selectedSource, query], () => { /* server-side filter happens via refresh */ void refresh() })

const formatDate = (iso: string): string => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const iconFor = (type: string) => {
  if (type === 'screenshot' || type.startsWith('image')) return ImageIcon
  if (type === 'pr_link') return ExternalLink
  if (type === 'test_log' || type === 'diff_summary' || type === 'command_output') return FileText
  return Box
}

const statusColor = (status: string | null) => {
  if (!status) return 'var(--muted)'
  switch (status) {
    case 'done': return 'var(--sage)'
    case 'in_progress': return 'var(--primary)'
    case 'human_review': return 'var(--dusty-blue)'
    case 'blocked': return 'var(--clay-red)'
    case 'backlog': return 'var(--muted)'
    default: return 'var(--ink)'
  }
}

const openIssue = (issueId: string) => {
  // Issues page would need a detail query; for now route to /
  // (kanban board). Front-end can later wire this to a real detail view.
  window.location.href = `/?issue=${issueId}`
}

const openPathOrUrl = (url: string | null) => {
  if (!url) return
  if (url.startsWith('http')) window.open(url, '_blank', 'noopener')
}
</script>

<template>
  <section class="deliveries-page">
    <header class="deliveries-page__topbar">
      <div class="deliveries-page__title">
        <span class="deliveries-page__kicker">Workspace / DevFlow</span>
        <h1>Deliveries</h1>
        <p>AI / handoff / completion outputs — screenshots, diffs, test results, PR links</p>
      </div>
      <button class="icon-btn" @click="refresh" :disabled="isLoading" title="Refresh">
        <RefreshCw :size="16" :class="{ spin: isLoading }" />
      </button>
    </header>

    <!-- Filter bar -->
    <div class="deliveries-page__toolbar">
      <div class="search-wrap">
        <Search :size="14" />
        <input v-model="query" type="text" class="search-input" placeholder="Search by title, summary, or issue…" />
      </div>
      <div class="filter-group">
        <span class="filter-group__label"><Filter :size="11" /> Type</span>
        <button
          class="chip"
          :class="{ 'chip--active': selectedType === null }"
          @click="selectedType = null"
        >All</button>
        <button
          v-for="t in types"
          :key="t"
          class="chip"
          :class="{ 'chip--active': selectedType === t }"
          @click="selectedType = selectedType === t ? null : t"
        >{{ t }}</button>
      </div>
      <div class="filter-group">
        <span class="filter-group__label"><Tag :size="11" /> Source</span>
        <button
          class="chip"
          :class="{ 'chip--active': selectedSource === null }"
          @click="selectedSource = null"
        >All</button>
        <button
          v-for="s in sources"
          :key="s"
          class="chip"
          :class="{ 'chip--active': selectedSource === s }"
          @click="selectedSource = selectedSource === s ? null : s"
        >{{ s }}</button>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="error" class="deliveries-page__error">
      {{ error }}
      <button @click="error = null" class="icon-btn"><X :size="14" /></button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading && items.length === 0" class="deliveries-page__loading">
      <RefreshCw :size="20" class="spin" /> Loading deliveries…
    </div>

    <!-- Empty -->
    <div v-else-if="filtered.length === 0" class="deliveries-page__empty">
      <Package :size="36" />
      <p>No deliveries yet</p>
      <span>Deliveries appear when AI runs, handoffs complete, or PRs are linked to an issue.</span>
    </div>

    <!-- Table -->
    <div v-else class="deliveries-table">
      <div class="deliveries-table__head">
        <div class="cell cell--issue">Issue</div>
        <div class="cell cell--title">Artifact</div>
        <div class="cell cell--type">Type</div>
        <div class="cell cell--source">Source</div>
        <div class="cell cell--created">Created</div>
        <div class="cell cell--summary">Summary</div>
      </div>
      <div class="deliveries-table__body">
        <button
          v-for="d in filtered"
          :key="d.id"
          class="deliveries-table__row"
          @click="d.pathOrUrl ? openPathOrUrl(d.pathOrUrl) : openIssue(d.issueId)"
        >
          <div class="cell cell--issue">
            <span v-if="d.issueKey" class="issue-key">{{ d.issueKey }}</span>
            <span v-else class="issue-key issue-key--missing">?</span>
            <span v-if="d.issueTitle" class="issue-title">{{ d.issueTitle }}</span>
            <span
              v-if="d.issueStatus"
              class="issue-status"
              :style="{ background: statusColor(d.issueStatus) }"
            >{{ d.issueStatus }}</span>
          </div>
          <div class="cell cell--title">
            <component :is="iconFor(d.artifactType)" :size="14" class="title-icon" />
            <span class="title-text">{{ d.title }}</span>
            <a
              v-if="d.pathOrUrl"
              :href="d.pathOrUrl"
              target="_blank"
              rel="noopener"
              class="title-link"
              @click.stop
              :title="d.pathOrUrl"
            >
              <ExternalLink :size="11" />
            </a>
          </div>
          <div class="cell cell--type">
            <span class="type-badge">{{ d.artifactType }}</span>
          </div>
          <div class="cell cell--source">
            <span v-if="d.source" class="source-text">{{ d.source }}</span>
            <span v-else class="source-text source-text--muted">—</span>
          </div>
          <div class="cell cell--created">{{ formatDate(d.createdAt) }}</div>
          <div class="cell cell--summary">
            <span v-if="d.summary" class="summary-text">{{ d.summary }}</span>
            <span v-else class="summary-text summary-text--muted">—</span>
            <span v-if="d.createdByName" class="summary-author">by {{ d.createdByName }}</span>
          </div>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.deliveries-page {
  display: flex; flex-direction: column; gap: 16px;
  padding: 24px 28px 40px; min-height: 100%;
}
.deliveries-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.deliveries-page__title { display: flex; flex-direction: column; gap: 6px; }
.deliveries-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.deliveries-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; margin: 0; }
.deliveries-page__title p { color: var(--muted); font-size: 0.875rem; margin: 0; }

.deliveries-page__toolbar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 12px 14px; background: var(--surface-soft);
  border: 1px solid var(--hairline); border-radius: 12px;
}
.search-wrap {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 8px; padding: 6px 10px; min-width: 240px; color: var(--muted);
}
.search-wrap input { border: none; background: transparent; outline: none; color: var(--ink); font-size: 0.875rem; width: 100%; }
.filter-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.filter-group__label {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.6875rem; text-transform: uppercase;
  color: var(--muted); font-family: var(--font-mono); letter-spacing: 0.04em;
}
.chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--surface); border: 1px solid var(--hairline);
  color: var(--muted); font-size: 0.75rem; cursor: pointer; transition: all 150ms;
}
.chip:hover { color: var(--ink); border-color: var(--primary); }
.chip--active { background: var(--primary); color: white; border-color: var(--primary); }

.deliveries-page__error {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; background: var(--clay-red); color: white;
  border-radius: 8px; font-size: 0.875rem;
}
.deliveries-page__loading,
.deliveries-page__empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 60px 20px; color: var(--muted);
  border: 1px dashed var(--hairline); border-radius: 12px; text-align: center;
}
.deliveries-page__empty p { color: var(--ink); font-weight: 600; font-size: 1.05rem; margin: 4px 0 0; }

.deliveries-table {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; overflow: hidden;
}
.deliveries-table__head,
.deliveries-table__row {
  display: grid;
  grid-template-columns: 1.4fr 2fr 0.9fr 0.9fr 1.1fr 2fr;
  gap: 12px; padding: 10px 14px; align-items: center;
}
.deliveries-table__head {
  background: var(--surface-soft); border-bottom: 1px solid var(--hairline);
  font-size: 0.6875rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); font-family: var(--font-mono);
}
.deliveries-table__body { display: flex; flex-direction: column; }
.deliveries-table__row {
  background: transparent; border: none; border-bottom: 1px solid var(--hairline);
  text-align: left; cursor: pointer; transition: background 150ms;
  font: inherit; color: inherit; width: 100%;
}
.deliveries-table__row:last-child { border-bottom: none; }
.deliveries-table__row:hover { background: var(--surface-soft); }

.cell { min-width: 0; }
.cell--issue { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.issue-key {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 600;
  background: var(--surface-soft); color: var(--ink);
  padding: 1px 6px; border-radius: 4px;
}
.issue-key--missing { color: var(--clay-red); background: rgba(204, 0, 0, 0.08); }
.issue-title { color: var(--ink); font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issue-status {
  color: white; font-size: 0.625rem; padding: 1px 6px; border-radius: 4px;
  font-family: var(--font-mono); text-transform: uppercase; font-weight: 700;
}

.cell--title { display: flex; align-items: center; gap: 6px; }
.title-icon { color: var(--primary); flex-shrink: 0; }
.title-text {
  color: var(--ink); font-size: 0.875rem; font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}
.title-link {
  color: var(--muted); padding: 2px 4px; border-radius: 4px;
  display: inline-flex; align-items: center;
}
.title-link:hover { color: var(--primary); background: var(--surface-soft); }

.type-badge {
  display: inline-block; font-family: var(--font-mono);
  font-size: 0.6875rem; padding: 2px 8px; border-radius: 4px;
  background: var(--surface-soft); color: var(--ink);
  border: 1px solid var(--hairline);
}

.source-text { font-family: var(--font-mono); font-size: 0.75rem; color: var(--ink); }
.source-text--muted { color: var(--muted); }

.cell--created { color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono); }

.cell--summary { display: flex; flex-direction: column; gap: 2px; }
.summary-text { color: var(--ink); font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.summary-text--muted { color: var(--muted); }
.summary-author { color: var(--muted); font-size: 0.6875rem; font-family: var(--font-mono); }

@media (max-width: 920px) {
  .deliveries-table__head { display: none; }
  .deliveries-table__row {
    grid-template-columns: 1fr;
    gap: 4px; padding: 12px 14px;
  }
}

.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: 1px solid var(--hairline);
  border-radius: 6px; color: var(--ink); cursor: pointer;
  text-decoration: none; transition: all 150ms;
}
.icon-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.icon-btn:disabled { opacity: 0.4; cursor: default; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
