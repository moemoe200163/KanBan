<script setup lang="ts">
/**
 * ReviewRowActions — the per-row footer for the /reviews queue
 * and the all-view reviewed sub-section.
 *
 * Encapsulates the *two* leader flows that can land on a cycle
 * report:
 *
 * - **Review**: Approve (green) or Request changes (orange)
 *   against the report itself, with an optional comment. Hits
 *   ``POST /cycle-reports/{id}/review`` (see migration 0020).
 *
 * - **Verdict override** (Mark as pass / Fail / Block): the
 *   pre-existing ``PATCH /issues/{id}/cycle-reports/{id}``
 *   flow, kept as the leader's accept/reject of the *work
 *   product*. A report can carry both, so the two button groups
 *   sit side-by-side.
 *
 * Props are passed by parent so state (comment text, errors,
 * in-flight flags) stays in the page-level Map keyed by report
 * id; this component is purely a presentational + event-emitter
 * shell, which keeps it easy to reuse from IssueDetail.vue
 * later.
 */
import type { PendingCycleReport } from '~/types'

const props = defineProps<{
  report: PendingCycleReport
  reviewComment: string
  reviewError: string | null
  isSelfReview: boolean
  isReviewing: boolean
  isOverriding: boolean
}>()

const emit = defineEmits<{
  (e: 'update-review-comment', value: string): void
  (e: 'submit-review', decision: 'approved' | 'changes_requested'): void
  (e: 'override', verdict: 'pass' | 'fail' | 'blocked'): void
}>()
</script>

<template>
  <footer class="review-row__actions">
    <span class="review-row__author">
      by <strong>{{ props.report.authorName || 'unknown' }}</strong>
      · {{ props.report.createdAt ? new Date(props.report.createdAt).toLocaleString() : '' }}
    </span>

    <div class="review-row__buttons">
      <!-- Verdict override (existing flow). -->
      <button
        class="review-btn review-btn--pass"
        :disabled="props.isOverriding"
        :data-testid="`reviews-override-pass-${props.report.id}`"
        @click="emit('override', 'pass')"
      >
        Mark as pass
      </button>
      <button
        class="review-btn review-btn--fail"
        :disabled="props.isOverriding"
        :data-testid="`reviews-override-fail-${props.report.id}`"
        @click="emit('override', 'fail')"
      >
        Fail
      </button>
      <button
        class="review-btn review-btn--block"
        :disabled="props.isOverriding"
        :data-testid="`reviews-override-block-${props.report.id}`"
        @click="emit('override', 'blocked')"
      >
        Block
      </button>
    </div>
  </footer>

  <section class="review-row__review" data-testid="reviews-row-review">
    <div v-if="props.isSelfReview" class="review-row__self-hint">
      You authored this cycle report — another reviewer must sign off.
    </div>
    <template v-else>
      <textarea
        class="review-row__review-input"
        rows="2"
        placeholder="Optional comment for the worker (visible in the audit trail)…"
        :value="props.reviewComment"
        :disabled="props.isReviewing"
        :data-testid="`reviews-review-comment-${props.report.id}`"
        @input="emit('update-review-comment', ($event.target as HTMLTextAreaElement).value)"
      />
      <div class="review-row__review-buttons">
        <button
          class="review-btn review-btn--approve"
          :disabled="props.isReviewing"
          :data-testid="`reviews-review-approve-${props.report.id}`"
          @click="emit('submit-review', 'approved')"
        >
          Approve
        </button>
        <button
          class="review-btn review-btn--changes"
          :disabled="props.isReviewing"
          :data-testid="`reviews-review-changes-${props.report.id}`"
          @click="emit('submit-review', 'changes_requested')"
        >
          Request changes
        </button>
      </div>
      <p
        v-if="props.reviewError"
        class="review-row__review-error"
        :data-testid="`reviews-review-error-${props.report.id}`"
      >
        {{ props.reviewError }}
      </p>
    </template>
  </section>
</template>
