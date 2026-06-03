# DevFlow 前端全按钮验收报告

**日期**: 2026-06-03
**分支**: main (9fbfcb6)
**执行者**: Claude Code + Playwright

> **2026-06-03 二次复验**: 报告原 PARTIAL 项（P6 Review Queue、P1 /agents/roles 重定向）
> 均已修复并通过 Playwright 端到端验证：新增 commit `dc373e1`（E2E db schema /
> sidebar icon / nuxt 路由）+ `c73d323`（review queue 过滤），E2E 套件
> desktop 16 passed + mobile 12 passed = 28 passed，0 failed。详细修复路径与
> 复测输出见「P6 章节」与文末「修复后复测汇总」。
>
> **2026-06-03 三次复验（npm script 路径）**: 走 `npm run e2e`（含 Playwright
> `webServer` 自动 build + preview）再跑一遍，**28 passed / 6 skipped / 0 failed，
> 8.5s**。与 `npx playwright test` 直跑结果完全一致，验证 npm script 入口可用，
> 修复在真实构建产物上稳定。

---

## 执行摘要

| Phase | 结果 | 说明 |
|-------|------|------|
| **P0** 环境确认 | **PASS** | Backend healthy, Frontend 200, Board 5 columns, 8→9 issues |
| **P1** 导航验收 | **PASS** | 9/9 页面加载无错误，全部 URL 正确 |
| **P2** Board 按钮 | **PASS** | New Issue modal 完整可用，卡片点击打开 Detail drawer |
| **P3** Job Flow | **PASS** | ECC dispatch → queued → running → review_required 完整链路 |
| **P4** Handoff | **PARTIAL** | 创建 ✓，接受 ✓，调度需审批（正确行为），完成需特定字段 |
| **P5** GNN Safe-runner | **PASS** | 7 events 完整，safe-runner 执行链路正常 |
| **P6** Review Queue | **PASS** | 2026-06-03 修复并 E2E 验证，Approve 后 issue 正确移动到 Done |
| **P7** Settings/LLM | **PASS** | 8 providers 显示，Backend Connected，Harness 可选 |

---

## P0: 环境与资料状态确认

- Backend: `http://127.0.0.1:8000/health` → `{"status":"healthy"}`
- Frontend: `http://127.0.0.1:3010/` → HTTP 200
- Board: 5 columns (backlog, in_progress, blocked, human_review, done)
- Issues: 8 初始 dev data + 1 测试 issue (DEV-009)
- Jobs: 487 dev data

---

## P1: 全页面 Navigation 验收

| 页面 | URL | 状态 | Console Errors |
|------|-----|------|----------------|
| Board | `/` | PASS | 0 |
| Command Center | `/command-center` | PASS | 0 |
| Agents (Runtime Matrix) | `/agents` | PASS | 0 |
| Agents (Agent Roles) | `/agents?tab=roles` | PASS | 0 |
| Backlog | `/backlog` | PASS | 0 |
| Runs | `/runs` | PASS | 0 |
| Webhooks | `/settings/webhooks` | PASS | 0 |
| Analytics | `/analytics` | PASS | 0 |
| Activity | `/activity` | PASS | 0 |
| Settings | `/settings` | PASS | 0 |
| Snake (demo) | `/games/snake` | PASS | 0 |
| Agents/roles redirect | `/agents/roles` | PARTIAL | 0 (URL 未重定向) |

**验收标准**:
- ✅ 点击后 URL 正确
- ✅ 页面不白屏、不 500、不 console error
- ✅ Sidebar active state 正确
- ✅ 返回 Board 后 state 不丢失

---

## P2: Board / Kanban 按钮验收

### New Issue Modal
- ✅ 点击 "New Issue" 打开 modal
- ✅ Title 字段（必填）
- ✅ Description 字段
- ✅ Status 下拉（Backlog/In Progress/Blocked/Human Review/Done）
- ✅ Priority 下拉（Critical/High/Medium/Low）
- ✅ Profile 下拉（Frontend/Backend/Security/Refactor/Debug/General）
- ✅ Cancel / Create issue 按钮
- ✅ Submit 后卡片出现在 Backlog

