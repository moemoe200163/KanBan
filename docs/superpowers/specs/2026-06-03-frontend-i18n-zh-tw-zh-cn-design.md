# DevFlow 前端繁中 / 簡中雙語化設計

> Date: 2026-06-03
> Status: Approved
> Scope: Frontend only, SPA (ssr: false)

## Summary

DevFlow 前端支援 `zh-TW`（預設）與 `zh-CN` 切換。不支援 English UI，不做多語系路由，不改 URL，不引入 `@nuxtjs/i18n`。

採用靜態 typed dictionary + localStorage locale store + composable `useI18n()`，所有使用者可見 UI 文字從硬編碼英文替換為 `t()` 呼叫。

## Architecture

### File Structure

```text
src/
  i18n/
    index.ts              # 匯出 resolve 邏輯、型別
    zh-TW.ts              # 繁中字典（canonical source）
    zh-CN.ts              # 簡中字典（key shape 必須與 zh-TW 一致）
  composables/
    useI18n.ts            # export { t, locale, setLocale, formatDateTime }
  stores/
    locale.ts             # locale 狀態 + localStorage 持久化
  components/
    common/
      LocaleSwitcher.vue  # 地球 icon + 下拉選單
```

### Runtime Flow

```text
localStorage 讀取 locale (預設 zh-TW)
  → locale store 初始化
  → useI18n() 提供 t() 給所有組件
  → setLocale() 更新 store + localStorage + 觸發 reactive 更新
  → formatDateTime() 根據 locale 切換日期格式
```

## Dictionary Format

```ts
// src/i18n/zh-TW.ts — canonical source
export const zhTW = {
  sidebar: {
    board: '看板',
    backlog: '待辦',
    agents: '代理',
    runs: '執行記錄',
    webhooks: 'Webhooks',
    analytics: '分析',
    settings: '設定',
    controlPlane: '控制平面',
    boardStats: '看板統計',
    backend: '後端',
    activeRuns: '執行中',
    review: '審核',
    blocked: '封鎖',
  },
  board: {
    title: 'AI 交付看板',
    newIssue: '新增任務',
    search: '搜尋...',
    activeRuns: '執行中',
    humanReview: '人工審核',
    harness: '執行工具',
  },
  status: {
    backlog: '待辦',
    inProgress: '執行中',
    blocked: '封鎖',
    humanReview: '人工審核',
    done: '完成',
  },
  priority: {
    low: '低',
    medium: '中',
    high: '高',
    critical: '緊急',
  },
  profile: {
    frontend: '前端',
    backend: '後端',
    security: '安全',
    refactor: '重構',
    debug: '除錯',
    general: '通用',
  },
  // ... 其餘 namespace（完整 key 列表見 Appendix）
} as const

export type Dictionary = typeof zhTW
```

```ts
// src/i18n/zh-CN.ts
import type { Dictionary } from './zh-TW'

export const zhCN: Dictionary = {
  sidebar: {
    board: '看板',
    backlog: '待办',
    agents: '代理',
    runs: '执行记录',
    webhooks: 'Webhooks',
    analytics: '分析',
    settings: '设置',
    controlPlane: '控制平面',
    boardStats: '看板统计',
    backend: '后端',
    activeRuns: '执行中',
    review: '审核',
    blocked: '阻塞',
  },
  board: {
    title: 'AI 交付看板',
    newIssue: '新增任务',
    search: '搜索...',
    activeRuns: '执行中',
    humanReview: '人工审核',
    harness: '执行工具',
  },
  status: {
    backlog: '待办',
    inProgress: '执行中',
    blocked: '阻塞',
    humanReview: '人工审核',
    done: '完成',
  },
  priority: {
    low: '低',
    medium: '中',
    high: '高',
    critical: '紧急',
  },
  profile: {
    frontend: '前端',
    backend: '后端',
    security: '安全',
    refactor: '重构',
    debug: '除错',
    general: '通用',
  },
  // ...
}
```

### Fallback Logic

