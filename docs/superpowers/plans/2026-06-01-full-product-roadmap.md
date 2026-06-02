# DevFlow 全產品規劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DevFlow 從「好看的 demo」進化成真正可運作的 AI Kanban Control Plane。

**Architecture:** 三層結構 — Nuxt 3 前端（Control Plane UI）→ FastAPI（控制平面）→ ECC 命令層（實際 agent runner）。前端不再用 mock data，改由後端 API 驅動。ECC job 從 in-memory 改為 SQLite 持久化。

**Tech Stack:** Nuxt 3, Pinia, FastAPI, SQLite (via SQLAlchemy), Pytest, Playwright

---

## 現況快照

| 維度 | 狀態 |
|------|------|
| `npm run typecheck` | ✅ 通過 |
| `npm run build` | ✅ 通過 |
| `pytest backend/tests` | ✅ 4 passed |
| 前端 3010 / 後端 8000 | ✅ 已固定 |
| 文件收斂 (PLAN/SPEC/Design) | ✅ 完成 |
| `completeAI` 串接 PATCH | ✅ 完成 |
| Issue -> 後端真實 API | ❌ 仍用 mock generateMockIssues() |
| Job 持久化 (SQLite) | ❌ in-memory，重啟消失 |
| 真正 ECC process runner | ❌ 只有 control-plane job record |
| E2E 可跑 | ⚠️ 檔案已寫，依賴未裝 |
| Metrics row | ❌ 缺少 |
| 側邊欄控制面狀態 | ⚠️ 部分虛擬 |
| Quality gate endpoint | ❌ 未實作 |
| Cancel/Pause endpoints | ✅ PATCH 已存在，cancel 已存在 |
| WebSocket 實時更新 | ⚠️ composable 已寫，未串接 |
| CI/PR webhook | ❌ 未實作 |
| 認證 | ❌ 未實作 |

---

## Phase P0: 鞏固地基（1-2 days）

> 確保 build / typecheck / tests 三棧永久綠燈；前端串接真實 API，脫離 mock data。

### P0-Task 1: Issue API 與前端串接

**Files:**
- Modify: `src/stores/board.ts` (fetchBoard action)
- Modify: `src/pages/index.vue` (use boardStore.fetchBoard)
- Create: `backend/api/v1/endpoints/board.py` (GET /board endpoint)

- [ ] **Step 1: 建立 GET /api/v1/board endpoint**

在 `backend/api/v1/endpoints/` 新增 `board.py`，回傳格式對齊前端 `BoardState`：

```python
@router.get("/board")
async def get_board():
    """Return full board state: columns with issues."""
    # 現階段回傳 _issues_db 的格式化資料
    # 最終替換為 SQLAlchemy query
    columns = []
    for status in VALID_STATUSES:
        issues = [i for i in _issues_db if i.status == status]
        columns.append({
            "id": status,
            "title": STATUS_LABELS[status],
            "color": STATUS_COLORS[status],
            "issues": [i.model_dump() for i in issues]
        })
    return {" columns": columns }
```

- [ ] **Step 2: 修改 board store fetchBoard**

```typescript
async fetchBoard() {
  this.isLoading = true
  try {
    const config = useRuntimeConfig()
    const data = await $fetch<{ columns: Column[] }>(`${config.public.apiBase}/board`)
    this.columns = data.columns
  } catch {
    // fallback: 仍用 generateMockIssues() 避免完全炸裂
    const issues = generateMockIssues()
    // ...
  } finally {
    this.isLoading = false
  }
}
```

- [ ] **Step 3: verify - 確認 board 從後端載入**

啟動前後端，確認 board 渲染不炸裂（可用 curl 驗證 API）。

- [ ] **Step 4: commit**

---

### P0-Task 2: Issue 建立 / 更新串接真實 API

**Files:**
- Modify: `src/stores/board.ts` (createIssue, moveIssue, handleIssueUpdate)

- [ ] **Step 1: createIssue 串接 POST /api/v1/issues**

```typescript
async createIssue(title: string, columnId: IssueStatus) {
  const config = useRuntimeConfig()
  const created = await $fetch<Issue>(`${config.public.apiBase}/issues`, {
    method: 'POST',
    body: { title, status: columnId }
  })
  // 加入對應 column
}
```

- [ ] **Step 2: moveIssue 串 PUT /api/v1/issues/{id}/status**

```typescript
// 在 moveIssue 中，確認成功後 call API
const apiUpdated = await $fetch(`${config.public.apiBase}/issues/${issue.id}/status`, {
  method: 'PUT',
  body: { status: toStatus }
})
```

- [ ] **Step 3: commit**

---

### P0-Task 3: Job 持久化 — SQLite + SQLAlchemy

**Files:**
- Create: `backend/db/database.py`
- Create: `backend/db/models.py`
- Modify: `backend/api/v1/endpoints/ecc.py`
- Modify: `backend/main.py`

