<script setup lang="ts">
/**
 * /notifications — the operator inbox.
 *
 * Surfaces every WebSocket event the WebSocket composable decided
 * was worth keeping (issue_updated / agent_status / webhook /
 * job_update / cycle_report). Persistence is handled by the store;
 * a refresh re-hydrates from localStorage.
 *
 * Why a separate page rather than a sidebar drawer:
 *  - Inbox can grow long enough that a drawer would crowd the
 *    board view.
 *  - The bell badge is the "needs attention" signal; the page
 *    is where the operator triages.
 *
 * The page intentionally does not poll any backend — the store is
 * the single source of truth. New entries arrive via WebSocket
 * events fired into the store from useWebSocket.ts.
 */
import { computed, onMounted } from 'vue'
import {
  BellOff,
  Check,
  CheckCheck,
  CircleAlert,
  Inbox,
  ListFilter,
  RefreshCcw,
  Trash2,
} from 'lucide-vue-next'
import { useNotificationsStore, type Notification, type NotificationType } from '~/stores/notifications'

const store = useNotificationsStore()

onMounted(() => {
  // Idempotent — store guards against double-hydration.
  store.hydrate()
})

type Filter = 'all' | 'unread'
const filter = ref<Filter>('all')

const visibleNotifications = computed<Notification[]>(() => {
  const list = filter.value === 'unread'
    ? store.notifications.filter(n => !n.read)
    : store.notifications
  // Inbox convention: newest first. The store keeps insertion order
  // (FIFO append from front), but we sort defensively so a rehydrate
  // from a stale localStorage can't break the order.
  return [...list].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  )
})

const unreadCount = computed(() => store.unreadCount)
const totalCount = computed(() => store.notifications.length)

const setFilter = (next: Filter) => {
  filter.value = next
}

const markRead = (id: string) => {
  store.markRead(id)
}
const markAllRead = () => {
  store.markAllRead()
}
const clearAll = () => {
  store.clearAll()
}

// Intl.RelativeTimeFormat: built into the runtime, so we don't have
// to ship a date library. ``numeric: 'auto'`` keeps "yesterday" /
// "now" instead of "1 day ago" for the most useful bucket.
const rtf = typeof Intl !== 'undefined' && Intl.RelativeTimeFormat
  ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  : null

const formatTimeAgo = (iso: string): string => {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diffSec = Math.round((then - Date.now()) / 1000)
  const abs = Math.abs(diffSec)
  if (rtf) {
    if (abs < 60) return rtf.format(diffSec, 'second')
    if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
    if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
    if (abs < 604800) return rtf.format(Math.round(diffSec / 86400), 'day')
    if (abs < 2629800) return rtf.format(Math.round(diffSec / 604800), 'week')
    if (abs < 31557600) return rtf.format(Math.round(diffSec / 2629800), 'month')
    return rtf.format(Math.round(diffSec / 31557600), 'year')
  }
  // Fallback: absolute date string.
  return new Date(iso).toLocaleString()
}

