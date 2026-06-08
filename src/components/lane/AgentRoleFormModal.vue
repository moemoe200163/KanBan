<script setup lang="ts">
/**
 * AgentRoleFormModal — create/edit modal for agent roles.
 *
 * Props:
 *   role   — existing AgentRole to edit (null = create mode)
 *   visible — controls open/close
 *
 * Emits:
 *   close — request to close modal
 *   saved — emitted after successful create/update with the saved role
 */

import { ref, watch, computed } from 'vue'
import type { AgentRole, RetryPolicy } from '~/types'
import { X } from 'lucide-vue-next'
import { useBoardStore } from '~/stores/board'

const props = defineProps<{
  role: AgentRole | null
  visible: boolean
}>()

const emit = defineEmits<{
  'close': []
  'saved': [role: AgentRole]
}>()

const boardStore = useBoardStore()

const isEditing = computed(() => props.role !== null)

// Form fields
const key = ref('')
const displayName = ref('')
const description = ref('')
const allowedProfiles = ref('')
const defaultProvider = ref('')
const defaultModel = ref('')
const allowedCommands = ref('')
const requiredCompletionFields = ref('')
const timeoutSeconds = ref(300)
const retryPolicy = ref<RetryPolicy>('none')
const retryMax = ref(0)
const nextRoles = ref('')
const humanApprovalRequired = ref(false)
const enabled = ref(true)

const localError = ref('')
const isSaving = ref(false)

// Reset form from role prop
function resetForm() {
  if (props.role) {
    key.value = props.role.key
    displayName.value = props.role.displayName
    description.value = props.role.description
    allowedProfiles.value = props.role.allowedProfiles.join(', ')
    defaultProvider.value = props.role.defaultProvider
    defaultModel.value = props.role.defaultModel
    allowedCommands.value = props.role.allowedCommands.join(', ')
    requiredCompletionFields.value = props.role.requiredCompletionFields.join(', ')
    timeoutSeconds.value = props.role.timeoutSeconds
    retryPolicy.value = props.role.retryPolicy
    retryMax.value = props.role.retryMax
    nextRoles.value = props.role.nextRoles.join(', ')
    humanApprovalRequired.value = props.role.humanApprovalRequired
    enabled.value = props.role.enabled
  } else {
    key.value = ''
    displayName.value = ''
    description.value = ''
    allowedProfiles.value = ''
    defaultProvider.value = ''
    defaultModel.value = ''
    allowedCommands.value = ''
    requiredCompletionFields.value = ''
    timeoutSeconds.value = 300
    retryPolicy.value = 'none'
    retryMax.value = 0
    nextRoles.value = ''
    humanApprovalRequired.value = false
    enabled.value = true
  }
  localError.value = ''
}

watch(() => props.visible, (v) => { if (v) resetForm() })
watch(() => props.role, () => { if (props.visible) resetForm() })

function parseList(raw: string): string[] {
  return raw.split(',').map(s => s.trim()).filter(Boolean)
}

