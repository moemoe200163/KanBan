/**
 * useKanbanProtocol — composable for the Kanban Protocol handoff API.
 *
 * Wraps all handoff CRUD + state-transition endpoints behind a
 * reactive, issue-scoped interface.  The board ID is fixed to
 * "board-default" for now (single-board P0).
 */

import type {
  Handoff,
  HandoffPreview,
  HandoffCreateRequest,
  HandoffDispatchRequest,
  HandoffBlockRequest,
  HandoffReviewRequest,
} from '~/types'

const BOARD_ID = 'board-default'

export function useKanbanProtocol(issueId: string) {
  const config = useRuntimeConfig()
  const base = computed(() =>
    `${config.public.apiBase}/boards/${BOARD_ID}/issues/${issueId}/handoffs`
  )

  // ---- helpers ----

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function _post<T>(path: string, body?: any): Promise<T> {
    return await $fetch<T>(path, {
      method: 'POST',
      body: body ?? {},
    })
  }

  // ---- handoff CRUD ----

  function createHandoff(req: HandoffCreateRequest): Promise<Handoff> {
    return _post<Handoff>(base.value, req)
  }

  function listHandoffs(): Promise<{ handoffs: Handoff[]; total: number }> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ($fetch as any)(base.value)
  }

  function getHandoff(handoffId: string): Promise<Handoff> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ($fetch as any)(`${base.value}/${handoffId}`)
  }

  // ---- state transitions ----

  function acceptHandoff(handoffId: string, actor?: string): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/accept`, { actor })
  }

  function dispatchHandoff(
    handoffId: string,
    req: HandoffDispatchRequest,
  ): Promise<{ handoff: Handoff; job: unknown }> {
    return _post(`${base.value}/${handoffId}/dispatch`, req)
  }

  function completeHandoff(
    handoffId: string,
    payload?: Record<string, unknown>,
    actor?: string,
  ): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/complete`, { actor, payload })
  }

  function blockHandoff(
    handoffId: string,
    reason: string,
    actor?: string,
  ): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/block`, {
      actor,
      blockReason: reason,
    } satisfies HandoffBlockRequest)
  }

  function unblockHandoff(handoffId: string, actor?: string): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/unblock`, { actor })
  }

  function cancelHandoff(handoffId: string, actor?: string): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/cancel`, { actor })
  }

  function reviewHandoff(
    handoffId: string,
    req: HandoffReviewRequest,
  ): Promise<Handoff> {
    return _post<Handoff>(`${base.value}/${handoffId}/review`, req)
  }

  // ---- comments ----

  function addComment(
    handoffId: string,
    body: string,
    opts?: { authorId?: string; authorName?: string; commentType?: string },
  ): Promise<unknown> {
    return _post(`${base.value}/${handoffId}/comment`, {
      body,
      authorId: opts?.authorId,
      authorName: opts?.authorName,
      commentType: opts?.commentType ?? 'handoff',
    })
  }

  // ---- preview ----

  function previewHandoff(handoffId: string): Promise<HandoffPreview> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ($fetch as any)(`${base.value}/${handoffId}/preview`)
  }

  return {
    createHandoff,
    listHandoffs,
    getHandoff,
    acceptHandoff,
    dispatchHandoff,
    completeHandoff,
    blockHandoff,
    unblockHandoff,
    cancelHandoff,
    reviewHandoff,
    addComment,
    previewHandoff,
  }
}
