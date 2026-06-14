/**
 * useDeliveryStage — Vue composable that wraps the pure mapping
 * function `resolveDeliveryStage` for use in components.
 *
 * The component passes a reactive list of jobs (and optionally
 * the issue status); the composable returns a `computed` ref to
 * a `DeliveryStageState`. Re-computes on every job list change,
 * so live-updating jobs in the board store flow straight through
 * the bar.
 */

import { computed, type ComputedRef, type Ref } from 'vue'
import type { IssueStatus } from '~/types'
import {
  resolveDeliveryStage,
  type DeliveryStageState,
} from '~/lib/deliveryStageMapping'

export interface UseDeliveryStageArgs {
  jobs: Ref<ReadonlyArray<{ status: any; updated_at: string }>>
  issueStatus?: Ref<IssueStatus | null | undefined>
}

export function useDeliveryStage(
  args: UseDeliveryStageArgs,
): ComputedRef<DeliveryStageState> {
  return computed(() => resolveDeliveryStage({
    jobs: args.jobs.value as any,
    issueStatus: args.issueStatus?.value ?? null,
  }))
}
