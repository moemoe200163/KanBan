# UI Roadmap — Design.md Alignment

> 本文件是 DevFlow 前端 UI/UX + Control Plane 模組化的正式開發計劃。
> 以 `Design.md` 為視覺與產品 source of truth，將原計劃表重新排序、修正切分、標記依賴。

---

## 1. Summary

本 roadmap 的目的：

- 將前端 UI 計劃表與 `Design.md` 完整對齊，確保每個階段都有明確的設計依據。
- 修正原計劃中階段切分過細（sidebar 統一獨自成階段）或順序不合理（Orchestrator 偏早）的問題。
- 明確標記 backend/API 依賴、工具鏈依賴、E2E 依賴，讓每個階段的前置條件可被驗證。
- 讓後續實作可以照階段推進，每階段結束時有可執行的驗收標準。

本文件不包含程式碼實作，僅作為開發任務的推進依據。

---

## 2. Design.md Alignment Matrix

| Roadmap 項目 | Design.md 對應章節 | 對齊狀態 | 備註與風險 |
|---|---|---|---|
| Sidebar 統一 | §6 App Shell, §6 Sidebar Requirements | 對齊 | Known Problem #6；需選定 `sidebar/Sidebar.vue` 為主 |
| 視覺調整（spacing / color / typography） | §4 Color Tokens, §5 Typography, §4 Usage Rules | 對齊 | Token 已定義於 `main.css`；需確認 light/dark 兩模式可讀性 |
| Command Center | §10 AI/ECC Workflow Mapping, §3 State Changes Are Commands | 對齊 | API 已存在（`POST /ecc/dispatch`）；新增 UI 模組即可 |
| Subagent Call Matrix | §11 Backend Control Plane（profiles） | 對齊 | Backend profiles 已定義；需避免暗示不存在的 backend 行為 |
| Delivery Orchestrator | §16 Phase 2 (Real Control Plane) | 部分對齊 | UI 想六段流程，但 backend job status 尚未完整支援 |
| 模組互動 | §3 State Changes Are Commands, §9 Issue Detail | 對齊 | 核心 UX 原則：拖卡 = 操作指令 |
| Issue Detail 強化 | §9 Issue Detail Panel (Required Sections) | 對齊 | 需加入 command / logs / activity 區塊 |
| Responsive | §12 Responsive Rules | 對齊 | Desktop / Tablet / Mobile 三段式；硬性規則：不重疊、不 collapse |
| E2E 測試 | §15 Verification Checklist | 對齊 | Playwright 未安裝，為 P7 blocker |

---

## 3. Key Adjustments

### 3.1 合併 Sidebar 統一與視覺對齊

原計劃將 sidebar 統一設為獨立 P0 階段，但該工作範圍過薄，不值得獨自成一個 phase。

調整：

- 合併為「收斂 UI 架構 + 視覺對齊」單一階段。
- 範圍包含：
  - sidebar 統一（選定 `src/components/sidebar/Sidebar.vue`，停用 `AppSidebar.vue`）
  - spacing 調整（對齊 Design.md 的 dense-but-readable 原則）
  - color token 使用（確認 `--canvas`, `--surface-card`, `--primary` 等 token 正確應用）
  - typography 對齊（Outfit / Source Sans 3 / JetBrains Mono 三字体）
  - app shell 一致性（桌面固定 sidebar、窄螢幕不遮 board）

### 3.2 Delivery Orchestrator 延後

Delivery Orchestrator 要表達 Intake → Dispatch → Execute → Quality Gate → Human Review → Release Ready 六段交付流程。但目前 backend job model 只有 `queued` / `running` / `paused` / `failed` / `review_required` / `completed` / `cancelled` 七個 status，不足以支撐六段式流程。

調整：

