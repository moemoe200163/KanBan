<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { Check, RotateCcw } from 'lucide-vue-next'

const boardStore = useBoardStore()
const reasons = ref<Record<string, string>>({})

const latestJob = (issueId: string) => {
  return boardStore.jobs
    .filter(job => job.issue_id === issueId)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
}

const requestChanges = async (issueId: string) => {
  await boardStore.requestChanges(issueId, reasons.value[issueId]?.trim() || 'Review requested changes')
  reasons.value[issueId] = ''
}
</script>

<template>
  <section class="review-queue" data-testid="review-queue">
    <div class="review-queue__header">
      <div>
        <span class="review-queue__kicker">Review Queue</span>
        <strong>{{ boardStore.reviewQueueItems.length }} waiting</strong>
      </div>
    </div>

    <div v-if="boardStore.reviewQueueItems.length === 0" class="review-queue__empty">
      <svg class="review-queue__empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
      <span>Nothing in review. All clear.</span>
    </div>

    <div v-else class="review-queue__items">
      <article
        v-for="item in boardStore.reviewQueueItems"
        :key="item.id"
        class="review-queue__item"
        data-testid="review-item"
      >
        <button class="review-queue__summary" @click="boardStore.selectIssue(item)">
          <span class="review-queue__key">{{ item.key }}</span>
          <span class="review-queue__title">{{ item.title }}</span>
          <small>{{ latestJob(item.id)?.message || item.eccJobMessage || 'Awaiting human decision' }}</small>
        </button>

        <div class="review-queue__meta">
          <span>{{ item.priority }}</span>
          <span>{{ item.profile }}</span>
          <span v-if="latestJob(item.id)">{{ latestJob(item.id)?.status }}</span>
        </div>

        <label class="review-queue__reason">
          <input v-model="reasons[item.id]" type="text" placeholder="Optional reason" />
        </label>

        <div class="review-queue__actions">
          <button class="review-queue__approve" data-testid="review-approve" @click="boardStore.approveReview(item.id)">
            <Check :size="14" />
            <span>Approve</span>
          </button>
          <button class="review-queue__changes" data-testid="review-request-changes" @click="requestChanges(item.id)">
            <RotateCcw :size="14" />
            <span>Request changes</span>
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.review-queue {
  display: grid;
  gap: 10px;
  padding: 12px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.review-queue__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.review-queue__kicker {
  display: block;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
}

.review-queue__header strong {
  color: var(--ink);
  font-size: 0.95rem;
}

.review-queue__empty {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 0.84rem;
}

.review-queue__empty-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.review-queue__items {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 8px;
}

.review-queue__item {
  display: grid;
  gap: 8px;
  padding: 10px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.review-queue__summary {
  display: grid;
  gap: 3px;
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.review-queue__key {
  color: var(--dusty-blue);
  font-family: var(--font-mono);
  font-size: 0.74rem;
  font-weight: 800;
}

.review-queue__title {
  color: var(--ink);
  font-size: 0.86rem;
  font-weight: 700;
}

.review-queue__summary small {
  color: var(--muted);
  font-size: 0.76rem;
}

.review-queue__meta,
.review-queue__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.review-queue__meta span {
  padding: 2px 6px;
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.68rem;
  text-transform: uppercase;
}

.review-queue__reason input {
  width: 100%;
  padding: 8px 9px;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-size: 0.82rem;
}

.review-queue__approve,
.review-queue__changes {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 6px 9px;
  border-radius: 8px;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
}

.review-queue__approve {
  color: var(--on-primary);
  background: var(--sage);
  border: 1px solid var(--sage);
}

.review-queue__changes {
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
}
</style>
