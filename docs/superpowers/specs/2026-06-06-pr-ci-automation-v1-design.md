# PR/CI Automation v1 — GitHub Webhook Ingestion

> **Status:** Design (ready for implementation)
> **Date:** 2026-06-06
> **Scope:** Webhook ingestion only — receive GitHub events, update issue state. No outbound GitHub API calls.

## Goal

接收真实的 GitHub webhook payloads，解析后更新 Kanban issue 的状态。打通外部事实回流路径：

```text
GitHub PR / CI event
→ DevFlow webhook
→ 找到 issue (通过 branch name / PR title / body / labels 中的 issue key)
→ 更新 pr_url / ci_status / status
→ 前端实时可见
```

## Design Principles

1. **Inbound only** — 接收 GitHub 事件，不主动操作 GitHub（PR 创建、merge、commit status 等留给 v2）。
2. **真实 payload** — 接受 GitHub 原生 webhook JSON，不使用自定义格式。
3. **Issue resolution by key** — 从 branch name、PR title、PR body、labels 中提取 issue key（如 `DEV-123`）。
4. **Graceful degradation** — 找不到对应 issue 时记录日志并返回 200，不报错。GitHub 不希望 webhook 因为接收方错误而重试。

## 现有基础设施

| 组件 | 状态 | 说明 |
|------|------|------|
| 自定义 webhook 端点 (`/webhooks/ci`, `/webhooks/pr`) | ✅ 存在 | 使用自定义 payload 格式，保留不动 |
| `Issue.pr_url` + `Issue.ci_status` | ✅ 存在 | 数据模型已就绪 |
| `update_issue_pr_url()` / `update_issue_ci_status()` | ✅ 存在 | Repository 函数已就绪 |
| `WebhookEvent` 模型 + HMAC 验证 | ✅ 存在 | 审计存储已就绪 |
| GitHub 原生 webhook 端点 | ❌ 缺失 | 本设计要建的 |
| Issue key 解析函数 | ❌ 缺失 | 从文本中提取 DEV-NNN |
| `find_issue_by_key()` repo 函数 | ❌ 缺失 | 按 key 查 issue |
| 前端 PR link / CI badge | ✅ 存在 | IssueCard 已渲染 ciStatus 和 prUrl |

## Schema Design

### 无新表

所有需要的字段已存在于 Issue 模型：
- `pr_url` (String 512, nullable)
- `ci_status` (String 32, nullable, indexed): `pending` | `passed` | `failed`
- `status` (String 32): `backlog` | `in_progress` | `blocked` | `human_review` | `done`

### 新增 Repository 函数

```python
async def find_issue_by_key(key: str) -> Optional[dict]:
    """按 issue key 精确查找 issue。返回 dict 或 None。"""
```

## GitHub Webhook Payload 格式

### Headers

| Header | 用途 |
|--------|------|
| `X-GitHub-Event` | 事件类型：`pull_request`, `workflow_run` |
| `X-Hub-Signature-256` | HMAC-SHA256 签名：`sha256=<hex>` |
| `X-GitHub-Delivery` | 事件 UUID（用于幂等性） |

### `pull_request` payload 关键字段

```json
{
  "action": "opened" | "closed" | "reopened" | "synchronize",
  "pull_request": {
    "number": 42,
    "title": "feat: add login DEV-123",
    "body": "Closes DEV-123",
    "html_url": "https://github.com/org/repo/pull/42",
    "head": { "ref": "feat/DEV-123-login" },
    "merged": true,
    "labels": [{"name": "DEV-123"}]
  }
}
```

### `workflow_run` payload 关键字段

```json
{
  "action": "completed",
  "workflow_run": {
    "conclusion": "success" | "failure" | "cancelled" | "timed_out",
    "head_branch": "feat/DEV-123-login",
    "pull_requests": [{"number": 42}]
  }
}
```

## Issue Key 解析

从多个来源按优先级提取 issue key：

1. **Branch name** — 匹配 `DEV-\d+` 模式（如 `feat/DEV-123-login` → `DEV-123`）
2. **PR title** — 匹配 `DEV-\d+` 模式
3. **PR body** — 匹配 `DEV-\d+` 模式（支持 `Closes DEV-123`, `Fixes DEV-123`, `#DEV-123`）
4. **Labels** — 匹配 `DEV-\d+` 格式的 label

