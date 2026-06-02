# DevFlow Team Collaboration - 5-Agent Architecture Plan

## 任務概述

建立一個基於 **DevFlow Kanban** 的多代理團隊協作系統，整合 AI 自動化工作流與安全監控。

### 系統目標

1. **多代理協作**：5 個專業 Agent（Architect, Frontend, Backend, Security, QA）分工處理任務
2. **AI 自動化**：當看板狀態變更時，自動觸發 AI Agent 執行任務
3. **團隊協作**：Webhook 驅動的狀態同步、PR 自動化、CI/CD 整合
4. **安全監控**：Agent Shield 審計、費用控制、Tailscale 安全訪問

---

## 1. 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Nuxt 3)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Kanban  │  │  Board   │  │  Issue   │  │  AI      │        │
│  │  Column  │  │  View    │  │  Detail  │  │  Status  │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │                │
│       └─────────────┴─────────────┴─────────────┘                │
│                         Pinia Store                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTP/WebSocket
┌─────────────────────────────▼───────────────────────────────────┐
│                      Backend (FastAPI)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Webhook  │  │  Task    │  │   AI    │  │  State   │        │
│  │ Handler  │  │  Queue   │  │ Client  │  │  Sync    │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │                │
│       └─────────────┴─────────────┴─────────────┘                │
│                    PostgreSQL + Redis                           │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                   AI Execution Engine                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Claude   │  │ Memory   │  │  GitHub  │  │ Budget   │        │
│  │ Code CLI │  │ System   │  │   API    │  │ Control  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 前端增強計劃 (Frontend Engineer)

### 2.1 需要新增的檔案

| 檔案 | 操作 | 描述 |
|------|------|------|
| `src/components/AgentStatusPanel.vue` | 新增 | 顯示 5 個 Agent 的即時狀態 |
| `src/components/CollaborationPanel.vue` | 新增 | 團隊成員 presence、評論 |
| `src/components/WebhookConfig.vue` | 新增 | Webhook URL 設定與歷史 |
| `src/composables/useWebSocket.ts` | 新增 | 即時狀態同步 |
| `src/stores/collaboration.ts` | 新增 | 協作狀態管理 |
| `src/pages/settings/webhooks.vue` | 新增 | Webhook 設定頁面 |

### 2.2 實作步驟

#### Step 1: WebSocket 即時同步
```typescript
// src/composables/useWebSocket.ts
export const useWebSocket = () => {
  const isConnected = ref(false)
  const lastEvent = ref<WebhookEvent | null>(null)

  const connect = () => {
    // 建立 WebSocket 連線
    // 監聽 Issue 狀態變更
    // 更新 Pinia store
  }

  return { isConnected, lastEvent, connect }
}
```

#### Step 2: Agent 狀態面板
- 顯示每個 Agent 的狀態（idle/running/error）
- 即時任務進度
- 錯誤與警告

#### Step 3: 協作功能
- 成員 presence（線上/離開）
- Issue 評論與討論
- 活動日誌串流

---

## 3. 後端建構計劃 (Backend Engineer)

### 3.1 需要新增的檔案

| 檔案 | 操作 | 描述 |
|------|------|------|
| `backend/main.py` | 新增 | FastAPI 主應用 |
| `backend/api/v1/endpoints/webhooks.py` | 新增 | Webhook 處理端點 |
| `backend/api/v1/endpoints/agents.py` | 新增 | Agent 狀態與控制 |
| `backend/api/v1/endpoints/issues.py` | 新增 | Issue CRUD |
| `backend/core/ai_client.py` | 新增 | Claude Code / API 客戶端 |
| `backend/core/task_queue.py` | 新增 | Task Queue 管理 |
| `backend/core/memory_system.py` | 新增 | Context Memory |
| `backend/db/models.py` | 新增 | Prisma Schema |
| `backend/core/security.py` | 新增 | Agent Shield 整合 |

