<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import {
  Download,
  Eye,
  FileText,
  Folder,
  FolderInput,
  History,
  Image as ImageIcon,
  Package,
  Plus,
  RefreshCw,
  Search,
  Tag,
  Trash2,
  Upload,
  X,
} from 'lucide-vue-next'

import { useArtifacts } from '~/composables/useArtifacts'

const {
  items,
  tags,
  folders,
  isLoading,
  isUploading,
  uploadProgress,
  error,
  query,
  selectedTag,
  selectedFolder,
  previewArtifact,
  versionChain,
  lightboxArtifact,
  showMoveDialog,
  moveTarget,
  movingArtifact,
  filtered,
  totalSizeBytes,
  list,
  loadTags,
  loadFolders,
  refresh,
  upload,
  remove,
  openMoveDialog,
  closeMoveDialog,
  confirmMove,
  openVersionChain,
  closePreview,
  openLightbox,
  closeLightbox,
  fetchText,
  blobUrl,
} = useArtifacts()

// ----- upload dialog state -----
const showUpload = ref(false)
const uploadFile = ref<File | null>(null)
const uploadTagsInput = ref('')
const uploadDescription = ref('')
const uploadUploader = ref('')
const uploadAsVersionOf = ref('')
const uploadFolder = ref('/Uploads')
const dragActive = ref(false)
const previewText = ref<string | null>(null)
const previewIsMarkdown = ref(false)
const previewIsImage = ref(false)

onMounted(async () => {
  await Promise.all([list(), loadTags(), loadFolders()])
})

// Auto re-fetch whenever the user changes the folder chip or search box.
watch([selectedFolder, selectedTag, query], () => { void list() })

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

const formatDate = (iso: string): string => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const iconFor = (mime: string) => {
  if (mime.startsWith('image/')) return ImageIcon
  if (mime.startsWith('text/') || mime === 'application/json' || mime === 'application/markdown') return FileText
  return Package
}

const isImage = (mime: string) => mime.startsWith('image/')
const isMarkdown = (mime: string, name: string) =>
  mime === 'text/markdown' || mime === 'application/markdown' || /\.(md|markdown)$/i.test(name)
const isPreviewableText = (mime: string, name: string) =>
  isMarkdown(mime, name) || mime.startsWith('text/') || mime === 'application/json'

const clearFilters = () => {
  query.value = ''
  selectedTag.value = null
  list()
}

const onTagClick = (tag: string) => {
  selectedTag.value = selectedTag.value === tag ? null : tag
}

const selectFolder = (path: string | null) => {
  selectedFolder.value = path
}

const onFileSelect = (e: Event) => {
  const input = e.target as HTMLInputElement
  if (input.files && input.files[0]) {
    uploadFile.value = input.files[0]
  }
}

const onDrop = (e: DragEvent) => {
  e.preventDefault()
  dragActive.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files[0]) {
    uploadFile.value = e.dataTransfer.files[0]
  }
}

const submitUpload = async () => {
  if (!uploadFile.value) return
  const tags = uploadTagsInput.value
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
  // Default to currently selected folder, falling back to /Uploads.
  const folder = uploadFolder.value.trim() || (selectedFolder.value || '/Uploads')
  const artifact = await upload(uploadFile.value, {
    tags,
    description: uploadDescription.value,
    uploader: uploadUploader.value,
    folderPath: folder,
    asVersionOf: uploadAsVersionOf.value || undefined,
  })
  if (artifact) closeUploadDialog()
}

const closeUploadDialog = () => {
  showUpload.value = false
  uploadFile.value = null
  uploadTagsInput.value = ''
  uploadDescription.value = ''
  uploadUploader.value = ''
  uploadAsVersionOf.value = ''
}

const handleDelete = async (id: string) => {
  if (!confirm('Delete this file? (versions keep their data but lose the parent link)')) return
  await remove(id)
}

