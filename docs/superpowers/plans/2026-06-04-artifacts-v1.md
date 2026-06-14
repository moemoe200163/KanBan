# Artifacts v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-create IssueArtifact records from handoff typed payloads, and add a manual "Add Artifact" button/modal in the Collaboration tab.

**Architecture:** Two independent slices. Slice A modifies `complete_handoff` in the backend to create artifacts inline after successful completion. Slice B adds a modal component and a button in `IssueCollaborationTab.vue` for manual artifact creation. Both slices use the existing `repo.create_issue_artifact()` and `collaborationStore.createArtifact()` — no new DB models, API endpoints, or migrations.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Vue 3 + Pinia + TypeScript (frontend), Playwright (e2e), pytest (backend)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `backend/api/v1/endpoints/handoffs.py:148-171` | Add artifact auto-creation after `_svc.complete()` |
| Create | `backend/tests/test_handoff_artifacts.py` | Backend test for auto-created artifacts |
| Create | `src/components/AddArtifactModal.vue` | Manual artifact creation form modal |
| Modify | `src/components/IssueCollaborationTab.vue:149-175` | Add "+ Add Artifact" button and modal wiring |
| Create | `e2e/artifacts.spec.ts` | E2E test for manual artifact creation |

---

## Task 1: Backend — Auto-create artifacts from handoff payload

**Files:**
- Modify: `backend/api/v1/endpoints/handoffs.py:148-171`

- [ ] **Step 1: Add artifact creation logic after successful handoff completion**

In `complete_handoff` (line 148), after the `await _svc.complete(...)` call succeeds and before returning, add artifact creation code. The modified function body should be:

```python
@router.post(
    "/boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/complete"
)
async def complete_handoff(
    board_id: str,
    issue_id: str,
    handoff_id: str,
    body: HandoffCompleteRequest,
):
    await _resolve_handoff(board_id, issue_id, handoff_id)
    try:
        result = await _svc.complete(
            handoff_id=handoff_id,
            actor=body.actor,
            payload=body.payload,
        )

        # Auto-create artifacts from typed payload fields.
        payload = body.payload or {}

        for shot in (payload.get("screenshots") or []):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title=shot,
                artifact_type="screenshot",
                job_id=None,
                source="handoff_complete",
                path_or_url=shot,
                summary=f"Screenshot from handoff {handoff_id}",
            )

        if payload.get("diff_summary"):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title="Diff Summary",
                artifact_type="diff_summary",
                job_id=None,
                source="handoff_complete",
                path_or_url=None,
                summary=payload["diff_summary"],
            )

        if payload.get("test_results"):
            await repo.create_issue_artifact(
                issue_id=issue_id,
                title="Test Results",
                artifact_type="test_log",
                job_id=None,
                source="handoff_complete",
                path_or_url=None,
                summary=payload["test_results"],
            )

        return result
    except PayloadValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Validation failed for lane '{exc.lane}'",
                "lane": exc.lane,
                "errors": exc.errors,
            },
        )
    except (ValueError, ScopeDeniedError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
```

Key points:
- `result = await _svc.complete(...)` — assign to variable so we can still return it after artifact creation.
- `payload = body.payload or {}` — default to empty dict.
- Each `screenshots` entry creates one artifact with `artifact_type="screenshot"`.
- `diff_summary` creates one artifact with `artifact_type="diff_summary"`.
- `test_results` creates one artifact with `artifact_type="test_log"`.
- `job_id=None` because handoff completion may be manual (no job).
- `source="handoff_complete"` to distinguish auto-created from manual artifacts.

- [ ] **Step 2: Run existing backend tests to verify no regression**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: All existing tests pass (no imports or interface changed).

- [ ] **Step 3: Commit**

```bash
git add backend/api/v1/endpoints/handoffs.py
git commit -m "feat(backend): auto-create artifacts from handoff payload on completion"
```

---

## Task 2: Backend test — Verify artifact auto-creation

**Files:**
- Create: `backend/tests/test_handoff_artifacts.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_handoff_artifacts.py` with the following content. This file follows the exact same `fresh_db` fixture pattern from `test_handoffs_api.py`:

