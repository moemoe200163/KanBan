/**
 * useArtifacts — composable for the /artifacts (Uploads) page.
 *
 * User uploads only. The /deliveries view (different page, different
 * composable) is for handoff/completion artifacts emitted by the
 * backend as IssueArtifact rows.
 *
 * Endpoints wrapped here:
 *   GET    /api/v1/artifacts             list (?tag, ?q, ?folder)
 *   POST   /api/v1/artifacts             upload (multipart; folder_path form field)
 *   GET    /api/v1/artifacts/tags        distinct tag list
 *   GET    /api/v1/artifacts/folders     distinct folder_path values w/ counts
 *   GET    /api/v1/artifacts/{id}/blob   download (we build direct <a> hrefs)
 *   GET    /api/v1/artifacts/{id}/versions  version chain
 *   PATCH  /api/v1/artifacts/{id}        edit folder/tags/description
 *   DELETE /api/v1/artifacts/{id}        hard delete
 */
import { computed, ref } from 'vue'
import { useRuntimeConfig } from '#imports'

export interface Artifact {
  id: string
  name: string
  mimeType: string
  sizeBytes: number
  tags: string[]
  description: string
  uploader: string
  version: number
  parentId: string | null
  folderPath: string
  createdAt: string
  updatedAt: string
}

export interface ArtifactFolder {
  path: string
  count: number
  isDefault: boolean
}

const PAGE_SIZE = 200
const DEFAULT_FOLDER = '/Uploads'

