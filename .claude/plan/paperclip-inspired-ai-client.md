# DevFlow AI Client 重構實施計劃

> 基於 Paperclip 架構模式的漸進式重構方案

---

## 概述

### 任務類型
- [x] Backend (→ Codex 分析)
- [x] Frontend (→ Gemini 分析)
- [x] Fullstack (→ 綜合兩者)

### 技術方案
採用三階段漸進式重構，參考 Paperclip 的 Adapter Pattern 與 Session Management。第一階段解鎖 P0 功能（實際 ECC dispatch + WebSocket 日誌），後兩階段進行架構解耦。

### 核心價值
- **解耦 (Decoupling)**: Adapter Pattern 消除底層執行引擎差異
- **狀態持久化 (State Persistence)**: Session Management 支援長任務中斷與恢復
- **統一通訊介面**: onLog callback → WebSocket 廣播

---

## 第一階段：提取執行與通訊介面（解鎖 P0）

### 目標
讓 Kanban 拖放操作實際觸發背景進程，並透過 WebSocket 推送日誌。

### 實作步驟

#### Step 1: 重構 `execute_claude()` 簽名

**檔案**: `backend/core/ai_client.py`

- [ ] **Step 1.1**: 修改 `execute_claude()` 方法簽名

```python
# Line ~214 - 新增 task_id 和 on_log_callback 參數
async def execute_claude(
    self,
    prompt: str,
    working_dir: str,
    task_id: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> tuple[str, str]:
```

- [ ] **Step 1.2**: 在 subprocess 執行時加入 streaming log

```python
# Line ~244-260 - 在 process.communicate() 之前加入
# 使用 ensure_future 非阻塞發送 log
if on_log and task_id:
    # 創建 async task 進行 log 發送
    asyncio.create_task(self._stream_logs(process, on_log))
```

- [ ] **Step 1.3**: 新增 `_stream_logs()` helper method

```python
async def _stream_logs(self, process, on_log: Callable):
    """非阻塞地將 stdout/stderr 通過 callback 發送"""
    # 讀取 process.stderr 並逐行發送
    # 避免阻塞主執行緒
```

#### Step 2: 將 onLog 綁定到 WebSocket 廣播器

**檔案**: `backend/api/v1/endpoints/ecc.py`

- [ ] **Step 2.1**: 在 `_complete_job()` 中觸發 `broadcast_job_update()`

```python
# Line ~72-78 - 修改 _complete_job 函數
def _complete_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if not job:
        return

    _transition_job(job, "running", "Dispatch accepted by local control plane")

    # 觸發 WebSocket 廣播
    from .ws import broadcast_job_update
    asyncio.ensure_future(broadcast_job_update(job_id, job.model_dump()))
```

- [ ] **Step 2.2**: 在 `dispatch_ecc_command()` 中連接 execute_claude 與 broadcast

```python
# Line ~152-208 - dispatch_ecc_command endpoint
# 在 background_tasks.add_task(_complete_job, job.id) 之後
# 新增實際的 AI 執行邏輯
```

#### Step 3: 前端 boardStore 呼叫 ECC dispatch

**檔案**: `src/stores/board.ts`

- [ ] **Step 3.1**: 新增 `dispatchECCCommand()` method

```typescript
// 在 moveIssue() 或新方法中呼叫
async function dispatchECCCommand(issueId: string, issueKey: string, command: string, profile: string) {
  const response = await fetch('/api/v1/ecc/dispatch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      issue_id: issueId,
      issue_key: issueKey,
      command: command,
      profile: profile,
      harness: 'claude-code'
    })
  })
  return response.json()
}
```

- [ ] **Step 3.2**: 修改 `moveIssueWithUnlock()` 以觸發 dispatch

```typescript
// 當 move 到 in_progress 時，呼叫 dispatchECCCommand
// 並將返回的 job_id 存入 issue.eccJobId
```

#### Step 4: 修復 Toolbar 過濾器

**檔案**: `src/components/KanbanBoard.vue`

- [ ] **Step 4.1**: 使用 store 的 filter 而非 local state

