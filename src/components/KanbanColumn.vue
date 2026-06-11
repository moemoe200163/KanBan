<script setup lang="ts">
import type { Column, Issue } from '~/types'
import { Plus, X, Check } from 'lucide-vue-next'

interface Props {
  column: Column
}

const props = defineProps<Props>()

const emit = defineEmits<{
  cardClick: [issue: Issue]
  drop: [issueId: string, newIndex: number]
  retry: [issueId: string]
  start: [issueId: string]
  create: [title: string, columnId: string]
}>()

const isDragOver = ref(false)
const isCreating = ref(false)
const newIssueTitle = ref('')
const createInput = ref<HTMLInputElement | null>(null)

const handleDragOver = (e: DragEvent) => {
  e.preventDefault()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'move'
  }
  isDragOver.value = true
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (e: DragEvent) => {
  e.preventDefault()
  isDragOver.value = false

  const issueId = e.dataTransfer?.getData('text/plain')
  if (issueId) {
    emit('drop', issueId, props.column.issues.length)
  }
}

const handleCardDrop = (e: DragEvent, index: number) => {
  e.preventDefault()
  e.stopPropagation()
  isDragOver.value = false

  const issueId = e.dataTransfer?.getData('text/plain')
  if (issueId) {
    emit('drop', issueId, index)
  }
}

const handleIssueCardDrop = (event: Event, index: number) => {
  handleCardDrop(event as DragEvent, index)
}

const startCreate = () => {
  isCreating.value = true
  nextTick(() => {
    createInput.value?.focus()
  })
}

const cancelCreate = () => {
  isCreating.value = false
  newIssueTitle.value = ''
}

const submitCreate = () => {
  const title = newIssueTitle.value.trim()
  if (title) {
    emit('create', title, props.column.id)
    newIssueTitle.value = ''
    isCreating.value = false
  }
}

const handleCreateKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    submitCreate()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    cancelCreate()
  }
}
</script>

<template>
  <div
    :class="['kanban-column', { 'kanban-column--drag-over': isDragOver }]"
    :data-testid="`kanban-column-${column.id}`"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <div class="kanban-column__header">
      <div class="kanban-column__title-row">
        <span class="kanban-column__stripe" :style="{ backgroundColor: column.color }" />
        <div>
          <h2 class="kanban-column__title">{{ column.title }}</h2>
          <span class="kanban-column__hint">{{ column.id.replace('_', ' ') }}</span>
        </div>
      </div>
      <span class="kanban-column__count">{{ column.issues.length }}</span>
    </div>

    <div class="kanban-column__cards">
      <IssueCard
        v-for="(issue, index) in column.issues"
        :key="issue.id"
        :issue="issue"
        :data-issue-id="issue.id"
        draggable="true"
        @select="emit('cardClick', issue)"
        @retry="emit('retry', $event)"
        @start="emit('start', $event)"
        @archive="emit('archive', $event)"
        @unarchive="emit('unarchive', $event)"
        @dragover.prevent
        @drop="handleIssueCardDrop($event, index)"
      />

      <div v-if="column.issues.length === 0 && !isCreating" class="kanban-column__empty">
        <span class="kanban-column__empty-text">Drop issues here</span>
      </div>

      <div v-if="isCreating" class="kanban-column__create-form">
        <input
          ref="createInput"
          v-model="newIssueTitle"
          type="text"
          :aria-label="`Issue title for ${column.title}`"
          placeholder="Issue title..."
          class="kanban-column__create-input"
          @keydown="handleCreateKeydown"
        />
        <div class="kanban-column__create-actions">
          <button
            class="kanban-column__create-btn kanban-column__create-btn--submit"
            :aria-label="`Create issue in ${column.title}`"
            @click="submitCreate"
          >
            <Check class="w-4 h-4" />
          </button>
          <button
            class="kanban-column__create-btn kanban-column__create-btn--cancel"
            aria-label="Cancel issue creation"
            @click="cancelCreate"
          >
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <button
        v-if="!isCreating"
        class="kanban-column__add-btn"
        @click="startCreate"
      >
        <Plus class="w-4 h-4" />
        <span>Add Issue</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.kanban-column {
  display: flex;
  flex-direction: column;
  min-width: 272px;
  height: 100%;
  min-height: 0;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 150ms ease-out, background 150ms ease-out, box-shadow 150ms ease-out;
  scroll-snap-align: start;
}

.kanban-column--drag-over {
  border-color: var(--primary);
  background: rgba(204, 120, 92, 0.06);
  box-shadow: 0 0 0 2px rgba(204, 120, 92, 0.15);
}

.kanban-column--drag-over .kanban-column__cards {
  background: rgba(204, 120, 92, 0.04);
}

.kanban-column__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 58px;
  padding: 12px;
  border-bottom: 1px solid var(--hairline);
  background: var(--surface-card);
  flex-shrink: 0;
}

.kanban-column__title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.kanban-column__stripe {
  width: 4px;
  height: 32px;
  border-radius: 999px;
  flex-shrink: 0;
}

.kanban-column__title {
  overflow: hidden;
  max-width: 150px;
  color: var(--ink);
  font-size: 0.875rem;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kanban-column__hint {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}

.kanban-column__count {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  padding: 3px 8px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 999px;
}

.kanban-column__cards {
  flex: 1;
  min-height: 0;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  transition: background 150ms ease-out;
}

.kanban-column__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 84px;
  padding: 18px 12px;
  border: 1px dashed var(--hairline);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.36);
}

.kanban-column__empty-text {
  font-size: 0.8125rem;
  color: var(--muted-soft);
}

.kanban-column__create-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  background: var(--surface-card);
  border: 1px solid var(--primary);
  border-radius: 8px;
  box-shadow: 0 0 0 2px rgba(204, 120, 92, 0.1);
}

.kanban-column__create-input {
  width: 100%;
  padding: 8px;
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: 0.875rem;
  color: var(--ink);
  outline: none;
}

.kanban-column__create-input::placeholder {
  color: var(--muted);
}

.kanban-column__create-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}

.kanban-column__create-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 150ms ease-out;
}

.kanban-column__create-btn--submit {
  background: var(--primary);
  color: white;
}

.kanban-column__create-btn--submit:hover {
  background: var(--primary-hover);
}

.kanban-column__create-btn--cancel {
  background: var(--surface-soft);
  color: var(--muted);
}

.kanban-column__create-btn--cancel:hover {
  background: var(--surface-card);
  color: var(--ink);
}

.kanban-column__add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  border: 1px dashed var(--hairline);
  background: transparent;
  border-radius: 8px;
  font-family: var(--font-body);
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  transition: all 150ms ease-out;
}

.kanban-column__add-btn:hover {
  background: var(--surface-soft);
  color: var(--ink);
  border-color: var(--muted-soft);
}
</style>