```python
"""Tests that completing a handoff with a typed payload auto-creates IssueArtifact records."""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, Issue as IssueModel

client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB seeded with a parent issue — mirrors test_handoffs_api.py."""
    db_path = tmp_path / "test_handoff_artifacts.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            session.add(IssueModel(
                id="issue-art-1",
                key="DEV-200",
                title="artifact test issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


def _create_accept_complete(request: TestClient, payload: dict) -> dict:
    """Helper: create handoff → accept → complete with the given payload. Returns complete response."""
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-art-1/handoffs",
        json={"toLane": "frontend", "payload": payload, "createdBy": "test"},
    )
    assert create_resp.status_code == 201, f"create: {create_resp.text}"
    handoff = create_resp.json()

    accept_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-art-1/handoffs/{handoff['id']}/accept",
        json={"actor": "test"},
    )
    assert accept_resp.status_code == 200, f"accept: {accept_resp.text}"

    complete_resp = client.post(
        f"/api/v1/boards/board-default/issues/issue-art-1/handoffs/{handoff['id']}/complete",
        json={"actor": "test", "payload": payload},
    )
    assert complete_resp.status_code == 200, f"complete: {complete_resp.text}"
    return complete_resp.json()


def test_complete_handoff_creates_screenshot_artifacts(fresh_db):
    """Completing with screenshots creates one artifact per screenshot."""
    payload = {
        "diff_summary": "Changed login flow",
        "screenshots": ["login.png", "dashboard.png"],
    }
    _create_accept_complete(client, payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 3  # 2 screenshots + 1 diff_summary

    screenshots = [a for a in artifacts if a["artifactType"] == "screenshot"]
    assert len(screenshots) == 2
    titles = {a["title"] for a in screenshots}
    assert titles == {"login.png", "dashboard.png"}
    for s in screenshots:
        assert s["source"] == "handoff_complete"
        assert s["pathOrUrl"] == s["title"]


def test_complete_handoff_creates_diff_summary_artifact(fresh_db):
    """Completing with diff_summary creates one diff_summary artifact."""
    payload = {"diff_summary": "Refactored auth module"}
    _create_accept_complete(client, payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["artifactType"] == "diff_summary"
    assert art["title"] == "Diff Summary"
    assert art["summary"] == "Refactored auth module"
    assert art["source"] == "handoff_complete"


def test_complete_handoff_creates_test_log_artifact(fresh_db):
    """Completing with test_results creates one test_log artifact."""
    payload = {"test_results": "42 passed, 0 failed"}
    _create_accept_complete(client, payload)

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["artifactType"] == "test_log"
    assert art["title"] == "Test Results"
    assert art["summary"] == "42 passed, 0 failed"
    assert art["source"] == "handoff_complete"


def test_complete_handoff_empty_payload_no_artifacts(fresh_db):
    """Completing with no payload fields creates zero artifacts."""
    _create_accept_complete(client, {})

    resp = client.get("/api/v1/issues/issue-art-1/artifacts")
    assert resp.json()["total"] == 0
```

- [ ] **Step 2: Run the new tests**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_handoff_artifacts.py -v`
Expected: 4 tests pass (screenshot, diff_summary, test_log, empty payload).

- [ ] **Step 3: Run full backend suite**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_handoff_artifacts.py
git commit -m "test(backend): verify auto-created artifacts from handoff completion payload"
```

---

## Task 3: Frontend — Create AddArtifactModal component

**Files:**
- Create: `src/components/AddArtifactModal.vue`

- [ ] **Step 1: Create the modal component**

Create `src/components/AddArtifactModal.vue`. The modal follows the same `Teleport to="body"` pattern as `NewIssueModal.vue`:

