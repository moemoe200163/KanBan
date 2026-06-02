<script setup lang="ts">
import { useBoardStore } from '~/stores/board'
import { Search, X } from 'lucide-vue-next'

const boardStore = useBoardStore()

// Local refs for controlled inputs
const searchQuery = ref(boardStore.searchQuery)
const profileFilter = ref(boardStore.profileFilter)
const harnessFilter = ref(boardStore.harnessFilter)

// Watch for store changes to sync
watch(() => boardStore.searchQuery, (val) => { searchQuery.value = val })
watch(() => boardStore.profileFilter, (val) => { profileFilter.value = val })
watch(() => boardStore.harnessFilter, (val) => { harnessFilter.value = val })

// Debounced search to avoid excessive filtering
let searchTimeout: ReturnType<typeof setTimeout>
watch(searchQuery, (val) => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    boardStore.setSearch(val)
  }, 150)
})

const onProfileChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  boardStore.setProfileFilter(target.value)
}

const onHarnessChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  boardStore.setHarnessFilter(target.value)
}

const clearAllFilters = () => {
  searchQuery.value = ''
  profileFilter.value = 'all'
  harnessFilter.value = 'all'
  boardStore.clearFilters()
}

const hasActiveFilters = computed(() => {
  return searchQuery.value !== '' || profileFilter.value !== 'all' || harnessFilter.value !== 'all'
})

// Profile options
const profiles = [
  { value: 'all', label: 'All Profiles' },
  { value: 'frontend', label: 'Frontend' },
  { value: 'backend', label: 'Backend' },
  { value: 'security', label: 'Security' },
  { value: 'refactor', label: 'Refactor' },
  { value: 'debug', label: 'Debug' },
  { value: 'general', label: 'General' }
]

// Harness options
const harnesses = [
  { value: 'all', label: 'All Harnesses' },
  { value: 'claude-code', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'cursor', label: 'Cursor' },
  { value: 'opencode', label: 'OpenCode' },
  { value: 'gemini', label: 'Gemini' }
]
</script>

<template>
  <div class="toolbar">
    <div class="toolbar__search">
      <Search :size="16" class="toolbar__search-icon" />
      <input
        v-model="searchQuery"
        type="search"
        placeholder="Search by title or key..."
        aria-label="Search issues"
      />
      <button
        v-if="searchQuery"
        class="toolbar__clear-btn"
        @click="searchQuery = ''; boardStore.setSearch('')"
        aria-label="Clear search"
      >
        <X :size="14" />
      </button>
    </div>

    <div class="toolbar__filters">
      <select
        :value="profileFilter"
        @change="onProfileChange"
        aria-label="Filter by profile"
        class="toolbar__select"
      >
        <option v-for="p in profiles" :key="p.value" :value="p.value">
          {{ p.label }}
        </option>
      </select>

      <select
        :value="harnessFilter"
        @change="onHarnessChange"
        aria-label="Filter by harness"
        class="toolbar__select"
      >
        <option v-for="h in harnesses" :key="h.value" :value="h.value">
          {{ h.label }}
        </option>
      </select>

      <button
        v-if="hasActiveFilters"
        class="toolbar__reset-btn"
        @click="clearAllFilters"
      >
        <X :size="14" />
        <span>Clear</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
}

.toolbar__search {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 200px;
  max-width: 320px;
}

.toolbar__search-icon {
  position: absolute;
  left: 10px;
  color: var(--muted);
  pointer-events: none;
}

.toolbar__search input {
  width: 100%;
  padding: 8px 32px 8px 34px;
  color: var(--ink);
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.875rem;
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.toolbar__search input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(204, 120, 92, 0.12);
}

.toolbar__search input::placeholder {
  color: var(--muted-soft);
}

.toolbar__clear-btn {
  position: absolute;
  right: 8px;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  color: var(--muted);
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.toolbar__clear-btn:hover {
  color: var(--ink);
  background: var(--hairline);
}

.toolbar__filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar__select {
  min-height: 36px;
  padding: 0 28px 0 10px;
  color: var(--ink);
  background: var(--surface-soft);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236c6a64' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.8125rem;
  cursor: pointer;
  outline: none;
  appearance: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.toolbar__select:focus {
  border-color: var(--primary);
}

.toolbar__reset-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 36px;
  padding: 0 10px;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.toolbar__reset-btn:hover {
  color: var(--ink);
  border-color: var(--muted-soft);
  background: var(--surface-soft);
}

@media (max-width: 640px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar__search {
    max-width: none;
  }

  .toolbar__filters {
    flex-wrap: wrap;
  }
}
</style>
