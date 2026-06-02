// Shared ECC job status color tokens.
// Single source of truth so the Sidebar, IssueDetail, and any future
// surface area use the same color for the same status.

export type ECCJobStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'failed'
  | 'review_required'
  | 'completed'
  | 'cancelled'

export const ECC_JOB_STATUS_COLORS: Record<ECCJobStatus, string> = {
  queued: 'var(--amber, #E5A65A)',
  running: 'var(--coral, #CC785C)',
  paused: 'var(--muted, #6c6a64)',
  review_required: 'var(--dusty-blue, #6F8FAF)',
  completed: 'var(--sage, #7D9E7D)',
  failed: 'var(--clay-red, #B85C4D)',
  cancelled: 'var(--clay-red, #B85C4D)'
}

export const jobStatusColor = (status: string): string => {
  return (ECC_JOB_STATUS_COLORS as Record<string, string>)[status]
    ?? 'var(--muted, #6c6a64)'
}
