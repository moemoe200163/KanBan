<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useLLMStore } from '~/stores/llm'
import type { ECCProfile, HarnessType, ExecutionMode, Issue } from '~/types'
import { ECC_COMMAND_MAP, COLUMN_CONFIG, PROFILE_CONFIG, HARNESS_CONFIGS } from '~/types'
import { Bot, Play, Terminal, Zap, Shield, ChevronDown } from 'lucide-vue-next'

const boardStore = useBoardStore()
const llmStore = useLLMStore()
const emit = defineEmits<{ dispatched: [jobId: string] }>()

const selectedIssueId = ref('')
const selectedProfile = ref<ECCProfile>('general')
const selectedHarness = ref<HarnessType>(boardStore.activeHarness as HarnessType)
const selectedProvider = ref<string>('')
const selectedModel = ref<string>('')
const selectedExecutionMode = ref<ExecutionMode>('safe-runner')
const isDispatching = ref(false)
const dispatchError = ref<string | null>(null)

// Load LLM providers on mount
onMounted(() => {
  llmStore.fetchProviders()
})

const availableIssues = computed(() =>
  boardStore.getAllIssues.filter(issue =>
    issue.status === 'backlog' || issue.status === 'in_progress'
  )
)

const selectedIssue = computed(() =>
  boardStore.getIssueById(selectedIssueId.value) ?? null
)

const commandPreview = computed(() => {
  if (!selectedIssue.value) return ''
  const base = ECC_COMMAND_MAP[selectedIssue.value.status] ?? '/loop-start'
  return `${base} --profile=${selectedProfile.value}`
})

const profileOptions = Object.entries(PROFILE_CONFIG).map(([key, config]) => ({
  value: key,
  label: config.label,
  color: config.color
}))

const harnessOptions = HARNESS_CONFIGS.filter(h => h.available).map(h => ({
  value: h.type,
  label: h.name
}))

const executionModeOptions: { value: ExecutionMode; label: string; icon: any; description: string }[] = [
  { value: 'safe-runner', label: 'Safe Runner', icon: Shield, description: 'Deterministic safe execution (default)' },
  { value: 'api-agent', label: 'API Agent', icon: Zap, description: 'Real LLM API execution (requires ALLOW_REAL_LLM_EXECUTION)' },
  { value: 'cli-agent', label: 'CLI Agent', icon: Terminal, description: 'CLI-based execution (requires CLI harness)' }
]

// Provider options from LLM store
const providerOptions = computed(() => [
  { value: '', label: 'Default (Safe Runner)' },
  ...llmStore.configuredProviders.map(p => ({
    value: p.id,
    label: p.name
  }))
])

// Model options based on selected provider
const modelOptions = computed(() => {
  if (!selectedProvider.value) return []
  const provider = llmStore.getProviderById(selectedProvider.value)
  if (!provider?.defaultModel) return []
  // For now, show the default model. Real model list will come from API in P2
  return [{ value: provider.defaultModel, label: provider.defaultModel }]
})

// Update execution mode when provider changes
watch(selectedProvider, (newProvider) => {
  if (newProvider) {
    selectedExecutionMode.value = 'api-agent'
  } else {
    selectedExecutionMode.value = 'safe-runner'
  }
})

// Update model when provider changes
watch(selectedProvider, () => {
  selectedModel.value = ''
})

const handleDispatch = async () => {
  if (!selectedIssue.value || isDispatching.value) return

  isDispatching.value = true
  dispatchError.value = null

  try {
    const job = await boardStore.dispatchCommand({
      issueId: selectedIssue.value.id,
      issueKey: selectedIssue.value.key,
      command: commandPreview.value,
      profile: selectedProfile.value,
      harness: selectedHarness.value,
      provider: selectedProvider.value || undefined,
      model: selectedModel.value || undefined,
      execution_mode: selectedExecutionMode.value
    })

    if (job) {
      emit('dispatched', job.id)
      selectedIssueId.value = ''
    } else {
      dispatchError.value = 'Dispatch failed. Backend may be unavailable.'
    }
  } catch (error) {
    dispatchError.value = error instanceof Error ? error.message : 'Unknown error'
  } finally {
    isDispatching.value = false
  }
}
</script>

