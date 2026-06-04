# Artifacts v1 — Auto-Create from Handoff + Manual UI

## §1 Goal

Two slices:

**Slice A — Auto-create artifacts from handoff completion.** When a handoff is completed via `POST /boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/complete`, the backend automatically creates `IssueArtifact` records from the typed payload fields. This makes handoff evidence discoverable in the Artifacts tab without manual action.

**Slice B — Manual "Add Artifact" UI.** A button in the Artifacts section of `IssueCollaborationTab` opens a modal form to manually create artifact records (link external files, PRs, screenshots, etc.). Uses the existing `POST /issues/{id}/artifacts` API.

## §2 Non-Goals

- No file upload or binary storage (v1 is metadata-only: path/URL references).
- No artifact detail view / lightbox (clicking an artifact does nothing beyond the existing list).
- No artifact deletion or editing UI.
- No new DB models, migrations, or API endpoints.
- No changes to `HandoffCard.vue` evidence display (already works via P1.6).
- No i18n or design pass.

## §3 Architecture

### 3.1 Slice A — Backend auto-create

**File modified:** `backend/api/v1/endpoints/handoffs.py`

In `complete_handoff` (line 148), after `_svc.complete(...)` succeeds, add artifact creation logic:

```python
# After successful completion, auto-create artifacts from payload.
payload = body.payload or {}
issue_id_val = issue_id  # already in scope from function params

# screenshots → one artifact per file
for shot in (payload.get("screenshots") or []):
    await repo.create_issue_artifact(
        issue_id=issue_id_val,
        title=shot,
        artifact_type="screenshot",
        job_id=None,
        source="handoff_complete",
        path_or_url=shot,
        summary=f"Screenshot from handoff {handoff_id}",
    )

# diff_summary → one diff artifact
if payload.get("diff_summary"):
    await repo.create_issue_artifact(
        issue_id=issue_id_val,
        title="Diff Summary",
        artifact_type="diff_summary",
        job_id=None,
        source="handoff_complete",
        path_or_url=None,
        summary=payload["diff_summary"],
    )

# test_results → one log artifact
if payload.get("test_results"):
    await repo.create_issue_artifact(
        issue_id=issue_id_val,
        title="Test Results",
        artifact_type="test_log",
        job_id=None,
        source="handoff_complete",
        path_or_url=None,
        summary=payload["test_results"],
    )
```

**Key decisions:**
- Artifacts are created inline (not via BackgroundTasks) because the payload is small and the DB write is fast. If latency becomes a concern, move to BackgroundTasks later.
- `job_id` is `None` because the handoff may not have a job (manual completion).
- `source` is `"handoff_complete"` to distinguish auto-created artifacts from manual ones.
- `sensitivity` defaults to `"public"` (the model default).

### 3.2 Slice B — Frontend manual UI

**Files modified:**
- `src/components/IssueCollaborationTab.vue` — add "Add Artifact" button + modal state
- `src/components/AddArtifactModal.vue` (new) — form modal

**AddArtifactModal.vue:**
- Modal with fields: `title` (text), `artifactType` (select: file, screenshot, test_log, pr_link, design_doc, diff_summary, command_output), `pathOrUrl` (text, optional), `summary` (textarea, optional).
- Calls `collaborationStore.createArtifact(issueId, { title, artifactType, pathOrUrl, summary })`.
- Emits `close` on success or cancel.

**IssueCollaborationTab.vue:**
- Add `+ Add Artifact` button in the Artifacts section header (next to the count badge).
- Button toggles `showAddArtifact` ref.
- `<AddArtifactModal>` rendered conditionally.

### 3.3 Existing infrastructure (no changes needed)

| Component | Status | Location |
|-----------|--------|----------|
| DB model `IssueArtifact` | ✅ Exists | `backend/db/models.py:437` |
| Repository `create_issue_artifact` | ✅ Exists | `backend/db/repository.py:670` |
| Repository `list_issue_artifacts` | ✅ Exists | `backend/db/repository.py:651` |
| API `GET /issues/{id}/artifacts` | ✅ Exists | `backend/api/v1/endpoints/issue_collaboration.py:138` |
| API `POST /issues/{id}/artifacts` | ✅ Exists | `backend/api/v1/endpoints/issue_collaboration.py:160` |
| Frontend type `IssueArtifact` | ✅ Exists | `src/types/index.ts:163` |
| Store `fetchArtifacts` | ✅ Exists | `src/stores/collaboration.ts:218` |
| Store `createArtifact` | ✅ Exists | `src/stores/collaboration.ts:235` |
| CollaborationTab render | ✅ Exists | `src/components/IssueCollaborationTab.vue:149` |

## §4 Data flow

### Slice A (auto-create)

```text
POST /handoffs/{id}/complete (with payload)
  → _svc.complete() succeeds
  → repo.create_issue_artifact() per payload field
  → GET /issues/{id}/artifacts returns new artifacts
  → IssueCollaborationTab renders them
```

### Slice B (manual)

```text
User clicks "+ Add Artifact"
  → AddArtifactModal opens
  → User fills form, clicks Create
  → collaborationStore.createArtifact() → POST /issues/{id}/artifacts
  → Store updates local state
  → IssueCollaborationTab re-renders with new artifact
```

## §5 Testing

### 5.1 Backend test (Slice A)

New test in `backend/tests/test_handoff_artifacts.py`:

- Create issue, create handoff, accept, complete with payload containing `screenshots: ["a.png", "b.png"]` and `diff_summary: "Changed X"`.
- Assert `GET /issues/{id}/artifacts` returns 3 artifacts: 2 screenshots + 1 diff_summary.
- Assert artifact fields: `artifactType`, `title`, `source == "handoff_complete"`, `summary`.

### 5.2 E2E test (Slice B)

New test in `e2e/handoff-completion.spec.ts` or new file `e2e/artifacts.spec.ts`:

- Open issue detail, switch to Collaboration tab.
- Click "+ Add Artifact", fill form, submit.
- Assert new artifact appears in the list.

## §6 Out of scope

- Artifact detail view / lightbox.
- Artifact edit or delete UI.
- File upload (v1 is URL/path metadata only).
- Filtering or searching artifacts.
- Linking artifacts to specific handoffs in the UI (data exists via `source` field, but no UI for it).

## §7 Completion standard

- `PYTHONPATH=backend pytest -q backend/tests` passes (including new artifact tests).
- `npm run typecheck` passes.
- `npm run build` passes.
- `npm run e2e` passes (including new artifact e2e test).
- Manual verification: complete a handoff → artifacts appear in Collaboration tab; click "+ Add Artifact" → can create artifact manually.
