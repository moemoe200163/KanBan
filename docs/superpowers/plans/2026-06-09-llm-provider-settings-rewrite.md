# LLM Provider Settings Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the LLM Provider Settings page with clear read-only / admin-only separation, draft-on-save editing, and zero 401 noise in unauthenticated sessions.

**Architecture:** Frontend-only rewrite (backend already correct). Split the monolithic provider card into 5 information zones: Provider Catalog (read-only), Credential Status, Model Routing, Admin Configuration (draft-on-save), and Verification Panel. The store gains explicit auth guards on every write action.

**Tech Stack:** Vue 3 Composition API, Pinia, TypeScript, Nuxt runtime config, existing FastAPI backend (no backend changes needed).

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|---------------|
| `src/types/index.ts` | Modify | Add `apiShape`, `endpointPath`, `credentialSource` to `LLMProvider` |
| `src/stores/llm.ts` | Rewrite | Clear action separation, auth guards, draft state |
| `src/pages/settings/index.vue` | Rewrite providers tab | 5-zone information architecture |
| `backend/core/llm/registry.py` | Modify | Add `credentialSource` + `apiShape` + `endpointPath` to response |
| `backend/tests/test_llm_providers.py` | Modify | Add test for `credentialSource` in provider list response |

---

## Task 1: Backend — Add `credentialSource` to provider response

**Files:**
- Modify: `backend/core/llm/registry.py:99-127`
- Modify: `backend/tests/test_llm_providers.py`

- [ ] **Step 1: Add `credentialSource` field to `list_providers()` response**

In `backend/core/llm/registry.py`, inside `list_providers()`, after building the `result` dict (around line 114), add `credentialSource` logic:

```python
        # Determine credential source
        credential_source = "none"
        if db_cfg and (db_cfg.get("apiKeyPrefix") or db_cfg.get("apiKeyLast4")):
            credential_source = "db"
        elif configured and p.auth_env_var:
            credential_source = "env"

        result: dict = {
            "id": p.id,
            "name": p.name,
            "adapter": p.adapter,
            "enabled": p.enabled if not db_cfg else db_cfg.get("enabled", p.enabled),
            "configured": configured,
            "status": status,
            "defaultModel": (db_cfg.get("model") if db_cfg else None) or p.default_model,
            "capabilities": p.capabilities,
            "authType": (db_cfg.get("authType") if db_cfg else None) or p.auth_type,
            "authEnvVar": env_var,
            "maskedSecret": masked,
            "healthStatus": health,
            "lastChecked": None,
            "errorSummary": error,
            "credentialSource": credential_source,
        }
```

Also surface `apiShape` and `endpointPath` from DB config when present:

```python
        # Surface DB-specific fields when present
        if db_cfg:
            if db_cfg.get("baseUrl"):
                result["baseUrl"] = db_cfg["baseUrl"]
            if db_cfg.get("apiShape"):
                result["apiShape"] = db_cfg["apiShape"]
            if db_cfg.get("endpointPath"):
                result["endpointPath"] = db_cfg["endpointPath"]
            if db_cfg.get("lastTestStatus"):
                result["healthStatus"] = db_cfg["lastTestStatus"]
            if db_cfg.get("lastTestAt"):
                result["lastChecked"] = db_cfg["lastTestAt"]
            if db_cfg.get("lastErrorMessage"):
                result["errorSummary"] = db_cfg["lastErrorMessage"]
```

- [ ] **Step 2: Add test for `credentialSource` in provider list**

In `backend/tests/test_llm_providers.py`, add a test after `test_list_providers_returns_200`:

```python
def test_list_providers_includes_credential_source(client, fresh_db):
    """Provider list includes credentialSource field."""
    res = client.get("/api/v1/llm/providers")
    assert res.status_code == 200
    providers = res.json()["providers"]
    assert len(providers) > 0
    for p in providers:
        assert "credentialSource" in p
        assert p["credentialSource"] in ("none", "env", "db")
```