const openPreview = async (art: import('~/composables/useArtifacts').Artifact) => {
  previewText.value = null
  previewIsMarkdown.value = false
  previewIsImage.value = false
  await openVersionChain(art)
  if (isPreviewableText(art.mimeType, art.name)) {
    try {
      const text = await fetchText(art.id)
      previewText.value = text.length > 200_000 ? text.slice(0, 200_000) + '\n\n…(truncated)' : text
      previewIsMarkdown.value = isMarkdown(art.mimeType, art.name)
    } catch (e) {
      previewText.value = `[Failed to fetch preview: ${e instanceof Error ? e.message : String(e)}]`
    }
  } else if (isImage(art.mimeType)) {
    previewIsImage.value = true
  }
}

const downloadHref = (id: string) => blobUrl(id)
</script>

<template>
  <section class="uploads-page">
    <!-- Top bar -->
    <header class="uploads-page__topbar">
      <div class="uploads-page__title">
        <span class="uploads-page__kicker">Workspace / DevFlow</span>
        <h1>Uploads</h1>
        <p>User-uploaded reference files, attachments, screenshots, and documents</p>
      </div>
      <div class="uploads-page__actions">
        <button class="icon-btn" @click="refresh" :disabled="isLoading" title="Refresh list">
          <RefreshCw :size="16" :class="{ spin: isLoading }" />
        </button>
        <button class="primary-btn" @click="showUpload = true; uploadFolder = selectedFolder || '/Uploads'" data-testid="uploads-open">
          <Plus :size="16" /> Upload
        </button>
      </div>
    </header>

    <div class="uploads-page__body">
      <!-- Folder sidebar -->
      <aside class="uploads-folders">
        <h3 class="uploads-folders__heading"><Folder :size="13" /> Folders</h3>
        <ul class="uploads-folders__list">
          <li>
            <button
              class="folder-item"
              :class="{ 'folder-item--active': selectedFolder === null }"
              @click="selectFolder(null)"
            >
              <Folder :size="13" />
              <span class="folder-item__name">All uploads</span>
              <span class="folder-item__count">{{ folders.reduce((s, f) => s + f.count, 0) }}</span>
            </button>
          </li>
          <li v-for="f in folders" :key="f.path">
            <button
              class="folder-item"
              :class="{ 'folder-item--active': selectedFolder === f.path }"
              @click="selectFolder(f.path)"
              :title="f.path"
            >
              <Folder :size="13" />
              <span class="folder-item__name">{{ f.path }}</span>
              <span class="folder-item__count">{{ f.count }}</span>
            </button>
          </li>
        </ul>
      </aside>

      <!-- Main area -->
      <div class="uploads-main">
        <!-- Stats row (scoped to current folder filter) -->
        <div class="uploads-page__stats">
          <div class="stat">
            <span class="stat__label">Files in view</span>
            <span class="stat__value">{{ items.length }}</span>
          </div>
          <div class="stat">
            <span class="stat__label">Total size</span>
            <span class="stat__value">{{ formatSize(totalSizeBytes) }}</span>
          </div>
          <div class="stat">
            <span class="stat__label">Distinct tags</span>
            <span class="stat__value">{{ tags.length }}</span>
          </div>
          <div class="stat">
            <span class="stat__label">Versioned chains</span>
            <span class="stat__value">{{ items.filter((a) => a.parentId).length }}</span>
          </div>
        </div>

        <!-- Search + tag chips -->
        <div class="uploads-page__toolbar">
          <div class="search-wrap">
            <Search :size="14" />
            <input
              type="text"
              v-model="query"
              class="search-input"
              placeholder="Search by filename…"
            />
          </div>
          <div class="tag-chips">
            <button
              class="chip"
              :class="{ 'chip--active': selectedTag === null }"
              @click="clearFilters"
            >
              All tags
            </button>
            <button
              v-for="t in tags"
              :key="t"
              class="chip"
              :class="{ 'chip--active': selectedTag === t }"
              @click="onTagClick(t)"
            >
              <Tag :size="11" /> {{ t }}
            </button>
          </div>
        </div>

        <!-- Error banner -->
        <div v-if="error" class="uploads-page__error">
          {{ error }}
          <button @click="error = null" class="icon-btn"><X :size="14" /></button>
        </div>

        <!-- Loading -->
        <div v-if="isLoading && items.length === 0" class="uploads-page__loading">
          <RefreshCw :size="20" class="spin" /> Loading uploads…
        </div>

        <!-- Empty -->
        <div v-else-if="filtered.length === 0" class="uploads-page__empty">
          <Package :size="36" />
          <p v-if="selectedFolder">No files in <code>{{ selectedFolder }}</code></p>
          <p v-else>No uploads yet</p>
          <span v-if="query || selectedTag">Try clearing filters.</span>
          <span v-else>Click <strong>Upload</strong> to add the first file.</span>
        </div>

        <!-- Grid -->
        <div v-else class="uploads-grid">
          <article
            v-for="art in filtered"
            :key="art.id"
            class="upload-card"
            :data-testid="`upload-card-${art.id}`"
          >
            <div class="upload-card__icon">
              <component :is="iconFor(art.mimeType)" :size="22" />
            </div>
            <div class="upload-card__body">
              <div class="upload-card__header">
                <h3 class="upload-card__name" :title="art.name">{{ art.name }}</h3>
                <span v-if="art.version > 1" class="version-badge">v{{ art.version }}</span>
              </div>
              <div class="upload-card__path" :title="art.folderPath">
                <Folder :size="11" /> {{ art.folderPath }}
              </div>
              <div class="upload-card__meta">
                <span>{{ formatSize(art.sizeBytes) }}</span>
                <span>·</span>
                <span>{{ formatDate(art.createdAt) }}</span>
                <span v-if="art.uploader">·</span>
                <span v-if="art.uploader">{{ art.uploader }}</span>
              </div>
              <p v-if="art.description" class="upload-card__description">{{ art.description }}</p>
              <div v-if="art.tags.length" class="upload-card__tags">
                <span v-for="t in art.tags" :key="t" class="tag-pill">{{ t }}</span>
              </div>
            </div>
            <div class="upload-card__actions">
              <a
                v-if="isImage(art.mimeType)"
                href="javascript:void(0)"
                class="icon-btn"
                title="View image"
                @click="openLightbox(art)"
                data-testid="upload-view-image"
              >
                <Eye :size="14" />
              </a>
              <button
                v-if="isPreviewableText(art.mimeType, art.name)"
                class="icon-btn"
                title="Preview"
                @click="openPreview(art)"
                data-testid="upload-preview"
              >
                <FileText :size="14" />
              </button>
              <button
                v-if="art.parentId || items.some((i) => i.parentId === art.id)"
                class="icon-btn"
                title="Version history"
                @click="openPreview(art)"
              >
                <History :size="14" />
              </button>
              <a
                :href="downloadHref(art.id)"
                :download="art.name"
                class="icon-btn"
                title="Download"
                data-testid="upload-download"
              >
                <Download :size="14" />
              </a>
              <button
                class="icon-btn"
                title="Move to folder"
                @click="openMoveDialog(art)"
                data-testid="upload-move"
              >
                <FolderInput :size="14" />
              </button>
              <button
                class="icon-btn icon-btn--danger"
                title="Delete"
                @click="handleDelete(art.id)"
              >
                <Trash2 :size="14" />
              </button>
            </div>
          </article>
        </div>
      </div>
    </div>

    <!-- Upload dialog -->
    <div v-if="showUpload" class="upload-modal" @click.self="closeUploadDialog">
      <div class="upload-modal__panel">
        <header class="upload-modal__header">
          <h2>Upload file</h2>
          <button class="icon-btn" @click="closeUploadDialog"><X :size="16" /></button>
        </header>
        <div
          class="upload-drop"
          :class="{ 'upload-drop--active': dragActive }"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop="onDrop"
        >
          <input type="file" id="uploads-file-input" @change="onFileSelect" hidden />
          <label for="uploads-file-input" class="upload-drop__label">
            <Upload :size="22" />
            <span v-if="uploadFile">{{ uploadFile.name }} ({{ formatSize(uploadFile.size) }})</span>
            <span v-else>Click to choose a file, or drag it here</span>
          </label>
        </div>
        <div class="upload-form">
          <label class="form-field">
            <span>Folder <em>(virtual path; defaults to current selection)</em></span>
            <input v-model="uploadFolder" type="text" placeholder="/Uploads or /Designs/Mockups" list="known-folders" />
            <datalist id="known-folders">
              <option v-for="f in folders" :key="f.path" :value="f.path" />
            </datalist>
          </label>
          <label class="form-field">
            <span>Tags <em>(comma-separated)</em></span>
            <input v-model="uploadTagsInput" type="text" placeholder="design, screenshot, v2" />
          </label>
          <label class="form-field">
            <span>Description</span>
            <textarea v-model="uploadDescription" rows="2" placeholder="What is this file?"></textarea>
          </label>
          <label class="form-field">
            <span>Uploader</span>
            <input v-model="uploadUploader" type="text" placeholder="Your name (optional)" />
          </label>
          <label class="form-field">
            <span>As new version of <em>(artifact id, optional)</em></span>
            <input v-model="uploadAsVersionOf" type="text" :placeholder="items[0]?.id || 'art_...'" />
          </label>
          <div v-if="isUploading" class="upload-progress">
            <div class="upload-progress__bar" :style="{ width: uploadProgress + '%' }"></div>
            <span>{{ uploadProgress }}%</span>
          </div>
        </div>
        <footer class="upload-modal__footer">
          <button class="secondary-btn" @click="closeUploadDialog" :disabled="isUploading">Cancel</button>
          <button
            class="primary-btn"
            @click="submitUpload"
            :disabled="!uploadFile || isUploading"
            data-testid="uploads-submit"
          >
            <Upload :size="14" /> {{ isUploading ? 'Uploading…' : 'Upload' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- Move-to-folder dialog -->
    <div v-if="showMoveDialog" class="upload-modal" @click.self="closeMoveDialog">
      <div class="upload-modal__panel upload-modal__panel--small">
        <header class="upload-modal__header">
          <h2>Move to folder</h2>
          <button class="icon-btn" @click="closeMoveDialog"><X :size="16" /></button>
        </header>
        <div class="upload-form">
          <p class="move-target__label">
            Moving <strong>{{ movingArtifact?.name }}</strong>
            <span class="muted"> from <code>{{ movingArtifact?.folderPath }}</code></span>
          </p>
          <label class="form-field">
            <span>New folder path</span>
            <input v-model="moveTarget" type="text" placeholder="/Uploads or /Archive/2026" list="known-folders" />
            <datalist id="known-folders">
              <option v-for="f in folders" :key="f.path" :value="f.path" />
            </datalist>
          </label>
        </div>
        <footer class="upload-modal__footer">
          <button class="secondary-btn" @click="closeMoveDialog">Cancel</button>
          <button class="primary-btn" @click="confirmMove" data-testid="uploads-move-confirm">
            <FolderInput :size="14" /> Move
          </button>
        </footer>
      </div>
    </div>

    <!-- Preview modal (markdown / text / version chain) -->
    <div v-if="previewArtifact" class="preview-modal" @click.self="closePreview">
      <div class="preview-modal__panel">
        <header class="preview-modal__header">
          <div>
            <h2>{{ previewArtifact.name }}</h2>
            <span class="preview-modal__meta">
              v{{ previewArtifact.version }} · {{ formatSize(previewArtifact.sizeBytes) }} ·
              <Folder :size="11" /> {{ previewArtifact.folderPath }} ·
              uploaded {{ formatDate(previewArtifact.createdAt) }} by {{ previewArtifact.uploader || '—' }}
            </span>
          </div>
          <button class="icon-btn" @click="closePreview"><X :size="16" /></button>
        </header>
        <div class="preview-modal__body">
          <div v-if="previewIsImage" class="preview-image">
            <img :src="downloadHref(previewArtifact.id)" :alt="previewArtifact.name" />
          </div>
          <pre v-else-if="previewText !== null" class="preview-text" :class="{ 'preview-text--md': previewIsMarkdown }">{{ previewText }}</pre>
          <div v-else class="preview-binary">
            <Package :size="32" />
            <p>This file type doesn't have an inline preview.</p>
            <a :href="downloadHref(previewArtifact.id)" :download="previewArtifact.name" class="primary-btn">
              <Download :size="14" /> Download
            </a>
          </div>
          <aside v-if="versionChain && versionChain.length > 1" class="version-chain">
            <h3><History :size="14" /> Version history</h3>
            <ul>
              <li
                v-for="v in versionChain"
                :key="v.id"
                :class="{ 'version-chain__item--current': v.id === previewArtifact?.id }"
              >
                <span class="version-chain__badge">v{{ v.version }}</span>
                <span class="version-chain__meta">{{ formatDate(v.createdAt) }} · {{ formatSize(v.sizeBytes) }} · {{ v.uploader || '—' }}</span>
                <a
                  v-if="v.id !== previewArtifact?.id"
                  :href="downloadHref(v.id)"
                  :download="v.name"
                  class="icon-btn"
                  title="Download this version"
                >
                  <Download :size="12" />
                </a>
                <span v-else class="version-chain__current-pill">current</span>
              </li>
            </ul>
          </aside>
        </div>
      </div>
    </div>

    <!-- Image lightbox -->
    <div v-if="lightboxArtifact" class="lightbox" @click.self="closeLightbox">
      <button class="lightbox__close" @click="closeLightbox"><X :size="20" /></button>
      <img :src="downloadHref(lightboxArtifact.id)" :alt="lightboxArtifact.name" class="lightbox__img" />
      <div class="lightbox__caption">
        <strong>{{ lightboxArtifact.name }}</strong>
        <span>{{ formatSize(lightboxArtifact.sizeBytes) }} · {{ lightboxArtifact.uploader || '—' }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.uploads-page {
  display: flex; flex-direction: column; gap: 16px;
  padding: 24px 28px 40px; min-height: 100%;
}
.uploads-page__topbar {
  display: flex; align-items: flex-start; justify-content: space-between;
}
.uploads-page__title { display: flex; flex-direction: column; gap: 6px; }
.uploads-page__kicker { color: var(--muted); font-family: var(--font-mono); font-size: 0.75rem; }
.uploads-page__title h1 { color: var(--ink); font-family: var(--font-display); font-size: 1.65rem; font-weight: 700; margin: 0; }
.uploads-page__title p { color: var(--muted); font-size: 0.875rem; margin: 0; }
.uploads-page__actions { display: flex; gap: 8px; align-items: center; }

.uploads-page__body { display: grid; grid-template-columns: 200px 1fr; gap: 18px; align-items: start; }
@media (max-width: 920px) {
  .uploads-page__body { grid-template-columns: 1fr; }
}

.uploads-folders {
  position: sticky; top: 16px;
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 12px;
}
.uploads-folders__heading {
  display: flex; align-items: center; gap: 6px;
  margin: 0 0 8px; padding: 0 4px;
  font-size: 0.6875rem; text-transform: uppercase;
  color: var(--muted); font-family: var(--font-mono); letter-spacing: 0.04em;
}
.uploads-folders__list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }
.folder-item {
  display: flex; align-items: center; gap: 6px; width: 100%;
  padding: 6px 8px; border-radius: 6px;
  background: transparent; border: none; cursor: pointer;
  color: var(--ink); font-size: 0.8125rem; text-align: left;
  transition: background 150ms;
}
.folder-item:hover { background: var(--surface-soft); }
.folder-item--active { background: var(--primary); color: white; }
.folder-item__name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.folder-item__count {
  font-size: 0.6875rem; padding: 1px 6px; border-radius: 4px;
  background: rgba(0,0,0,0.06); color: var(--muted);
  font-family: var(--font-mono);
}
.folder-item--active .folder-item__count { background: rgba(255,255,255,0.2); color: white; }

.uploads-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }

.uploads-page__stats {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.stat {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 14px 18px;
  display: flex; flex-direction: column; gap: 4px;
}
.stat__label { color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono); }
.stat__value { color: var(--ink); font-size: 1.35rem; font-weight: 700; }
@media (max-width: 720px) { .uploads-page__stats { grid-template-columns: repeat(2, 1fr); } }

.uploads-page__toolbar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 12px 14px; background: var(--surface-soft);
  border: 1px solid var(--hairline); border-radius: 12px;
}
.search-wrap {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 8px; padding: 6px 10px; min-width: 240px;
  color: var(--muted);
}
.search-wrap input { border: none; background: transparent; outline: none; color: var(--ink); font-size: 0.875rem; width: 100%; }
.tag-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--surface); border: 1px solid var(--hairline);
  color: var(--muted); font-size: 0.75rem; cursor: pointer; transition: all 150ms;
}
.chip:hover { color: var(--ink); border-color: var(--primary); }
.chip--active { background: var(--primary); color: white; border-color: var(--primary); }

