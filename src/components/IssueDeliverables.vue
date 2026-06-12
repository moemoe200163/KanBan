<script setup lang="ts">
/**
 * IssueDeliverables — Plan D: list of artifacts attached to an issue.
 *
 * Renders inside IssueDetail's Worker tab pane. Fetches from
 * /api/v1/deliveries?issue_id=<id> on mount, on issue-id change,
 * and on demand via the explicit refresh button.
 *
 * The link column is rendered as a clickable "Play" or "Open"
 * button when the artifact is a build output with a /deliveries/
 * path, otherwise as a plain URL.
 */

import { computed, onMounted, ref, watch } from 'vue'
import { authHeaders } from '~/utils/authHeaders'

interface Props {
  issueId: string
  refreshKey?: number
}

const props = withDefaults(defineProps<Props>(), { refreshKey: 0 })

interface Artifact {
  id: string
  artifactType: string
  title: string
  pathOrUrl: string | null
  source: string | null
  sensitivity: string
  summary: string | null
  createdByName: string | null
  createdAt: string
  metadata?: Record<string, unknown>
}

const items = ref<Artifact[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function load() {
  if (!props.issueId) return
  isLoading.value = true
  error.value = null
  try {
    const config = useRuntimeConfig()
    const apiBase = config.public.apiBase as string
    const res = await $fetch<{ items: Artifact[]; count: number }>(
      `${apiBase}/deliveries`,
      {
        params: { issue_id: props.issueId },
        headers: authHeaders(),
      },
    )
    items.value = res.items ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load deliverables'
    items.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(load)
watch(() => props.issueId, load)
watch(() => props.refreshKey, load)

function refresh() {
  return load()
}

function iconFor(artifactType: string): string {
  switch (artifactType) {
    case 'build_output': return '🎮'
    case 'cycle_report': return '📋'
    case 'screenshot': return '📸'
    case 'pr_link': return '🔗'
    case 'diff_summary': return '📝'
    case 'test_log': return '🧪'
    case 'design_doc': return '📐'
    case 'file': return '📄'
    case 'command_output': return '⚙️'
    default: return '📦'
  }
}

function labelFor(artifact: Artifact): string {
  // Play button for playable build outputs.
  if (artifact.artifactType === 'build_output' && artifact.pathOrUrl) {
    return 'Play'
  }
  if (artifact.pathOrUrl) return 'Open'
  return 'View'
}

const grouped = computed(() => {
  const sorted = items.value.slice().sort((a, b) => {
    return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  })
  // Group by artifactType for stable rendering.
  const groups = new Map<string, Artifact[]>()
  for (const it of sorted) {
    if (!groups.has(it.artifactType)) groups.set(it.artifactType, [])
    groups.get(it.artifactType)!.push(it)
  }
  return Array.from(groups.entries())
})
</script>

<template>
  <section class="deliverables" data-testid="issue-deliverables">
    <header class="deliverables__head">
      <h4 class="deliverables__title">Deliverables</h4>
      <button
        type="button"
        class="deliverables__refresh"
        :disabled="isLoading"
        @click="refresh"
        data-testid="deliverables-refresh"
      >
        {{ isLoading ? 'Loading…' : 'Refresh' }}
      </button>
    </header>

    <p v-if="error" class="deliverables__error">{{ error }}</p>

    <p
      v-else-if="!isLoading && items.length === 0"
      class="deliverables__empty"
      data-testid="deliverables-empty"
    >
      No deliverables yet. Mavis will register build outputs here
      when complete.
    </p>

    <div v-else class="deliverables__list">
      <article
        v-for="[type, list] in grouped"
        :key="type"
        class="deliverables__group"
      >
        <h5 class="deliverables__group-title">
          <span class="deliverables__group-icon">{{ iconFor(type) }}</span>
          {{ type.replace(/_/g, ' ') }}
          <span class="deliverables__count">{{ list.length }}</span>
        </h5>
        <ul class="deliverables__items">
          <li
            v-for="artifact in list"
            :key="artifact.id"
            class="deliverables__item"
            data-testid="deliverable-row"
          >
            <div class="deliverables__item-main">
              <div class="deliverables__item-title">{{ artifact.title }}</div>
              <div v-if="artifact.summary" class="deliverables__item-summary">
                {{ artifact.summary }}
              </div>
              <div class="deliverables__item-meta">
                <span v-if="artifact.source">source: {{ artifact.source }}</span>
                <span v-if="artifact.createdByName">by {{ artifact.createdByName }}</span>
                <span>{{ new Date(artifact.createdAt).toLocaleString() }}</span>
              </div>
            </div>
            <a
              v-if="artifact.pathOrUrl"
              :href="artifact.pathOrUrl"
              target="_blank"
              rel="noopener"
              class="deliverables__item-action"
              :data-testid="`deliverable-open-${artifact.id}`"
            >
              {{ labelFor(artifact) }} ↗
            </a>
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>

<style scoped>
.deliverables {
  background: var(--panel, #1f2937);
  border: 1px solid var(--border, #374151);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}

.deliverables__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.deliverables__title {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #9ca3af);
  margin: 0;
}

.deliverables__refresh {
  background: var(--surface-2, #374151);
  color: var(--text, #f3f4f6);
  border: 1px solid var(--border, #4b5563);
  border-radius: 4px;
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  cursor: pointer;
}
.deliverables__refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.deliverables__error {
  color: var(--danger, #f87171);
  font-size: 0.8125rem;
  margin: 0.5rem 0 0;
}

.deliverables__empty {
  color: var(--text-muted, #9ca3af);
  font-size: 0.8125rem;
  font-style: italic;
  margin: 0.5rem 0 0;
}

.deliverables__list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.deliverables__group-title {
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted, #6b7280);
  margin: 0 0 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.deliverables__group-icon {
  font-size: 0.875rem;
}

.deliverables__count {
  background: var(--surface-2, #374151);
  color: var(--text-muted, #9ca3af);
  border-radius: 999px;
  padding: 0 0.375rem;
  font-size: 0.6875rem;
  font-weight: 500;
}

.deliverables__items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.deliverables__item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  background: var(--surface, #111827);
  border: 1px solid var(--border, #374151);
  border-radius: 6px;
  padding: 0.625rem 0.75rem;
}

.deliverables__item-main {
  flex: 1;
  min-width: 0;
}

.deliverables__item-title {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text, #f3f4f6);
}

.deliverables__item-summary {
  font-size: 0.8125rem;
  color: var(--text-muted, #9ca3af);
  margin-top: 0.125rem;
}

.deliverables__item-meta {
  font-size: 0.6875rem;
  color: var(--text-muted, #6b7280);
  margin-top: 0.25rem;
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.deliverables__item-action {
  background: var(--accent, #60a5fa);
  color: var(--accent-on, #0a0a0a);
  font-weight: 600;
  font-size: 0.8125rem;
  border-radius: 4px;
  padding: 0.375rem 0.75rem;
  text-decoration: none;
  white-space: nowrap;
  align-self: center;
  transition: filter 0.15s ease;
}
.deliverables__item-action:hover {
  filter: brightness(1.1);
}
</style>