```javascript
// Line ~45 - 改為讀取 boardStore.searchQuery, boardStore.profileFilter
const filteredColumns = computed(() => {
  return columns.value.map(column => ({
    ...column,
    issues: column.issues.filter(issue => {
      // 使用 boardStore 的過濾器
      const matchesSearch = boardStore.searchQuery
        ? issue.title.toLowerCase().includes(boardStore.searchQuery.toLowerCase())
        : true
      const matchesProfile = !boardStore.profileFilter
        || issue.profile === boardStore.profileFilter
      return matchesSearch && matchesProfile
    })
  }))
})
```

### 預期交付
- 拖放卡片到 "In Progress" 實際觸發 `/loop-start --profile={profile}`
- WebSocket 即時推送執行日誌到 UI
- Toolbar 的 Profile/Harness 過濾器實際運作

### 關鍵檔案

| 檔案 | 操作 | 描述 |
|------|------|------|
| `backend/core/ai_client.py:214-286` | Modify | execute_claude() 新增 task_id, on_log callback |
| `backend/api/v1/endpoints/ecc.py:72-78` | Modify | _complete_job() 觸發 WebSocket 廣播 |
| `backend/api/v1/endpoints/ecc.py:152-208` | Modify | dispatch_ecc_command() 連接 AI 執行 |
| `src/stores/board.ts:new` | Add | dispatchECCCommand() method |
| `src/components/KanbanBoard.vue:L40-60` | Modify | 使用 store filter 而非 local state |

---

## 第二階段：引入 Adapter 介面（對齊 P1/P2）

### 目標
為未來切換 Codex/Cursor 鋪路，解決 subprocess 管理混亂。

### 實作步驟

#### Step 1: 建立 Adapter 基礎設施

**目錄**: `backend/core/adapters/`

- [ ] **Step 1.1**: 創建 `__init__.py` 和 `base.py`

```python
# backend/core/adapters/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable

class BaseAIAdapter(ABC):
    @abstractmethod
    async def dispatch(self, issue: Dict[str, Any], context: Dict[str, Any]) -> ExecutionResult:
        """觸發 AI 執行並返回結果"""
        pass

    @abstractmethod
    async def execute(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        on_log: Optional[Callable[[str], None]] = None
    ) -> ExecutionResult:
        """執行單一任務並可選地 streaming log"""
        pass

    @property
    @abstractmethod
    def supported_harnesses(self) -> list[str]:
        """返回支援的 harness 類型"""
        pass
```

- [ ] **Step 1.2**: 創建 `claude_local.py`

```python
# backend/core/adapters/claude_local.py
from .base import BaseAIAdapter
# 將現有的 AIClient.execute_claude() 邏輯移入這裡
```

#### Step 2: 建立 Adapter Registry

**檔案**: `backend/core/adapters/registry.py`

- [ ] **Step 2.1**: 創建 HarnessRegistry

```python
class HarnessRegistry:
    _adapters: Dict[str, BaseAIAdapter] = {}

    @classmethod
    def register(cls, harness_type: str, adapter: BaseAIAdapter):
        cls._adapters[harness_type] = adapter

    @classmethod
    def get(cls, harness_type: str) -> BaseAIAdapter:
        return cls._adapters.get(harness_type)
```

#### Step 3: 新增 Migration

**檔案**: `backend/db/migrations/add_harness_type_to_issues.py`

- [ ] **Step 3.1**: 在 JobModel 或新 table 加入 harness_type 欄位

```python
# ALTER TABLE jobs ADD COLUMN harness VARCHAR(32) DEFAULT 'claude-code'
```

### 預期交付
- BaseAIAdapter 抽象類別定義統一介面
- ClaudeLocalAdapter 實作當前邏輯
- HarnessRegistry 支援動態切換 harness

### 關鍵檔案

| 檔案 | 操作 | 描述 |
|------|------|------|
| `backend/core/adapters/__init__.py` | Create | adapters 目錄起點 |
| `backend/core/adapters/base.py` | Create | BaseAIAdapter 抽象類別 |
| `backend/core/adapters/claude_local.py` | Create | Claude 本地執行適配器 |
| `backend/core/adapters/registry.py` | Create | HarnessRegistry |
| `backend/db/migrations/add_harness_type.py` | Create | DB migration |

---

## 第三階段：狀態序列化與恢復機制

### 目標
處理長運行任務的網路中斷或 Token 耗盡問題。

### 實作步驟

#### Step 1: 定義 AgentSessions Table

**檔案**: `backend/db/models.py`