.uploads-page__error {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; background: var(--clay-red); color: white;
  border-radius: 8px; font-size: 0.875rem;
}
.uploads-page__loading,
.uploads-page__empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 60px 20px; color: var(--muted);
  border: 1px dashed var(--hairline); border-radius: 12px;
  text-align: center;
}
.uploads-page__empty p { color: var(--ink); font-weight: 600; font-size: 1.05rem; margin: 4px 0 0; }
.uploads-page__empty code {
  background: var(--surface-soft); padding: 1px 6px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 0.875rem;
}

.uploads-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
@media (max-width: 720px) { .uploads-grid { grid-template-columns: 1fr; } }

.upload-card {
  display: flex; gap: 14px;
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 14px; transition: border-color 150ms;
}
.upload-card:hover { border-color: var(--primary); }
.upload-card__icon {
  width: 40px; height: 40px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 8px; background: var(--surface-soft); color: var(--primary);
}
.upload-card__body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.upload-card__header { display: flex; align-items: center; gap: 6px; }
.upload-card__name {
  font-size: 0.95rem; font-weight: 600; color: var(--ink);
  margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}
.version-badge {
  background: var(--amber); color: white;
  font-size: 0.6875rem; font-weight: 700; font-family: var(--font-mono);
  padding: 1px 6px; border-radius: 4px;
}
.upload-card__path {
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--primary); font-size: 0.6875rem; font-family: var(--font-mono);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.upload-card__meta {
  display: flex; gap: 6px; flex-wrap: wrap;
  color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono);
}
.upload-card__description {
  margin: 2px 0 0; color: var(--ink); font-size: 0.8125rem; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.upload-card__tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.tag-pill {
  background: var(--surface-soft); color: var(--muted);
  font-size: 0.6875rem; padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono);
}
.upload-card__actions { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: 1px solid var(--hairline);
  border-radius: 6px; color: var(--ink); cursor: pointer;
  text-decoration: none; transition: all 150ms;
}
.icon-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.icon-btn:disabled { opacity: 0.4; cursor: default; }
.icon-btn--danger:hover { color: var(--clay-red); border-color: var(--clay-red); }
.primary-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px;
  background: var(--primary); color: white; font-size: 0.8125rem; font-weight: 600;
  border: none; cursor: pointer; text-decoration: none; transition: opacity 150ms;
}
.primary-btn:hover:not(:disabled) { opacity: 0.85; }
.primary-btn:disabled { opacity: 0.5; cursor: default; }
.secondary-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px;
  background: transparent; color: var(--ink); font-size: 0.8125rem; font-weight: 600;
  border: 1px solid var(--hairline); cursor: pointer;
}
.secondary-btn:hover { border-color: var(--primary); }