```ts
// src/i18n/index.ts
import { zhTW } from './zh-TW'
import { zhCN } from './zh-CN'
import type { Dictionary } from './zh-TW'

export type Locale = 'zh-TW' | 'zh-CN'

const dictionaries: Record<Locale, Dictionary> = {
  'zh-TW': zhTW,
  'zh-CN': zhCN,
}

export function resolve(locale: Locale, path: string): string {
  const dict = dictionaries[locale]
  const keys = path.split('.')
  let current: any = dict
  for (const key of keys) {
    if (current == null) return fallback(locale, path)
    current = current[key]
  }
  if (typeof current !== 'string') return fallback(locale, path)
  return current
}

function fallback(locale: Locale, path: string): string {
  console.warn(`[i18n] Missing key "${path}" in locale "${locale}"`)
  // fallback to zh-TW
  if (locale !== 'zh-TW') return resolve('zh-TW', path)
  return path
}
```

## Composable API

```ts
// src/composables/useI18n.ts
import { useLocaleStore } from '~/stores/locale'
import { resolve } from '~/i18n'
import type { Locale } from '~/i18n'

const DATE_LOCALE_MAP: Record<Locale, string> = {
  'zh-TW': 'zh-TW',
  'zh-CN': 'zh-CN',
}

export function useI18n() {
  const store = useLocaleStore()

  function t(path: string): string {
    return resolve(store.locale, path)
  }

  function formatDateTime(date: Date | string, options?: Intl.DateTimeFormatOptions): string {
    const d = typeof date === 'string' ? new Date(date) : date
    return d.toLocaleDateString(DATE_LOCALE_MAP[store.locale], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      ...options,
    })
  }

  return {
    locale: computed(() => store.locale),
    setLocale: store.setLocale,
    t,
    formatDateTime,
  }
}
```

## Locale Store

```ts
// src/stores/locale.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Locale } from '~/i18n'

const STORAGE_KEY = 'devflow-locale'

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<Locale>(
    (localStorage.getItem(STORAGE_KEY) as Locale) || 'zh-TW'
  )

  function setLocale(l: Locale) {
    locale.value = l
    localStorage.setItem(STORAGE_KEY, l)
  }

  return { locale, setLocale }
})
```

## LocaleSwitcher Component

```vue
<!-- src/components/common/LocaleSwitcher.vue -->
<template>
  <div class="relative" ref="dropdownRef">
    <button
      class="locale-toggle"
      @click="open = !open"
      title="語言設定"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none"
        viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
          d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418" />
      </svg>
    </button>

    <div v-if="open" class="locale-dropdown">
      <button
        v-for="loc in locales"
        :key="loc.value"
        @click="switchLocale(loc.value)"
        :class="{ active: locale === loc.value }"
      >
        {{ loc.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Locale } from '~/i18n'

const open = ref(false)
const dropdownRef = ref<HTMLElement>()
const { locale, setLocale } = useI18n()

const locales = [
  { value: 'zh-TW' as const, label: '繁體中文' },
  { value: 'zh-CN' as const, label: '简体中文' },
]

function switchLocale(l: Locale) {
  setLocale(l)
  open.value = false
}

// 點擊外部關閉
onMounted(() => {
  document.addEventListener('click', (e) => {
    if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
      open.value = false
    }
  })
})
</script>
```

位置：`layouts/default.vue` 右上角，與 Dark Mode 切換相鄰。

## Component Integration Pattern

### 替換硬編碼文字

```vue
<!-- Before -->
<h1>AI Delivery Board</h1>
<span>Backlog</span>

<!-- After -->
<h1>{{ t('board.title') }}</h1>
<span>{{ t('status.backlog') }}</span>
```

### Config Objects 整合

`types/index.ts` 中的 `COLUMN_CONFIG`、`PRIORITY_CONFIG`、`PROFILE_CONFIG` 移除 label，由 `t()` 翻譯：

```ts
// Before
export const COLUMN_CONFIG = {
  backlog: { title: 'Backlog', color: '#6B7280' },
}

// After — color 保留，title 改由 t() 翻譯
export const COLUMN_CONFIG = {
  backlog: { color: '#6B7280' },
}
```

