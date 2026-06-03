import { defineStore } from 'pinia'
import type { LLMProvider, LLMDefaults } from '~/types'

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

    async testHealth(providerId: string): Promise<{ status: string; error: string | null }> {
      try {
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/health`, {
          method: 'POST',
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        // Update local state
        const idx = this.providers.findIndex(p => p.id === providerId)
        if (idx !== -1) {
          this.providers[idx] = {
            ...this.providers[idx],
            healthStatus: data.status,
            lastChecked: new Date().toISOString(),
            errorSummary: data.error,
          }
        }
        return data
      } catch (e: any) {
        return { status: 'unhealthy', error: e.message }
      }
    },

    async updateProviderConfig(providerId: string, config: { enabled?: boolean; defaultModel?: string }) {
      try {
        const res = await fetch(`${API_BASE}/llm/providers/${providerId}/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const updated = await res.json()
        const idx = this.providers.findIndex(p => p.id === providerId)
        if (idx !== -1) {
          this.providers[idx] = updated
        }
      } catch (e: any) {
        this.error = e.message || 'Failed to update provider'
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
