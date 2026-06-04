<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useLLMStore } from '~/stores/llm'
import { useDarkMode } from '~/composables/useDarkMode'
import { HARNESS_CONFIGS } from '~/types'
import type { LLMProvider, HarnessType } from '~/types'
import {
  Check, Loader2, RefreshCw, Server, Settings, X,
  Zap, Shield, Code, MessageSquare, Eye, Terminal,
  ChevronDown, ChevronRight, AlertCircle, CheckCircle2,
  Power, PowerOff, Star, Activity
} from 'lucide-vue-next'

const boardStore = useBoardStore()
const llmStore = useLLMStore()
const { isDark, toggleDark } = useDarkMode()
const config = useRuntimeConfig()

const apiBase = ref(config.public.apiBase)
const activeTab = ref<'system' | 'providers' | 'defaults' | 'appearance'>('system')
const backendStatus = ref<'checking' | 'healthy' | 'error'>('checking')
const expandedProvider = ref<string | null>(null)
const testingProvider = ref<string | null>(null)
const savingDefaults = ref(false)
const editingKeyFor = ref<string | null>(null)
const newApiKey = ref('')

const harnessOptions = HARNESS_CONFIGS.filter(h => h.available).map(h => h.type)
const selectedHarness = ref<HarnessType>(boardStore.activeHarness)

// Capability icons
const capabilityIcons: Record<string, any> = {
  chat: MessageSquare,
  code: Code,
  'tool-use': Zap,
  streaming: Activity,
  vision: Eye,
  cli: Terminal
}
const healthStatusLabel = (status: string | null) => {
  switch (status) {
    case 'healthy': return 'Healthy'
    case 'auth_error': return 'Auth Error'
    case 'billing_error': return 'Billing Error'
    case 'model_error': return 'Model Error'
    case 'rate_limited': return 'Rate Limited'
    case 'endpoint_error': return 'Endpoint Error'
    case 'timeout': return 'Timeout'
    case 'not_configured': return 'Not Configured'
    case 'unhealthy': return 'Unhealthy'
    default: return 'Unknown'
  }
}

const healthStatusColor = (status: string | null) => {
  switch (status) {
    case 'healthy': return 'var(--sage)'
    case 'auth_error':
    case 'billing_error':
    case 'model_error': return 'var(--clay-red)'
    case 'rate_limited': return 'var(--amber)'
    case 'endpoint_error':
    case 'timeout': return 'var(--amber)'
    case 'not_configured': return 'var(--muted)'
    default: return 'var(--muted)'
  }
}

const startEditKey = (provider: LLMProvider) => {
  editingKeyFor.value = provider.id
  newApiKey.value = ''
}

const saveApiKey = async (provider: LLMProvider) => {
  if (!newApiKey.value) return
  await llmStore.updateProviderConfig(provider.id, { apiKey: newApiKey.value })
  editingKeyFor.value = null
  newApiKey.value = ''
}

const updateBaseUrl = async (provider: LLMProvider, baseUrl: string) => {
  await llmStore.updateProviderConfig(provider.id, { baseUrl })
}

const updateModel = async (provider: LLMProvider, model: string) => {
  await llmStore.updateProviderConfig(provider.id, { model })
}

const selectProviderAction = async (providerId: string) => {
  await llmStore.selectProvider(providerId)
}