.upload-modal {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.upload-modal__panel {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; width: 540px; max-width: 90vw; max-height: 90vh;
  display: flex; flex-direction: column;
}
.upload-modal__panel--small { width: 420px; }
.upload-modal__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--hairline);
}
.upload-modal__header h2 { margin: 0; font-size: 1.1rem; font-family: var(--font-display); }
.upload-drop {
  margin: 18px;
  border: 2px dashed var(--hairline); border-radius: 10px;
  padding: 32px 20px; text-align: center; transition: all 150ms;
}
.upload-drop--active { border-color: var(--primary); background: var(--surface-soft); }
.upload-drop__label {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  cursor: pointer; color: var(--muted); font-size: 0.875rem;
}
.upload-drop__label span { color: var(--ink); }
.upload-form { display: flex; flex-direction: column; gap: 12px; padding: 0 18px 18px; }
.move-target__label { margin: 0; color: var(--ink); font-size: 0.875rem; }
.move-target__label .muted { color: var(--muted); }
.move-target__label code { background: var(--surface-soft); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 0.8125rem; }
.form-field { display: flex; flex-direction: column; gap: 4px; }
.form-field span { color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono); }
.form-field em { font-style: normal; opacity: 0.6; }
.form-field input,
.form-field textarea {
  background: var(--surface-soft); border: 1px solid var(--hairline);
  border-radius: 6px; padding: 8px 10px;
  color: var(--ink); font-size: 0.875rem; font-family: inherit;
  outline: none; transition: border-color 150ms;
}
.form-field input:focus,
.form-field textarea:focus { border-color: var(--primary); }
.upload-progress {
  position: relative; height: 18px;
  background: var(--surface-soft); border-radius: 9px; overflow: hidden;
  border: 1px solid var(--hairline);
}
.upload-progress__bar { position: absolute; left: 0; top: 0; bottom: 0; background: var(--primary); transition: width 200ms; }
.upload-progress span {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  font-size: 0.6875rem; color: var(--ink); font-family: var(--font-mono);
}
.upload-modal__footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 14px 18px; border-top: 1px solid var(--hairline);
}

