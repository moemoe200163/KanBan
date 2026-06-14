<script setup lang="ts">
/**
 * ProviderSelector — dropdown to pick the LLM provider + model
 * for new conversations.
 *
 * The available list comes from ``useLLMStore.fetchProviders()``
 * (Plan H). The store already filters on
 * ``LLMProvider.configured``; we surface ``configuredProviders``
 * as the dropdown choices and surface the others as a small
 * "unconfigured" tag so the operator knows why a known
 * provider is missing.
 *
 * We also let the operator type a model id directly — some
 * providers accept ad-hoc model strings (e.g. OpenAI's
 * gpt-4o-mini) and the backend will pass it through. The
 * dropdown is the friendly default; the input is the escape
 * hatch.
 */

import { computed, onMounted, ref, watch } from 'vue'
import { ChevronDown, Cpu, KeyRound, RefreshCcw } from 'lucide-vue-next'
import { useAIStudioStore } from '~/stores/aiStudio'
import { useLLMStore } from '~/stores/llm'

const aiStudio = useAIStudioStore()
const llm = useLLMStore()

onMounted(async () => {
  if (llm.providers.length === 0) {
    await llm.fetchProviders()
    if (!aiStudio.selectedProviderId) {
      // Default the selection to the first configured provider,
      // falling back to the global default. We persist the
      // choice via the store's action so a refresh keeps it.
      const first = llm.configuredProviders[0]?.id
        ?? llm.defaults?.providerId
        ?? null
      if (first) aiStudio.setSelectedProvider(first)
    }
  }
})

const open = ref(false)
const dropdownRef = ref<HTMLDivElement | null>(null)

function toggle() {
  open.value = !open.value
}

function onSelect(id: string) {
  aiStudio.setSelectedProvider(id)
  open.value = false
}

const selectedProvider = computed(() =>
  llm.providers.find((p) => p.id === aiStudio.selectedProviderId) ?? null,
)

const selectedLabel = computed(() => {
  if (!selectedProvider.value) return 'Select provider…'
  return selectedProvider.value.name
})

// Click-outside closer — keep the logic tiny, we only have one
// dropdown and the page never nests another inside it.
function onDocClick(e: MouseEvent) {
  if (!open.value) return
  const root = dropdownRef.value
  if (!root) return
  if (!root.contains(e.target as Node)) open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})

const modelInput = ref(aiStudio.selectedModel ?? '')
watch(modelInput, (val) => {
  aiStudio.setSelectedModel(val.trim() || null)
})
// Keep the input in sync if the store resets it (e.g. when
// navigating to a fresh conversation).
watch(
  () => aiStudio.selectedModel,
  (val) => {
    if (val !== modelInput.value) modelInput.value = val ?? ''
  },
)

async function refresh() {
  await llm.fetchProviders()
}
</script>

<template>
  <div class="ps">
    <div ref="dropdownRef" class="ps__dropdown">
      <button
        type="button"
        class="ps__trigger"
        :class="{ 'ps__trigger--active': open }"
        :disabled="llm.isLoading"
        data-testid="ai-studio-provider-trigger"
        @click="toggle"
      >
        <Cpu :size="14" />
        <span class="ps__trigger-label">{{ selectedLabel }}</span>
        <ChevronDown :size="14" :class="{ 'ps__trigger-chevron--open': open }" />
      </button>
      <div v-if="open" class="ps__menu" data-testid="ai-studio-provider-menu">
        <div v-if="llm.configuredProviders.length === 0" class="ps__empty">
          No configured providers. Add one in Settings → LLM Providers.
        </div>
        <button
          v-for="p in llm.configuredProviders"
          :key="p.id"
          type="button"
          class="ps__item"
          :class="{ 'ps__item--active': p.id === aiStudio.selectedProviderId }"
          :data-testid="`ai-studio-provider-${p.id}`"
          @click="onSelect(p.id)"
        >
          <span class="ps__item-name">{{ p.name }}</span>
          <span class="ps__item-meta">
            <span class="ps__item-id">{{ p.id }}</span>
            <span v-if="p.model" class="ps__item-model">{{ p.model }}</span>
          </span>
        </button>
        <div v-if="llm.unconfiguredProviders.length > 0" class="ps__subgroup">
          <div class="ps__subgroup-label">
            <KeyRound :size="11" />
            <span>Unconfigured</span>
          </div>
          <div
            v-for="p in llm.unconfiguredProviders"
            :key="p.id"
            class="ps__item ps__item--disabled"
            :title="`${p.name} needs an API key in Settings → LLM Providers`"
          >
            <span class="ps__item-name">{{ p.name }}</span>
            <span class="ps__item-id">{{ p.id }}</span>
          </div>
        </div>
        <button
          type="button"
          class="ps__refresh"
          data-testid="ai-studio-provider-refresh"
          @click="refresh"
        >
          <RefreshCcw :size="12" />
          <span>Refresh providers</span>
        </button>
      </div>
    </div>
    <label class="ps__model">
      <span class="ps__model-label">Model</span>
      <input
        v-model="modelInput"
        type="text"
        class="ps__model-input"
        :placeholder="selectedProvider?.model ?? 'optional model id'"
        data-testid="ai-studio-model-input"
      />
    </label>
  </div>
</template>

<style scoped>
.ps {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ps__dropdown {
  position: relative;
}

.ps__trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
  height: 34px;
  padding: 0 12px;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  font-family: var(--font-body);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.ps__trigger:hover,
.ps__trigger--active {
  border-color: var(--primary);
}
.ps__trigger:disabled {
  cursor: progress;
  color: var(--muted);
}

.ps__trigger-label {
  flex: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ps__trigger-chevron--open {
  transform: rotate(180deg);
}

.ps__menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 20;
  min-width: 240px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(23, 22, 21, 0.10);
}

.ps__empty {
  padding: 12px;
  color: var(--muted);
  font-size: 0.8125rem;
  text-align: center;
}

.ps__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 8px 10px;
  color: var(--ink);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.ps__item:hover {
  background: var(--surface-soft);
}
.ps__item--active {
  background: rgba(204, 120, 92, 0.10);
  border-color: var(--primary);
}
.ps__item--disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ps__item-name {
  font-weight: 600;
}
.ps__item-meta {
  display: flex;
  gap: 8px;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}

.ps__subgroup {
  margin-top: 4px;
  padding-top: 6px;
  border-top: 1px solid var(--hairline-soft);
}
.ps__subgroup-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.625rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.ps__refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  padding: 6px 10px;
  width: 100%;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--hairline-soft);
  border-radius: 6px;
  font-size: 0.75rem;
  cursor: pointer;
}
.ps__refresh:hover {
  color: var(--ink);
  background: var(--surface-soft);
}

.ps__model {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 34px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}
.ps__model-label {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.ps__model-input {
  width: 160px;
  padding: 0;
  color: var(--ink);
  background: transparent;
  border: none;
  outline: none;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
}
.ps__model-input::placeholder {
  color: var(--muted-soft);
}
</style>
