<script setup lang="ts">
/**
 * /board/epic/[id] — epic tree view for Mavis-style parent-child
 * relationships.
 *
 * The board already shows the parentId marker on every child card,
 * but the leader needs a single surface that:
 *   - names the epic and shows its description / status,
 *   - lists every child with progress (X / N done),
 *   - groups children by status so a glance tells you what's
 *     stuck, what's in flight, and what's done,
 *   - links the child cards back to the issue drawer.
 *
 * Fetches two endpoints:
 *   GET /api/v1/issues/{epicId}            — the epic itself
 *   GET /api/v1/issues/{epicId}/children  — every linked issue
 *
 * Both require auth (same as the rest of the issue API). We don't
 * 404 explicitly: if the epic is missing, ``epic.value`` is null and
 * the template renders a not-found state.
 */
import { authHeaders } from '~/utils/authHeaders'

interface Issue {
  id: string
  key: string
  title: string
  status: string
  priority: string
  parentId: string | null
  acceptanceCriteria: Array<{ id: string; text: string; done: boolean }>
  createdAt?: string
  updatedAt?: string
}

const route = useRoute()
const config = useRuntimeConfig()
const router = useRouter()
const epicId = computed(() => String(route.params.id ?? ''))

const epic = ref<Issue | null>(null)
const children = ref<Issue[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

const STATUS_ORDER = ['backlog', 'in_progress', 'blocked', 'human_review', 'done'] as const
const STATUS_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  in_progress: 'In Progress',
  blocked: 'Blocked',
  human_review: 'Human Review',
  done: 'Done',
}

const grouped = computed(() => {
  const buckets: Record<string, Issue[]> = {
    backlog: [], in_progress: [], blocked: [], human_review: [], done: [],
  }
  for (const child of children.value) {
    const key = STATUS_ORDER.includes(child.status as any) ? child.status : 'backlog'
    buckets[key].push(child)
  }
  return buckets
})

const progress = computed(() => {
  const total = children.value.length
  const done = children.value.filter(c => c.status === 'done').length
  const ratio = total === 0 ? 0 : Math.round((done / total) * 100)
  return { total, done, ratio }
})

const loadEpic = async () => {
  if (!epicId.value) return
  isLoading.value = true
  error.value = null
  try {
    const [epicRes, childrenRes] = await Promise.all([
      $fetch<Issue>(`${config.public.apiBase}/issues/${epicId.value}`, {
        headers: authHeaders(),
      }),
      $fetch<{ children: Issue[]; total: number }>(
        `${config.public.apiBase}/issues/${epicId.value}/children`,
        { headers: authHeaders() },
      ),
    ])
    epic.value = epicRes
    children.value = childrenRes.children ?? []
  } catch (err: any) {
    error.value = err instanceof Error ? err.message : 'Failed to load epic'
  } finally {
    isLoading.value = false
  }
}

const openIssue = (id: string) => {
  // For now we just navigate to the board. Wiring the issue
  // drawer to deep-link by id is a separate piece — the
  // store's openDetail(id) helper isn't quite there yet.
  router.push('/')
}

const formatDate = (ts: string | undefined) => {
  if (!ts) return ''
  try { return new Date(ts).toLocaleString() } catch { return ts }
}

onMounted(() => { void loadEpic() })
watch(() => epicId.value, () => { void loadEpic() })
</script>

<template>
  <div class="epic-page">
    <header class="epic-page__header">
      <button class="epic-page__back" @click="router.push('/')">
        ← Back to board
      </button>
      <h1 v-if="epic" class="epic-page__title">
        <span class="epic-page__key">{{ epic.key }}</span>
        {{ epic.title }}
      </h1>
      <p v-if="epic" class="epic-page__meta">
        <span :class="['epic-page__status', `epic-page__status--${epic.status}`]">
          {{ STATUS_LABELS[epic.status] || epic.status }}
        </span>
        · priority: <strong>{{ epic.priority }}</strong>
        · created {{ formatDate(epic.createdAt) }}
      </p>
    </header>

    <div v-if="error" class="epic-page__error">{{ error }}</div>
    <div v-else-if="isLoading" class="epic-page__loading">Loading epic…</div>

    <template v-else-if="epic">
      <!-- Progress bar — X/N done. The bar's width is bound to the
           ratio so the visual matches the count without a layout
           shift when children move between lanes. -->
      <section class="epic-page__progress">
        <div class="epic-page__progress-row">
          <h2>Progress</h2>
          <span class="epic-page__progress-count">
            {{ progress.done }} / {{ progress.total }} done
            <span v-if="progress.total > 0" class="epic-page__progress-pct">
              ({{ progress.ratio }}%)
            </span>
          </span>
        </div>
        <div class="epic-page__progress-bar">
          <div
            class="epic-page__progress-fill"
            :style="{ width: `${progress.ratio}%` }"
          />
        </div>
      </section>

      <!-- Grouped children. Each lane is collapsible: if a leader
           only cares about blocked, they hide the rest. The default
           is "all expanded" because there's no per-lane count that
           would justify a hide-on-empty policy. -->
      <section
        v-for="status in STATUS_ORDER"
        :key="status"
        class="epic-lane"
      >
        <header class="epic-lane__header">
          <h3>{{ STATUS_LABELS[status] }}</h3>
          <span class="epic-lane__count">{{ grouped[status].length }}</span>
        </header>
        <div v-if="grouped[status].length === 0" class="epic-lane__empty">
          No children in this lane.
        </div>
        <ul v-else class="epic-lane__list">
          <li
            v-for="child in grouped[status]"
            :key="child.id"
            class="epic-child"
            @click="openIssue(child.id)"
          >
            <div class="epic-child__row">
              <span class="epic-child__key">{{ child.key }}</span>
              <span class="epic-child__title">{{ child.title }}</span>
              <span class="epic-child__priority">{{ child.priority }}</span>
            </div>
            <div v-if="child.acceptanceCriteria?.length" class="epic-child__ac">
              <span
                v-for="ac in child.acceptanceCriteria"
                :key="ac.id"
                :class="['epic-child__ac-item', ac.done && 'epic-child__ac-item--done']"
              >
                {{ ac.done ? '✓' : '·' }} {{ ac.text }}
              </span>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <div v-else class="epic-page__not-found">
      <h2>Epic not found</h2>
      <p>No issue with id <code>{{ epicId }}</code> exists, or you don't have permission to view it.</p>
    </div>
  </div>
