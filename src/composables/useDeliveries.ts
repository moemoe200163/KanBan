/**
 * useDeliveries — composable for the /deliveries page.
 *
 * Wraps the read-only /api/v1/deliveries endpoints, which serve the
 * ``issue_artifacts`` table cross-issue. This is metadata-only by
 * design: no blob bytes, no upload pipeline. Uploads live in
 * ``/api/v1/artifacts`` (the Uploads page).
 */
import { computed, ref } from 'vue'
import { useRuntimeConfig } from '#imports'

export interface Delivery {
  id: string
  issueId: string
  jobId: string | null
  title: string
  artifactType: string
  source: string | null
  pathOrUrl: string | null
  sensitivity: string
  summary: string | null
  metadata: Record<string, unknown>
  createdById: string | null
  createdByName: string | null
  createdAt: string
  boardId: string
  // Enriched fields from /api/v1/deliveries (joined on issue)
  issueKey: string | null
  issueTitle: string | null
  issueStatus: string | null
}

export const useDeliveries = () => {
  const config = useRuntimeConfig()
  const apiBase = (config.public?.apiBase as string) || 'http://127.0.0.1:8000/api/v1'

  const items = ref<Delivery[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Local UI state
  const query = ref('')
  const selectedType = ref<string | null>(null)
  const selectedSource = ref<string | null>(null)
  const selectedIssueId = ref<string | null>(null)
  const types = ref<string[]>([])
  const sources = ref<string[]>([])

  const filtered = computed<Delivery[]>(() => {
    const ql = query.value.trim().toLowerCase()
    return items.value.filter((d) => {
      if (selectedType.value && d.artifactType !== selectedType.value) return false
      if (selectedSource.value && d.source !== selectedSource.value) return false
      if (selectedIssueId.value && d.issueId !== selectedIssueId.value) return false
      if (ql) {
        const hay = `${d.title} ${d.summary || ''} ${d.issueKey || ''} ${d.issueTitle || ''}`.toLowerCase()
        if (!hay.includes(ql)) return false
      }
      return true
    })
  })

  const loadTypes = async () => {
    try {
      const resp = await fetch(`${apiBase}/deliveries/types`)
      if (!resp.ok) return
      const body = await resp.json()
      types.value = body.types || []
    } catch { /* best effort */ }
  }
  const loadSources = async () => {
    try {
      const resp = await fetch(`${apiBase}/deliveries/sources`)
      if (!resp.ok) return
      const body = await resp.json()
      sources.value = body.sources || []
    } catch { /* best effort */ }
  }

  const list = async () => {
    isLoading.value = true
    error.value = null
    try {
      const params = new URLSearchParams()
      if (selectedType.value) params.set('artifactType', selectedType.value)
      if (selectedSource.value) params.set('source', selectedSource.value)
      if (selectedIssueId.value) params.set('issueId', selectedIssueId.value)
      params.set('limit', '500')
      const resp = await fetch(`${apiBase}/deliveries?${params.toString()}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const body = await resp.json()
      items.value = body.items || []
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load deliveries'
      items.value = []
    } finally {
      isLoading.value = false
    }
  }

  const refresh = async () => {
    await Promise.all([list(), loadTypes(), loadSources()])
  }

  return {
    // state
    items,
    types,
    sources,
    isLoading,
    error,
    query,
    selectedType,
    selectedSource,
    selectedIssueId,
    // derived
    filtered,
    // actions
    list,
    loadTypes,
    loadSources,
    refresh,
  }
}
