<script setup lang="ts">
interface TeamMember {
  id: string
  name: string
  avatar: string
  status: 'online' | 'away' | 'offline'
  role: string
}

interface ActivityItem {
  id: string
  actor: string
  action: string
  target: string
  timestamp: string
}

const props = defineProps<{
  issueId?: string
}>()

const teamMembers = ref<TeamMember[]>([
  { id: 'u1', name: 'Alex Chen', avatar: 'https://i.pravatar.cc/150?u=alex', status: 'online', role: 'Backend' },
  { id: 'u2', name: 'Jamie Rivera', avatar: 'https://i.pravatar.cc/150?u=jamie', status: 'online', role: 'Frontend' },
  { id: 'u3', name: 'Sam Taylor', avatar: 'https://i.pravatar.cc/150?u=sam', status: 'away', role: 'QA' }
])

const activities = ref<ActivityItem[]>([
  { id: 'a1', actor: 'Alex Chen', action: 'moved', target: 'DEV-003 to In Progress', timestamp: '2m ago' },
  { id: 'a2', actor: 'Jamie Rivera', action: 'created', target: 'DEV-010', timestamp: '5m ago' },
  { id: 'a3', actor: 'Sam Taylor', action: 'commented on', target: 'DEV-007', timestamp: '12m ago' }
])

const newComment = ref('')

const statusConfig = {
  online: { color: '#7d9e7d', label: 'Online' },
  away: { color: '#d4a84b', label: 'Away' },
  offline: { color: '#8e8b82', label: 'Offline' }
}

const addComment = () => {
  if (!newComment.value.trim()) return
  const newActivity: ActivityItem = {
    id: `a${Date.now()}`,
    actor: 'You',
    action: 'commented on',
    target: props.issueId || 'this issue',
    timestamp: 'just now'
  }
  activities.value.unshift(newActivity)
  newComment.value = ''
}
</script>

<template>
  <div class="collaboration-panel">
    <!-- Team Members -->
    <div class="collaboration-panel__section">
      <h4 class="collaboration-panel__section-title">Team</h4>
      <div class="member-list">
        <div
          v-for="member in teamMembers"
          :key="member.id"
          class="member-item"
        >
          <div class="member-item__avatar-wrapper">
            <img
              :src="member.avatar"
              :alt="member.name"
              class="member-item__avatar"
            />
            <span
              class="member-item__status"
              :class="`member-item__status--${member.status}`"
              :title="statusConfig[member.status].label"
            />
          </div>
          <div class="member-item__info">
            <span class="member-item__name">{{ member.name }}</span>
            <span class="member-item__role">{{ member.role }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Activity Feed -->
    <div class="collaboration-panel__section">
      <h4 class="collaboration-panel__section-title">Recent Activity</h4>
      <div class="activity-list">
        <div
          v-for="activity in activities"
          :key="activity.id"
          class="activity-item"
        >
          <span class="activity-item__actor">{{ activity.actor }}</span>
          <span class="activity-item__action">{{ activity.action }}</span>
          <span class="activity-item__target">{{ activity.target }}</span>
          <span class="activity-item__time">{{ activity.timestamp }}</span>
        </div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="collaboration-panel__section">
      <h4 class="collaboration-panel__section-title">Quick Actions</h4>
      <div class="quick-actions">
        <button class="quick-action-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          Comment
        </button>
        <button class="quick-action-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
          Assign
        </button>
        <button class="quick-action-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="8.5" cy="7" r="4" />
            <line x1="20" y1="8" x2="20" y2="14" />
            <line x1="23" y1="11" x2="17" y2="11" />
          </svg>
          Invite
        </button>
      </div>
    </div>

    <!-- Comment Input -->
    <div class="collaboration-panel__section collaboration-panel__comment-section">
      <div class="comment-input-wrapper">
        <textarea
          v-model="newComment"
          class="comment-input"
          placeholder="Add a comment..."
          rows="2"
        />
        <button
          class="comment-submit"
          :disabled="!newComment.trim()"
          @click="addComment"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.collaboration-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  font-family: var(--font-body);
}

.collaboration-panel__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.collaboration-panel__section-title {
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin: 0;
}

/* Member List */
.member-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.member-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2);
  background: var(--surface-soft);
  border-radius: var(--radius-md);
  transition: background-color var(--duration-fast) var(--ease-out);
}

.member-item:hover {
  background: var(--surface-cream-strong);
}

.dark .member-item:hover {
  background: var(--surface-dark-elevated);
}

.member-item__avatar-wrapper {
  position: relative;
  flex-shrink: 0;
}

.member-item__avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--hairline);
}

.member-item__status {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--surface-card);
}

.member-item__status--online {
  background-color: #7d9e7d;
}

.member-item__status--away {
  background-color: #d4a84b;
}

.member-item__status--offline {
  background-color: #8e8b82;
}

.member-item__info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.member-item__name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.member-item__role {
  font-size: var(--text-xs);
  color: var(--muted);
}

/* Activity List */
.activity-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 200px;
  overflow-y: auto;
}

.activity-item {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--surface-soft);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.dark .activity-item {
  background: var(--surface-dark-soft);
}

.activity-item__actor {
  font-weight: 600;
  color: var(--ink);
}

.activity-item__action {
  color: var(--muted);
}

.activity-item__target {
  color: var(--primary);
  font-weight: 500;
}

.activity-item__time {
  margin-left: auto;
  color: var(--muted-soft);
  flex-shrink: 0;
}

/* Quick Actions */
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.quick-action-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--body);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.quick-action-btn:hover {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--on-primary);
}

.quick-action-btn svg {
  flex-shrink: 0;
}

/* Comment Section */
.collaboration-panel__comment-section {
  margin-top: auto;
}

.comment-input-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.comment-input {
  width: 100%;
  padding: var(--space-3);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--ink);
  resize: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.comment-input::placeholder {
  color: var(--muted-soft);
}

.comment-input:focus {
  outline: none;
  border-color: var(--primary);
}

.dark .comment-input {
  background: var(--surface-dark-soft);
}

.comment-submit {
  align-self: flex-end;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--primary);
  border: none;
  border-radius: var(--radius-md);
  color: var(--on-primary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.comment-submit:hover:not(:disabled) {
  background: var(--primary-hover);
}

.comment-submit:disabled {
  background: var(--hairline);
  color: var(--muted-soft);
  cursor: not-allowed;
}
</style>