- [ ] **Step 1: 安裝依賴**

```bash
pip install sqlalchemy aiosqlite
```

- [ ] **Step 2: 建立 database.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = "sqlite+aiosqlite:///./devflow.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 3: 建立 models.py**

```python
# 同步 Design.md 的 Prisma schema 到 SQLAlchemy
class IssueModel(Base):
    __tablename__ = "issues"
    id = Column(String, primary_key=True)
    key = Column(String, unique=True)
    title = Column(String)
    description = Column(String, default="")
    status = Column(String, default="backlog")
    priority = Column(String, default="medium")
    profile = Column(String, default="general")
    # ... 其他欄位對齊 Issue interface
```

- [ ] **Step 4: 改造 ecc.py 的 _jobs 為資料庫**

把 `Dict[str, ECCDispatchJob]` 換成 SQLite 寫入。`_complete_job` / `_transition_job` 改為寫入 DB。

- [ ] **Step 5: verify - 重啟後端，確認 jobs 不消失**

```bash
# 建立一個 job
curl -X POST http://localhost:8000/api/v1/ecc/dispatch \
  -H "Content-Type: application/json" \
  -d '{"issue_id":"1","issue_key":"DEV-001","command":"/loop-start --profile=frontend","profile":"frontend","harness":"claude-code"}'

# 重啟後端
# 查詢 job 還在
curl http://localhost:8000/api/v1/ecc/jobs
```

- [ ] **Step 6: commit**

---

## Phase P1: Control Plane 完整化（2-3 days）

> 所有 column action 都有對應後端 endpoint；quality gate / pause / cancel 全上；metrics row 真實。

### P1-Task 1: Quality Gate Endpoint

**Files:**
- Modify: `backend/api/v1/endpoints/ecc.py`

- [ ] **Step 1: 新增 POST /ecc/quality-gate**

```python
@router.post("/ecc/quality-gate")
async def quality_gate(issue_id: str, job_id: str):
    """Run quality checks: lint + test + security scan."""
    # 讀取 job events，模擬 quality gate 結果
    # 回傳: { "passed": bool, "checks": [...], "blocked": bool }
```

- [ ] **Step 2: commit**

---

### P1-Task 2: Metrics Row

**Files:**
- Create: `src/components/MetricsRow.vue`
- Modify: `src/pages/index.vue`

- [ ] **Step 1: 建立 MetricsRow.vue**

顯示四格：Active Runs / Human Review / Blocked / Harness。資料來自 `boardStore` getters。

```vue
<template>
  <div class="metrics-row">
    <div class="metrics-tile">
      <span class="metrics-tile__value">{{ boardStore.inProgressCount }}</span>
      <span class="metrics-tile__label">Active Runs</span>
    </div>
    <!-- 其他三格類似 -->
  </div>
</template>
```

- [ ] **Step 2: 加入 index.vue**

- [ ] **Step 3: commit**

---

### P1-Task 3: CI/PR Webhook Endpoint

**Files:**
- Create: `backend/api/v1/endpoints/webhooks.py` (已有內容，確認完整)

- [ ] **Step 1: 確認 POST /webhooks/ci 端點存在且更新 issue.ciStatus**

```python
@router.post("/webhooks/ci")
async def ci_webhook(payload: CIDeployRequest):
    # 根據 job_id 或 issue_key 找 issue
    # 更新 ciStatus: "pending" | "passed" | "failed"
```

- [ ] **Step 2: 確認 webhook 端點可從 GitHub Actions call**

- [ ] **Step 3: commit**

---

## Phase P2: 真正 Agent Runner（3-5 days）

> `/ecc/dispatch` 不只是建立 job record，而是真的啟動 `claude-code` 之類的 process。

### P2-Task 1: ECC Process Runner

**Files:**
- Create: `backend/core/runner.py`
- Modify: `backend/api/v1/endpoints/ecc.py`

- [ ] **Step 1: 建立 runner.py**

```python
import asyncio
import subprocess
from typing import Optional

class ECCRunner:
    def __init__(self):
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def start(self, job_id: str, command: str, working_dir: str) -> None:
        """Start an ECC command as a subprocess."""
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.active_processes[job_id] = process

    async def read_output(self, job_id: str) -> str:
        """Read stdout/stderr from running process."""
        process = self.active_processes.get(job_id)
        if not process:
            return ""
        # 非阻塞讀取
        # 寫入 job events 表
```

- [ ] **Step 2: 改造 dispatch 端點**

`POST /ecc/dispatch` 在建立 job record 後，馬上啟動 `ECCRunner`。

- [ ] **Step 3: stdout/stderr 寫入 job events**

每個 job 的 events 陣列真實紀錄 agent 輸出。

- [ ] **Step 4: commit**

