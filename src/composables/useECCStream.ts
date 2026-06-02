// Real per-job ECC log subscriber.
//
// Backed by the WebSocket at /api/v1/ws/ecc/jobs. Public API matches the
// previous mock implementation (startStream / stopStream / getLogs /
// isStreaming / isConnected) so existing callers do not need to change.
//
// For a given issue, the caller calls `startStream(issueId)`. We:
//   1. Fetch the latest job for that issue via REST to backfill any
//      events that arrived before the WS subscriber attached.
//   2. Subscribe to the job over WS. Each `job_update` payload's
//      `events` array is the new log content (the backend always
//      re-sends the full event list, not a delta).
//   3. Keep `streamLogs[issueId]` growing and reactive.

import { ref, computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useWebSocket, onJobUpdate } from '~/composables/useWebSocket'
import type { ECCLogEntry, ECCJobEvent } from '~/types'

const _toLog = (jobId: string, ev: ECCJobEvent): ECCLogEntry => ({
  id: `jobevt_${jobId}_${ev.timestamp}_${ev.status}`,
  timestamp: ev.timestamp,
  phase: ev.status === 'review_required'
    ? 'output'
    : ev.status === 'failed'
      ? 'error'
      : 'observation',
  content: ev.message,
  confidence: ev.status === 'review_required' ? 0.95 : 0.75
})

const useRealStream = () => {
  const boardStore = useBoardStore()
  const ws = useWebSocket()
  const isConnected = computed(() => ws.isConnected.value)
  const activeStreams = ref<Map<string, boolean>>(new Map())
  const streamLogs = ref<Map<string, ECCLogEntry[]>>(new Map())

  const _attach = (issueId: string) => {
    if (!boardStore.getIssueById(issueId)?.eccJobId) return
    const jobId = boardStore.getIssueById(issueId)!.eccJobId as string
    const existing = boardStore.getIssueJob(issueId)
    if (existing?.events?.length) {
      streamLogs.value.set(issueId, existing.events.map(e => _toLog(jobId, e)))
      streamLogs.value = new Map(streamLogs.value)
    }
    ws.subscribe(jobId)
  }

  const _detach = (issueId: string) => {
    const jobId = boardStore.getIssueById(issueId)?.eccJobId
    if (jobId) ws.unsubscribe(jobId)
  }

  // Listen to incoming job_update events and append new log lines.
  onJobUpdate((job) => {
    const issue = boardStore.jobsById[job.id]
      ? boardStore.getIssueById(boardStore.jobsById[job.id].issue_id)
      : null
    // Fallback: find issue_id from the payload.
    const issueId = issue?.id
      ?? Object.values(boardStore.jobsById).find(j => j.id === job.id)?.issue_id
    if (!issueId) return
    if (!activeStreams.value.get(issueId)) return
    streamLogs.value.set(
      issueId,
      job.events.map((e: ECCJobEvent) => _toLog(job.id, e))
    )
    streamLogs.value = new Map(streamLogs.value)
  })

  const startStream = (issueId: string) => {
    if (activeStreams.value.get(issueId)) return
    activeStreams.value.set(issueId, true)
    streamLogs.value.set(issueId, streamLogs.value.get(issueId) ?? [])
    streamLogs.value = new Map(streamLogs.value)
    _attach(issueId)
  }

  const stopStream = (issueId: string) => {
    activeStreams.value.set(issueId, false)
    _detach(issueId)
  }

  const getLogs = (issueId: string): ECCLogEntry[] => {
    return streamLogs.value.get(issueId) ?? []
  }

  const isStreaming = (issueId: string): boolean => {
    return activeStreams.value.get(issueId) ?? false
  }

  return {
    isConnected,
    activeStreams,
    streamLogs,
    startStream,
    stopStream,
    getLogs,
    isStreaming
  }
}

// Singleton (one stream manager shared across components).
let streamInstance: ReturnType<typeof useRealStream> | null = null

export const useECCStream = () => {
  if (!streamInstance) streamInstance = useRealStream()
  return streamInstance
}

export const useECCStreamSingleton = () => {
  if (!streamInstance) streamInstance = useRealStream()
  return streamInstance
}