- 此階段延後至 backend control plane 更成熟後再做。
- 實作前必須先決定策略：
  - **選項 A**：只做 visual-only UI，不改 API。UI 用 frontend status mapping 呈現六段，backend 仍用既有 status。文件與 UI copy 必須明確標記為 visual overlay。
  - **選項 B**：先擴充 backend status / job model，新增 delivery stage 欄位。需通過 API contract check。
  - **選項 C**：將此階段完全延後到 Phase 2（Real Control Plane）之後。
- 不論選哪個，不得破壞既有 `queued → running → review_required` 流程。

### 3.3 Playwright E2E 拆分

Playwright 尚未安裝（`@playwright/test` 不在 `devDependencies`），`npm run e2e` 無法執行。不應在未安裝的前提下要求 E2E 驗收。

調整：

- 拆成兩段：
  - **P7a — Playwright Setup + Smoke Test**：安裝 Playwright、建立最小 smoke test（首頁載入、主要路由可開）、確認可被本機或 CI 執行。
  - **P7b — Feature E2E Scenarios**：補 command dispatch flow、issue detail + logs flow、review queue flow、module interaction flow、responsive smoke。
- P7b 以 P7a 通過為前提。

### 3.4 Nuxt Dev Server 工具鏈問題前置

Nuxt 3.21.6 + Node 25 存在 vite-node IPC socket path 未配置的 bug，導致 `npm run dev` 無法正常啟動 dev server。此問題會阻礙 P1–P6 所有前端功能的開發體驗。

調整：

- 此問題在 UI 功能開發前必須先處理。
- 建議優先方案與 fallback：

| 優先級 | 方案 | 優點 | 缺點 |
|--------|------|------|------|
| 1 | 降 Node 到 v22（`nvm use 22`） | 最快、最穩定 | 需管理多版本 Node |
| 2 | 升 Nuxt 到修復版本 | 根本解決 | 可能引入其他 breaking change |
| 3 | 暫時接受 build → preview 模式 | 零改動 | 犧牲 HMR，開發體驗差 |

- 文件中標記：建議方案為降 Node 到 v22，fallback 為 build → preview。

---

## 4. Revised Roadmap

### P0 — Toolchain Stabilization + UI Foundation

**目標：**

- 修復開發體驗與 UI 基礎一致性。
- 避免後續 P1–P6 被 dev server、sidebar 或 design token 問題卡住。

**範圍：**

- 修復或規避 Nuxt dev server 問題（降 Node / 升 Nuxt / 接受 preview mode）。
- 統一 sidebar：選定 `src/components/sidebar/Sidebar.vue`，確認 `AppSidebar.vue` 不再被引用。
- 對齊 spacing、color tokens、typography。
- 檢查 light/dark mode 基本可讀性。

**依賴：**

- Nuxt dev server 穩定性為本階段核心交付。

**驗收：**

- Nuxt dev / build / preview 至少有一條穩定可用路徑。
- Sidebar 與 app shell 符合 Design.md §6。
- 基礎視覺 token 使用一致（§4 Color Tokens）。
- Typography 使用正確字体（§5 Typography）。
- 不引入新的 layout regression。

---

### P1 — Command Center

**目標：**

- 優先實作最有價值的新 UI 模組。
- 對齊 Design.md §10 AI/ECC Workflow Mapping。

**範圍：**

- Command Center UI：選 issue、profile、harness、ECC command。
- command dispatch 入口：按下後呼叫 `POST /api/v1/ecc/dispatch`。
- command 狀態展示：queued / running / review_required / failed / completed。
- 錯誤、loading、empty state 處理。
- 與既有 API 對接（不新增 backend API）。

**依賴：**

- API 已存在，無 backend 依賴。
- P0 必須完成（sidebar / visual foundation）。

**驗收：**

- 使用者能從 UI 發起 command。
- 成功、失敗、等待狀態清楚可辨。
- API request/response 與 frontend type 假設一致。
- 不破壞既有頁面。

---

### P2 — Issue Detail Enhancement

**目標：**

- 強化 issue detail 的可操作性與可追溯性。

**範圍：**

