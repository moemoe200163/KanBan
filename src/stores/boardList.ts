/**
 * Board selector store.
 *
 * Source of truth for the "which board am I looking at?" state. The
 * sidebar selector binds to this store, and the board store's
 * ``fetchBoard`` reads ``activeBoardId`` so a board switch reloads
 * the columns.
 *
 * Why a separate store? The board store is already huge (issue
 * mutations, jobs, dependency graph, handoffs, websocket handling,
 * ...). Board switching is a different concern with its own
 * persistence and network shape, so we keep it isolated.
 *
 * Persistence:
 *   ``localStorage.devflow:activeBoardId`` remembers the active
 *   board across reloads. We hydrate the value on store creation
 *   but do not persist a default — that way a brand-new operator
 *   with no prior choice falls back to ``DEFAULT_BOARD_ID``.
 *
 * Auth:
 *   The new ``GET /api/v1/boards`` endpoint requires a JWT. We send
 *   the same Authorization header the rest of the app uses, so a
 *   logged-out operator gets an empty list and the selector stays
 *   hidden (per the "no board data → no selector" requirement).
 */
import { defineStore } from 'pinia'
import { authHeaders } from '~/utils/authHeaders'

const STORAGE_KEY = 'devflow:activeBoardId'
/** Matches ``DEFAULT_BOARD_ID`` on the backend. Kept as a constant
 *  here so a future rename only needs to be made in one place. */
export const DEFAULT_BOARD_ID = 'board-default'

export interface BoardSummary {
  id: string
  name: string
  issueCount: number
}

interface BoardListState {
  boards: BoardSummary[]
  activeBoardId: string
  isLoading: boolean
  error: string | null
  /** True once we've made at least one fetch attempt (success or
   *  failure). Used by the sidebar to decide whether to show the
   *  selector — it should appear even on an empty list, but only
   *  after we know the list is genuinely empty. */
  hasLoaded: boolean
}

/** Read the persisted active board id, or null if nothing is stored. */
function readStoredActiveId(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // localStorage may be unavailable (private mode, sandboxed
    // iframe); fall back to the default.
    return null
  }
}

/** Persist the active board id. No-op on the server / when
 *  localStorage is unavailable. */
function writeStoredActiveId(id: string) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // ignore — the operator can still switch boards in this session.
  }
}

export const useBoardListStore = defineStore('boardList', {
  state: (): BoardListState => ({
    boards: [],
    activeBoardId: readStoredActiveId() || DEFAULT_BOARD_ID,
    isLoading: false,
    error: null,
    hasLoaded: false,
  }),

  getters: {
    /** The currently active board, or ``null`` if the active id
     *  isn't in the loaded list (e.g. the operator switched to a
     *  board that was later removed). The sidebar falls back to
     *  the default in that case. */
    activeBoard(state): BoardSummary | null {
      return state.boards.find(b => b.id === state.activeBoardId) ?? null
    },

    /** True when the operator has at least one board to choose
     *  from. The sidebar uses this to hide the selector entirely
     *  for logged-out visitors and for fresh DBs that haven't
     *  finished hydrating yet. */
    hasMultipleBoards(state): boolean {
      return state.boards.length > 1
    },
  },

  actions: {
    async fetchBoards() {
      this.isLoading = true
      this.error = null
      try {
        const config = useRuntimeConfig()
        const apiBase = config.public.apiBase as string
        const list = await $fetch<BoardSummary[]>(`${apiBase}/boards`, {
          headers: authHeaders(),
        })
        this.boards = Array.isArray(list) ? list : []

        // If the persisted active id no longer exists in the list
        // (board was deleted upstream, or the stored value was
        // hand-edited), fall back to the default. We do not
        // overwrite localStorage here — the operator's next
        // setActive() call will reset it.
        const known = this.boards.find(b => b.id === this.activeBoardId)
        if (!known && this.boards.length > 0) {
          this.activeBoardId = this.boards[0].id
        } else if (!known) {
          this.activeBoardId = DEFAULT_BOARD_ID
        }
      } catch (err) {
        // Don't blow up the sidebar over a transient failure.
        // Logged-out operators and stale tokens will land here.
        console.warn('[BoardListStore] fetchBoards failed:', err)
        this.error = err instanceof Error ? err.message : 'Failed to load boards'
        this.boards = []
        this.activeBoardId = DEFAULT_BOARD_ID
      } finally {
        this.isLoading = false
        this.hasLoaded = true
      }
    },

    /** Set the active board and persist the choice. Returns the id
     *  that ended up active (caller can compare to detect a no-op
     *  switch or a default fallback). */
    setActive(boardId: string): string {
      const candidate = boardId?.trim() || DEFAULT_BOARD_ID
      // Reject known-bad inputs: empty, whitespace, overlong. The
      // backend has the same guard, but failing fast here means
      // the board store doesn't issue a doomed fetch.
      if (candidate.length > 64) {
        console.warn('[BoardListStore] setActive rejected overlong id')
        return this.activeBoardId
      }
      if (candidate === this.activeBoardId) return candidate
      this.activeBoardId = candidate
      writeStoredActiveId(candidate)
      return candidate
    },
  },
})