async function submit() {
  localError.value = ''

  if (!displayName.value.trim()) {
    localError.value = 'Display name is required'
    return
  }
  if (!isEditing.value && !key.value.trim()) {
    localError.value = 'Key is required'
    return
  }
  if (key.value && !/^[a-z0-9_\-]+$/.test(key.value)) {
    localError.value = 'Key must be lowercase alphanumeric with hyphens or underscores'
    return
  }

  const payload: Record<string, unknown> = {
    displayName: displayName.value.trim(),
    description: description.value.trim(),
    allowedProfiles: parseList(allowedProfiles.value),
    defaultProvider: defaultProvider.value.trim(),
    defaultModel: defaultModel.value.trim(),
    allowedCommands: parseList(allowedCommands.value),
    requiredCompletionFields: parseList(requiredCompletionFields.value),
    timeoutSeconds: timeoutSeconds.value,
    retryPolicy: retryPolicy.value,
    retryMax: retryMax.value,
    nextRoles: parseList(nextRoles.value),
    humanApprovalRequired: humanApprovalRequired.value,
    enabled: enabled.value,
  }

  if (!isEditing.value) {
    payload.key = key.value.trim()
  }

  isSaving.value = true
  try {
    let saved: AgentRole
    if (isEditing.value && props.role) {
      saved = await boardStore.updateAgentRole(props.role.key, payload)
    } else {
      saved = await boardStore.createAgentRole(payload)
    }
    emit('saved', saved)
    emit('close')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    localError.value = msg || 'Save failed'
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="visible" class="agent-role-modal" data-testid="agent-role-form-modal">
        <div class="agent-role-modal__backdrop" @click="emit('close')" />
        <form class="agent-role-modal__panel" @submit.prevent="submit">
          <header class="agent-role-modal__header">
            <div>
              <h2>{{ isEditing ? 'Edit Agent Role' : 'New Agent Role' }}</h2>
              <p>{{ isEditing ? 'Update role configuration' : 'Define a new agent role' }}</p>
            </div>
            <button
              type="button"
              class="agent-role-modal__icon-btn"
              aria-label="Close modal"
              @click="emit('close')"
            >
              <X :size="18" />
            </button>
          </header>

          <div class="agent-role-modal__body">
            <!-- Key -->
            <label class="agent-role-modal__field">
              <span>Key</span>
              <input
                v-model="key"
                type="text"
                :disabled="isEditing"
                placeholder="e.g. reviewer"
                class="disabled:opacity-50"
              />
            </label>

            <!-- Display Name -->
            <label class="agent-role-modal__field">
              <span>Display Name</span>
              <input v-model="displayName" type="text" placeholder="e.g. Reviewer" />
            </label>

            <!-- Description -->
            <label class="agent-role-modal__field">
              <span>Description</span>
              <textarea v-model="description" rows="2" placeholder="Short description" />
            </label>

            <!-- Provider / Model row -->
            <div class="agent-role-modal__row">
              <label class="agent-role-modal__field">
                <span>Default Provider</span>
                <input v-model="defaultProvider" type="text" placeholder="e.g. anthropic" />
              </label>
              <label class="agent-role-modal__field">
                <span>Default Model</span>
                <input v-model="defaultModel" type="text" placeholder="e.g. claude-opus-4-6" />
              </label>
            </div>

            <!-- Allowed Profiles -->
            <label class="agent-role-modal__field">
              <span>Allowed Profiles (comma-separated)</span>
              <input v-model="allowedProfiles" type="text" placeholder="e.g. frontend, backend" />
            </label>

            <!-- Allowed Commands -->
            <label class="agent-role-modal__field">
              <span>Allowed Commands (comma-separated)</span>
              <input v-model="allowedCommands" type="text" placeholder="e.g. /loop-start, /quality-gate" />
            </label>

            <!-- Required Completion Fields -->
            <label class="agent-role-modal__field">
              <span>Required Completion Fields (comma-separated)</span>
              <input v-model="requiredCompletionFields" type="text" placeholder="e.g. pr_url, tests_pass" />
            </label>

            <!-- Timeout / Retry row -->
            <div class="agent-role-modal__row">
              <label class="agent-role-modal__field">
                <span>Timeout (seconds)</span>
                <input v-model.number="timeoutSeconds" type="number" min="0" />
              </label>
              <label class="agent-role-modal__field">
                <span>Retry Policy</span>
                <select v-model="retryPolicy">
                  <option value="none">None</option>
                  <option value="fixed">Fixed</option>
                  <option value="exponential">Exponential</option>
                </select>
              </label>
              <label class="agent-role-modal__field">
                <span>Max Retries</span>
                <input v-model.number="retryMax" type="number" min="0" />
              </label>
            </div>

            <!-- Next Roles -->
            <label class="agent-role-modal__field">
              <span>Next Roles (comma-separated keys)</span>
              <input v-model="nextRoles" type="text" placeholder="e.g. reviewer, deployer" />
            </label>

            <!-- Checkboxes -->
            <div class="agent-role-modal__checks">
              <label class="agent-role-modal__check">
                <input v-model="humanApprovalRequired" type="checkbox" />
                <span>Human approval required</span>
              </label>
              <label class="agent-role-modal__check">
                <input v-model="enabled" type="checkbox" />
                <span>Enabled</span>
              </label>
            </div>

            <!-- Error -->
            <p
              v-if="localError"
              class="agent-role-modal__error"
              data-testid="agent-role-form-error"
            >
              {{ localError }}
            </p>
          </div>

          <footer class="agent-role-modal__actions">
            <button
              type="button"
              class="agent-role-modal__secondary"
              @click="emit('close')"
            >
              Cancel
            </button>
            <button
              type="submit"
              class="agent-role-modal__primary"
              data-testid="agent-role-form-submit"
              :disabled="isSaving"
            >
              {{ isSaving ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Role' }}
            </button>
          </footer>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.agent-role-modal {
  position: fixed;
  inset: 0;
  z-index: 140;
  display: grid;
  place-items: center;
  padding: 20px;
}

.agent-role-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 19, 0.42);
  backdrop-filter: blur(3px);
}

.agent-role-modal__panel {
  position: relative;
  width: min(600px, 100%);
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
  padding: 18px;
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: var(--shadow-xl);
}

.agent-role-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.agent-role-modal__header h2 {
  color: var(--ink);
  font-size: 1.1rem;
  font-weight: 700;
}

.agent-role-modal__header p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 0.84rem;
}

.agent-role-modal__icon-btn {
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

.agent-role-modal__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-role-modal__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.agent-role-modal__field span {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.agent-role-modal__field input,
.agent-role-modal__field textarea,
.agent-role-modal__field select {
  width: 100%;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 11px;
  font-size: 0.875rem;
}

.agent-role-modal__row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.agent-role-modal__checks {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.agent-role-modal__check {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink);
  font-size: 0.875rem;
  cursor: pointer;
}

.agent-role-modal__check input {
  accent-color: var(--primary);
}

.agent-role-modal__error {
  padding: 9px 10px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid rgba(184, 92, 77, 0.28);
  border-radius: 8px;
  font-size: 0.83rem;
}

.agent-role-modal__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--hairline);
}

.agent-role-modal__primary,
.agent-role-modal__secondary {
  min-height: 36px;
  padding: 8px 14px;
  border-radius: 8px;
  font-weight: 700;
  font-size: 0.875rem;
  cursor: pointer;
}

.agent-role-modal__primary {
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
}

.agent-role-modal__primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.agent-role-modal__secondary {
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
</style>