- 加入 command 區塊（該 issue 的 ECC command 歷史）。
- 加入 logs / activity 區塊（job events 為 source of truth）。
- 對齊 Design.md §9 Required Sections。
- 保持 §3 State Changes Are Commands 原則：detail 內也能觸發操作。

**依賴：**

- P1 必須完成（Command Center 提供 command 歷史資料）。

**驗收：**

- Issue detail 能看出狀態、命令、記錄與下一步。
- UI 不只展示資料，也能表達可執行操作。
- 空狀態與錯誤狀態清楚。

---

### P3 — Subagent Call Matrix

**目標：**

- 新增 subagent / profile 視覺化矩陣。
- 對齊 Design.md §11 Backend Control Plane profiles。

**範圍：**

- Subagent matrix UI：Frontend、Backend、Security、Reviewer、QA、Delivery Orchestrator 六角色。
- profile 狀態展示。
- agent capability / responsibility 顯示。
- 點擊角色可預填命令草稿（與 P1 Command Center 串接）。

**依賴：**

- P1 必須完成（profile 與 command preset 需要 Command Center 基礎）。
- 不得暗示不存在的 backend 行為。

**驗收：**

- 使用者能理解不同 subagent 的角色與職責。
- profile 狀態與能力顯示清楚。
- 點擊角色能預填命令草稿。

---

### P4 — Delivery Orchestrator

**目標：**

- 呈現 delivery pipeline：Intake → Dispatch → Execute → Quality Gate → Human Review → Release Ready。
- **實作前必須先釐清 backend status 策略。**

**範圍：**

- Delivery Orchestrator UI 模組。
- 選中 issue 時能看到目前交付階段、下一個建議命令、最近 job 狀態。

**實作前決策（Blocking）：**

- 是否只做 visual-only UI（frontend status mapping，不改 API）。
- 是否新增 frontend status mapping。
- 是否需要 backend status 擴充（新增 `delivery_stage` 欄位）。
- 是否影響 existing job/session API。

**依賴：**

- P2 必須完成（Issue Detail 需能顯示 orchestrator 狀態）。
- Backend status 策略必須先決定。

**驗收：**

- UI 狀態不與 backend 真實狀態衝突。
- 若 visual-only，文件與 UI copy 必須明確標記。
- 若改 API，需通過 API contract check。
- 不破壞既有 `queued / running / review_required` 流程。

---

### P5 — Module Interaction Wiring

**目標：**

- 將 Command Center、Issue Detail、Subagent Matrix、Delivery Orchestrator 串成一致互動體驗。

**範圍：**

- Cross-module navigation（從 sidebar → matrix → command → detail → logs）。
- 狀態同步（command 執行後更新 issue status、job list、review queue）。
- command → issue → logs → review queue 完整流程。
- 互動 copy 與 loading/error state。

**依賴：**

- P1–P4 必須完成。

**驗收：**

- 使用者能理解不同模組如何相互關聯。
- command 執行後能找到對應 issue / logs / review 狀態。
- 不出現互相矛盾的狀態。

---

### P6 — Responsive Polish

**目標：**

- 對齊 Design.md §12 Responsive Rules。
- 完成桌面、平板、手機基本可用性。

**範圍：**

- Sidebar responsive 行為（桌面固定、平板 icon rail、手機不遮 board）。
- Card/grid layout 在不同寬度下的呈現。
- Issue detail 小螢幕呈現（full-width slide-over）。
- Command Center 小螢幕呈現。
- Matrix / orchestrator 在窄螢幕下的 fallback。

**依賴：**

- P1–P5 必須完成（需有完整功能才能做 responsive 調整）。

**驗收：**

- Desktop 可讀可用。
- Tablet 可讀可用（sidebar icon rail）。
- Mobile 不破版（不重疊、不 collapse）。
- 重要操作不被隱藏或截斷。

---

### P7 — Playwright E2E

#### P7a — Playwright Setup + Smoke Test

**範圍：**

- 安裝 `@playwright/test`。
- 建立最小 smoke test（首頁載入、主要路由可開）。
- 建立可被 CI 或本機執行的 script。