<template>
  <div class="composer">
    <div class="composer__header">
      <Terminal :size="18" />
      <h3>Command Composer</h3>
      <span class="composer__mode-badge" :class="`composer__mode-badge--${selectedExecutionMode}`">
        {{ selectedExecutionMode === 'safe-runner' ? 'Safe Mode' : 'Real LLM' }}
      </span>
    </div>

    <div class="composer__form">
      <!-- Issue Selector -->
      <div class="composer__field">
        <label class="composer__label">Issue</label>
        <select v-model="selectedIssueId" class="composer__select" data-testid="command-issue-select">
          <option value="" disabled>Select an issue...</option>
          <option v-for="issue in availableIssues" :key="issue.id" :value="issue.id">
            {{ issue.key }} — {{ issue.title.slice(0, 50) }}{{ issue.title.length > 50 ? '...' : '' }}
          </option>
        </select>
      </div>

      <!-- Profile Selector -->
      <div class="composer__field">
        <label class="composer__label">Profile</label>
        <div class="composer__chips">
          <button
            v-for="opt in profileOptions"
            :key="opt.value"
            class="composer__chip"
            :class="{ 'composer__chip--active': selectedProfile === opt.value }"
            :style="{ '--chip-color': opt.color }"
            @click="selectedProfile = opt.value as ECCProfile"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <!-- Execution Mode Selector -->
      <div class="composer__field">
        <label class="composer__label">Execution Mode</label>
        <div class="composer__execution-modes">
          <button
            v-for="mode in executionModeOptions"
            :key="mode.value"
            :class="['composer__mode-btn', { 'composer__mode-btn--active': selectedExecutionMode === mode.value }]"
            @click="selectedExecutionMode = mode.value"
          >
            <component :is="mode.icon" :size="14" />
            <span class="composer__mode-label">{{ mode.label }}</span>
          </button>
        </div>
        <span class="composer__mode-desc">
          {{ executionModeOptions.find(m => m.value === selectedExecutionMode)?.description }}
        </span>
      </div>

      <!-- Provider Selector (shown when execution mode is api-agent) -->
      <div v-if="selectedExecutionMode === 'api-agent'" class="composer__field composer__field--inline">
        <label class="composer__label">Provider</label>
        <select v-model="selectedProvider" class="composer__select composer__select--sm">
          <option v-for="p in providerOptions" :key="p.value" :value="p.value">
            {{ p.label }}
          </option>
        </select>
      </div>

      <!-- Model Selector (shown when provider is selected) -->
      <div v-if="selectedProvider && modelOptions.length > 0" class="composer__field composer__field--inline">
        <label class="composer__label">Model</label>
        <select v-model="selectedModel" class="composer__select composer__select--sm">
          <option v-for="m in modelOptions" :key="m.value" :value="m.value">
            {{ m.label }}
          </option>
        </select>
      </div>

      <!-- Harness Selector -->
      <div class="composer__field">
        <label class="composer__label">Harness</label>
        <select v-model="selectedHarness" class="composer__select">
          <option v-for="h in harnessOptions" :key="h.value" :value="h.value">
            {{ h.label }}
          </option>
        </select>
      </div>

      <!-- Command Preview -->
      <div class="composer__field">
        <label class="composer__label">Command</label>
        <div class="composer__command-preview">
          <code>{{ commandPreview || 'Select an issue first' }}</code>
        </div>
      </div>

      <!-- Execution Summary -->
      <div class="composer__summary">
        <div class="composer__summary-row">
          <span class="composer__summary-label">Mode:</span>
          <span class="composer__summary-value">{{ selectedExecutionMode }}</span>
        </div>
        <div v-if="selectedProvider" class="composer__summary-row">
          <span class="composer__summary-label">Provider:</span>
          <span class="composer__summary-value">{{ selectedProvider }}</span>
        </div>
        <div v-if="selectedModel" class="composer__summary-row">
          <span class="composer__summary-label">Model:</span>
          <span class="composer__summary-value">{{ selectedModel }}</span>
        </div>
      </div>

      <!-- Dispatch Error -->
      <div v-if="dispatchError" class="composer__error">
        {{ dispatchError }}
      </div>

      <!-- Dispatch Button -->
      <button
        class="composer__dispatch"
        :disabled="!selectedIssue || isDispatching"
        data-testid="command-dispatch"
        @click="handleDispatch"
      >
        <Bot v-if="!isDispatching" :size="16" />
        <span v-else class="composer__spinner" />
        <span>{{ isDispatching ? 'Dispatching...' : 'Dispatch Command' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  overflow: hidden;
}

.composer__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  color: var(--ink);
  background: var(--surface-soft);
  border-bottom: 1px solid var(--hairline);
}

.composer__header h3 {
  flex: 1;
  font-family: var(--font-display);
  font-size: 0.9375rem;
  font-weight: 700;
}

.composer__mode-badge {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
}

.composer__mode-badge--safe-runner {
  background: var(--sage);
  color: white;
}

.composer__mode-badge--api-agent,
.composer__mode-badge--cli-agent {
  background: var(--amber);
  color: white;
}

.composer__form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
}

.composer__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.composer__field--inline {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.composer__field--inline .composer__label {
  min-width: 70px;
}

.composer__label {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.composer__select {
  min-height: 38px;
  padding: 0 10px;
  color: var(--ink);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
}

.composer__select--sm {
  min-height: 32px;
  flex: 1;
}

.composer__select:focus {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.composer__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.composer__chip {
  min-height: 30px;
  padding: 5px 10px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 150ms ease-out;
}

.composer__chip:hover {
  border-color: var(--chip-color, var(--muted));
  color: var(--ink);
}

.composer__chip--active {
  color: var(--on-primary);
  background: var(--chip-color, var(--primary));
  border-color: var(--chip-color, var(--primary));
}

/* Execution Mode Buttons */
.composer__execution-modes {
  display: flex;
  gap: 8px;
}

.composer__mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  color: var(--muted);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease-out;
}

.composer__mode-btn:hover {
  border-color: var(--primary);
  color: var(--ink);
}

.composer__mode-btn--active {
  color: var(--on-primary);
  background: var(--primary);
  border-color: var(--primary);
}

.composer__mode-label {
  font-weight: 600;
}

.composer__mode-desc {
  font-size: 0.75rem;
  color: var(--muted);
  font-style: italic;
}

.composer__command-preview {
  padding: 10px 12px;
  background: var(--surface-dark);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  overflow-x: auto;
}

.composer__command-preview code {
  color: var(--sage);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  font-weight: 500;
  white-space: nowrap;
}

/* Execution Summary */
.composer__summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.composer__summary-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
}

.composer__summary-label {
  color: var(--muted);
  font-family: var(--font-mono);
}

.composer__summary-value {
  color: var(--ink);
  font-weight: 500;
}

.composer__error {
  padding: 10px 12px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid rgba(184, 92, 77, 0.24);
  border-radius: 8px;
  font-size: 0.8125rem;
}

.composer__dispatch {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 8px;
  font-weight: 700;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 150ms ease-out;
}

.composer__dispatch:hover:not(:disabled) {
  background: var(--primary-hover);
}

.composer__dispatch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: var(--on-primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