```python
import re

_ISSUE_KEY_PATTERN = re.compile(r"(?:DEV-)(\d+)", re.IGNORECASE)

def extract_issue_key(text: str) -> Optional[str]:
    """从文本中提取 issue key (如 DEV-123)。返回标准化大写格式或 None。"""
    match = _ISSUE_KEY_PATTERN.search(text)
    if match:
        return f"DEV-{match.group(1)}"
    return None
```

## Event Routing

### GitHub `pull_request` events

| action | 处理 |
|--------|------|
| `opened` | 提取 issue key → 更新 `pr_url`，设置 `ci_status=pending` |
| `synchronize` | 提取 issue key → 无操作（CI 正在重跑） |
| `reopened` | 提取 issue key → 设置 `ci_status=pending` |
| `closed` + `merged=true` | 提取 issue key → issue status 移到 `done` |
| `closed` + `merged=false` | 无操作（PR 被关闭但未 merge） |

### GitHub `workflow_run` events

| conclusion | 处理 |
|-----------|------|
| `success` | 通过 head_branch → issue key → `ci_status=passed` |
| `failure` | → `ci_status=failed` |
| `cancelled` | → `ci_status=failed` |
| `timed_out` | → `ci_status=failed` |
| 其他 | 无操作 |

### Issue key lookup 流程

```
GitHub event
  → extract_issue_key(branch_name)
  → if None: extract_issue_key(PR title)
  → if None: extract_issue_key(PR body)
  → if None: extract_issue_key(labels)
  → if still None: log warning, return 200 (graceful skip)
  → find_issue_by_key(key)
  → if None: log warning, return 200
  → apply update to issue
```

## API Endpoint

```python
@router.post("/webhooks/github")
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None),
):
```

- **Input:** Raw request body (JSON), GitHub headers
- **Signature:** HMAC-SHA256 via `X-Hub-Signature-256`（格式 `sha256=<hex>`，与现有 `X-Webhook-Signature` 相同格式但不同 header name）
- **Events handled:** `pull_request`, `workflow_run`
- **Unknown events:** 返回 200, 记录 debug 日志
- **Invalid signature:** 返回 401
- **Issue not found:** 返回 200（graceful skip）
- **Idempotency:** 使用 `X-GitHub-Delivery` 记录到 WebhookEvent，但不做去重（简单实现）

### Signature 验证

```python
def verify_github_signature(payload: bytes, signature: str) -> bool:
    """验证 GitHub webhook HMAC-SHA256 签名。

    GitHub 格式: sha256=<hex-digest>
    与现有 verify_webhook_signature 逻辑一致，但接收 X-Hub-Signature-256 header。
    """
    if not WEBHOOK_SECRET:
        return True  # dev mode
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

注意：现有的 `verify_webhook_signature()` 函数也可以复用，因为格式相同（`sha256=<hex>`）。直接调用即可，不需要新函数。

## Background Processing

所有 issue 更新在 BackgroundTasks 中执行，不阻塞 webhook 响应：

```python
# Pull request event
background_tasks.add_task(
    _handle_github_pr_event,
    payload,
)

# Workflow run event
background_tasks.add_task(
    _handle_github_workflow_run_event,
    payload,
)
```

### `_handle_github_pr_event(payload)`

```python
async def _handle_github_pr_event(payload: dict) -> None:
    action = payload.get("action")
    pr = payload.get("pull_request", {})

    # 提取 issue key
    issue_key = (
        extract_issue_key(pr.get("head", {}).get("ref", ""))
        or extract_issue_key(pr.get("title", ""))
        or extract_issue_key(pr.get("body", ""))
        or extract_issue_key(
            " ".join(l.get("name", "") for l in pr.get("labels", []))
        )
    )
    if not issue_key:
        logger.debug("GitHub PR event: no issue key found in PR #%s", pr.get("number"))
        return

    issue = await repo.find_issue_by_key(issue_key)
    if not issue:
        logger.debug("GitHub PR event: issue %s not found", issue_key)
        return

    # opened: set pr_url, ci_status=pending
    if action == "opened":
        await repo.update_issue_pr_url(issue["id"], pr.get("html_url", ""))
        await repo.update_issue_ci_status(issue["id"], "pending")
        logger.info("Issue %s: pr_url set, ci_status=pending (PR opened)", issue_key)

    # closed + merged: move to done
    elif action == "closed" and pr.get("merged"):
        await repo.update_issue_status(issue["id"], "done")
        logger.info("Issue %s: status=done (PR merged)", issue_key)
