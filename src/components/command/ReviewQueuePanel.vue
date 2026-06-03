<script setup lang="ts">
import { computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { Eye, ThumbsUp, ThumbsDown } from 'lucide-vue-next'
import type { ECCDispatchJob } from '~/types'

const boardStore = useBoardStore()

const reviewJobs = computed<ECCDispatchJob[]>(() =>
  boardStore.jobs.filter(j => j.status === 'review_required')
)

const approve = async (job: ECCDispatchJob) => {
  const issue = boardStore.getIssueById(job.issue_id)
  if (issue) {
    await boardStore.approveReview(issue.id)
  } else {
    // Fallback: synthesize an issue so the job status is at least updated
    await boardStore.updateECCJobStatus(
      boardStore._synthIssue(job),
      'completed',
      'Approved via Review Queue'
    )
  }
}

const requestChanges = async (job: ECCDispatchJob) => {
  const issue = boardStore.getIssueById(job.issue_id)
  if (issue) {
    await boardStore.requestChanges(issue.id, 'Changes requested via Review Queue')
  } else {
    await boardStore.updateECCJobStatus(
      boardStore._synthIssue(job),
      'failed',
      'Changes requested via Review Queue'
    )
  }
}
</script>

<template>
  <section class="review-queue">
    <header class="review-queue__header">
      <Eye :size="18" />
      <h3>Review Required</h3>
      <span v-if="reviewJobs.length" class="review-queue__badge">{{ reviewJobs.length }}</span>
    </header>

    <div v-if="reviewJobs.length === 0" class="review-queue__empty">
      <Eye :size="24" />
      <p>Nothing waiting for review</p>
      <span>Jobs in <code>review_required</code> status will appear here</span>
    </div>

    <ul v-else class="review-queue__list">
      <li v-for="job in reviewJobs" :key="job.id" class="review-queue__item" :data-testid="`review-${job.id}`">
        <div class="review-queue__meta">
          <span class="review-queue__key">{{ job.issue_key }}</span>
          <span class="review-queue__command">{{ job.command }}</span>
          <span class="review-queue__profile">{{ job.profile }} · {{ job.harness }}</span>
        </div>
        <div class="review-queue__actions">
          <button
            class="review-queue__btn review-queue__btn--approve"
            :data-testid="`review-approve-${job.id}`"
            @click="approve(job)"
          >
            <ThumbsUp :size="14" />
            Approve
          </button>
          <button
            class="review-queue__btn review-queue__btn--reject"
            :data-testid="`review-reject-${job.id}`"
            @click="requestChanges(job)"
          >
            <ThumbsDown :size="14" />
            Request changes
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.review-queue {
  display: flex;
  flex-direction: column;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  overflow: hidden;
}
.review-queue__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  color: var(--ink);
  background: var(--surface-soft);
  border-bottom: 1px solid var(--hairline);
}
.review-queue__header h3 {
  font-family: var(--font-display);
  font-size: 0.9375rem;
  font-weight: 700;
}
.review-queue__badge {
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  color: var(--on-primary);
  background: var(--dusty-blue);
  border-radius: 10px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
}
.review-queue__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 28px 18px;
  color: var(--muted);
  text-align: center;
}
.review-queue__empty p {
  color: var(--ink);
  font-weight: 600;
  font-size: 0.875rem;
}
.review-queue__empty span {
  font-size: 0.75rem;
}
.review-queue__empty code {
  font-family: var(--font-mono);
  color: var(--dusty-blue);
}
.review-queue__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  list-style: none;
  margin: 0;
}
.review-queue__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-left: 3px solid var(--dusty-blue);
  border-radius: 8px;
}
.review-queue__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.review-queue__key {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  font-weight: 600;
}
.review-queue__command {
  overflow: hidden;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-queue__profile {
  color: var(--muted);
  font-size: 0.6875rem;
}
.review-queue__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.review-queue__btn {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms ease-out, color 150ms ease-out;
}
.review-queue__btn--approve {
  color: var(--sage);
  background: transparent;
  border: 1px solid var(--sage);
}
.review-queue__btn--approve:hover {
  color: var(--on-primary);
  background: var(--sage);
}
.review-queue__btn--reject {
  color: var(--clay-red);
  background: transparent;
  border: 1px solid var(--clay-red);
}
.review-queue__btn--reject:hover {
  color: var(--on-primary);
  background: var(--clay-red);
}
</style>