const formatTime = (iso: string) => {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// Backend health check
const checkBackend = async () => {
  backendStatus.value = 'checking'
  try {
    const healthUrl = apiBase.value.replace('/api/v1', '/health')
    const res = await fetch(healthUrl)
    backendStatus.value = res.ok ? 'healthy' : 'error'
  } catch {
    backendStatus.value = 'error'
  }
}

// Provider actions
const toggleExpand = (providerId: string) => {
  expandedProvider.value = expandedProvider.value === providerId ? null : providerId
}

const testConnection = async (providerId: string) => {
  testingProvider.value = providerId
  await llmStore.testHealth(providerId)
  testingProvider.value = null
}

const toggleProviderEnabled = async (provider: LLMProvider) => {
  await llmStore.updateProviderConfig(provider.id, { enabled: !provider.enabled })
}

// Defaults form
const defaultsForm = reactive({
  providerId: '',
  modelId: '',
  harness: 'safe-runner' as HarnessType,
  maxRuntimeSeconds: 300,
  tokenBudget: null as number | null,
  costBudget: null as number | null,
  streamingLogs: true
})

const loadDefaults = () => {
  if (llmStore.defaults) {
    Object.assign(defaultsForm, llmStore.defaults)
  }
}

const saveDefaults = async () => {
  savingDefaults.value = true
  await llmStore.updateDefaults({ ...defaultsForm })
  savingDefaults.value = false
}

const saveHarness = () => {
  boardStore.setHarness(selectedHarness.value)
}

// Initialize
onMounted(async () => {
  checkBackend()
  await Promise.all([
    llmStore.fetchProviders(),
    llmStore.fetchDefaults()
  ])
  loadDefaults()
})

watch(() => llmStore.defaults, loadDefaults)

const backendStatusColor = computed(() => {
  switch (backendStatus.value) {
    case 'healthy': return 'var(--sage)'
    case 'error': return 'var(--clay-red)'
    default: return 'var(--amber)'
  }
})
</script>

<template>
  <section class="settings-page">
    <header class="settings-page__topbar">
      <div class="settings-page__title">
        <span class="settings-page__kicker">Workspace / DevFlow</span>
        <h1>Settings</h1>
        <p>System configuration, LLM providers, and execution defaults</p>
      </div>
    </header>

    <!-- Tab Navigation -->
    <nav class="settings-tabs">
      <button
        v-for="tab in [
          { id: 'system', label: 'System', icon: Server },
          { id: 'providers', label: 'LLM Providers', icon: Zap },
          { id: 'defaults', label: 'Execution Defaults', icon: Settings },
          { id: 'appearance', label: 'Appearance', icon: Eye }
        ]"
        :key="tab.id"
        :class="['settings-tab', { 'settings-tab--active': activeTab === tab.id }]"
        @click="activeTab = tab.id as any"
      >
        <component :is="tab.icon" :size="16" />
        {{ tab.label }}
      </button>
    </nav>

    <!-- System Tab -->
    <div v-if="activeTab === 'system'" class="settings-content">
      <div class="settings-card">
        <div class="settings-card__header">
          <Server :size="18" />
          <h3>Backend Status</h3>
          <button class="settings-card__action" @click="checkBackend">
            <RefreshCw :size="14" />
          </button>
        </div>
        <div class="settings-card__body">
          <div class="status-row">
            <span class="status-dot" :style="{ background: backendStatusColor }" />
            <span class="status-text">
              {{ backendStatus === 'checking' ? 'Checking...' : backendStatus === 'healthy' ? 'Connected' : 'Unreachable' }}
            </span>
          </div>
          <div class="field">
            <label>API Base URL</label>
            <input v-model="apiBase" type="text" class="field__input" readonly />
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card__header">
          <Settings :size="18" />
          <h3>Active Harness</h3>
        </div>
        <div class="settings-card__body">
          <div class="field">
            <label>Default Harness</label>
            <select v-model="selectedHarness" class="field__input">
              <option v-for="h in harnessOptions" :key="h" :value="h">{{ h }}</option>
            </select>
          </div>
          <button class="settings-btn" @click="saveHarness">Save</button>
        </div>
      </div>
    </div>

    <!-- LLM Providers Tab -->
    <div v-if="activeTab === 'providers'" class="settings-content">
      <div v-if="llmStore.isLoading" class="settings-loading">
        <Loader2 :size="24" class="spin" />
        <span>Loading providers...</span>
      </div>

      <div v-else-if="llmStore.error" class="settings-error">
        <AlertCircle :size="20" />
        <span>{{ llmStore.error }}</span>
        <button class="settings-btn settings-btn--sm" @click="llmStore.fetchProviders()">Retry</button>
      </div>

      <div v-else class="providers-grid">
        <div
          v-for="provider in llmStore.providers"
          :key="provider.id"
          :class="['provider-card', { 'provider-card--expanded': expandedProvider === provider.id }]"
        >
          <!-- Provider Header -->
          <div class="provider-card__header" @click="toggleExpand(provider.id)">
            <div class="provider-card__info">
              <span class="provider-card__name">{{ provider.name }}</span>
              <span class="provider-card__adapter">{{ provider.adapter }}</span>
            </div>
            <div class="provider-card__status">
              <span
                class="health-badge"
                :class="`health-badge--${provider.lastTestStatus || provider.healthStatus || 'unknown'}`"
              >
                {{ healthStatusLabel(provider.lastTestStatus || provider.healthStatus) }}
              </span>
              <component :is="expandedProvider === provider.id ? ChevronDown : ChevronRight" :size="16" />
            </div>
          </div>

          <!-- Provider Summary -->
          <div class="provider-card__summary">
            <div class="provider-card__model">
              <span class="label">Model:</span>
              <span class="value">{{ provider.model || provider.defaultModel || 'Not set' }}</span>
            </div>
            <div class="provider-card__caps">
              <span
                v-for="cap in provider.capabilities"
                :key="cap"
                class="cap-tag"
                :title="cap"
              >
                <component :is="capabilityIcons[cap] || Code" :size="12" />
              </span>
            </div>
          </div>

          <!-- Expanded Details -->
          <div v-if="expandedProvider === provider.id" class="provider-card__details">
            <!-- Base URL -->
            <div class="provider-detail-row">
              <span class="label">Base URL:</span>
              <input
                :value="provider.baseUrl || ''"
                class="field__input field__input--sm"
                placeholder="API base URL"
                @change="updateBaseUrl(provider, ($event.target as HTMLInputElement).value)"
              />
            </div>

            <!-- Model -->
            <div class="provider-detail-row">
              <span class="label">Model:</span>
              <input
                :value="provider.model || provider.defaultModel || ''"
                class="field__input field__input--sm"
                placeholder="Model name"
                @change="updateModel(provider, ($event.target as HTMLInputElement).value)"
              />
            </div>

            <!-- API Key -->
            <div class="provider-detail-row">
              <span class="label">API Key:</span>
              <div class="api-key-field">
                <input
                  v-if="editingKeyFor === provider.id"
                  v-model="newApiKey"
                  type="text"
                  class="field__input field__input--sm"
                  placeholder="Enter API key"
                  @keyup.enter="saveApiKey(provider)"
                />
                <code v-else class="env-var">{{ provider.maskedSecret || 'Not configured' }}</code>
                <button
                  v-if="editingKeyFor === provider.id"
                  class="action-btn action-btn--save"
                  @click="saveApiKey(provider)"
                >Save</button>
                <button
                  v-else
                  class="action-btn action-btn--edit"
                  @click="startEditKey(provider)"
                >Edit</button>
              </div>
            </div>

            <!-- Warning about key types -->
            <div class="provider-warning">
              <AlertCircle :size="14" />
              <span>Provider keys (sk-cp-...) are LLM API credentials, NOT SecurityWeb Access Keys.</span>
            </div>

            <!-- Last Test Info -->
            <div v-if="provider.lastTestStatus" class="provider-detail-row">
              <span class="label">Last Test:</span>
              <span class="value">
                {{ healthStatusLabel(provider.lastTestStatus) }}
                <span v-if="provider.lastLatencyMs"> · {{ provider.lastLatencyMs }}ms</span>
                <span v-if="provider.lastChecked"> · {{ formatTime(provider.lastChecked) }}</span>
              </span>
            </div>
            <div v-if="provider.lastErrorMessage" class="provider-detail-row">
              <span class="label">Error:</span>
              <span class="value provider-error">{{ provider.lastErrorMessage }}</span>
            </div>

            <!-- Actions -->
            <div class="provider-card__actions">
              <button
                class="action-btn action-btn--test"
                :disabled="testingProvider === provider.id"
                @click.stop="testConnection(provider.id)"
              >
                <Loader2 v-if="testingProvider === provider.id" :size="14" class="spin" />
                <Zap v-else :size="14" />
                Test
              </button>
              <button
                class="action-btn action-btn--default"
                @click.stop="selectProviderAction(provider.id)"
              >
                <Star :size="14" />
                Select Active
              </button>
              <button
                :class="['action-btn', provider.enabled ? 'action-btn--disable' : 'action-btn--enable']"
                @click.stop="toggleProviderEnabled(provider)"
              >
                <PowerOff v-if="provider.enabled" :size="14" />
                <Power v-else :size="14" />
                {{ provider.enabled ? 'Disable' : 'Enable' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Execution Defaults Tab -->
    <div v-if="activeTab === 'defaults'" class="settings-content">
      <div class="settings-card settings-card--full">
        <div class="settings-card__header">
          <Settings :size="18" />
          <h3>Execution Defaults</h3>
        </div>
        <div class="settings-card__body">
          <div class="defaults-grid">
            <div class="field">
              <label>Default Provider</label>
              <select v-model="defaultsForm.providerId" class="field__input">
                <option value="">Safe Runner (Default)</option>
                <option v-for="p in llmStore.configuredProviders" :key="p.id" :value="p.id">
                  {{ p.name }}
                </option>
              </select>
            </div>

            <div class="field">
              <label>Default Model</label>
              <input
                v-model="defaultsForm.modelId"
                type="text"
                class="field__input"
                placeholder="e.g., gpt-4o, claude-sonnet-4-20250514"
              />
            </div>

            <div class="field">
              <label>Default Harness</label>
              <select v-model="defaultsForm.harness" class="field__input">
                <option v-for="h in HARNESS_CONFIGS" :key="h.type" :value="h.type">
                  {{ h.name }}
                </option>
              </select>
            </div>

            <div class="field">
              <label>Max Runtime (seconds)</label>
              <input
                v-model.number="defaultsForm.maxRuntimeSeconds"
                type="number"
                class="field__input"
                min="30"
                max="3600"
              />
            </div>

            <div class="field">
              <label>Token Budget</label>
              <input
                v-model.number="defaultsForm.tokenBudget"
                type="number"
                class="field__input"
                placeholder="Unlimited"
                min="0"
              />
            </div>

            <div class="field">
              <label>Cost Budget ($)</label>
              <input
                v-model.number="defaultsForm.costBudget"
                type="number"
                class="field__input"
                placeholder="Unlimited"
                min="0"
                step="0.01"
              />
            </div>
          </div>

          <div class="field field--row">
            <label>Streaming Logs</label>
            <button
              :class="['toggle-btn', { 'toggle-btn--on': defaultsForm.streamingLogs }]"
              @click="defaultsForm.streamingLogs = !defaultsForm.streamingLogs"
            >
              {{ defaultsForm.streamingLogs ? 'ON' : 'OFF' }}
            </button>
          </div>

          <button class="settings-btn" :disabled="savingDefaults" @click="saveDefaults">
            <Loader2 v-if="savingDefaults" :size="14" class="spin" />
            Save Defaults
          </button>
        </div>
      </div>
    </div>

    <!-- Appearance Tab -->
    <div v-if="activeTab === 'appearance'" class="settings-content">
      <div class="settings-card">
        <div class="settings-card__header">
          <Eye :size="18" />
          <h3>Appearance</h3>
        </div>
        <div class="settings-card__body">
          <div class="theme-row">
            <span>Dark Mode</span>
            <button class="theme-toggle" @click="toggleDark">
              {{ isDark ? 'Light' : 'Dark' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script lang="ts">
// Helper to get models for a provider (simple placeholder)
function getProviderModels(provider: LLMProvider): string[] {
  // For now, return the default model as a single-item list
  // This will be enhanced when model discovery is implemented
  return provider.defaultModel ? [provider.defaultModel] : []
}
</script>

<style scoped>
.settings-page {
  display: flex; flex-direction: column; height: 100vh; min-width: 0;
  padding: 22px; gap: 18px; overflow-y: auto;
}
.settings-page__topbar { display: flex; align-items: flex-start; justify-content: space-between; }
.settings-page__title { display: flex; flex-direction: column; gap: 6px; }
.settings-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.settings-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; }
.settings-page__title p { margin-top: 4px; color: var(--muted); font-size: 0.9rem; }

/* Tabs */
.settings-tabs {
  display: flex; gap: 4px; padding: 4px;
  background: var(--surface-soft); border-radius: 10px;
  border: 1px solid var(--hairline);
}
.settings-tab {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px; border: none;
  background: transparent; color: var(--muted);
  font-size: 0.8125rem; font-weight: 500;
  cursor: pointer; transition: all 150ms;
}
.settings-tab:hover { color: var(--ink); background: var(--surface-card); }
.settings-tab--active { color: var(--ink); background: var(--surface-card); font-weight: 600; }

/* Content */
.settings-content { display: flex; flex-direction: column; gap: 16px; }

/* Cards */
.settings-card {
  display: flex; flex-direction: column; gap: 14px; padding: 18px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
}
.settings-card--full { grid-column: 1 / -1; }
.settings-card__header { display: flex; align-items: center; gap: 8px; color: var(--ink); }
.settings-card__header h3 { flex: 1; font-family: var(--font-display); font-size: 0.9375rem; font-weight: 700; }
.settings-card__action {
  padding: 4px; border-radius: 6px; border: none; background: transparent;
  color: var(--muted); cursor: pointer; transition: color 150ms;
}
.settings-card__action:hover { color: var(--ink); }
.settings-card__body { display: flex; flex-direction: column; gap: 12px; }

/* Status */
.status-row { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; }
.status-text { font-size: 0.875rem; font-weight: 500; }

/* Fields */
.field { display: flex; flex-direction: column; gap: 4px; }
.field--row { flex-direction: row; align-items: center; justify-content: space-between; }
.field label { font-size: 0.8125rem; font-weight: 600; color: var(--ink); }
.field__input {
  padding: 8px 12px; border-radius: 8px; border: 1px solid var(--hairline);
  background: var(--surface-soft); color: var(--ink); font-size: 0.875rem;
  font-family: var(--font-mono);
}
.field__input:focus { outline: none; border-color: var(--primary); }

/* Buttons */
.settings-btn {
  align-self: flex-start; padding: 8px 18px; border-radius: 8px;
  background: var(--primary); color: var(--on-primary); border: none;
  font-size: 0.875rem; font-weight: 600; cursor: pointer; transition: opacity 150ms;
  display: flex; align-items: center; gap: 6px;
}
.settings-btn:hover { opacity: 0.9; }
.settings-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.settings-btn--sm { padding: 6px 12px; font-size: 0.8125rem; }

/* Loading & Error */
.settings-loading, .settings-error {
  display: flex; align-items: center; gap: 10px; padding: 20px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
  color: var(--muted);
}
.settings-error { color: var(--clay-red); }

/* Providers Grid */
.providers-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px;
}

/* Provider Card */
.provider-card {
  display: flex; flex-direction: column;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
  overflow: hidden; transition: border-color 150ms;
}
.provider-card:hover { border-color: var(--primary); }
.provider-card--expanded { border-color: var(--primary); }

.provider-card__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; cursor: pointer;
}
.provider-card__info { display: flex; flex-direction: column; gap: 2px; }
.provider-card__name { font-weight: 600; font-size: 0.9375rem; color: var(--ink); }
.provider-card__adapter { font-size: 0.75rem; color: var(--muted); font-family: var(--font-mono); }
.provider-card__status { display: flex; align-items: center; gap: 8px; }

.provider-card__summary {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px 12px; gap: 12px;
}
.provider-card__model { font-size: 0.8125rem; color: var(--muted); }
.provider-card__model .label { margin-right: 4px; }
.provider-card__model .value { color: var(--ink); font-family: var(--font-mono); }
.provider-card__caps { display: flex; gap: 4px; }
.cap-tag {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 6px;
  background: var(--surface-soft); color: var(--muted);
}

/* Provider Details */
.provider-card__details {
  display: flex; flex-direction: column; gap: 10px;
  padding: 12px 16px; border-top: 1px solid var(--hairline);
  background: var(--surface-soft);
}
.provider-detail-row {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.8125rem;
}
.provider-detail-row .label { color: var(--muted); min-width: 70px; }
.provider-detail-row .value { color: var(--ink); }
.provider-error { color: var(--clay-red); }
.env-var {
  padding: 2px 6px; border-radius: 4px;
  background: var(--surface-card); font-family: var(--font-mono);
  font-size: 0.75rem; color: var(--ink);
}

/* Provider Actions */
.provider-card__actions {
  display: flex; gap: 8px; margin-top: 4px;
}
.action-btn {
  display: flex; align-items: center; gap: 4px;
  padding: 6px 10px; border-radius: 6px; border: 1px solid var(--hairline);
  background: var(--surface-card); color: var(--ink);
  font-size: 0.75rem; font-weight: 500; cursor: pointer;
  transition: all 150ms;
}
.action-btn:hover { border-color: var(--primary); }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-btn--test { border-color: var(--sage); color: var(--sage); }
.action-btn--test:hover { background: var(--sage); color: white; }
.action-btn--default { border-color: var(--amber); color: var(--amber); }
.action-btn--default:hover { background: var(--amber); color: white; }
.action-btn--disable { border-color: var(--clay-red); color: var(--clay-red); }
.action-btn--disable:hover { background: var(--clay-red); color: white; }
.action-btn--enable { border-color: var(--sage); color: var(--sage); }
.action-btn--enable:hover { background: var(--sage); color: white; }

/* Models */
.provider-models {
  display: flex; flex-direction: column; gap: 6px;
  padding-top: 8px; border-top: 1px solid var(--hairline);
}
.provider-models .label { font-size: 0.75rem; color: var(--muted); }
.model-list { display: flex; flex-wrap: wrap; gap: 4px; }
.model-tag {
  padding: 3px 8px; border-radius: 4px;
  background: var(--surface-card); border: 1px solid var(--hairline);
  font-size: 0.6875rem; font-family: var(--font-mono); color: var(--ink);
}

/* Defaults Grid */
.defaults-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;
}

