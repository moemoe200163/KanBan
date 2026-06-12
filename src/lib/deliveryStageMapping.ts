/**
 * Delivery Stage Mapping — frontend-only visual overlay.
 *
 * Per roadmap §16 + `docs/ui-roadmap-design-alignment.md` §3.2, the
 * Delivery Orchestrator is a six-stage visual representation of the
 * issue's progress through the safe-runner pipeline:
 *
 *   1. Intake        — issue created, no worker engaged
 *   2. Dispatch      — work scheduled, no execution yet
 *   3. Execute       — safe-runner actively running
 *   4. Quality Gate  — quality gate check in flight
 *   5. Human Review  — work product awaiting leader decision
 *   6. Release Ready — approved, lane = done
 *
 * Backend exposes seven ECCJobStatus values
 * ('queued' | 'running' | 'paused' | 'failed' | 'review_required'
 *  | 'completed' | 'cancelled'); we map them onto the six stages plus
 * two failure-side overlays ('failed' / 'cancelled') that show on
 * top of whichever stage the work was at.
 *
 * This module is **pure data + pure functions** — no Vue, no DOM,
 * no fetches. Same input always returns the same output, so
 * `useDeliveryStage` and the bar/hint components can call it
 * without testing ceremony.
 */

import type { ECCJobStatus, IssueStatus } from '~/types'

export type DeliveryStage =
  | 'intake'
  | 'dispatch'
  | 'execute'
  | 'quality_gate'
  | 'human_review'
  | 'release_ready'

export type DeliveryOverlay = 'failed' | 'cancelled' | null

export interface DeliveryStageState {
  /** The 1-indexed stage number (1..6). Always defined. */
  stage: DeliveryStage
  stageIndex: number
  /** Terminal overlay (red/grey) shown on top of the stage. */
  overlay: DeliveryOverlay
  /** Convenience flags used by the bar/hint components. */
  isFailed: boolean
  isCancelled: boolean
  isTerminal: boolean
}

export const DELIVERY_STAGES: readonly DeliveryStage[] = [
  'intake',
  'dispatch',
  'execute',
  'quality_gate',
  'human_review',
  'release_ready',
] as const

export const DELIVERY_STAGE_LABELS: Record<DeliveryStage, string> = {
  intake: 'Intake',
  dispatch: 'Dispatch',
  execute: 'Execute',
  quality_gate: 'Quality Gate',
  human_review: 'Human Review',
  release_ready: 'Release Ready',
}

export const DELIVERY_STAGE_SHORT: Record<DeliveryStage, string> = {
  intake: 'IN',
  dispatch: 'DS',
  execute: 'EX',
  quality_gate: 'QG',
  human_review: 'RV',
  release_ready: 'RD',
}

/**
 * Map one backend job status onto a single stage. Order matters:
 * the most specific signal wins. ``review_required`` is always
 * Human Review regardless of whether the runner is technically
 * still in a paused state — the leader's call is the gating
 * decision, not the runner's heartbeat.
 */
const JOB_TO_STAGE: Record<ECCJobStatus, DeliveryStage> = {
  queued: 'dispatch',
  running: 'execute',
  paused: 'quality_gate',
  failed: 'execute',
  review_required: 'human_review',
  completed: 'release_ready',
  cancelled: 'execute',
}

/**
 * Map an IssueStatus lane position onto a stage, used when no
 * job exists yet. Backend's lane transitions are
 * backlog → in_progress → blocked → human_review → done.
 */
const ISSUE_TO_STAGE: Record<IssueStatus, DeliveryStage> = {
  backlog: 'intake',
  in_progress: 'execute',
  blocked: 'quality_gate',
  human_review: 'human_review',
  done: 'release_ready',
}

/**
 * Resolve which single job is the "current" one for an issue.
 * Preference order: in-flight (non-terminal) > most recent.
 */
export function pickCurrentJob<
  J extends { status: ECCJobStatus; updated_at: string },
>(jobs: J[] | undefined | null): J | null {
  if (!jobs || jobs.length === 0) return null
  const inFlight = jobs.find(
    (j) => j.status !== 'completed'
      && j.status !== 'failed'
      && j.status !== 'cancelled',
  )
  if (inFlight) return inFlight
  // Most recently updated, terminal or not
  return jobs
    .slice()
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
}

export interface ResolveArgs {
  jobs?: Array<{ status: ECCJobStatus; updated_at: string }> | null
  issueStatus?: IssueStatus | null
}

/**
 * Compute the displayed DeliveryStageState for an issue.
 *
 * Precedence:
 *   1. The issue's most-recent job's status (gives the most
 *      specific signal — ``review_required`` is exact, ``paused``
 *      is exactly quality_gate, etc).
 *   2. The issue's lane (``IssueStatus``), used when no job
 *      exists yet or all jobs are stale.
 *   3. Fall back to ``intake``.
 */
export function resolveDeliveryStage(
  args: ResolveArgs,
): DeliveryStageState {
  const job = pickCurrentJob(args.jobs ?? null)
  let stage: DeliveryStage
  let overlay: DeliveryOverlay = null

  if (job) {
    stage = JOB_TO_STAGE[job.status]
    if (job.status === 'failed') overlay = 'failed'
    if (job.status === 'cancelled') overlay = 'cancelled'
  } else if (args.issueStatus) {
    stage = ISSUE_TO_STAGE[args.issueStatus]
  } else {
    stage = 'intake'
  }

  const stageIndex = DELIVERY_STAGES.indexOf(stage) + 1
  return {
    stage,
    stageIndex,
    overlay,
    isFailed: overlay === 'failed',
    isCancelled: overlay === 'cancelled',
    isTerminal: stage === 'release_ready' && !overlay,
  }
}

/**
 * Suggested next action for a human at the current stage.
 * Pure data — no button wiring. The bar and hint components
 * render this verbatim.
 */
export const NEXT_COMMAND_HINTS: Record<DeliveryStage | 'failed' | 'cancelled', string> = {
  intake: 'Dispatch a worker: open the issue and run /loop-start',
  dispatch: 'Wait for the safe runner to claim the job',
  execute: 'Runner is executing — check the ECC Logs tab for live progress',
  quality_gate: 'Quality gate in flight — review the gate output before approving',
  human_review: 'Leader action required: Approve or Request changes on the cycle report',
  release_ready: 'Done — lane already at Release Ready',
  failed: 'Runner failed — see the ECC Logs tab and decide whether to retry or cancel',
  cancelled: 'Run was cancelled — re-dispatch from the issue if you want to retry',
}
