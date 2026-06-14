/**
 * Notification center store.
 *
 * Buffers WebSocket events the operator would otherwise miss
 * (issue_updated / agent_status / webhook_received / job_update /
 * cycle_report) and exposes:
 *
 *   - a reactive `notifications` list (newest first, capped at MAX)
 *   - an `unreadCount` getter for the bell badge
 *   - `markRead` / `markAllRead` / `clearAll` actions
 *   - localStorage persistence so a refresh keeps the inbox intact
 *
 * The dedup window is 30s per (type, resource) pair — see
 * `shouldSuppress`. We dedup here, not in the WebSocket layer, so a
 * single source of truth survives the future case where a page other
 * than useWebSocket pushes notifications.
 */
import { defineStore } from 'pinia'

export type NotificationType =
  | 'issue_updated'
  | 'agent_status'
  | 'webhook'
  | 'job_update'
  | 'cycle_report'

export interface Notification {
  id: string
  type: NotificationType
  title: string
  message: string
  /** Optional deep link. Falls back to `/notifications` if missing. */
  link?: string
  /** Opaque resource key (issueId, agentId, jobId, ...). Used for dedup. */
  resource?: string
  read: boolean
  createdAt: string // ISO
}

const STORAGE_KEY = 'devflow:notifications'
const MAX_NOTIFICATIONS = 100
const DEDUP_WINDOW_MS = 30_000

interface PersistedState {
  notifications: Notification[]
}

const safeReadStorage = (): PersistedState | null => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !Array.isArray(parsed.notifications)) return null
    return {
      notifications: parsed.notifications
        .filter((n: any) => n && typeof n.id === 'string')
        .slice(0, MAX_NOTIFICATIONS)
        .map((n: any) => ({
          id: String(n.id),
          type: (n.type as NotificationType) ?? 'issue_updated',
          title: String(n.title ?? ''),
          message: String(n.message ?? ''),
          link: typeof n.link === 'string' ? n.link : undefined,
          resource: typeof n.resource === 'string' ? n.resource : undefined,
          read: Boolean(n.read),
          createdAt: String(n.createdAt ?? new Date().toISOString()),
        })),
    }
  } catch {
    return null
  }
}

const safeWriteStorage = (notifications: Notification[]) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ notifications }))
  } catch {
    // localStorage quota / disabled — fail silently, the in-memory
    // copy still works for the current session.
  }
}

const generateId = (): string => {
  // Avoid crypto.randomUUID for older browsers; the backend uses
  // similar aribitrary strings so this is plenty unique.
  return `n-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useNotificationsStore = defineStore('notifications', {
  state: (): { notifications: Notification[]; hydrated: boolean } => ({
    notifications: [],
    hydrated: false,
  }),

  getters: {
    unreadCount: (state): number =>
      state.notifications.reduce((n, item) => n + (item.read ? 0 : 1), 0),

    /** Newest first, for the inbox view. */
    sortedNotifications: (state): Notification[] =>
      [...state.notifications].sort(
        (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      ),
  },

  actions: {
    /** Load persisted state. Safe to call multiple times. */
    hydrate() {
      if (this.hydrated) return
      const persisted = safeReadStorage()
      if (persisted) {
        this.notifications = persisted.notifications
      }
      this.hydrated = true
    },

    /**
     * Append a notification, deduped by (type, resource) within
     * `DEDUP_WINDOW_MS`. Returns the new (or existing) notification,
     * or `null` if suppressed.
     */
    push(input: Omit<Notification, 'id' | 'read' | 'createdAt'>): Notification | null {
      this.hydrate()
      if (this.shouldSuppress(input.type, input.resource)) {
        return null
      }
      const item: Notification = {
        ...input,
        id: generateId(),
        read: false,
        createdAt: new Date().toISOString(),
      }
      // FIFO: append then trim from the front.
      this.notifications = [item, ...this.notifications].slice(0, MAX_NOTIFICATIONS)
      this.persist()
      return item
    },

    shouldSuppress(type: NotificationType, resource?: string): boolean {
      const now = Date.now()
      return this.notifications.some(n => {
        if (n.type !== type) return false
        if ((n.resource ?? null) !== (resource ?? null)) return false
        const age = now - new Date(n.createdAt).getTime()
        return age < DEDUP_WINDOW_MS
      })
    },

    markRead(id: string) {
      const item = this.notifications.find(n => n.id === id)
      if (item && !item.read) {
        item.read = true
        this.persist()
      }
    },

    markAllRead() {
      let changed = false
      this.notifications = this.notifications.map(n => {
        if (!n.read) {
          changed = true
          return { ...n, read: true }
        }
        return n
      })
      if (changed) this.persist()
    },

    clearAll() {
      if (this.notifications.length === 0) return
      this.notifications = []
      this.persist()
    },

    remove(id: string) {
      const before = this.notifications.length
      this.notifications = this.notifications.filter(n => n.id !== id)
      if (this.notifications.length !== before) this.persist()
    },

    /** Internal: write current state to localStorage. */
    persist() {
      safeWriteStorage(this.notifications)
    },
  },
})