- [ ] **Step 3: Run backend tests to verify**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_llm_providers.py backend/tests/test_llm_provider_config.py -x`
Expected: All tests pass (existing + new)

- [ ] **Step 4: Commit**

```bash
git add backend/core/llm/registry.py backend/tests/test_llm_providers.py
git commit -m "feat(backend): add credentialSource, apiShape, endpointPath to provider response"
```

---

## Task 2: Frontend — Update `LLMProvider` type

**Files:**
- Modify: `src/types/index.ts:423-443`

- [ ] **Step 1: Add new fields to `LLMProvider` interface**

```typescript
export interface LLMProvider {
  id: string
  name: string
  adapter: LLMAdapterType
  enabled: boolean
  configured: boolean
  status: LLMProviderStatus
  defaultModel: string | null
  model: string | null
  capabilities: LLMCapability[]
  authType: 'api_key' | 'oauth' | 'cli_path' | 'none'
  authEnvVar: string | null
  maskedSecret: string | null
  healthStatus: 'healthy' | 'unhealthy' | 'unknown' | 'not_configured' | 'auth_error' | 'billing_error' | 'model_error' | 'rate_limited' | 'endpoint_error' | 'timeout'
  lastChecked: string | null
  errorSummary: string | null
  baseUrl: string | null
  apiShape: string | null
  endpointPath: string | null
  credentialSource: 'none' | 'env' | 'db'
  lastTestStatus: string | null
  lastLatencyMs: number | null
  lastErrorMessage: string | null
}
```

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: Pass (new fields are optional-compatible since backend now sends them)

- [ ] **Step 3: Commit**

```bash
git add src/types/index.ts
git commit -m "feat(types): add apiShape, endpointPath, credentialSource to LLMProvider"
```

---

## Task 3: Frontend — Rewrite `llm.ts` store

**Files:**
- Rewrite: `src/stores/llm.ts`

- [ ] **Step 1: Rewrite store with clear action separation**

Replace the entire `src/stores/llm.ts` with:

```typescript
import { defineStore } from 'pinia'
import type { LLMProvider, LLMDefaults, LLMTestResult } from '~/types'

function useApiBase() {
  return useRuntimeConfig().public.apiBase as string
}