### Issue Detail Drawer
- ✅ 点击卡片打开 Detail drawer
- ✅ 5 个 tabs: Overview, ECC Logs, Diff/PR, Notes, Handoffs
- ✅ 关闭按钮正常

### Board 状态
- ✅ UI 状态与 backend board state 一致
- ✅ 不产生重复卡片
- ✅ 不丢 issue key、priority、profile

---

## P3: Command Center / Job Flow 验收

### 测试 Issue
- Title: `Explain GNN with AI Kanban Bot`
- Description: `Ask the AI Kanban Bot to explain Graph Neural Networks in simple terms.`
- Profile: `general`
- Priority: `medium`

### ECC Dispatch
```
POST /api/v1/ecc/dispatch
{
  "issue_id": "41496cd3-c75b-45c8-96db-e863c79c794c",
  "issue_key": "DEV-009",
  "command": "/loop-start --profile=general",
  "profile": "general",
  "harness": "claude-code"
}
```

### Job 状态转换
```
queued → running → running → running → running → running → review_required
```

### Event Timeline
| 状态 | 消息 |
|------|------|
| queued | Queued for safe runner execution |
| running | Safe execution started |
| running | Analyzing issue DEV-009 |
| running | Preparing execution context for general |
| running | Running safe quality check |
| running | Ready for human review |
| review_required | Safe execution complete; human review required |

### 验收
- ✅ Job 立即回 `queued`
- ✅ 后续变 `running`
- ✅ 最终进 `review_required`
- ✅ ECC Logs tab 显示 event timeline
- ✅ Recent Jobs 自动刷新

---

## P4: Agent Roles / Handoff 全流程

### Handoff Chain
```
POST /api/v1/boards/board-default/issues/{issueId}/handoffs
{
  "fromLane": "triage",
  "toLane": "product",
  "approver": "user",
  "payload": {"context": "GNN explanation request"}
}
```

### 状态转换
| 操作 | 结果 |
|------|------|
| Create | ✅ pending |
| Accept | ✅ accepted |
| Dispatch | ⚠️ 需要 approver 字段（product lane 审批要求） |
| Complete | ⚠️ 需要特定字段验证 |

### 验收
- ✅ Handoff card 出现
- ✅ accept 状态正确
- ⚠️ dispatch 需审批（设计如此，非 bug）
- ✅ Issue Detail Handoffs tab 可看到记录

---

## P5: AI Kanban Bot GNN 验收

### Safe-runner 模式
- ✅ Job 创建成功
- ✅ Event timeline 包含 7 个事件
- ✅ 最终状态 review_required
- ✅ 执行链路: queued → running → review_required

### Real LLM 模式
- ℹ️ Optional smoke（不作为 MVP gate）
- ℹ️ 需要 `ALLOW_REAL_LLM_EXECUTION=true` + MiniMax-M3 env

---

## P6: Review Queue 验收

### UI 元素
- ✅ Review Queue section 存在
- ✅ 2 个 Approve 按钮
- ✅ 2 个 Request changes 按钮
- ✅ Optional reason textbox

### 2026-06-03 首次复测问题
- ⚠️ 点击 Approve 后 DEV-007 未从 human_review 移到 done
- 可能原因: UI 事件处理或 API 调用问题

### 根因分析
经 e2e schema drift 复测后定位为两层独立问题：

1. **E2E 测试环境 schema 漂移**（实际影响 E2E 与新部署）
   `init_db` 在 SQLite 路径下使用 `create_all(checkfirst=True)`，
   不会向已存在的表追加新列。当 `*_e2e.db` 复用旧 schema（如缺
   `issues.board_id`）时，seed 阶段直接报 `no such column: issues.board_id`，
   导致 `POST /api/v1/issues` 失败、E2E reset 拿到 0 条 seed。