</template>

<style scoped>
.epic-page {
  padding: var(--space-5);
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.epic-page__header { display: flex; flex-direction: column; gap: var(--space-2); }
.epic-page__back {
  align-self: flex-start;
  font-size: var(--text-sm);
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  padding: 4px 10px;
  cursor: pointer;
  color: var(--ink-muted);
}
.epic-page__back:hover { color: var(--ink); }
.epic-page__title { font-size: var(--text-2xl); margin: 0; display: flex; gap: var(--space-3); align-items: center; }
.epic-page__key {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--ink-muted);
  background: var(--canvas-elevated);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}
.epic-page__meta { font-size: var(--text-sm); color: var(--ink-muted); margin: 0; }
.epic-page__status {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: rgba(140, 130, 121, 0.18);
  color: #6B6660;
}
.epic-page__status--backlog     { background: rgba(140, 130, 121, 0.18); color: #6B6660; }
.epic-page__status--in_progress { background: rgba(107, 139, 164, 0.18); color: #4A6680; }
.epic-page__status--done        { background: rgba(125, 158, 125, 0.18); color: #4F6F4F; }
.epic-page__status--human_review{ background: rgba(212, 168, 75, 0.18); color: #8A6B22; }
.epic-page__status--blocked     { background: rgba(184, 92, 77, 0.18); color: #B85C4D; }

.epic-page__loading, .epic-page__not-found, .epic-page__error {
  padding: var(--space-6);
  text-align: center;
  color: var(--ink-muted);
}
.epic-page__error { color: #B85C4D; }

.epic-page__progress {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background: var(--canvas-elevated);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.epic-page__progress-row { display: flex; justify-content: space-between; align-items: baseline; }
.epic-page__progress-row h2 { margin: 0; font-size: var(--text-lg); }
.epic-page__progress-count { font-size: var(--text-sm); color: var(--ink-muted); }
.epic-page__progress-pct { margin-left: 4px; color: var(--ink-faint); }
.epic-page__progress-bar {
  height: 8px;
  background: var(--canvas-subtle, rgba(0, 0, 0, 0.04));
  border-radius: 999px;
  overflow: hidden;
}
.epic-page__progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #7D9E7D 0%, #4F6F4F 100%);
  transition: width 0.3s var(--ease-out);
}

.epic-lane {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.epic-lane__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-bottom: 1px solid var(--hairline);
  padding-bottom: var(--space-2);
}
.epic-lane__header h3 { margin: 0; font-size: var(--text-sm); text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-muted); }
.epic-lane__count {
  font-size: var(--text-xs);
  background: var(--canvas-elevated);
  padding: 1px 8px;
  border-radius: 999px;
  font-weight: 600;
}
.epic-lane__empty {
  font-size: var(--text-sm);
  color: var(--ink-faint);
  padding: var(--space-2) 0;
  font-style: italic;
}
.epic-lane__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.epic-child {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--canvas-elevated);
  padding: var(--space-3);
  cursor: pointer;
  transition: border-color var(--duration-fast), background var(--duration-fast);
}
.epic-child:hover { border-color: var(--ink-muted); }
.epic-child__row { display: grid; grid-template-columns: 90px 1fr auto; gap: var(--space-3); align-items: center; }
.epic-child__key {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--ink-muted);
}
.epic-child__title { font-size: var(--text-sm); font-weight: 500; color: var(--ink); }
.epic-child__priority {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.epic-child__ac {
  margin-top: var(--space-2);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.epic-child__ac-item {
  font-size: var(--text-xs);
  background: var(--canvas-subtle, rgba(0,0,0,0.04));
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
}
.epic-child__ac-item--done {
  background: rgba(125, 158, 125, 0.18);
  color: #4F6F4F;
  text-decoration: line-through;
}
</style>