function useAuthHeaders(): Record<string, string> {
  const token = useCookie('auth_token').value
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface LLMState {
  providers: LLMProvider[]
  defaults: LLMDefaults | null
  isLoading: boolean
  error: string | null
}

export const useLLMStore = defineStore('llm', {
  state: (): LLMState => ({
    providers: [],
    defaults: null,
    isLoading: false,
    error: null,
  }),

  getters: {
    configuredProviders: (state) => state.providers.filter(p => p.configured),
    unconfiguredProviders: (state) => state.providers.filter(p => !p.configured),
    safeRunner: (state) => state.providers.find(p => p.id === 'safe-runner'),
    getProviderById: (state) => (id: string) => state.providers.find(p => p.id === id),
  },

  actions: {
    // ── Public reads (no auth required) ──────────────────────────────

    async fetchProviders() {
      this.isLoading = true
      this.error = null
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/providers`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        this.providers = data.providers
      } catch (e: any) {
        this.error = e.message || 'Failed to load providers'
      } finally {
        this.isLoading = false
      }
    },

    async fetchDefaults() {
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/defaults`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        this.defaults = await res.json()
      } catch (e: any) {
        this.error = e.message || 'Failed to load defaults'
      }
    },

    // ── Admin-only writes (auth required) ────────────────────────────

    async updateProviderConfig(providerId: string, config: { baseUrl?: string; model?: string; apiKey?: string; enabled?: boolean; endpointPath?: string }) {
      const token = useCookie('auth_token').value
      if (!token) {
        this.error = 'Login required to update provider settings'
        return
      }
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/providers/${providerId}/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(config),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        await this.fetchProviders()
      } catch (e: any) {
        this.error = e.message || 'Failed to update provider'
      }
    },

    async testProvider(providerId: string): Promise<LLMTestResult | null> {
      const token = useCookie('auth_token').value
      if (!token) {
        this.error = 'Login required to test provider'
        return null
      }
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/providers/${providerId}/test`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        // Update local provider state
        const idx = this.providers.findIndex(p => p.id === providerId)
        if (idx !== -1) {
          this.providers[idx] = {
            ...this.providers[idx],
            healthStatus: data.status,
            lastTestStatus: data.status,
            lastChecked: data.checkedAt,
            lastLatencyMs: data.latencyMs,
            lastErrorMessage: data.safeError,
            configured: data.status !== 'not_configured',
          }
        }
        return data
      } catch (e: any) {
        return null
      }
    },

    async selectProvider(providerId: string) {
      const token = useCookie('auth_token').value
      if (!token) {
        this.error = 'Login required to select a provider'
        return
      }
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/providers/${providerId}/select`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        await this.fetchDefaults()
      } catch (e: any) {
        this.error = e.message || 'Failed to select provider'
      }
    },

    async updateDefaults(patch: Partial<LLMDefaults>) {
      const token = useCookie('auth_token').value
      if (!token) {
        this.error = 'Login required to save defaults'
        return
      }
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/defaults`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(patch),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        this.defaults = await res.json()
      } catch (e: any) {
        this.error = e.message || 'Failed to update defaults'
      }
    },

    async fetchModels(providerId: string): Promise<string[]> {
      try {
        const apiBase = useApiBase()
        const res = await fetch(`${apiBase}/llm/providers/${providerId}/models`)
        if (!res.ok) return []
        const data = await res.json()
        return data.models || []
      } catch {
        return []
      }
    },
  },
})
```

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: Pass

- [ ] **Step 3: Commit**

```bash
git add src/stores/llm.ts
git commit -m "refactor(llm store): rewrite with clear read/write separation and auth guards"
```

---

## Task 4: Frontend — Rewrite providers tab in settings page

**Files:**
- Modify: `src/pages/settings/index.vue` (providers tab section, lines ~246-409)

- [ ] **Step 1: Add draft state and helper functions**

In the `<script setup>` section, add draft state for the provider edit form:

```typescript
// Provider edit draft (only sent on Save)
const providerDraft = ref<{
  providerId: string
  baseUrl: string
  model: string
  apiKey: string
  endpointPath: string
} | null>(null)

const startEditProvider = (provider: LLMProvider) => {
  providerDraft.value = {
    providerId: provider.id,
    baseUrl: provider.baseUrl || '',
    model: provider.model || provider.defaultModel || '',
    apiKey: '',
    endpointPath: (provider as any).endpointPath || '',
  }
}

const cancelEditProvider = () => {
  providerDraft.value = null
}

const saveProviderDraft = async () => {
  if (!providerDraft.value || !isAdmin.value) return
  const d = providerDraft.value
  const config: Record<string, string> = {}
  if (d.baseUrl) config.baseUrl = d.baseUrl
  if (d.model) config.model = d.model
  if (d.apiKey) config.apiKey = d.apiKey
  if (d.endpointPath) config.endpointPath = d.endpointPath
  await llmStore.updateProviderConfig(d.providerId, config)
  providerDraft.value = null
}
```

Also add a helper for the MiniMax-specific info display:

```typescript
const apiShapeLabel = (provider: LLMProvider): string => {
  const shape = (provider as any).apiShape
  if (shape === 'anthropic-messages') return 'Anthropic Messages'
  if (shape === 'openai-chat') return 'OpenAI Chat'
  if (shape === 'openai-responses') return 'OpenAI Responses'
  if (shape === 'ollama') return 'Ollama'
  return provider.adapter
}

const credentialLabel = (provider: LLMProvider): string => {
  const src = (provider as any).credentialSource
  if (src === 'db') return 'Saved in DB'
  if (src === 'env') return 'Environment variable'
  return 'Not configured'
}
```

- [ ] **Step 2: Rewrite the providers tab template**

Replace the `<div v-if="activeTab === 'providers'" ...>` section (lines ~247-409) with the 5-zone layout:

```html
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
        <!-- Auth notice (when not logged in) -->
        <div v-if="!isAdmin" class="auth-notice">
          <Shield :size="14" />
          <span>Login to configure providers.</span>
        </div>

        <div
          v-for="provider in llmStore.providers"
          :key="provider.id"
          :class="['provider-card', { 'provider-card--expanded': expandedProvider === provider.id }]"
        >
          <!-- Zone 1: Provider Catalog (always visible) -->
          <div class="provider-card__header" @click="toggleExpand(provider.id)">
            <div class="provider-card__info">
              <span class="provider-card__name">{{ provider.name }}</span>
              <span class="provider-card__adapter">
                {{ apiShapeLabel(provider) }}
                <span v-if="(provider as any).endpointPath" class="provider-card__endpoint">
                  {{ (provider as any).endpointPath }}
                </span>
              </span>
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

          <!-- Zone 1b: Provider Summary (always visible) -->
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

          <!-- Expanded details -->
          <div v-if="expandedProvider === provider.id" class="provider-card__details">

            <!-- Zone 2: Credential Status -->
            <div class="provider-detail-row">
              <span class="label">Credentials:</span>
              <span class="value">
                <code v-if="provider.maskedSecret" class="env-var">{{ provider.maskedSecret }}</code>
                <span v-else class="text-muted">Not configured</span>
                <span class="credential-tag" :class="`credential-tag--${(provider as any).credentialSource || 'none'}`">
                  {{ credentialLabel(provider) }}
                </span>
              </span>
            </div>

            <!-- Zone 3: Model Routing -->
            <div class="provider-detail-row">
              <span class="label">Base URL:</span>
              <span class="value provider-url">{{ provider.baseUrl || 'Default' }}</span>
            </div>
            <div class="provider-detail-row">
              <span class="label">Auth:</span>
              <span class="value">{{ provider.authType }} <small v-if="provider.authEnvVar">({{ provider.authEnvVar }})</small></span>
            </div>

            <!-- Zone 4: Admin Configuration (draft-on-save) -->
            <template v-if="isAdmin">
              <div v-if="providerDraft?.providerId === provider.id" class="provider-config-form">
                <div class="provider-detail-row">
                  <span class="label">Base URL:</span>
                  <input
                    v-model="providerDraft.baseUrl"
                    class="field__input field__input--sm"
                    placeholder="API base URL"
                  />
                </div>
                <div class="provider-detail-row">
                  <span class="label">Model:</span>
                  <input
                    v-model="providerDraft.model"
                    class="field__input field__input--sm"
                    placeholder="Model name"
                  />
                </div>
                <div class="provider-detail-row">
                  <span class="label">API Key:</span>
                  <input
                    v-model="providerDraft.apiKey"
                    type="password"
                    class="field__input field__input--sm"
                    placeholder="Enter API key (leave blank to keep current)"
                  />
                </div>
                <div class="provider-config-form__actions">
                  <button class="action-btn action-btn--save" @click.stop="saveProviderDraft">
                    <Check :size="14" />
                    Save
                  </button>
                  <button class="action-btn" @click.stop="cancelEditProvider">Cancel</button>
                </div>
              </div>
              <div v-else class="provider-card__actions">
                <button
                  class="action-btn action-btn--edit"
                  @click.stop="startEditProvider(provider)"
                >
                  <Settings :size="14" />
                  Configure
                </button>
                <button
                  class="action-btn action-btn--test"
                  :disabled="testingProvider === provider.id || !provider.maskedSecret"
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
            </template>

            <!-- Zone 5: Verification Panel -->
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

            <!-- Warning -->
            <div class="provider-warning">
              <AlertCircle :size="14" />
              <span>Provider keys are LLM API credentials, NOT SecurityWeb Access Keys.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
```

- [ ] **Step 3: Add CSS for new elements**

Add to the `<style scoped>` section:

```css
/* Credential tag */
.credential-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.credential-tag--db { background: rgba(125, 158, 125, 0.15); color: var(--sage); }
.credential-tag--env { background: rgba(59, 130, 246, 0.1); color: var(--primary); }
.credential-tag--none { background: var(--surface-soft); color: var(--muted); }

/* Provider URL */
.provider-url {
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  word-break: break-all;
}

/* Provider endpoint */
.provider-card__endpoint {
  margin-left: 6px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--muted);
}

/* Config form */
.provider-config-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--hairline);
}
.provider-config-form__actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

/* Text muted helper */
.text-muted { color: var(--muted); }
```

- [ ] **Step 4: Remove old provider config fields**

Remove the old inline Base URL / Model / API Key inputs that were in the expanded details (the ones that fire on `@change`). The new draft-on-save form replaces them.

Also remove the old `startEditKey`, `saveApiKey`, `updateBaseUrl`, `updateModel` functions since they're replaced by the draft pattern.

- [ ] **Step 5: Run typecheck and build**

Run: `npm run typecheck && NUXT_IGNORE_LOCK=1 npm run build`
Expected: Both pass

- [ ] **Step 6: Commit**

```bash
git add src/pages/settings/index.vue
git commit -m "feat(settings): rewrite providers tab with 5-zone layout and draft-on-save"
```

---

## Task 5: Verify — No 401 noise in unauthenticated session

**Files:** None (verification only)

- [ ] **Step 1: Run backend tests**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_llm_providers.py backend/tests/test_llm_provider_config.py backend/tests/test_llm_minimax.py`
Expected: All pass

- [ ] **Step 2: Run frontend typecheck + build**

Run: `npm run typecheck && NUXT_IGNORE_LOCK=1 npm run build`
Expected: Both pass

- [ ] **Step 3: Browser acceptance test**

1. Clear `auth_token` cookie
2. Open `http://127.0.0.1:3010/settings`
3. Click "LLM Providers" tab
4. Open DevTools Network tab
5. Verify: provider cards render with names, models, health badges
6. Verify: no `401` responses in Network tab
7. Verify: "Login to configure providers" notice visible
8. Verify: Configure / Test / Select Active / Disable buttons NOT visible (hidden for non-admin)
9. Expand MiniMax card — verify read-only: Base URL, Model, Auth type, credential status shown
10. Login as admin, repeat — verify Configure button appears, draft form opens on click, Save sends PUT

- [ ] **Step 4: Commit verification (if any fixups needed)**

```bash
git add -A && git commit -m "fix(settings): address verification findings"
```

---

## Summary of Changes

| Area | What changes | What stays the same |
|------|-------------|-------------------|
| Backend response | `credentialSource`, `apiShape`, `endpointPath` added | All existing fields, auth policy, encryption |
| Frontend types | 3 new fields on `LLMProvider` | All existing fields |
| Store actions | Auth guards on every write, `useApiBase()` helper | Public reads unchanged |
| Provider card | 5-zone layout, draft-on-save, hidden buttons for non-admin | Health badges, capability icons, expand/collapse |
| Testing | New `credentialSource` test | All 63+ existing tests |