**依賴：**

- Playwright 安裝為本階段 blocker。

**驗收：**

- `npm run e2e` 可正常執行。
- Smoke test 通過。
- 測試失敗時輸出可診斷。

#### P7b — Feature E2E Scenarios

**範圍：**

- Command dispatch flow。
- Issue detail command/logs flow。
- Review queue flow。
- Module interaction flow。
- Responsive smoke。

**依賴：**

- P7a 必須完成。
- P1–P6 必須完成（需有完整功能才能寫 E2E）。

**驗收：**

- 核心使用者流程被 E2E 覆蓋。
- E2E 不依賴脆弱 timing（用 deterministic wait，不用 sleep）。
- 測試資料 setup / teardown 清楚。

---

## 5. Dependency Notes

| 依賴項目 | 類型 | 影響範圍 | 處理方式 |
|----------|------|----------|----------|
| Nuxt dev server 穩定性 | P0 blocker | P0–P6 所有前端開發 | 降 Node v22（優先）/ 升 Nuxt / preview mode（fallback） |
| Playwright 安裝 | P7a blocker | P7a、P7b | `npm i -D @playwright/test && npx playwright install` |
| Backend job status 擴充 | P4 決策項 | Delivery Orchestrator | 實作前決定 visual-only 或 API 擴充 |
| Command Center API | 已就緒 | P1 | `POST /ecc/dispatch`、`GET /ecc/jobs` 已存在 |
| Subagent profiles | 已就緒 | P3 | Backend profiles 已定義（frontend / backend / security / refactor / debug / general） |
| Sidebar 選定 | P0 | P0 | 選定 `sidebar/Sidebar.vue`，確認 `AppSidebar.vue` 不再被引用 |

---

## 6. Verification Plan

每階段結束時必須執行以下驗證：

| 驗證項目 | 適用階段 | 執行指令 |
|----------|----------|----------|
| TypeScript type check | P0–P7 | `npm run typecheck` |
| Production build | P0–P7 | `npm run build` |
| Backend tests | P0–P7 | `PYTHONPATH=backend pytest -q backend/tests` |
| Route smoke check | P0–P6 | 手動：`http://127.0.0.1:3010` 首頁可載入 |
| Backend health | P0–P7 | `curl http://127.0.0.1:8000/health` |
| Browser manual acceptance | P0–P6 | 手動：確認 UI 符合 Design.md 預期 |
| API contract check | P1、P4 | 手動：確認 frontend type 與 backend response 一致 |
| E2E setup check | P7a | `npm run e2e` 可執行且 smoke test 通過 |
| E2E scenario check | P7b | `npm run e2e` 全部通過 |
| Responsive manual check | P6 | 手動：Desktop / Tablet / Mobile 三寬度檢查 |

不宣稱所有 gate 已通過，除非實際執行並確認輸出。

---

## 7. Final Recommendation

1. **採用 revised roadmap（P0–P7）**作為後續 UI 開發的正式依據。
2. **P0 必須先做**：Nuxt dev server 穩定性與 UI foundation 是所有後續階段的前提。
3. **P1 Command Center 是第一個高價值功能**：API 已就緒，實作成本低，使用者可立即受益。
4. **P4 Delivery Orchestrator 必須先釐清 backend status 策略**：不論選 visual-only 或 API 擴充，都必須在實作前決定，避免 UI 與 backend 狀態不一致。
5. **P7 必須先完成 Playwright setup（P7a）**，再補完整 E2E scenarios（P7b）。
6. **原計劃的 sidebar 獨立階段已合併進 P0**，不再單獨存在。
7. **原計劃的 Delivery Orchestrator 從 P4 前置改為 P4 後置**（需先釐清 backend 依賴）。

---

> 本文件取代 `docs/superpowers/plans/2026-06-01-full-product-roadmap.md` 中的 UI 部分。
> 全產品 roadmap（backend runner、WebSocket、CI webhook、auth、Docker）仍以該文件為準。