export const useArtifacts = () => {
  const config = useRuntimeConfig()
  const apiBase = (config.public?.apiBase as string) || 'http://127.0.0.1:8000/api/v1'

  const items = ref<Artifact[]>([])
  const tags = ref<string[]>([])
  const folders = ref<ArtifactFolder[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const isUploading = ref(false)
  const uploadProgress = ref(0)
  const lastUploadedId = ref<string | null>(null)

  // Local UI state
  const query = ref('')
  const selectedTag = ref<string | null>(null)
  const selectedFolder = ref<string | null>(null)  // null = "All uploads"
  const previewArtifact = ref<Artifact | null>(null)
  const versionChain = ref<Artifact[] | null>(null)
  const lightboxArtifact = ref<Artifact | null>(null)
  const showMoveDialog = ref(false)
  const moveTarget = ref('')
  const movingArtifact = ref<Artifact | null>(null)

  const filtered = computed<Artifact[]>(() => items.value)
  const totalSizeBytes = computed(() => items.value.reduce((sum, a) => sum + a.sizeBytes, 0))

  const blobUrl = (id: string) => `${apiBase}/artifacts/${id}/blob`

  /** Inline-friendly content for markdown / text previews. Capped at
   *  200 KB to keep the page snappy. */
  const fetchText = async (id: string): Promise<string> => {
    const resp = await fetch(blobUrl(id))
    if (!resp.ok) throw new Error(`Failed to fetch blob: ${resp.status}`)
    return await resp.text()
  }

  const list = async () => {
    isLoading.value = true
    error.value = null
    try {
      const params = new URLSearchParams()
      if (selectedTag.value) params.set('tag', selectedTag.value)
      if (query.value.trim()) params.set('q', query.value.trim())
      if (selectedFolder.value) params.set('folder', selectedFolder.value)
      params.set('limit', String(PAGE_SIZE))
      const url = `${apiBase}/artifacts?${params.toString()}`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const body = await resp.json()
      items.value = body.items || []
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load artifacts'
      items.value = []
    } finally {
      isLoading.value = false
    }
  }

  const loadTags = async () => {
    try {
      const resp = await fetch(`${apiBase}/artifacts/tags`)
      if (!resp.ok) return
      const body = await resp.json()
      tags.value = body.tags || []
    } catch {
      // Tag list is convenience; don't block on it.
    }
  }

  const loadFolders = async () => {
    try {
      const resp = await fetch(`${apiBase}/artifacts/folders`)
      if (!resp.ok) return
      const body = await resp.json()
      folders.value = body.folders || []
      // Make sure the default folder is always present in the sidebar
      // even when no uploads exist yet.
      if (folders.value.length === 0 || !folders.value.some((f) => f.path === DEFAULT_FOLDER)) {
        folders.value = [{ path: DEFAULT_FOLDER, count: 0, isDefault: true }, ...folders.value]
      }
    } catch {
      // Same — best effort.
    }
  }

  const refresh = async () => {
    await Promise.all([list(), loadFolders()])
  }

  const upload = async (
    file: File,
    opts: { tags: string[]; description: string; uploader: string; folderPath: string; asVersionOf?: string }
  ): Promise<Artifact | null> => {
    isUploading.value = true
    uploadProgress.value = 0
    error.value = null
    try {
      const form = new FormData()
      form.append('file', file)
      if (opts.tags.length) form.append('tags', JSON.stringify(opts.tags))
      if (opts.description) form.append('description', opts.description)
      if (opts.uploader) form.append('uploader', opts.uploader)
      if (opts.folderPath) form.append('folder_path', opts.folderPath)
      if (opts.asVersionOf) form.append('as_version_of', opts.asVersionOf)

      // XHR for upload progress events (fetch can't).
      const artifact = await new Promise<Artifact | null>((resolve) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${apiBase}/artifacts`, true)
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            uploadProgress.value = Math.round((e.loaded / e.total) * 100)
          }
        }
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const body = JSON.parse(xhr.responseText)
              resolve(body)
            } catch {
              resolve(null)
            }
          } else {
            error.value = `Upload failed: HTTP ${xhr.status}`
            resolve(null)
          }
        }
        xhr.onerror = () => {
          error.value = 'Network error during upload'
          resolve(null)
        }
        xhr.send(form)
      })

      if (artifact) {
        lastUploadedId.value = artifact.id
        await refresh()
      }
      return artifact
    } finally {
      isUploading.value = false
      uploadProgress.value = 0
    }
  }

  const remove = async (id: string) => {
    try {
      const resp = await fetch(blobUrl(id).replace(/\/blob$/, ''), { method: 'DELETE' })
      if (resp.ok) {
        items.value = items.value.filter((a) => a.id !== id)
        if (previewArtifact.value?.id === id) previewArtifact.value = null
        if (lightboxArtifact.value?.id === id) lightboxArtifact.value = null
        await loadFolders()
      } else {
        error.value = `Delete failed: HTTP ${resp.status}`
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Delete failed'
    }
  }

  const move = async (id: string, folderPath: string) => {
    try {
      const form = new FormData()
      form.append('folder_path', folderPath)
      const resp = await fetch(`${apiBase}/artifacts/${id}`, {
        method: 'PATCH',
        body: form,
      })
      if (!resp.ok) {
        error.value = `Move failed: HTTP ${resp.status}`
        return null
      }
      const updated = await resp.json()
      // Refresh so the new folder's count is correct.
      await refresh()
      return updated
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Move failed'
      return null
    }
  }

  const openMoveDialog = (art: Artifact) => {
    movingArtifact.value = art
    moveTarget.value = art.folderPath || DEFAULT_FOLDER
    showMoveDialog.value = true
  }

  const closeMoveDialog = () => {
    showMoveDialog.value = false
    movingArtifact.value = null
    moveTarget.value = ''
  }

  const confirmMove = async () => {
    if (!movingArtifact.value || !moveTarget.value.trim()) return
    const ok = await move(movingArtifact.value.id, moveTarget.value.trim())
    if (ok) closeMoveDialog()
  }

  const openVersionChain = async (art: Artifact) => {
    try {
      const resp = await fetch(`${apiBase}/artifacts/${art.id}/versions`)
      if (resp.ok) {
        const body = await resp.json()
        versionChain.value = body.items || []
        previewArtifact.value = art
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load versions'
    }
  }

  const closePreview = () => {
    previewArtifact.value = null
    versionChain.value = null
  }

  const openLightbox = (art: Artifact) => {
    if (art.mimeType.startsWith('image/')) {
      lightboxArtifact.value = art
    }
  }

  const closeLightbox = () => {
    lightboxArtifact.value = null
  }

  return {
    // state
    items,
    tags,
    folders,
    isLoading,
    isUploading,
    uploadProgress,
    error,
    lastUploadedId,
    query,
    selectedTag,
    selectedFolder,
    previewArtifact,
    versionChain,
    lightboxArtifact,
    showMoveDialog,
    moveTarget,
    movingArtifact,
    // derived
    filtered,
    totalSizeBytes,
    // actions
    list,
    loadTags,
    loadFolders,
    refresh,
    upload,
    remove,
    move,
    openMoveDialog,
    closeMoveDialog,
    confirmMove,
    openVersionChain,
    closePreview,
    openLightbox,
    closeLightbox,
    fetchText,
    blobUrl,
  }
}
