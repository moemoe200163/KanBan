<script setup lang="ts">
import { useCollaborationStore } from '~/stores/collaboration'
import type { IssueEvent, IssueComment, IssueArtifact } from '~/types'
import { MessageSquare, Clock, Package, Send } from 'lucide-vue-next'

const props = defineProps<{
  issueId: string
}>()

const collaborationStore = useCollaborationStore()

const newComment = ref('')
const isSubmitting = ref(false)

// Fetch data when component mounts
onMounted(async () => {
  await Promise.all([
    collaborationStore.fetchEvents(props.issueId),
    collaborationStore.fetchComments(props.issueId),
    collaborationStore.fetchArtifacts(props.issueId)
  ])
})

const events = computed(() => collaborationStore.getEventsByIssue(props.issueId))
const comments = computed(() => collaborationStore.getCommentsByIssue(props.issueId))
const artifacts = computed(() => collaborationStore.getArtifactsByIssue(props.issueId))

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const eventTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    comment: 'Comment',
    status_change: 'Status Change',
    artifact_added: 'Artifact Added',
    handoff: 'Handoff',
    decision: 'Decision'
  }
  return labels[type] || type
}

const artifactTypeIcon = (type: string) => {
  const icons: Record<string, string> = {
    file: '📄',
    screenshot: '🖼️',
    test_log: '📋',
    pr_link: '🔗',
    design_doc: '📝',
    diff_summary: '📊',
    command_output: '💻'
  }
  return icons[type] || '📦'
}

const submitComment = async () => {
  if (!newComment.value.trim() || isSubmitting.value) return

  isSubmitting.value = true
  try {
    await collaborationStore.createComment(props.issueId, newComment.value.trim())
    newComment.value = ''
  } catch (error) {
    console.error('Failed to submit comment:', error)
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="collab-tab">
    <!-- Events Timeline -->
    <div class="collab-section">
      <h4 class="collab-section__title">
        <Clock :size="14" />
        Timeline
        <span v-if="events.length > 0" class="collab-section__count">{{ events.length }}</span>
      </h4>
      <div v-if="events.length === 0" class="collab-empty">No events yet</div>
      <div v-else class="collab-timeline">
        <div
          v-for="event in events"
          :key="event.id"
          class="collab-timeline__item"
        >
          <div class="collab-timeline__dot" />
          <div class="collab-timeline__content">
            <span class="collab-timeline__type">{{ eventTypeLabel(event.eventType) }}</span>
            <span class="collab-timeline__summary">{{ event.summary }}</span>
            <span class="collab-timeline__time">{{ formatDate(event.createdAt) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Comments -->
    <div class="collab-section">
      <h4 class="collab-section__title">
        <MessageSquare :size="14" />
        Notes
        <span v-if="comments.length > 0" class="collab-section__count">{{ comments.length }}</span>
      </h4>
      <div v-if="comments.length === 0" class="collab-empty">No comments yet</div>
      <div v-else class="collab-comments">
        <div
          v-for="comment in comments"
          :key="comment.id"
          class="collab-comment"
        >
          <div class="collab-comment__header">
            <span class="collab-comment__author">{{ comment.authorName || 'Anonymous' }}</span>
            <span class="collab-comment__type" :class="`collab-comment__type--${comment.commentType}`">
              {{ comment.commentType }}
            </span>
            <span class="collab-comment__time">{{ formatDate(comment.createdAt) }}</span>
          </div>
          <p class="collab-comment__body">{{ comment.body }}</p>
        </div>
      </div>

      <!-- Comment Input -->
      <div class="collab-comment-input">
        <textarea
          v-model="newComment"
          placeholder="Add a note..."
          class="collab-comment-input__field"
          rows="3"
          @keydown.meta.enter="submitComment"
          @keydown.ctrl.enter="submitComment"
        />
        <button
          class="collab-comment-input__submit"
          :disabled="!newComment.trim() || isSubmitting"
          @click="submitComment"
        >
          <Send :size="14" />
          {{ isSubmitting ? 'Sending...' : 'Send' }}
        </button>
      </div>
    </div>

    <!-- Artifacts -->
    <div class="collab-section">
      <h4 class="collab-section__title">
        <Package :size="14" />
        Artifacts
        <span v-if="artifacts.length > 0" class="collab-section__count">{{ artifacts.length }}</span>
      </h4>
      <div v-if="artifacts.length === 0" class="collab-empty">No artifacts yet</div>
      <div v-else class="collab-artifacts">
        <div
          v-for="artifact in artifacts"
          :key="artifact.id"
          class="collab-artifact"
        >
          <span class="collab-artifact__icon">{{ artifactTypeIcon(artifact.artifactType) }}</span>
          <div class="collab-artifact__info">
            <span class="collab-artifact__title">{{ artifact.title }}</span>
            <span class="collab-artifact__meta">
              {{ artifact.artifactType }}
              <template v-if="artifact.createdByName"> by {{ artifact.createdByName }}</template>
              <template v-if="artifact.sensitivity !== 'public'"> · {{ artifact.sensitivity }}</template>
            </span>
          </div>
          <span class="collab-artifact__time">{{ formatDate(artifact.createdAt) }}</span>
        </div>
      </div>
    </div>

    <!-- Comment Input -->
    <div class="collab-input">
      <textarea
        v-model="newComment"
        class="collab-input__field"
        placeholder="Add a note..."
        rows="2"
        @keydown.meta.enter="submitComment"
      />
      <button
        class="collab-input__submit"
        :disabled="!newComment.trim() || isSubmitting"
        @click="submitComment"
      >
        <Send :size="14" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.collab-tab {
  padding: 16px 0;
}

.collab-section {
  margin-bottom: 24px;
}

.collab-section__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
}

.collab-section__count {
  background: var(--color-surface-hover);
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
}

.collab-empty {
  color: var(--color-text-tertiary);
  font-size: 13px;
  font-style: italic;
}

/* Timeline */
.collab-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.collab-timeline__item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.collab-timeline__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
  margin-top: 5px;
  flex-shrink: 0;
}

.collab-timeline__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.collab-timeline__type {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
}

.collab-timeline__summary {
  font-size: 13px;
  color: var(--color-text-primary);
}

.collab-timeline__time {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

/* Comments */
.collab-comments {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.collab-comment {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
}

.collab-comment__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.collab-comment__author {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.collab-comment__type {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  text-transform: uppercase;
}

.collab-comment__type--handoff {
  background: rgba(107, 139, 164, 0.2);
  color: #6b8ba4;
}

.collab-comment__type--decision {
  background: rgba(125, 158, 125, 0.2);
  color: #7d9e7d;
}

/* Artifacts */
.collab-artifacts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.collab-artifact {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 6px;
}

.collab-artifact__icon {
  font-size: 16px;
}

.collab-artifact__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.collab-artifact__title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
}

.collab-artifact__meta {
  font-size: 11px;
  color: var(--color-text-tertiary);
  text-transform: capitalize;
}

.collab-artifact__time {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

/* Comment Input */
.collab-input {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.collab-input__field {
  flex: 1;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--color-text-primary);
  resize: none;
  font-family: inherit;
}

.collab-input__field:focus {
  outline: none;
  border-color: var(--color-accent);
}

.collab-input__submit {
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s;
}

.collab-input__submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.collab-input__submit:not(:disabled):hover {
  opacity: 0.9;
}
</style>
