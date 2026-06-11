<script setup lang="ts">
import type { Issue } from '~/types'
import { PRIORITY_CONFIG, PROFILE_CONFIG } from '~/types'
import { AlertCircle, Bot, GitBranch, GitPullRequest, Link2, RotateCcw } from 'lucide-vue-next'

interface Props {
  issue: Issue
}

const props = defineProps<Props>()

const emit = defineEmits<{
  select: [issue: Issue]
  retry: [issueId: string]
  start: [issueId: string]
}>()

const priorityConfig = computed(() => PRIORITY_CONFIG[props.issue.priority])
const profileConfig = computed(() => PROFILE_CONFIG[props.issue.profile])
const isPending = computed(() => props.issue.moveStatus === 'pending')
const isFailed = computed(() => props.issue.moveStatus === 'failed')
const dependencyCount = computed(() => (props.issue.dependencies ?? []).length)

const ciStatusConfig = computed(() => {
  if (!props.issue.ciStatus) return null
  return {
    pending: { label: 'CI pending', className: 'issue-card__ci--pending' },
    passed: { label: 'CI passed', className: 'issue-card__ci--passed' },
    failed: { label: 'CI failed', className: 'issue-card__ci--failed' }
  }[props.issue.ciStatus]
})

const aiLabel = computed(() => {
  if (isPending.value) return 'Confirming'
  if (isFailed.value) return 'Move failed'
  if (props.issue.eccJobStatus === 'queued') return 'Job queued'
  if (props.issue.eccJobStatus === 'running') return 'Job running'
  if (props.issue.eccJobStatus === 'review_required') return 'Needs review'
  if (props.issue.eccJobStatus === 'failed') return 'Job failed'
  if (props.issue.eccJobStatus === 'cancelled') return 'Cancelled'
  if (props.issue.aiStatus === 'running') return 'AI running'
  if (props.issue.aiStatus === 'error') return 'AI error'
  return null
})

const handleDragStart = (event: DragEvent) => {
  if (isPending.value || isFailed.value) {
    event.preventDefault()
    return
  }
  event.dataTransfer?.setData('text/plain', props.issue.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

const handleRetry = (event: Event) => {
  event.stopPropagation()
  emit('retry', props.issue.id)
}

const handleStart = (event: Event) => {
  event.stopPropagation()
  emit('start', props.issue.id)
}
</script>

<template>
  <article
    class="issue-card"
    data-testid="issue-card"
    :class="{
      'issue-card--running': issue.aiStatus === 'running',
      'issue-card--blocked': issue.status === 'blocked',
      'issue-card--pending': isPending,
      'issue-card--failed': isFailed || issue.aiStatus === 'error'
    }"
    :style="{ '--priority-color': priorityConfig.color }"
    :draggable="!isPending && !isFailed"
    @click="emit('select', issue)"
    @dragstart="handleDragStart"
  >
    <div class="issue-card__top">
      <span class="issue-card__key">
        <svg
          v-if="issue.parentId"
          class="issue-card__epic-marker"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          title="Subtask of an epic"
        >
          <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
          <rect x="9" y="3" width="6" height="4" rx="1" />
          <path d="M9 13h6M9 17h4" />
        </svg>
        {{ issue.key }}
      </span>
      <span class="issue-card__priority" :title="priorityConfig.label">
        {{ priorityConfig.label }}
      </span>
    </div>

    <h3 class="issue-card__title">{{ issue.title }}</h3>

    <div class="issue-card__chips">
      <span class="issue-card__chip" :style="{ color: profileConfig.color }">
        {{ profileConfig.label }}
      </span>
      <span v-if="issue.harnessType" class="issue-card__chip issue-card__chip--mono">
        {{ issue.harnessType }}
      </span>
      <span v-if="dependencyCount" class="issue-card__chip issue-card__chip--icon">
        <Link2 :size="12" />
        {{ dependencyCount }}
      </span>
    </div>

    <div v-if="issue.labels.length" class="issue-card__labels">
      <LabelChip
        v-for="label in issue.labels.slice(0, 2)"
        :key="label.id"
        :label="label"
        size="sm"
      />
      <span v-if="issue.labels.length > 2" class="issue-card__more">+{{ issue.labels.length - 2 }}</span>
    </div>

    <div class="issue-card__footer">
      <AvatarStack :name="issue.assigneeName" :avatar-url="issue.assigneeAvatar" size="sm" />
      <div class="issue-card__signals">
        <button
          v-if="issue.status === 'backlog'"
          class="issue-card__start"
          data-testid="start-issue"
          title="Start issue"
          @click="handleStart"
        >
          Start
        </button>
        <span v-if="issue.storyPoints" class="issue-card__points">{{ issue.storyPoints }}pt</span>
        <span v-if="issue.prUrl" class="issue-card__signal" title="Pull request">
          <GitPullRequest :size="13" />
        </span>
        <span
          v-if="ciStatusConfig"
          class="issue-card__ci"
          :class="ciStatusConfig.className"
          :title="ciStatusConfig.label"
        />
      </div>
    </div>

    <div v-if="aiLabel" class="issue-card__execution">
      <Bot v-if="!isFailed" :size="14" />
      <AlertCircle v-else :size="14" />
      <span>{{ aiLabel }}</span>
      <span v-if="issue.eccJobId" class="issue-card__job-id">{{ issue.eccJobId }}</span>
      <button v-if="isFailed" class="issue-card__retry" title="Retry move" @click="handleRetry">
        <RotateCcw :size="13" />
      </button>
    </div>

    <div v-if="issue.status === 'blocked' && dependencyCount" class="issue-card__blocked-note">
      <GitBranch :size="13" />
      <span>Waiting on {{ dependencyCount }} dependenc{{ dependencyCount === 1 ? 'y' : 'ies' }}</span>
    </div>
  </article>
</template>

<style scoped>
.issue-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 156px;
  padding: 12px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-left: 4px solid var(--priority-color);
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
  cursor: grab;
  transition: transform var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}