### 3.2 API 端點設計

```python
# Webhook 端點
POST /api/v1/webhooks/trigger
  - Body: { issue_id, old_status, new_status, actor }
  - 觸發 AI Agent 執行

# Agent 控制
GET  /api/v1/agents/status
POST /api/v1/agents/dispatch
POST /api/v1/agents/terminate
GET  /api/v1/agents/budget

# Issue 管理
GET  /api/v1/issues
POST /api/v1/issues
PUT  /api/v1/issues/:id/status
```

### 3.3 任務流程

```
1. Frontend 發送 Webhook → FastAPI
2. FastAPI 驗證並加入 Task Queue (Redis)
3. AI Client 從 Queue 取出任務
4. 執行 Claude Code CLI
5. GitHub API 建立 PR
6. CI 回調更新 Issue 狀態
```

---

## 4. AI 執行引擎 (Architect)

### 4.1 Claude Code 整合

```python
# backend/core/ai_client.py
class AIClient:
    async def dispatch(self, issue: Issue, context: dict) -> ExecutionResult:
        # 1. 準備 context（讀取 memory system）
        # 2. 執行 Claude Code CLI
        # 3. 監控進度（WebSocket 推送）
        # 4. 建立 PR
        # 5. 返回結果
```

### 4.2 Memory System

```
backend/memory/
├── context.json          # 當前任務上下文
├── embeddings/           # 向量資料庫（可選）
└── sessions/             # 長期會話記憶
```

### 4.3 費用控制

```python
# Budget Controller
class BudgetController:
    MAX_HOURS = 5  # 每月上限

    def check_limit(self) -> bool:
        # 檢查已用 token / 時間
        # 接近上限時終止 Agent
```

---

## 5. 安全監控計劃 (Security Engineer)

### 5.1 Agent Shield 整合

- **威脅檢測**：API 注入、敏感資料外洩
- **audit**：所有 Agent 操作均被記錄
- **合規**：OWASP Top 10 預防

### 5.2 安全措施

| 措施 | 實作 |
|------|------|
| Webhook 簽名驗證 | HMAC-SHA256 |
| API Key 管理 | Environment Variable |
| Rate Limiting | Redis + Lua Script |
| 審計日誌 | PostgreSQL + Logstash |

---

## 6. 實作順序

### Phase 1: 基礎設施（1-2 天）
1. [ ] FastAPI 專案架構建立
2. [ ] PostgreSQL + Redis 設定
3. [ ] 基礎 API 端點

### Phase 2: 前端增強（2-3 天）
4. [ ] WebSocket 即時同步
5. [ ] Agent 狀態面板
6. [ ] 協作功能

### Phase 3: AI 整合（3-4 天）
7. [ ] Claude Code CLI 整合
8. [ ] Memory System 建構
9. [ ] PR 自動化

### Phase 4: 安全與監控（2 天）
10. [ ] Agent Shield 整合
11. [ ] 費用控制系統
12. [ ] 審計日誌

---

## 7. SESSION_ID（用於後續執行）

此计划为初始版本，暂未调用外部模型。

```
CODEX_SESSION: 待創建
GEMINI_SESSION: 待創建
```

---

## 8. 風險與緩解

| 風險 | 可能性 | 影響 | 緩解措施 |
|------|--------|------|----------|
| Claude Code API 延遲 | 中 | 中 | 任務佇列 + 進度顯示 |
| Webhook 可靠性 | 低 | 高 | 重試機制 + 補償 |
| 費用超支 | 中 | 高 | Budget Controller |
| 安全漏洞 | 低 | 高 | Agent Shield + 審計 |

---

## 9. 驗收標準

- [ ] Kanban 狀態變更觸發 AI Agent
- [ ] 5 個 Agent 狀態即時顯示
- [ ] PR 自動建立並更新狀態
- [ ] Budget 接近上限時自動終止
- [ ] 所有操作有審計日誌