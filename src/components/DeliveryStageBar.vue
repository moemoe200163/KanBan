<script setup lang="ts">
/**
 * DeliveryStageBar — six-segment visual progress bar.
 *
 * Shows where in the safe-runner pipeline the issue is. Designed
 * to be readable at a glance both in the IssueDetail header and
 * as a mini bar on the Deliveries page.
 *
 * This is a **visual overlay** — it does not change backend
 * state. See `~/lib/deliveryStageMapping` for the full mapping
 * rationale (roadmap §16 / `docs/ui-roadmap-design-alignment.md`
 * §3.2).
 */
import { computed } from 'vue'
import type { IssueStatus } from '~/types'
import type { ECCDispatchJob } from '~/types'
import {
  DELIVERY_STAGES,
  DELIVERY_STAGE_LABELS,
  type DeliveryStage,
} from '~/lib/deliveryStageMapping'
import { useDeliveryStage } from '~/composables/useDeliveryStage'

interface Props {
  jobs: ReadonlyArray<ECCDispatchJob> | null | undefined
  issueStatus?: IssueStatus | null
  /** Compact mode: smaller bar, single-line labels (used in card lists). */
  variant?: 'full' | 'compact'
}

const props = withDefaults(defineProps<Props>(), {
  issueStatus: null,
  variant: 'full',
})

// Reactive wiring: useDeliveryStage takes a Ref but we want to accept
// plain props. Wrap in shallowRef-style so jobs changes propagate.
const jobsRef = computed(() => props.jobs ?? [])
const issueStatusRef = computed(() => props.issueStatus ?? null)
const state = useDeliveryStage({ jobs: jobsRef, issueStatus: issueStatusRef })

/**
 * Each stage's "fill" color when active. Pulled from the
 * design-system CSS vars in `main.css` so a dark-mode toggle
 * stays consistent.
 */
const STAGE_COLORS: Record<DeliveryStage, string> = {
  intake: 'var(--muted)',
  dispatch: 'var(--dusty-blue)',
  execute: 'var(--amber)',
  quality_gate: 'var(--primary)',
  human_review: 'var(--amber)',
  release_ready: 'var(--sage)',
}

const stageInfo = computed(() =>
  DELIVERY_STAGES.map((stage, i) => {
    const isPast = i + 1 < state.value.stageIndex
    const isCurrent = i + 1 === state.value.stageIndex
    const isFuture = i + 1 > state.value.stageIndex
    return {
      stage,
      label: DELIVERY_STAGE_LABELS[stage],
      color: STAGE_COLORS[stage],
      isPast,
      isCurrent,
      isFuture,
    }
  }),
)

const overlayClass = computed(() => {
  if (state.value.isFailed) return 'delivery-stage-bar--failed'
  if (state.value.isCancelled) return 'delivery-stage-bar--cancelled'
  if (state.value.isTerminal) return 'delivery-stage-bar--terminal'
  return ''
})
</script>

<template>
  <div
    :class="['delivery-stage-bar', `delivery-stage-bar--${variant}`, overlayClass]"
    role="progressbar"
    :aria-valuemin="1"
    :aria-valuemax="6"
    :aria-valuenow="state.stageIndex"
    :aria-valuetext="`Stage ${state.stageIndex} of 6: ${DELIVERY_STAGE_LABELS[state.stage]}`"
    data-testid="delivery-stage-bar"
  >
    <div
      v-for="(seg, i) in stageInfo"
      :key="seg.stage"
      :class="[
        'delivery-stage-bar__seg',
        seg.isPast && 'is-past',
        seg.isCurrent && 'is-current',
        seg.isFuture && 'is-future',
      ]"
      :style="{ '--seg-color': seg.color }"
    >
      <span
        v-if="variant === 'full'"
        class="delivery-stage-bar__num"
        :data-stage="i + 1"
      >{{ i + 1 }}</span>
      <span class="delivery-stage-bar__label">{{ seg.label }}</span>
      <span
        v-if="seg.isCurrent"
        class="delivery-stage-bar__now"
        :title="`Currently on ${seg.label}`"
      >●</span>
    </div>
    <span
      v-if="state.overlay"
      class="delivery-stage-bar__overlay-badge"
      :data-overlay="state.overlay"
    >
      {{ state.overlay === 'failed' ? 'Failed' : 'Cancelled' }}
    </span>
  </div>
</template>

<style scoped>
.delivery-stage-bar {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--space-1, 4px);
  font-family: var(--font-body);
  font-size: 11px;
  color: var(--muted);
  position: relative;
}

.delivery-stage-bar--compact {
  grid-template-columns: repeat(6, 1fr);
  font-size: 10px;
}

.delivery-stage-bar--failed {
  --overlay-color: var(--clay-red);
}
.delivery-stage-bar--cancelled {
  --overlay-color: var(--muted-soft);
}
.delivery-stage-bar--terminal {
  --overlay-color: var(--sage);
}

.delivery-stage-bar__seg {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 4px;
  border-radius: 4px;
  background: var(--surface-cream-strong, #ded8cc);
  border: 1px solid var(--hairline, #ddd7ce);
  position: relative;
  text-align: center;
  line-height: 1.2;
  min-height: 36px;
  transition: background 120ms ease, border-color 120ms ease;
}

.delivery-stage-bar--compact .delivery-stage-bar__seg {
  padding: 3px 2px;
  min-height: 22px;
  font-size: 9px;
}

.delivery-stage-bar__seg.is-past {
  background: var(--seg-color);
  color: var(--on-primary, #fff);
  border-color: var(--seg-color);
  opacity: 0.65;
}
.delivery-stage-bar__seg.is-current {
  background: var(--seg-color);
  color: var(--on-primary, #fff);
  border-color: var(--seg-color);
  font-weight: 600;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--seg-color) 30%, transparent);
}
.delivery-stage-bar__seg.is-future {
  background: transparent;
  color: var(--muted-soft, #8b8479);
  border-color: var(--hairline-soft, #e8e3dc);
}

.delivery-stage-bar__num {
  font-family: var(--font-mono);
  font-size: 9px;
  opacity: 0.7;
}
.delivery-stage-bar--compact .delivery-stage-bar__num {
  display: none;
}
.delivery-stage-bar__label {
  font-weight: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.delivery-stage-bar--compact .delivery-stage-bar__label {
  font-size: 9px;
  white-space: nowrap;
}

.delivery-stage-bar__now {
  position: absolute;
  top: -4px;
  right: -4px;
  font-size: 8px;
  color: var(--seg-color);
  background: var(--surface-card, #fff);
  border-radius: 50%;
  width: 12px;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.delivery-stage-bar__overlay-badge {
  position: absolute;
  top: -8px;
  right: 0;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--overlay-color, var(--clay-red));
  color: var(--on-primary, #fff);
}
.delivery-stage-bar__overlay-badge[data-overlay='cancelled'] {
  background: var(--muted-soft, #8b8479);
}
</style>