const formatAbsolute = (iso: string): string => {
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

// Per-type icon + tint. Tints follow the existing project palette
// (sage for success-ish, dusty-blue for review, clay-red for failure).
const TYPE_META: Record<NotificationType, { label: string; icon: any; tint: string }> = {
  issue_updated: { label: 'Issue', icon: Inbox, tint: 'var(--primary)' },
  agent_status: { label: 'Agent', icon: ListFilter, tint: 'var(--dusty-blue)' },
  webhook: { label: 'Webhook', icon: RefreshCcw, tint: 'var(--amber)' },
  job_update: { label: 'Job', icon: CircleAlert, tint: 'var(--clay-red)' },
  cycle_report: { label: 'Cycle', icon: Inbox, tint: 'var(--sage)' },
}

const metaFor = (type: NotificationType) => TYPE_META[type] ?? TYPE_META.issue_updated

const openLink = (n: Notification) => {
  // Marking read is a side-effect of clicking, since the user
  // presumably just saw the row. The link itself is the primary
  // intent.
  if (!n.read) store.markRead(n.id)
  const target = n.link || '/notifications'
  if (typeof window !== 'undefined') {
    window.location.href = target
  }
}
</script>

<template>
  <section class="notifications-page">
    <header class="notifications-page__topbar">
      <div class="notifications-page__title">
        <span class="notifications-page__kicker">Workspace / DevFlow</span>
        <h1>Notifications</h1>
        <p>Everything that arrived over WebSocket while you were away — issues, agents, webhooks, jobs.</p>
      </div>
      <div class="notifications-page__actions">
        <button
          class="icon-btn"
          :disabled="unreadCount === 0"
          data-testid="mark-all-read"
          @click="markAllRead"
          title="Mark all as read"
        >
          <CheckCheck :size="16" />
          <span>Mark all read</span>
        </button>
        <button
          class="icon-btn icon-btn--danger"
          :disabled="totalCount === 0"
          data-testid="clear-all"
          @click="clearAll"
          title="Clear all notifications"
        >
          <Trash2 :size="16" />
          <span>Clear all</span>
        </button>
      </div>
    </header>

    <!-- Filter + count bar -->
    <div class="notifications-page__toolbar">
      <div class="filter-group" role="tablist" aria-label="Filter notifications">
        <button
          class="chip"
          :class="{ 'chip--active': filter === 'all' }"
          role="tab"
          :aria-selected="filter === 'all'"
          data-testid="filter-all"
          @click="setFilter('all')"
        >
          All
          <span class="chip__count">{{ totalCount }}</span>
        </button>
        <button
          class="chip"
          :class="{ 'chip--active': filter === 'unread' }"
          role="tab"
          :aria-selected="filter === 'unread'"
          data-testid="filter-unread"
          @click="setFilter('unread')"
        >
          Unread
          <span class="chip__count">{{ unreadCount }}</span>
        </button>
      </div>
    </div>

    <!-- List -->
    <div
      v-if="visibleNotifications.length === 0"
      class="notifications-page__empty"
      data-testid="notifications-empty"
    >
      <BellOff :size="40" />
      <h2 v-if="filter === 'unread'">No unread notifications</h2>
      <h2 v-else>No notifications yet</h2>
      <p v-if="filter === 'unread'">
        Everything that arrived has been read or dismissed. New events will land here in real time.
      </p>
      <p v-else>
        WebSocket events will show up here as they happen — issue updates, agent idle flips, webhook fires, and job status changes.
      </p>
    </div>

    <ul
      v-else
      class="notification-list"
      data-testid="notification-list"
    >
      <li
        v-for="n in visibleNotifications"
        :key="n.id"
        class="notification"
        :class="{ 'notification--unread': !n.read }"
        :data-testid="`notification-item-${n.id}`"
        :data-notification-type="n.type"
      >
        <div
          class="notification__icon"
          :style="{ background: metaFor(n.type).tint + '20', color: metaFor(n.type).tint }"
          :aria-label="metaFor(n.type).label"
        >
          <component :is="metaFor(n.type).icon" :size="16" />
        </div>
        <div class="notification__body">
          <div class="notification__row">
            <button
              class="notification__title"
              :title="n.title"
              data-testid="notification-link"
              @click="openLink(n)"
            >{{ n.title }}</button>
            <span
              v-if="!n.read"
              class="notification__dot"
              :title="'Unread'"
              aria-label="Unread"
            />
          </div>
          <p class="notification__message">{{ n.message }}</p>
          <div class="notification__meta">
            <span class="notification__type">{{ metaFor(n.type).label }}</span>
            <span class="notification__sep">·</span>
            <span class="notification__time" :title="formatAbsolute(n.createdAt)">{{ formatTimeAgo(n.createdAt) }}</span>
          </div>
        </div>
        <div class="notification__actions">
          <button
            v-if="!n.read"
            class="notification__action"
            :data-testid="`mark-read-${n.id}`"
            title="Mark as read"
            aria-label="Mark as read"
            @click="markRead(n.id)"
          >
            <Check :size="14" />
          </button>
          <button
            v-else
            class="notification__action"
            disabled
            aria-label="Already read"
            title="Read"
          >
            <Check :size="14" />
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.notifications-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 24px 28px 32px;
  background: var(--canvas);
  color: var(--ink);
  overflow-y: auto;
}

.notifications-page__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.notifications-page__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.notifications-page__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.notifications-page__title h1 {
  margin: 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.2;
}

.notifications-page__title p {
  margin: 0;
  color: var(--muted);
  font-size: 0.875rem;
  max-width: 56ch;
}

.notifications-page__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}

.icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--muted);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn--danger:not(:disabled):hover {
  color: var(--clay-red, #d04a3a);
  border-color: var(--clay-red, #d04a3a);
}

.notifications-page__toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}

.chip:hover {
  color: var(--ink);
  border-color: var(--muted);
}

.chip--active {
  color: var(--ink);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border-color: var(--primary);
}

.chip__count {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  color: var(--ink);
  background: var(--surface-card);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
}

.chip--active .chip__count {
  background: var(--primary);
  color: #fff;
}

.notification-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notification {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  transition: background 150ms ease, border-color 150ms ease;
}

.notification:hover {
  border-color: var(--muted);
}

.notification--unread {
  background: color-mix(in srgb, var(--primary) 4%, var(--surface-card));
  border-color: color-mix(in srgb, var(--primary) 30%, var(--hairline));
}

.notification__icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  flex-shrink: 0;
}

.notification__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.notification__row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notification__title {
  margin: 0;
  padding: 0;
  color: var(--ink);
  background: none;
  border: none;
  font-size: 0.9375rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.notification__title:hover {
  text-decoration: underline;
}

.notification__dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  background: var(--primary);
  border-radius: 50%;
}

.notification__message {
  margin: 0;
  color: var(--muted);
  font-size: 0.8125rem;
  line-height: 1.4;
  word-break: break-word;
}

.notification__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--subtle, var(--muted));
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.notification__sep {
  opacity: 0.5;
}

.notification__actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
  align-items: center;
}

.notification__action {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  color: var(--muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
}

.notification__action:hover:not(:disabled) {
  color: var(--ink);
  background: var(--surface-hover);
  border-color: var(--hairline);
}

.notification__action:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.notifications-page__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 64px 24px;
  text-align: center;
  color: var(--muted);
}

.notifications-page__empty svg {
  color: var(--muted);
  opacity: 0.6;
}

.notifications-page__empty h2 {
  margin: 4px 0 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.125rem;
  font-weight: 600;
}

.notifications-page__empty p {
  margin: 0;
  max-width: 48ch;
  font-size: 0.875rem;
}

@media (max-width: 640px) {
  .notifications-page {
    padding: 16px;
  }
  .notification {
    grid-template-columns: 32px minmax(0, 1fr) auto;
  }
}
</style>
