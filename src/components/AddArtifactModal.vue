<script setup lang="ts">
import { useCollaborationStore } from '~/stores/collaboration'
import type { IssueArtifact } from '~/types'
import { X } from 'lucide-vue-next'

const props = defineProps<{
  issueId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const collaborationStore = useCollaborationStore()

const title = ref('')
const artifactType = ref<IssueArtifact['artifactType']>('file')
const pathOrUrl = ref('')
const summary = ref('')
const localError = ref('')
const isSubmitting = ref(false)

const ARTIFACT_TYPES: { value: IssueArtifact['artifactType']; label: string }[] = [
  { value: 'file', label: 'File' },
  { value: 'screenshot', label: 'Screenshot' },
  { value: 'test_log', label: 'Test Log' },
  { value: 'pr_link', label: 'PR Link' },
  { value: 'design_doc', label: 'Design Doc' },
  { value: 'diff_summary', label: 'Diff Summary' },
  { value: 'command_output', label: 'Command Output' },
]

const resetForm = () => {
  title.value = ''
  artifactType.value = 'file'
  pathOrUrl.value = ''
  summary.value = ''
  localError.value = ''
}

const close = () => {
  resetForm()
  emit('close')
}

const submit = async () => {
  if (!title.value.trim()) {
    localError.value = 'Title is required'
    return
  }

  isSubmitting.value = true
  localError.value = ''
  try {
    await collaborationStore.createArtifact(props.issueId, {
      title: title.value.trim(),
      artifactType: artifactType.value,
      pathOrUrl: pathOrUrl.value.trim() || undefined,
      summary: summary.value.trim() || undefined,
    })
    close()
  } catch (err) {
    localError.value = err instanceof Error ? err.message : 'Failed to create artifact'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="add-artifact" data-testid="add-artifact-modal">
      <div class="add-artifact__backdrop" @click="close" />
      <form class="add-artifact__panel" @submit.prevent="submit">
        <header class="add-artifact__header">
          <div>
            <h2>Add Artifact</h2>
            <p>Link a file, screenshot, PR, or other reference.</p>
          </div>
          <button type="button" class="add-artifact__icon-btn" aria-label="Close modal" @click="close">
            <X :size="18" />
          </button>
        </header>

        <label class="add-artifact__field">
          <span>Title</span>
          <input v-model="title" data-testid="artifact-title" type="text" maxlength="200" autofocus />
        </label>

        <label class="add-artifact__field">
          <span>Type</span>
          <select v-model="artifactType" data-testid="artifact-type">
            <option v-for="t in ARTIFACT_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </label>

        <label class="add-artifact__field">
          <span>Path or URL <small>(optional)</small></span>
          <input v-model="pathOrUrl" data-testid="artifact-path" type="text" maxlength="500" />
        </label>

        <label class="add-artifact__field">
          <span>Summary <small>(optional)</small></span>
          <textarea v-model="summary" data-testid="artifact-summary" rows="3" maxlength="5000" />
        </label>

        <p v-if="localError" class="add-artifact__error" data-testid="artifact-error">
          {{ localError }}
        </p>

        <footer class="add-artifact__actions">
          <button type="button" class="add-artifact__secondary" @click="close">Cancel</button>
          <button type="submit" class="add-artifact__primary" data-testid="artifact-submit" :disabled="isSubmitting">
            {{ isSubmitting ? 'Creating...' : 'Create' }}
          </button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.add-artifact {
  position: fixed;
  inset: 0;
  z-index: 140;
  display: grid;
  place-items: center;
  padding: 20px;
}

.add-artifact__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 19, 0.42);
  backdrop-filter: blur(3px);
}

.add-artifact__panel {
  position: relative;
  width: min(480px, 100%);
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
  padding: 18px;
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: var(--shadow-xl);
}

.add-artifact__header,
.add-artifact__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.add-artifact__header {
  margin-bottom: 16px;
}

.add-artifact__header h2 {
  color: var(--ink);
  font-size: 1.1rem;
  font-weight: 700;
}

.add-artifact__header p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 0.84rem;
}

.add-artifact__icon-btn {
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

.add-artifact__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.add-artifact__field span {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.add-artifact__field small {
  font-weight: 400;
  text-transform: none;
}

.add-artifact__field input,
.add-artifact__field textarea,
.add-artifact__field select {
  width: 100%;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 11px;
}

.add-artifact__error {
  padding: 9px 10px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid rgba(184, 92, 77, 0.28);
  border-radius: 8px;
  font-size: 0.83rem;
}

.add-artifact__actions {
  margin-top: 16px;
}

.add-artifact__primary,
.add-artifact__secondary {
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.add-artifact__primary {
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
}

.add-artifact__secondary {
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
}
</style>