```vue
<span :style="{ color: COLUMN_CONFIG[col].color }">
  {{ t(`status.${col}`) }}
</span>
```

### Store 層英文標籤

`llm.ts`、`collaboration.ts` 中的英文 status labels 改為小寫 key：

```ts
// Before
status: 'Healthy'

// After
status: 'healthy'
```

```vue
<span>{{ t(`llmStatus.${job.status}`) }}</span>
```

### Date 格式化

使用 `formatDateTime()` 替換 `toLocaleDateString('en-US', ...)`：

```vue
<!-- Before -->
<span>{{ new Date(entry.timestamp).toLocaleDateString('en-US', { ... }) }}</span>

<!-- After -->
<span>{{ formatDateTime(entry.timestamp) }}</span>
```

## Fixed Terminology

| Concept | zh-TW | zh-CN |
|---|---|---|
| Issue | 任務 | 任务 |
| Job | 執行作業 | 执行作业 |
| Handoff | 交接 | 交接 |
| Evidence | 證據 | 证据 |
| Review | 審核 | 审核 |
| Blocked | 封鎖 | 阻塞 |
| Worker Lane | 工作泳道 | 工作泳道 |
| Delivery Orchestrator | 交付編排器 | 交付编排器 |
| Control Plane | 控制平面 | 控制平面 |

## Not Translated

- Issue key: `DEV-001`
- Commands: `/loop-start`
- Provider/model IDs: `claude-code`, `gpt-4.1`, `safe-runner`
- API payload keys
- Backend raw logs
- Agent output

## Extraction Order

按影響範圍排序：

1. `sidebar/Sidebar.vue` — 全局導航
2. `KanbanBoard.vue` + `KanbanColumn.vue` — 主要工作區
3. `IssueDetail.vue` + `IssueCard.vue` — 核心互動
4. `NewIssueModal.vue` — 表單文字
5. `toolbar/Toolbar.vue` — 搜尋篩選
6. `pages/settings/index.vue` — 設定頁
7. `pages/command-center.vue` — Command Center
8. `StatusBadge.vue` — 狀態標籤
9. `lane/HandoffCard.vue` + `HandoffSection.vue` + `LaneMatrix.vue` — 工作泳道
10. 其餘頁面（agents, analytics, activity, backlog, runs, lanes）
11. 其餘組件（WebhookConfig, CollaborationPanel, ReviewQueue 等）

## Verification

### Automated

```bash
npm run typecheck        # zh-CN key shape 編譯期檢查
npm run build            # 確認無編譯錯誤
npm run i18n:check       # 新增腳本：驗證 key 一致性
```

`i18n:check` 檢查項目：

- `zh-CN` key shape 等於 `zh-TW`
- 沒有空字串 value
- 沒有 fallback 到 key path 的情況

### Manual

| 項目 | 預期 |
|------|------|
| 預設語系 | 顯示繁體中文 |
| 切到簡中 | Sidebar / Board / Modal / Issue Detail / Settings 全部更新 |
| 刷新頁面 | 語系保留 |
| 切換語系 | 不清空 board state |
| Mobile 地球 icon | 可點擊，下拉選單不遮擋內容 |
| 長字串 | 不溢出按鈕、卡片、tab |
| Date 格式 | 隨語系切換 (zh-TW / zh-CN) |

### E2E (建議)

- default locale is zh-TW
- switch to zh-CN and persists after reload
- switch back to zh-TW
- locale dropdown closes on outside click
- New Issue modal labels follow locale
- Issue Detail tabs follow locale
- Command Center labels follow locale

## Assumptions

- DevFlow 是 SPA (`ssr: false`)，不需要 Nuxt i18n route integration。
- 第一版只支援 zh-TW 與 zh-CN，不做 English UI。
- 不引入 `@nuxtjs/i18n` module。
- MCP 僅作為開發/驗收工具，不成為產品 runtime 依賴。
- 翻譯字典為靜態，不從外部 API 動態載入。