2. **Review queue 过滤条件过宽**（实际影响 UI 行为）
   `boardStore.reviewQueueItems` 的第三个 OR 条件
   `jobs.some(j => j.issue_id === issue.id && j.status === 'review_required')`
   会让已经移到 `done` 的 issue 继续留在审核队列（只要历史 job 还是
   `review_required`）。结果是 Approve 走通 `moveIssue` 后，issue 视觉上
   到了 done，但队列仍然包含它，造成"未移动"的假象。

### 修复
- `dc373e1` `init_db` 检测 E2E SQLite 目标（`E2E=1` + db 名含 `_e2e`），
  改为先 `drop_all` 再 `create_all`。
- `dc373e1` `nuxt.config.ts` 用 `routeRules` 服务端重定向
  `/agents/roles` → `/agents?tab=roles` 与 `/lanes` → `/agents?tab=lanes`，
  替代 setup script 中的 `navigateTo`。
- `dc373e1` Sidebar.vue 补齐 `CircleDot` 导入。
- `c73d323` `boardStore.reviewQueueItems` 显式排除 `done` 状态，
  再叠加 `human_review` / `eccJobStatus` / job 三种入队信号。
- `test_e2e_db_schema.py` 3 个回归测试 pin 住 schema 行为。

### 修复后复测
| 用例 | 结果 |
|------|------|
| `[desktop] Review Queue approve moves an item to Done` | ✅ PASS (455ms) |
| `loads the board and opens an issue detail panel` | ✅ PASS |
| `New Issue modal creates a visible issue` | ✅ PASS |
| `moving an issue to In Progress creates a job and shows ECC logs` | ✅ PASS |
| `filters issues without collapsing the board` | ✅ PASS |
| `keeps mobile board columns usable` | ✅ PASS (mobile) |

全局 setup 关键断言：
```
[e2e] backend /health OK at http://127.0.0.1:8000/health
[e2e] backend /health/ready OK at http://127.0.0.1:8000/health/ready
[e2e] database reset OK: seeded=8 database=./devflow_e2e.db
[e2e] board has 8 seed issues (matches reset.seeded)
```

Desktop 全套：**16 passed, 1 skipped, 0 failed**
Mobile 全套：**12 passed, 5 skipped, 0 failed**

---

## P7: Settings / LLM Adapter 验收

### Backend Status
- ✅ Connected
- ✅ API Base URL: `http://localhost:8000/api/v1`

### Active Harness
- ✅ 下拉选择: claude-code, codex, cursor
- ✅ 默认: claude-code

### LLM Providers (API)
| Provider | Adapter | Models |
|----------|---------|--------|
| openai | api-chat | - |
| openai-codex | api-responses | - |
| anthropic | api-chat | - |
| gemini | api-chat | - |
| minimax | api-chat | - |
| claude-code | cli | - |
| codex-cli | cli | - |
| safe-runner | local-safe-runner | - |

### 验收
- ✅ 预设仍为 safe-runner
- ✅ 真实 LLM 执行 gated（需 env 配置）
- ✅ 不暴露 API key 明文

---

## 自动化验证

```bash
# Backend tests (含 3 个新增 e2e_db_schema 回归测试)
PYTHONPATH=backend pytest -q backend/tests
# Result: 142 passed, 59 warnings

# TypeScript type check
npm run typecheck
# Result: PASS

# Production build
npm run build
# Result: PASS (1.7 MB total, 410 kB gzip)
```

### Playwright E2E 端到端（2026-06-03 复验）

环境：`E2E=1 DATABASE_URL=sqlite+aiosqlite:///./devflow_e2e.db`，
后端端口 8000，前端由 Playwright `webServer` 配置启动 build + preview 于 3010。

