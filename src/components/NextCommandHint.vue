<script setup lang="ts">
/**
 * NextCommandHint — short copy that says "what should the human do
 * next" for the current delivery stage. Pure UI sugar on top of
 * `NEXT_COMMAND_HINTS` from the mapping module.
 *
 * Designed to sit just under the DeliveryStageBar in the
 * IssueDetail header.
 */
import { computed } from 'vue'
import type { IssueStatus } from '~/types'
import type { ECCDispatchJob } from '~/types'
import { NEXT_COMMAND_HINTS } from '~/lib/deliveryStageMapping'
import { useDeliveryStage } from '~/composables/useDeliveryStage'

interface Props {
  jobs: ReadonlyArray<ECCDispatchJob> | null | undefined
  issueStatus?: IssueStatus | null
}

const props = withDefaults(defineProps<Props>(), {
  issueStatus: null,
})

const jobsRef = computed(() => props.jobs ?? [])
const issueStatusRef = computed(() => props.issueStatus ?? null)
const state = useDeliveryStage({ jobs: jobsRef, issueStatus: issueStatusRef })

const hint = computed(() => {
  if (state.value.overlay) return NEXT_COMMAND_HINTS[state.value.overlay]
  return NEXT_COMMAND_HINTS[state.value.stage]
})

const tone = computed(() => {
  if (state.value.isFailed) return 'tone-failed'
  if (state.value.isCancelled) return 'tone-cancelled'
  if (state.value.stage === 'human_review') return 'tone-action'
  if (state.value.isTerminal) return 'tone-success'
  return 'tone-neutral'
})
</script>

<template>
  <div
    :class="['next-command-hint', tone]"
    data-testid="next-command-hint"
  >
    <span class="next-command-hint__label">Next:</span>
    <span class="next-command-hint__body">{{ hint }}</span>
  </div>
</template>

<style scoped>
.next-command-hint {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--font-body);
  font-size: 12px;
  line-height: 1.4;
  padding: 6px 10px;
  border-radius: 4px;
  background: var(--surface-cream-strong, #ded8cc);
  border: 1px solid var(--hairline, #ddd7ce);
  color: var(--body, #3f3b36);
}
.next-command-hint.tone-failed {
  background: color-mix(in srgb, var(--clay-red) 12%, var(--surface-card));
  border-color: color-mix(in srgb, var(--clay-red) 40%, var(--hairline));
  color: var(--clay-red-muted);
}
.next-command-hint.tone-cancelled {
  background: color-mix(in srgb, var(--muted-soft) 12%, var(--surface-card));
  border-color: color-mix(in srgb, var(--muted-soft) 40%, var(--hairline));
  color: var(--muted);
}
.next-command-hint.tone-action {
  background: color-mix(in srgb, var(--amber) 14%, var(--surface-card));
  border-color: color-mix(in srgb, var(--amber) 50%, var(--hairline));
  color: var(--amber-muted);
}
.next-command-hint.tone-success {
  background: color-mix(in srgb, var(--sage) 14%, var(--surface-card));
  border-color: color-mix(in srgb, var(--sage) 40%, var(--hairline));
  color: var(--sage-muted);
}
.next-command-hint__label {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 10px;
  flex-shrink: 0;
}
.next-command-hint__body {
  flex: 1;
}
</style>
