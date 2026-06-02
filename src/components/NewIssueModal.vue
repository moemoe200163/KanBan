<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import type { ECCProfile, IssueStatus, Priority } from '~/types'
import { COLUMN_CONFIG, PRIORITY_CONFIG, PROFILE_CONFIG } from '~/types'
import { X } from 'lucide-vue-next'

const boardStore = useBoardStore()

const title = ref('')
const description = ref('')
const status = ref<IssueStatus>('backlog')
const priority = ref<Priority>('medium')
const profile = ref<ECCProfile>('general')
const localError = ref('')

const resetForm = () => {
  title.value = ''
  description.value = ''
  status.value = 'backlog'
  priority.value = 'medium'
  profile.value = 'general'
  localError.value = ''
}

const close = () => {
  resetForm()
  boardStore.closeNewIssueModal()
}

const submit = async () => {
  if (!title.value.trim()) {
    localError.value = 'Title is required'
    return
  }

  const success = await boardStore.createIssueFromModal({
    title: title.value.trim(),
    description: description.value.trim(),
    status: status.value,
    priority: priority.value,
    profile: profile.value
  })

  if (success) resetForm()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="boardStore.isNewIssueModalOpen" class="new-issue" data-testid="new-issue-modal">
        <div class="new-issue__backdrop" @click="close" />
        <form class="new-issue__panel" @submit.prevent="submit">
          <header class="new-issue__header">
            <div>
              <h2>New Issue</h2>
              <p>Create a board item for the local control plane.</p>
            </div>
            <button type="button" class="new-issue__icon-btn" aria-label="Close modal" @click="close">
              <X :size="18" />
            </button>
          </header>

          <label class="new-issue__field">
            <span>Title</span>
            <input v-model="title" data-testid="new-issue-title" type="text" maxlength="200" autofocus />
          </label>

          <label class="new-issue__field">
            <span>Description</span>
            <textarea v-model="description" data-testid="new-issue-description" rows="4" maxlength="5000" />
          </label>

          <div class="new-issue__grid">
            <label class="new-issue__field">
              <span>Status</span>
              <select v-model="status" data-testid="new-issue-status">
                <option v-for="(config, key) in COLUMN_CONFIG" :key="key" :value="key">
                  {{ config.title }}
                </option>
              </select>
            </label>
            <label class="new-issue__field">
              <span>Priority</span>
              <select v-model="priority" data-testid="new-issue-priority">
                <option v-for="(config, key) in PRIORITY_CONFIG" :key="key" :value="key">
                  {{ config.label }}
                </option>
              </select>
            </label>
            <label class="new-issue__field">
              <span>Profile</span>
              <select v-model="profile" data-testid="new-issue-profile">
                <option v-for="(config, key) in PROFILE_CONFIG" :key="key" :value="key">
                  {{ config.label }}
                </option>
              </select>
            </label>
          </div>

          <p v-if="localError || boardStore.createIssueError" class="new-issue__error" data-testid="new-issue-error">
            {{ localError || boardStore.createIssueError }}
          </p>

          <footer class="new-issue__actions">
            <button type="button" class="new-issue__secondary" @click="close">Cancel</button>
            <button type="submit" class="new-issue__primary" data-testid="new-issue-submit" :disabled="boardStore.isCreatingIssue">
              {{ boardStore.isCreatingIssue ? 'Creating...' : 'Create issue' }}
            </button>
          </footer>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.new-issue {
  position: fixed;
  inset: 0;
  z-index: 140;
  display: grid;
  place-items: center;
  padding: 20px;
}

.new-issue__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 19, 0.42);
  backdrop-filter: blur(3px);
}

.new-issue__panel {
  position: relative;
  width: min(560px, 100%);
  padding: 18px;
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: var(--shadow-xl);
}

.new-issue__header,
.new-issue__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.new-issue__header {
  margin-bottom: 16px;
}

.new-issue__header h2 {
  color: var(--ink);
  font-size: 1.1rem;
  font-weight: 700;
}

.new-issue__header p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 0.84rem;
}

.new-issue__icon-btn {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  cursor: pointer;
}

.new-issue__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.new-issue__field span {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.new-issue__field input,
.new-issue__field textarea,
.new-issue__field select {
  width: 100%;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 11px;
}

.new-issue__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.new-issue__error {
  padding: 9px 10px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid rgba(184, 92, 77, 0.28);
  border-radius: 8px;
  font-size: 0.83rem;
}

.new-issue__actions {
  margin-top: 16px;
}

.new-issue__primary,
.new-issue__secondary {
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.new-issue__primary {
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
}

.new-issue__secondary {
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 160ms ease-out;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

@media (max-width: 640px) {
  .new-issue__grid {
    grid-template-columns: 1fr;
  }
}
</style>
