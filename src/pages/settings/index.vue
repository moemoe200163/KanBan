<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { useDarkMode } from '~/composables/useDarkMode'
import { Check, Loader2, RefreshCw, Server, Settings, X } from 'lucide-vue-next'

const boardStore = useBoardStore()
const { isDark, toggleDark } = useDarkMode()
const config = useRuntimeConfig()

const apiBase = ref(config.public.apiBase)
const harnessOptions = ['claude-code', 'codex', 'cursor', 'opencode', 'gemini'] as const
const selectedHarness = ref(boardStore.activeHarness)

const backendStatus = ref<'checking' | 'healthy' | 'error'>('checking')

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

onMounted(() => {
  checkBackend()
})

const saveHarness = () => {
  boardStore.setHarnessFilter(selectedHarness.value)
}

const statusColor = computed(() => {
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
        <p>API configuration, harness, and system status</p>
      </div>
    </header>

    <div class="settings-page__grid">
      <!-- Backend Status -->
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
            <span class="status-dot" :style="{ background: statusColor }" />
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

      <!-- Harness -->
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

      <!-- Theme -->
      <div class="settings-card">
        <div class="settings-card__header">
          <Settings :size="18" />
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
.settings-page__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.settings-card {
  display: flex; flex-direction: column; gap: 14px; padding: 18px;
  background: var(--surface-card); border: 1px solid var(--hairline); border-radius: 12px;
}
.settings-card__header { display: flex; align-items: center; gap: 8px; color: var(--ink); }
.settings-card__header h3 { flex: 1; font-family: var(--font-display); font-size: 0.9375rem; font-weight: 700; }
.settings-card__action {
  padding: 4px; border-radius: 6px; border: none; background: transparent;
  color: var(--muted); cursor: pointer; transition: color 150ms;
}
.settings-card__action:hover { color: var(--ink); }
.settings-card__body { display: flex; flex-direction: column; gap: 12px; }
.status-row { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; }
.status-text { font-size: 0.875rem; font-weight: 500; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 0.8125rem; font-weight: 600; color: var(--ink); }
.field__input {
  padding: 8px 12px; border-radius: 8px; border: 1px solid var(--hairline);
  background: var(--surface-soft); color: var(--ink); font-size: 0.875rem;
  font-family: var(--font-mono);
}
.field__input:focus { outline: none; border-color: var(--primary); }
.settings-btn {
  align-self: flex-start; padding: 8px 18px; border-radius: 8px;
  background: var(--primary); color: var(--on-primary); border: none;
  font-size: 0.875rem; font-weight: 600; cursor: pointer; transition: opacity 150ms;
}
.settings-btn:hover { opacity: 0.9; }
.theme-row { display: flex; align-items: center; justify-content: space-between; }
.theme-toggle {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--hairline);
  background: transparent; color: var(--ink); font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: all 150ms;
}
.theme-toggle:hover { border-color: var(--primary); }
</style>