- [ ] **Step 1.1**: 新增 AgentSession model

```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String(64), primary_key=True)
    job_id = Column(String(64), nullable=False, index=True)
    harness = Column(String(32), nullable=False)
    session_id = Column(String(128), nullable=True)  # AI runtime session
    state = Column(JSON, nullable=False)  # serialized state
    checkpoint_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    resumed_at = Column(DateTime(timezone=True), nullable=True)
```

#### Step 2: 實現 SessionCodec

**檔案**: `backend/core/session_codec.py`

- [ ] **Step 2.1**: 定義序列化/反序列化邏輯

```python
class SessionCodec:
    @staticmethod
    def serialize(state: Dict) -> str:
        """將執行狀態序列化为 JSON 字串"""
        return json.dumps(state)

    @staticmethod
    def deserialize(raw: str) -> Dict:
        """從 JSON 字串恢復執行狀態"""
        return json.loads(raw)

    @staticmethod
    def get_display_id(params: Dict) -> str:
        """返回 session 的可讀標識"""
        return params.get('session_id', 'unknown')[:8]
```

#### Step 3: 實現 CheckpointManager

**檔案**: `backend/core/checkpoint_manager.py`

- [ ] **Step 3.1**: 定期寫入 checkpoint

```python
class CheckpointManager:
    async def write_checkpoint(self, job_id: str, state: Dict):
        """每隔 30-60 秒寫入 checkpoint"""
        # 寫入臨時檔案再 atomic rename
        pass

    async def load_checkpoint(self, job_id: str) -> Optional[Dict]:
        """載入最新的 checkpoint"""
        pass
```

#### Step 4: 在 Adapter 中集成 Resume

```python
# 在 ClaudeLocalAdapter.execute() 中
async def execute(self, task_id, prompt, workspace, on_log=None):
    # 檢查是否有可恢復的 session
    session = await self.load_session(task_id)
    if session:
        # 使用 --resume flag
        return await self._execute_with_resume(session, prompt, ...)
```

### 預期交付
- AgentSessions 表存储 session 狀態
- SessionCodec 實現狀態序列化
- CheckpointManager 實現斷點續傳

### 關鍵檔案

| 檔案 | 操作 | 描述 |
|------|------|------|
| `backend/db/models.py` | Modify | 新增 AgentSession model |
| `backend/core/session_codec.py` | Create | 序列化/反序列化邏輯 |
| `backend/core/checkpoint_manager.py` | Create | checkpoint 管理 |
| `backend/core/adapters/claude_local.py` | Modify | 集成 resume 邏輯 |

---

## 風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| Phase 1: Callback 阻塞 | 高 | 使用 `asyncio.create_task` 非阻塞發送 |
| Phase 1: Log 量過大沖垮 WebSocket | 中 | Rate-limit 或批次發送 |
| Phase 2: Interface 膨脹 | 中 | 保持 BaseAIAdapter 最小化 |
| Phase 3: Subprocess 狀態檢測脆弱 | 高 | 使用結構化 JSON checkpoint |

---

## 測試策略

### Phase 1 (整合測試)
```python
def test_ecc_dispatch_triggers_websocket():
    # 1. dispatch job
    # 2. verify WebSocket receives job_update
    # 3. verify log entries appear in ecc-logs tab
```

### Phase 2 (單元測試)
```python
def test_adapter_interface_compliance():
    # 驗證 ClaudeLocalAdapter 實現所有抽象方法
    # 驗證 harness_type 正確存入資料庫
```

### Phase 3 (E2E)
```python
def test_session_resume_after_interrupt():
    # 1. 啟動長期任務
    # 2. 中斷 (模擬進程 kill)
    # 3. 恢復 session
    # 4. 驗證結果與未中斷相同
```

---

## SESSION_ID (用於 /ccg:execute resume)

- CODEX_SESSION: af843ebffade8d3cd (後端分析)
- GEMINI_SESSION: aca5b7a4296abb1bb (前端分析)

---

**Plan generated and saved to `.claude/plan/paperclip-inspired-ai-client.md`**

**請回顧上述計劃。你可以：**
- **修改計劃**：告訴我需要調整的部分，我會更新計劃
- **執行計劃**：複製以下命令到新 session

```
/ccg:execute .claude/plan/paperclip-inspired-ai-client.md
```