.issue-card:hover {
  transform: translateY(-1px);
  border-color: var(--muted-soft);
  box-shadow: var(--shadow-md);
}

.issue-card:active {
  cursor: grabbing;
}

.issue-card--running {
  border-color: rgba(204, 120, 92, 0.5);
  border-left-color: var(--priority-color);
}

.issue-card--blocked {
  background: linear-gradient(180deg, rgba(212, 168, 75, 0.08), var(--surface-card) 42%);
}

.issue-card--pending {
  opacity: 0.72;
  cursor: wait;
}

.issue-card--failed {
  background: linear-gradient(180deg, rgba(184, 92, 77, 0.08), var(--surface-card) 44%);
}

.issue-card__top,
.issue-card__footer,
.issue-card__signals,
.issue-card__chips,
.issue-card__execution,
.issue-card__blocked-note {
  display: flex;
  align-items: center;
}

.issue-card__top {
  justify-content: space-between;
  gap: 8px;
}

.issue-card__key {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 700;
}

.issue-card__priority {
  overflow: hidden;
  max-width: 86px;
  color: var(--priority-color);
  font-size: 0.6875rem;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card__title {
  display: -webkit-box;
  min-height: 40px;
  overflow: hidden;
  color: var(--ink);
  font-size: 0.92rem;
  font-weight: 700;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.issue-card__chips {
  flex-wrap: wrap;
  gap: 6px;
}

.issue-card__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 22px;
  max-width: 120px;
  padding: 3px 7px;
  overflow: hidden;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card__chip--mono {
  color: var(--muted);
  font-family: var(--font-mono);
  font-weight: 600;
}

.issue-card__chip--icon {
  color: var(--muted);
}

.issue-card__labels {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  max-height: 24px;
  overflow: hidden;
}

.issue-card__more {
  color: var(--muted);
  font-size: 0.7rem;
  line-height: 20px;
}

.issue-card__footer {
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
}

.issue-card__signals {
  gap: 7px;
  color: var(--muted);
}

.issue-card__start {
  min-height: 24px;
  padding: 3px 8px;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 7px;
  font-size: 0.68rem;
  font-weight: 800;
  cursor: pointer;
}

.issue-card__points {
  padding: 2px 7px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 0.72rem;
}

.issue-card__signal {
  display: inline-flex;
}

.issue-card__ci {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--muted-soft);
}

.issue-card__ci--pending {
  background: var(--amber);
}

.issue-card__ci--passed {
  background: var(--sage);
}

.issue-card__ci--failed {
  background: var(--clay-red);
}

.issue-card__execution,
.issue-card__blocked-note {
  gap: 7px;
  min-height: 28px;
  padding: 6px 8px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 700;
}

.issue-card__execution {
  color: var(--primary-active);
}

.issue-card__job-id {
  overflow: hidden;
  max-width: 92px;
  margin-left: auto;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.66rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card__retry {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-left: auto;
  color: var(--clay-red);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  cursor: pointer;
}
</style>