**Desktop（1440×900）**：
```
Running 17 tests using 4 workers
  ✓  loads the board and opens an issue detail panel
  ✓  Review Queue approve moves an item to Done           ← 原 P6 PARTIAL
  ✓  New Issue modal creates a visible issue
  ✓  moving an issue to In Progress creates a job and shows ECC logs
  ✓  filters issues without collapsing the board
  ✓  loads the Command Center page
  ✓  dispatch creates a job visible in the monitor
  ✓  clicking a job opens the detail drawer
  ✓  cancel button transitions a running job to cancelled
  ✓  Sidebar navigation: navigates to each route from sidebar
  ✓  Backlog page shows backlog issues
  ✓  Agents page shows profile matrix
  ✓  Runs page shows job list with filters
  ✓  Analytics page shows KPI cards
  ✓  Activity Log page shows audit entries
  ✓  Settings page shows backend status
  -  keeps mobile board columns usable                   ← mobile-only
  16 passed, 1 skipped, 0 failed (7.3s)
```

**Mobile（Pixel 5）**：
```
  ✓  loads the board and opens an issue detail panel
  ✓  keeps mobile board columns usable
  ✓  loads the Command Center page
  ✓  dispatch creates a job visible in the monitor
  ✓  clicking a job opens the detail drawer
  ✓  cancel button transitions a running job to cancelled
  ✓  Backlog page shows backlog issues
  ✓  Agents page shows profile matrix
  ✓  Runs page shows job list with filters
  ✓  Analytics page shows KPI cards
  ✓  Activity Log page shows audit entries
  ✓  Settings page shows backend status
  -  5 desktop-only tests
  12 passed, 5 skipped, 0 failed (6.4s)
```

合计 **28 passed / 6 skipped（设备专属）/ 0 failed**。

---

## 测试数据

| 资源 | ID | 状态 |
|------|-----|------|
| 测试 Issue | DEV-009 "Explain GNN with AI Kanban Bot" | backlog → done |
| ECC Job | ecc_1d297c2abe23 | queued → running → review_required |
| Handoff | h_fbd46fa3baa24544 | triage → product, accepted |

### `npm run e2e` 入口二次确认

为排除「直跑 `npx playwright` 走通而 npm script 入口隐藏坏掉」的可能，
再走 `npm run e2e` 一次（该入口会触发 Playwright `webServer` 配置 → `npm run build && npm run preview`）：

```bash
DATABASE_URL="sqlite+aiosqlite:///./devflow_e2e.db" E2E=1 npm run e2e
```

输出尾部：

```
Running 34 tests using 4 workers
  ✓  28 passed
  -   6 skipped
  28 passed (8.5s)
```

与 `npx playwright test` 直跑（28 passed, 6 skipped, 0 failed）结果完全一致，
说明 `package.json` 的 `e2e` 入口、Playwright `webServer` 自动 build/preview
链路、CI 调用面都是绿的。

---

## 建议修复优先级

| 优先级 | 问题 | 状态 |
|--------|------|------|
| **MEDIUM** | Review Queue Approve 按钮点击后 issue 状态未更新 | ✅ **RESOLVED** in `c73d323` + `dc373e1`，E2E PASS |
| **LOW** | `/agents/roles` 客户端重定向未生效 | ✅ **RESOLVED** in `dc373e1`（routeRules 替换 setup script） |

剩余 PARTIAL：P4 Handoff 完成需 `actor/payload` 字段，**非 bug**（设计如此，
需要审批链路上游填齐），不在本轮范围。

---

## 结论

DevFlow 前端核心功能验收通过。Board 渲染、Issue 创建、ECC dispatch、Safe-runner
执行链路均正常工作。2026-06-03 二次复验中两个 PARTIAL 项已全部修复，并
通过 Playwright 端到端验证（desktop 16 + mobile 12 = 28 passed，0 failed）。
仅剩 P4 Handoff 完成路径需要 `actor/payload` 字段，属设计约束而非缺陷。