```vue
<script setup lang="ts">
import { useCollaborationStore } from '~/stores/collaboration'
import type { IssueArtifact } from '~/types'
import { X } from 'lucide-vue-next'

const props = defineProps<{
  issueId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const collaborationStore = useCollaborationStore()

const title = ref('')
const artifactType = ref<IssueArtifact['artifactType']>('file')
const pathOrUrl = ref('')
const summary = ref('')
const localError = ref('')
const isSubmitting = ref(false)

const ARTIFACT_TYPES: { value: IssueArtifact['artifactType']; label: string }[] = [
  { value: 'file', label: 'File' },
  { value: 'screenshot', label: 'Screenshot' },
  { value: 'test_log', label: 'Test Log' },
  { value: 'pr_link', label: 'PR Link' },
  { value: 'design_doc', label: 'Design Doc' },
  { value: 'diff_summary', label: 'Diff Summary' },
  { value: 'command_output', label: 'Command Output' },
]

const resetForm = () => {
  title.value = ''
  artifactType.value = 'file'
  pathOrUrl.value = ''
  summary.value = ''
  localError.value = ''
}

const close = () => {
  resetForm()
  emit('close')
}

const submit = async () => {
  if (!title.value.trim()) {
    localError.value = 'Title is required'
    return
  }

  isSubmitting.value = true
  localError.value = ''
  try {
    await collaborationStore.createArtifact(props.issueId, {
      title: title.value.trim(),
      artifactType: artifactType.value,
      pathOrUrl: pathOrUrl.value.trim() || undefined,
      summary: summary.value.trim() || undefined,
    })
    close()
  } catch (err) {
    localError.value = err instanceof Error ? err.message : 'Failed to create artifact'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="add-artifact" data-testid="add-artifact-modal">
      <div class="add-artifact__backdrop" @click="close" />
      <form class="add-artifact__panel" @submit.prevent="submit">
        <header class="add-artifact__header">
          <div>
            <h2>Add Artifact</h2>
            <p>Link a file, screenshot, PR, or other reference.</p>
          </div>
          <button type="button" class="add-artifact__icon-btn" aria-label="Close modal" @click="close">
            <X :size="18" />
          </button>
        </header>

        <label class="add-artifact__field">
          <span>Title</span>
          <input v-model="title" data-testid="artifact-title" type="text" maxlength="200" autofocus />
        </label>

        <label class="add-artifact__field">
          <span>Type</span>
          <select v-model="artifactType" data-testid="artifact-type">
            <option v-for="t in ARTIFACT_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </label>

        <label class="add-artifact__field">
          <span>Path or URL <small>(optional)</small></span>
          <input v-model="pathOrUrl" data-testid="artifact-path" type="text" maxlength="500" />
        </label>

        <label class="add-artifact__field">
          <span>Summary <small>(optional)</small></span>
          <textarea v-model="summary" data-testid="artifact-summary" rows="3" maxlength="5000" />
        </label>

        <p v-if="localError" class="add-artifact__error" data-testid="artifact-error">
          {{ localError }}
        </p>

        <footer class="add-artifact__actions">
          <button type="button" class="add-artifact__secondary" @click="close">Cancel</button>
          <button type="submit" class="add-artifact__primary" data-testid="artifact-submit" :disabled="isSubmitting">
            {{ isSubmitting ? 'Creating...' : 'Create' }}
          </button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.add-artifact {
  position: fixed;
  inset: 0;
  z-index: 140;
  display: grid;
  place-items: center;
  padding: 20px;
}

.add-artifact__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 20, 19, 0.42);
  backdrop-filter: blur(3px);
}

.add-artifact__panel {
  position: relative;
  width: min(480px, 100%);
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
  padding: 18px;
  background: var(--canvas);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  box-shadow: var(--shadow-xl);
}

.add-artifact__header,
.add-artifact__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.add-artifact__header {
  margin-bottom: 16px;
}

.add-artifact__header h2 {
  color: var(--ink);
  font-size: 1.1rem;
  font-weight: 700;
}

.add-artifact__header p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 0.84rem;
}

.add-artifact__icon-btn {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  cursor: pointer;
}

.add-artifact__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.add-artifact__field span {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.add-artifact__field small {
  font-weight: 400;
  text-transform: none;
}

.add-artifact__field input,
.add-artifact__field textarea,
.add-artifact__field select {
  width: 100%;
  color: var(--ink);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 11px;
}

.add-artifact__error {
  padding: 9px 10px;
  color: var(--clay-red);
  background: rgba(184, 92, 77, 0.08);
  border: 1px solid rgba(184, 92, 77, 0.28);
  border-radius: 8px;
  font-size: 0.83rem;
}

.add-artifact__actions {
  margin-top: 16px;
}

.add-artifact__primary,
.add-artifact__secondary {
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.add-artifact__primary {
  color: var(--on-primary);
  background: var(--primary);
  border: 1px solid var(--primary);
}

.add-artifact__secondary {
  color: var(--muted);
  background: var(--surface-card);
  border: 1px solid var(--hairline);
}
</style>
```

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/AddArtifactModal.vue
git commit -m "feat(frontend): add AddArtifactModal component for manual artifact creation"
```

---

## Task 4: Frontend — Wire up "+ Add Artifact" button in IssueCollaborationTab

**Files:**
- Modify: `src/components/IssueCollaborationTab.vue`

- [ ] **Step 1: Add showAddArtifact ref and import Plus icon**

At the top of the `<script setup>` block (after the existing imports on line 4), add `Plus` to the lucide import and add the `showAddArtifact` ref and `AddArtifactModal` import:

Change line 4 from:
```typescript
import { MessageSquare, Clock, Package, Send } from 'lucide-vue-next'
```
to:
```typescript
import { MessageSquare, Clock, Package, Plus, Send } from 'lucide-vue-next'
import AddArtifactModal from '~/components/AddArtifactModal.vue'
```

After `const isSubmitting = ref(false)` (line 13), add:
```typescript
const showAddArtifact = ref(false)
```

- [ ] **Step 2: Add "+ Add Artifact" button in the Artifacts section header**

Replace the Artifacts section header (lines 150-155) from:
```html
<h4 class="collab-section__title">
  <Package :size="14" />
  Artifacts
  <span v-if="artifacts.length > 0" class="collab-section__count">{{ artifacts.length }}</span>