```

### `_handle_github_workflow_run_event(payload)`

```python
async def _handle_github_workflow_run_event(payload: dict) -> None:
    action = payload.get("action")
    if action != "completed":
        return

    wr = payload.get("workflow_run", {})
    conclusion = wr.get("conclusion")
    head_branch = wr.get("head_branch", "")

    # conclusion → ci_status
    status_map = {
        "success": "passed",
        "failure": "failed",
        "cancelled": "failed",
        "timed_out": "failed",
    }
    ci_status = status_map.get(conclusion)
    if not ci_status:
        return

    issue_key = extract_issue_key(head_branch)
    if not issue_key:
        # Try PR numbers if available
        prs = wr.get("pull_requests", [])
        # We'd need to look up PRs to get their titles/branches
        # For v1, branch name is the primary resolution path
        logger.debug("GitHub workflow_run: no issue key from branch '%s'", head_branch)
        return

    issue = await repo.find_issue_by_key(issue_key)
    if not issue:
        return

    await repo.update_issue_ci_status(issue["id"], ci_status)
    logger.info("Issue %s: ci_status=%s (workflow_run %s)", issue_key, ci_status, conclusion)
```

## File Structure

```
backend/
├── api/v1/endpoints/webhooks.py       # Add receive_github_webhook() + handlers
├── db/repository.py                    # Add find_issue_by_key()
└── tests/test_github_webhooks.py       # New test file
```

### Changes to existing files

| File | Change |
|------|--------|
| `backend/api/v1/endpoints/webhooks.py` | Add `receive_github_webhook` endpoint + `_handle_github_pr_event` + `_handle_github_workflow_run_event` + `extract_issue_key` |
| `backend/db/repository.py` | Add `find_issue_by_key(key)` function |

### New files

| File | Purpose |
|------|---------|
| `backend/tests/test_github_webhooks.py` | Tests for GitHub webhook endpoint, issue key parsing, event handlers |

## Testing Strategy

### Unit Tests

1. **`extract_issue_key`** — branch name、PR title、PR body、labels 各种格式
2. **`find_issue_by_key`** — 精确匹配、不存在返回 None

### Integration Tests

1. **Happy path: PR opened** — 发送真实格式 PR webhook → issue 的 pr_url 和 ci_status 更新
2. **Happy path: PR merged** — 发送 merged=true → issue status 变成 done
3. **Happy path: workflow_run success** — 发送 success conclusion → ci_status=passed
4. **Happy path: workflow_run failure** — 发送 failure → ci_status=failed
5. **Unknown issue key** — PR title 没有 DEV-NNN → 返回 200，不报错
6. **Invalid signature** — 错误签名 → 401
7. **Missing signature (dev mode)** — WEBHOOK_SECRET 为空 → 跳过验证
8. **Unknown event type** — 非 PR/workflow_run → 200，debug 日志
9. **Workflow run non-completed** — action=queued → 无操作
10. **PR closed not merged** — merged=false → 不改变 status

### Regression

```bash
PYTHONPATH=backend pytest -q backend/tests
```

## What This Design Does NOT Do

- 不自动创建 PR（留给 v2）
- 不写 GitHub commit status / check run（留给 v2）
- 不自动 push branch 或 merge（留给 v2）
- 不做 webhook 重试 / 出站 delivery（保留 WebhookEvent 模型，但不做 outbound sender）
- 不修改现有 `/webhooks/ci` 和 `/webhooks/pr` 端点
- 不添加新数据库表或列

## Migration Impact

- **零 migration** — 无新表、无新列、无 schema 变更
- 所有需要的字段已存在