.preview-modal { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.preview-modal__panel {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 12px; width: 920px; max-width: 92vw; max-height: 88vh;
  display: flex; flex-direction: column;
}
.preview-modal__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--hairline);
}
.preview-modal__header h2 { margin: 0; font-size: 1.05rem; font-family: var(--font-display); }
.preview-modal__meta {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  color: var(--muted); font-size: 0.75rem; font-family: var(--font-mono); margin-top: 2px;
}
.preview-modal__body { display: grid; grid-template-columns: 1fr; gap: 16px; padding: 18px; overflow: auto; flex: 1; min-height: 0; }
.preview-modal__body:has(.version-chain) { grid-template-columns: 2fr 1fr; }
.preview-text {
  background: var(--surface-soft); border: 1px solid var(--hairline);
  border-radius: 8px; padding: 14px;
  font-family: var(--font-mono); font-size: 0.8125rem;
  line-height: 1.5; color: var(--ink);
  overflow: auto; max-height: 60vh; white-space: pre-wrap; word-break: break-word; margin: 0;
}
.preview-text--md { font-family: var(--font-display); }
.preview-image { display: flex; justify-content: center; align-items: center; }
.preview-image img { max-width: 100%; max-height: 60vh; border-radius: 8px; }
.preview-binary { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 40px 20px; color: var(--muted); }
.preview-binary p { color: var(--ink); font-weight: 600; margin: 0; }
.version-chain { background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: 8px; padding: 12px 14px; }
.version-chain h3 { margin: 0 0 8px; font-size: 0.8125rem; color: var(--ink); display: flex; align-items: center; gap: 6px; }
.version-chain ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.version-chain li { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; background: var(--surface); border: 1px solid var(--hairline); }
.version-chain__item--current { border-color: var(--primary); }
.version-chain__badge { background: var(--amber); color: white; font-size: 0.6875rem; font-weight: 700; font-family: var(--font-mono); padding: 1px 6px; border-radius: 4px; }
.version-chain__meta { flex: 1; min-width: 0; color: var(--muted); font-size: 0.6875rem; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-chain__current-pill { font-size: 0.625rem; color: var(--primary); font-weight: 700; font-family: var(--font-mono); text-transform: uppercase; }

.lightbox { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.85); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 110; padding: 40px; }
.lightbox__close { position: absolute; top: 16px; right: 16px; background: var(--surface); border: 1px solid var(--hairline); border-radius: 6px; padding: 6px; color: var(--ink); cursor: pointer; }
.lightbox__img { max-width: 90vw; max-height: 80vh; object-fit: contain; border-radius: 8px; }
.lightbox__caption { margin-top: 16px; display: flex; flex-direction: column; align-items: center; gap: 4px; color: white; font-family: var(--font-mono); font-size: 0.8125rem; }
.lightbox__caption strong { font-size: 0.95rem; }
.lightbox__caption span { color: rgba(255, 255, 255, 0.7); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