</h4>
```
to:
```html
<h4 class="collab-section__title">
  <Package :size="14" />
  Artifacts
  <span v-if="artifacts.length > 0" class="collab-section__count">{{ artifacts.length }}</span>
  <button class="collab-section__add" data-testid="add-artifact-btn" @click="showAddArtifact = true">
    <Plus :size="12" />
    Add Artifact
  </button>
</h4>
```

- [ ] **Step 3: Render AddArtifactModal conditionally**

After the closing `</div>` of the Artifacts section (line 175), add:
```html
<AddArtifactModal
  v-if="showAddArtifact"
  :issue-id="issueId"
  @close="showAddArtifact = false"
/>
```

- [ ] **Step 4: Add CSS for the "+ Add Artifact" button**

Add the following rule inside the `<style scoped>` block (after the `.collab-section__count` rule around line 223):

```css
.collab-section__add {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  padding: 2px 8px;
  color: var(--color-accent);
  background: transparent;
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  text-transform: none;
  letter-spacing: normal;
  transition: opacity 0.15s;
}

.collab-section__add:hover {
  opacity: 0.8;
}
```

- [ ] **Step 5: Run typecheck and build**

Run: `npm run typecheck && npm run build`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/IssueCollaborationTab.vue
git commit -m "feat(frontend): add '+ Add Artifact' button in IssueCollaborationTab Artifacts section"
```

---

## Task 5: E2E test — Manual artifact creation

**Files:**
- Create: `e2e/artifacts.spec.ts`

- [ ] **Step 1: Write the e2e test file**

Create `e2e/artifacts.spec.ts`:

```typescript
import { expect, test, type APIRequestContext } from '@playwright/test'

// Create an issue via the issues API. Returns the issue JSON.
const createIssue = async (request: APIRequestContext, title: string) => {
  const response = await request.post('http://127.0.0.1:8000/api/v1/issues', {
    data: {
      description: 'Created by Playwright E2E for artifact tests.',
      status: 'backlog',
      priority: 'medium',
      profile: 'frontend',
      title,
    },
  })
  expect(response.ok()).toBeTruthy()
  return await response.json()
}

test.describe('Manual artifact creation', () => {
  test('clicking "+ Add Artifact" opens modal, filling form creates artifact', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only artifact creation flow')

    const issue = await createIssue(request, 'Artifact E2E Test')
    const issueId = issue.id as string

    // Navigate to board, wait for the issue card to appear.
    await page.goto('/')
    await expect(
      page.locator(`[data-issue-id="${issueId}"]`)
    ).toBeVisible({ timeout: 5_000 })

    // Open issue detail via e2e store hook (same pattern as handoff-completion.spec.ts).
    await page.evaluate((id) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ not exposed')
      const issue = hook.store.getAllIssues.find(i => i.id === id)
      if (!issue) throw new Error(`Issue ${id} not found in store`)
      hook.store.selectIssue(issue)
    }, issueId)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()

    // Switch to Collaboration tab.
    await page.getByRole('button', { name: 'Collaboration' }).click()

    // Click "+ Add Artifact" button.
    await page.getByTestId('add-artifact-btn').click()
    await expect(page.getByTestId('add-artifact-modal')).toBeVisible()

    // Fill the form.
    await page.getByTestId('artifact-title').fill('Test Screenshot')
    await page.getByTestId('artifact-type').selectOption('screenshot')
    await page.getByTestId('artifact-path').fill('https://example.com/screenshot.png')
    await page.getByTestId('artifact-summary').fill('A test screenshot from E2E')

    // Submit.
    await page.getByTestId('artifact-submit').click()

    // Modal should close.
    await expect(page.getByTestId('add-artifact-modal')).not.toBeVisible()

    // Artifact should appear in the list.
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'Test Screenshot' })
    ).toBeVisible({ timeout: 5_000 })
  })

  test('completing a handoff auto-creates artifacts visible in Collaboration tab', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'desktop-only artifact creation flow')

    const issue = await createIssue(request, 'Handoff Artifact E2E')
    const issueId = issue.id as string

    // Create and accept a handoff via API.
    const createResp = await request.post(
      `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issueId}/handoffs`,
      { data: { toLane: 'frontend', createdBy: 'e2e' } }
    )
    expect(createResp.ok()).toBeTruthy()
    const handoff = await createResp.json()

    const acceptResp = await request.post(
      `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/accept`,
      { data: { actor: 'e2e' } }
    )
    expect(acceptResp.ok()).toBeTruthy()

    // Complete with payload containing screenshots and diff_summary.
    const completeResp = await request.post(
      `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issueId}/handoffs/${handoff.id}/complete`,
      {
        data: {
          actor: 'e2e',
          payload: {
            screenshots: ['login-v2.png'],
            diff_summary: 'Updated auth flow',
          },
        },
      }
    )
    expect(completeResp.ok()).toBeTruthy()

    // Open issue in UI and switch to Collaboration tab.
    await page.goto('/')
    await expect(
      page.locator(`[data-issue-id="${issueId}"]`)
    ).toBeVisible({ timeout: 5_000 })

    await page.evaluate((id) => {
      const hook = (window as Window).__DEVFLOW_E2E__
      if (!hook) throw new Error('__DEVFLOW_E2E__ not exposed')
      const issue = hook.store.getAllIssues.find(i => i.id === id)
      if (!issue) throw new Error(`Issue ${id} not found in store`)
      hook.store.selectIssue(issue)
    }, issueId)
    await expect(page.locator('.issue-detail__panel')).toBeVisible()
    await page.getByRole('button', { name: 'Collaboration' }).click()

    // Both auto-created artifacts should appear.
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'login-v2.png' })
    ).toBeVisible({ timeout: 5_000 })
    await expect(
      page.locator('.collab-artifact__title', { hasText: 'Diff Summary' })
    ).toBeVisible()
  })
})
```

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: No errors.

- [ ] **Step 3: Run e2e tests**

Run: `npm run e2e`
Expected: All tests pass, including the new artifact tests.

- [ ] **Step 4: Commit**

```bash
git add e2e/artifacts.spec.ts
git commit -m "test(e2e): manual artifact creation and handoff auto-create artifacts"
```

---

## Task 6: Full verification

- [ ] **Step 1: Run all backend tests**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: All pass (including new `test_handoff_artifacts.py`).

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`
Expected: No errors.

- [ ] **Step 3: Run build**

Run: `npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Run e2e**

Run: `npm run e2e`
Expected: All tests pass (including new `e2e/artifacts.spec.ts`).

- [ ] **Step 5: Manual verification**

1. Start backend: `PYTHONPATH=backend python3 -m uvicorn main:app --host 127.0.0.1 --port 8000`
2. Start frontend: `npm run dev`
3. Create an issue, create a handoff, accept, complete with `screenshots` and `diff_summary` in payload.
4. Open the issue's Collaboration tab — verify auto-created artifacts appear.
5. Click "+ Add Artifact" — fill form, submit — verify manual artifact appears.

- [ ] **Step 6: Update docs if needed**

If any files referenced in `CLAUDE.md` or `docs/claude-code-execution-plan.md` changed semantics, update those docs.

---

## Completion Criteria

- `PYTHONPATH=backend pytest -q backend/tests` passes (including 4 new artifact tests).
- `npm run typecheck` passes.
- `npm run build` passes.
- `npm run e2e` passes (including 2 new artifact e2e tests).
- Manual: complete a handoff → artifacts appear in Collaboration tab.
- Manual: click "+ Add Artifact" → can create artifact manually.