---

### P2-Task 2: WebSocket 實時推送

**Files:**
- Modify: `backend/main.py` (add WebSocket route)
- Modify: `src/composables/useWebSocket.ts` (已存在，確認串接)
- Modify: `src/stores/board.ts`

- [ ] **Step 1: 後端 WebSocket endpoint**

```python
from fastapi import WebSocket

@router.websocket("/ws/board")
async def board_websocket(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # 廣播 job event 給所有 clients
```

- [ ] **Step 2: 前端 useWebSocket 串接到 board store**

當收到 job update event 時，自動更新對應 issue 的 `eccJobStatus`。

- [ ] **Step 3: commit**

---

## Phase P3: 完整 UI / UX（2-3 days）

### P3-Task 1: Toolbar（搜尋 + 篩選）

**Files:**
- Modify: `src/components/KanbanBoard.vue`

- [ ] **Step 1: 加入搜尋框**

`useBoardStore` 的 `getAllIssues` getter 已經存在，搜尋可做 client-side filter。

- [ ] **Step 2: 加入 Priority / Profile filter 下拉**

- [ ] **Step 3: commit**

---

### P3-Task 2: 側邊欄控制面狀態

**Files:**
- Modify: `src/components/AppSidebar.vue`

- [ ] **Step 1: Backend status indicator**

Call `GET /health` 或 `GET /api/v1/ecc/jobs` 看有多少 active jobs。

- [ ] **Step 2: Human Review count badge**

- [ ] **Step 3: Harness switcher（切換 claude-code / codex 等）**

- [ ] **Step 4: commit**

---

## Phase P4: E2E 測試（1 day）

### P4-Task 1: Playwright 安裝與 E2E 跑通

**Files:**
- Modify: `package.json` (加入 @playwright/test dependency)

- [ ] **Step 1: 安裝 @playwright/test**

```bash
npm install --save-dev @playwright/test
npx playwright install chromium
```

- [ ] **Step 2: 執行 e2e/board.spec.ts**

```bash
npm run e2e
```

- [ ] **Step 3: commit**

---

## Phase P5: 生產就緒（2-3 days）

### P5-Task 1: 認證

**Files:**
- Create: `backend/core/auth.py`
- Modify: `backend/main.py`

- [ ] **Step 1: 加入簡單 JWT 認證 middleware**

所有 `/api/v1/` 端點需要 `Authorization: Bearer <token>` header。

- [ ] **Step 2: commit**

---

### P5-Task 2: Docker / 部署

**Files:**
- Modify: `Dockerfile` (已有，需確認完整)
- Create: `docker-compose.yml`

- [ ] **Step 1: 確認 Dockerfile multi-stage build**

- [ ] **Step 2: 加入 docker-compose.yml**

- [ ] **Step 3: commit**

---

## 執行順序建議

```
P0 (鞏固地基)
  └─ Task 1: 前端串接 GET /board API
  └─ Task 2: Issue CRUD 串接
  └─ Task 3: SQLite 持久化

P1 (Control Plane 完整化)
  └─ Task 1: Quality Gate endpoint
  └─ Task 2: Metrics Row
  └─ Task 3: CI/PR Webhook

P2 (真正 Runner)
  └─ Task 1: ECC Process Runner
  └─ Task 2: WebSocket 實時更新

P3 (UI/UX)
  └─ Task 1: Toolbar 搜尋/篩選
  └─ Task 2: 側邊欄控制面狀態

P4 (E2E)
  └─ Task 1: Playwright 安裝與跑通

P5 (生產)
  └─ Task 1: 認證
  └─ Task 2: Docker 部署
```

---

## 驗收標準（每 Phase 結束時）

| Phase | 驗收 |
|-------|------|
| P0 | `npm run typecheck && npm run build && pytest -q` 全綠燈；前後端重啟不丟 jobs；board 真實從 API 載入 |
| P1 | Quality gate endpoint 存在且被 call；Metrics row 有數字；CI webhook 更新 issue.ciStatus |
| P2 | `/ecc/dispatch` 真的啟動 process；job events 有真實 stdout/stderr；WebSocket 推送更新前端 |
| P3 | 搜尋即時過濾；側邊欄顯示真實 backend 狀態 |
| P4 | `npm run e2e` 全部通過 |
| P5 | Docker compose up 成功；未認證 request 被 block |

---

**Plan complete.** 儲存於 `docs/superpowers/plans/2026-06-01-full-product-roadmap.md`

**執行選項：**

**1. Subagent-Driven（推薦）** — 每個 Task 由獨立 subagent 執行，Task 間有檢查點

**2. Inline Execution** — 在這個 session 內批次執行，有檢查點

你想從哪個 Phase 開始？建議從 **P0** 做起——鞏固地基再做上層，否則上層改動會一直踩到 mock data 不匹配的問題。