/* Toggle */
.toggle-btn {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: var(--surface-soft); color: var(--muted);
  font-size: 0.8125rem; font-weight: 600; cursor: pointer;
  transition: all 150ms;
}
.toggle-btn--on { background: var(--sage); color: white; border-color: var(--sage); }

/* Theme */
.theme-row { display: flex; align-items: center; justify-content: space-between; }
.theme-toggle {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--ink); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.theme-toggle:hover { border-color: var(--primary); }

/* Spin animation */
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Health Badge */
.health-badge {
  padding: 3px 8px; border-radius: 6px;
  font-size: 0.6875rem; font-weight: 600; color: white;
  text-transform: uppercase; letter-spacing: 0.02em;
}
.health-badge--healthy { background: var(--sage); }
.health-badge--unhealthy,
.health-badge--auth_error,
.health-badge--billing_error,
.health-badge--model_error { background: var(--clay-red); }
.health-badge--rate_limited,
.health-badge--endpoint_error,
.health-badge--timeout { background: var(--amber); }
.health-badge--not_configured,
.health-badge--unknown { background: var(--muted); }

/* API Key Field */
.api-key-field {
  display: flex; align-items: center; gap: 6px; flex: 1;
}

/* Provider Warning */
.provider-warning {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px; border-radius: 6px;
  background: color-mix(in srgb, var(--amber) 10%, transparent);
  color: var(--amber); font-size: 0.75rem;
}

/* Small Input */
.field__input--sm {
  padding: 5px 8px; font-size: 0.8125rem; flex: 1;
}

/* Action Button Variants */
.action-btn--save {
  border-color: var(--sage); color: var(--sage);
}
.action-btn--save:hover {
  background: var(--sage); color: white;
}
.action-btn--edit {
  border-color: var(--primary); color: var(--primary);
}
.action-btn--edit:hover {
  background: var(--primary); color: white;
}
</style>
