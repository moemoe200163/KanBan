import { defineStore } from 'pinia'
import type { LLMProvider, LLMDefaults, LLMTestResult } from '~/types'

const API_BASE = useRuntimeConfig().public.apiBase as string

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
    async fetchProviders() {
      this.isLoading = true
      this.error = null
      try {
        const res = await fetch(`${API_BASE}/llm/providers`)
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
        const res = await fetch(`${API_BASE}/llm/defaults`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        this.defaults = await res.json()
      } catch (e: any) {
        this.error = e.message || 'Failed to load defaults'
      }
    },

    async updateDefaults(patch: Partial<LLMDefaults>) {
      try {
        const res = await fetch(`${API_BASE}/llm/defaults`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        this.defaults = await res.json()
      } catch (e: any) {
        this.error = e.message || 'Failed to update defaults'
      }
    },

    async testHealth(providerId: string): Promise<LLMTestResult | null> {
      try {
        const token = useCookie('auth_token').value
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/test`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
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

    async updateProviderConfig(providerId: string, config: { baseUrl?: string; model?: string; apiKey?: string; enabled?: boolean }) {
      try {
        const token = useCookie('auth_token').value
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/config`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(config),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        // Re-fetch providers to get updated state
        await this.fetchProviders()
      } catch (e: any) {
        this.error = e.message || 'Failed to update provider'
      }
    },

    async selectProvider(providerId: string) {
      try {
        const token = useCookie('auth_token').value
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/select`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        await this.fetchDefaults()
      } catch (e: any) {
        this.error = e.message || 'Failed to select provider'
      }
    },

    async fetchModels(providerId: string): Promise<string[]> {
      try {
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/models`)
        if (!res.ok) return []
        const data = await res.json()
        return data.models || []
      } catch {
        return []
      }
    },
  },
})
