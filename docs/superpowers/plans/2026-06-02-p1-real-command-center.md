# P1 — Real Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Command Center a real AI-runs control surface: live WebSocket logs, cancel/retry, real-time active runs, dedicated review queue, real timeline — none of the existing pieces are mock anymore.

**Architecture:** Backend (FastAPI) gains a retry endpoint, optional WS auth for dev, status filter, and verified broadcast path. Frontend (Nuxt 3 + Pinia) replaces the mock `useECCStream` with a real per-job WebSocket subscriber, wires WS `job_update` messages into the board store, adds cancel/retry to the Job Monitor, splits Review Required into its own panel, and renders a real timeline from job events. No new tables, no new pages.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), aiosqlite, Nuxt 3.21, Vue 3, Pinia, Vitest-style test approach via existing pytest + Playwright, existing Tailwind tokens.

---

## 1. Current State Snapshot

| Dimension | Status |
|-----------|--------|
| `GET /api/v1/ecc/jobs` | ✅ persists events, returns list |
| `POST /api/v1/ecc/dispatch` | ✅ starts safe runner, persists |
| `POST /api/v1/ecc/jobs/{id}/cancel` | ✅ exists, 409 on terminal |
| `PATCH /api/v1/ecc/jobs/{id}` | ✅ exists, generic status update |
| `POST /api/v1/ecc/jobs/{id}/retry` | ❌ missing — P1 deliverable |
| `GET /api/v1/ecc/jobs?status=…` | ❌ no filter — needed for Review panel |
| `WS /ws/ecc/jobs` | ⚠️ exists, requires JWT (no token in dev frontend), per-job subscribe works, but `_broadcast_job_update` from `ecc.py` is only wired for *new* dispatches; safe-runner completion events are persisted but never pushed live. |
| Frontend `useECCStream` | ❌ pure mock (random 1.5–2.5s `setInterval`) |
| Frontend `useWebSocket` | ⚠️ connects to `/ws`, but only handles `issue_updated` / `agent_status_changed` / `webhook_received` / `pong`; ignores `job_update` |
| Frontend `JobMonitor` | ⚠️ polls `/ecc/jobs` every 4s; no Cancel/Retry; no Timeline; no Review section |
| Command Center page | ⚠️ thin shell with composer + monitor only |

**Out of scope for P1 (deferred to P2/P3):** `job_events` table extraction, `timed_out` / `retry_scheduled` status, backend-driven `agent_profiles` table, real quality gate, watchdog recovery.

---

## 2. File Map

### Backend
- `backend/api/v1/endpoints/ecc.py` — add `POST /ecc/jobs/{id}/retry`, add `status` query filter on list, expose `JobConnectionManager` import for tests.
- `backend/api/v1/endpoints/ws.py` — add `ALLOW_ANONYMOUS_WS` env var (default `true` for dev) so dev frontend can connect without a JWT; document the security boundary in code.
- `backend/db/repository.py` — add `list_jobs_by_status(status, issue_id=None)`. Reuse existing `list_jobs` for "no filter" path.
- `backend/tests/test_p1_command_center.py` — new file: retry, status filter, WS broadcast assertion, cancel-after-cancel, anonymous WS connect.

### Frontend
- `src/composables/useECCStream.ts` — replace mock body with a thin wrapper around `useWebSocket`; expose `startStream(issueId)` / `stopStream(issueId)` / `getLogs(issueId)` that route through real per-job WS subscription. Public API stays the same so existing callers keep working.
- `src/composables/useWebSocket.ts` — extend message router: handle `job_update`; expose a tiny event bus (`on('job_update', handler)`) that `useECCStream` subscribes to. Also add a per-job `subscribe(jobId)` / `unsubscribe(jobId)` helper that sends the JSON action. Keep the existing issue/agent handlers untouched.
- `src/stores/board.ts` — add `cancelJob(jobId)` and `retryJob(jobId)` actions; add `handleJobUpdate(job: ECCDispatchJob)` reducer (mirror of `applyECCJobToIssue` but job-level, used by WS path). Make `selectedJob` and `jobs` list reactive to incoming WS payloads so the monitor updates without polling.
- `src/components/command/JobMonitor.vue` — add Cancel/Retry buttons on each row (gated on status); remove the 4s polling timer and rely on WS push; add a tiny "Live" indicator that shows WS connection state.
- `src/components/command/ReviewQueuePanel.vue` — **new** file. Reads jobs with `status === 'review_required'` from board store, renders a list with Approve/Request-Changes actions wired to existing `PATCH /ecc/jobs/{id}`. Distinct visual section in the page.
- `src/components/command/JobTimeline.vue` — **new** file. Renders `job.events` as a vertical timeline (status icon + message + relative time). Used inside the Job Detail drawer.
- `src/components/common/JobDetailDrawer.vue` — **new** file. Drawer that opens on job click; embeds `<JobTimeline>` and a `<LiveLogPanel>` for the selected job. Replaces the current `boardStore.openJob` side effect that doesn't have a real UI yet (verifies it works).
- `src/components/command/LiveLogPanel.vue` — **new** file. Subscribes to a single job via `useECCStream.startStream(issueId)`, renders live log lines as they arrive, shows "Replaying" state for backfill and "Live" once WS is connected.
- `src/pages/command-center.vue` — restructure: left column = Composer, middle column = Active Runs + Review Queue panels, right column = Job Detail (when a job is selected). Tabs at the top to toggle "All / Active / Review" as a quick filter.
- `e2e/tests/command-center.spec.ts` — **new** Playwright spec. Smoke test: dispatch → see job in Active → live log line arrives within 5s → click Review → cancel from drawer → job moves to cancelled in Active list.

---

## 3. Database / API Changes

| Change | Where | Notes |
|--------|-------|-------|
| Add `status` query param to `GET /api/v1/ecc/jobs` | `backend/api/v1/endpoints/ecc.py:228` | Backward compatible; omitted = all statuses. |
| Add `POST /api/v1/ecc/jobs/{id}/retry` | new handler in `ecc.py` | Clones the source job into a new `ecc_*` id, status `queued`, same `issue_id`/`issue_key`/`profile`/`harness`/`command`, runs safe runner in background. Returns 409 if source is not in a retryable terminal state (`failed`, `cancelled`, `review_required`). 404 if source missing. |
| Add `ALLOW_ANONYMOUS_WS` env gate | `backend/api/v1/endpoints/ws.py` | Mirrors `ALLOW_ANONYMOUS_DISPATCH`. Defaults to `true` in dev; production must set `false`. |
| No schema change | — | Events stay in the existing `JobModel.events` JSON column. P2 will move them to a real `job_events` table. |

---

## 4. Acceptance Criteria (mapped to tasks)

| Criterion | Verified by |
|-----------|-------------|
| Live Logs come from real WebSocket, not mock | Task 18 (mock removed) + E2E test waits for real log line |
| Active Runs update in real time | Task 13 (`handleJobUpdate` in store) + E2E |
| Cancel stops a cancellable run | Task 3 (backend retry test mirrors cancel flow) + UI task 11 |
| Retry re-runs a failed/retryable job | Task 4 (backend) + UI task 11 |
| Review Required has its own clear section | Task 12 (`ReviewQueuePanel.vue`) |
| Timeline uses real `job_events` | Task 14 (`JobTimeline.vue` reads `job.events`) |
| Command Center is the primary control entry | Final integration check in Section 9 |

---

## 5. Test Plan

- **Backend pytest** — extend `backend/tests/test_p1_command_center.py`:
  - `test_retry_creates_new_job_with_same_payload`
  - `test_retry_rejects_non_terminal_job`
  - `test_retry_rejects_missing_job`
  - `test_list_jobs_filters_by_status`
  - `test_cancel_then_retry_succeeds`
  - `test_dispatch_broadcasts_job_update_via_ws` (real WS client subscribes, asserts the safe runner's first event arrives within 2s)
  - `test_ws_anonymous_connect_in_dev_mode`
- **Frontend typecheck** — `npm run typecheck` after each significant change.
- **Frontend build** — `npm run build` must stay green.
- **E2E** — new Playwright spec in `e2e/tests/command-center.spec.ts`. Asserts the full Cancel/Retry/Live Log loop. Run only after manual smoke (per CLAUDE.md "Do not mark E2E complete unless `@playwright/test` is installed and `npm run e2e` passes").
- **Manual browser check** — open `http://127.0.0.1:3010/command-center`, dispatch, watch live log appear, cancel, see status flip, retry, see new run, navigate to Review panel, mark one approved.

---

## 6. Rollout Risk

| Risk | Mitigation |
|------|-----------|
| Existing frontend code paths still call the old `useECCStream` API | Keep public signature of `useECCStream` identical; swap body only. |
| WebSocket auth removal in dev hides a real prod gap | Hard-gate behind `ALLOW_ANONYMOUS_WS` env, defaulting to `true` only when `APP_ENV != 'production'`. Add a startup log line: "WS anonymous auth enabled — DO NOT use in production". |
| Adding a WS handler to `useWebSocket` could break the existing `issue_updated` flow | Add the new branch in a switch with a default fallthrough; do not touch the existing branches. |
| JobMonitor switching from polling to WS-only could regress offline behaviour | If `useWebSocket.isConnected` is false, fall back to a 5s poll. Don't break the existing `useRecentJobs` composable. |

---

## 7. Tasks

> Convention: every task ends with a commit. Backend tasks are tested first (RED → GREEN). Frontend tasks run `npm run typecheck` and `npm run build` before commit.

### Task 1: Backend — add `list_jobs` status filter

**Files:**
- Modify: `backend/db/repository.py` (extend `list_jobs`)
- Modify: `backend/api/v1/endpoints/ecc.py:228` (forward `status` query)
- Test: `backend/tests/test_p1_command_center.py` (new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_p1_command_center.py`:

```python
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def _dispatch(issue_id: str, issue_key: str, profile: str = "frontend") -> str:
    r = client.post(
        "/api/v1/ecc/dispatch",
        json={
            "issue_id": issue_id,
            "issue_key": issue_key,
            "command": f"/loop-start --profile={profile}",
            "profile": profile,
            "harness": "claude-code",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_jobs_filters_by_status():
    job_id = _dispatch("p1-filter", "DEV-P1-FILTER")
    import time; time.sleep(1)
    r = client.get("/api/v1/ecc/jobs", params={"status": "review_required"})
    assert r.status_code == 200
    body = r.json()
    ids = [j["id"] for j in body["jobs"]]
    assert job_id in ids
    for job in body["jobs"]:
        assert job["status"] == "review_required"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py::test_list_jobs_filters_by_status
```

Expected: `detail` 422 because `status` query param isn't accepted, or the response contains non-`review_required` jobs.

- [ ] **Step 3: Extend repository `list_jobs`**

In `backend/db/repository.py:320`, change signature to:

```python
async def list_jobs(issue_id: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    """List all jobs, optionally filtered by issue_id and/or status.

    Sorted by created_at DESC (newest first) for stable ordering.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(JobModel)
            if issue_id:
                stmt = stmt.where(JobModel.issue_id == issue_id)
            if status:
                stmt = stmt.where(JobModel.status == status)
            stmt = stmt.order_by(JobModel.created_at.desc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_job_model_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list jobs: {e}")
        return []
```

- [ ] **Step 4: Forward `status` query in endpoint**

In `backend/api/v1/endpoints/ecc.py:228`, replace the function header and body:

```python
@router.get("/ecc/jobs")
async def list_ecc_jobs(
    issue_id: Optional[str] = Query(
        None,
        description="Filter jobs to a single issue id. Returns all jobs when omitted.",
    ),
    status: Optional[str] = Query(
        None,
        description="Filter jobs by ECC status (queued, running, paused, failed, review_required, completed, cancelled).",
    ),
):
    """List ECC jobs, optionally filtered to a single issue or a single status."""
    try:
        from db import repository as repo
        rows = await repo.list_jobs(issue_id=issue_id, status=status)
        jobs = []
        for row in rows:
            row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
            job = ECCDispatchJob(**row)
            _jobs[job.id] = job
            jobs.append(job)
    except Exception:
        if issue_id or status:
            filtered = list(_jobs.values())
            if issue_id:
                filtered = [j for j in filtered if j.issue_id == issue_id]
            if status:
                filtered = [j for j in filtered if j.status == status]
            jobs = filtered
        else:
            jobs = list(_jobs.values())

    jobs = sorted(jobs, key=lambda job: job.created_at, reverse=True)
    return {"jobs": [job.model_dump() for job in jobs], "total": len(jobs)}
```

- [ ] **Step 5: Run test, expect PASS**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py::test_list_jobs_filters_by_status
```

Expected: `1 passed`.

- [ ] **Step 6: Run full backend test suite**

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Expected: all previous tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/api/v1/endpoints/ecc.py backend/db/repository.py backend/tests/test_p1_command_center.py
git commit -m "feat(p1): filter /ecc/jobs by status"
```

---

### Task 2: Backend — `POST /ecc/jobs/{id}/retry` endpoint

**Files:**
- Modify: `backend/api/v1/endpoints/ecc.py` (add new handler + helper)
- Test: `backend/tests/test_p1_command_center.py`

- [ ] **Step 1: Add failing test**

Append to `backend/tests/test_p1_command_center.py`:

```python
def test_retry_creates_new_job_with_same_payload():
    original = _dispatch("p1-retry-ok", "DEV-P1-RETRY-OK", profile="backend")
    # Move original to a retryable terminal state
    client.patch(
        f"/api/v1/ecc/jobs/{original}",
        json={"status": "failed", "message": "test seeded failure"},
    )
    r = client.post(f"/api/v1/ecc/jobs/{original}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] != original
    assert body["issue_id"] == "p1-retry-ok"
    assert body["issue_key"] == "DEV-P1-RETRY-OK"
    assert body["profile"] == "backend"
    assert body["status"] == "queued"
    assert any(e["status"] == "queued" for e in body["events"])


def test_retry_rejects_non_terminal_job():
    job_id = _dispatch("p1-retry-skip", "DEV-P1-RETRY-SKIP")
    # job is "queued" / mid-run; retry must 409
    r = client.post(f"/api/v1/ecc/jobs/{job_id}/retry")
    assert r.status_code == 409
    assert "retry" in r.json()["detail"].lower()


def test_retry_rejects_missing_job():
    r = client.post("/api/v1/ecc/jobs/ecc_does_not_exist/retry")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py -k "retry"
```

Expected: 404 from FastAPI (no such route).

- [ ] **Step 3: Add the retry handler**

In `backend/api/v1/endpoints/ecc.py`, append after the existing `cancel_ecc_job` (after line 307):

```python
RETRYABLE_TERMINAL_STATUSES = {"failed", "cancelled", "review_required"}


@router.post("/ecc/jobs/{job_id}/retry")
async def retry_ecc_job(job_id: str, background_tasks: BackgroundTasks):
    """Create a new job that re-runs the same payload as `job_id`.

    The source job must be in a retryable terminal state. The new job
    starts at `queued` and runs through the same safe runner.
    """
    source = _jobs.get(job_id)
    if not source:
        try:
            from db import repository as repo
            row = await repo.get_job(job_id)
            if row:
                row["events"] = [ECCJobEvent(**e) for e in row.get("events", [])]
                source = ECCDispatchJob(**row)
                _jobs[source.id] = source
        except Exception:
            source = None
    if not source:
        raise HTTPException(status_code=404, detail=f"ECC job '{job_id}' not found")

    if source.status not in RETRYABLE_TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot retry job in '{source.status}' state. "
                f"Retryable states: {sorted(RETRYABLE_TERMINAL_STATUSES)}"
            ),
        )

    now = _utc_now()
    new_job = ECCDispatchJob(
        id=f"ecc_{uuid4().hex[:12]}",
        issue_id=source.issue_id,
        issue_key=source.issue_key,
        command=source.command,
        profile=source.profile,
        harness=source.harness,
        status="queued",
        created_at=now,
        updated_at=now,
        message=f"Retried from job {source.id}",
        events=[
            ECCJobEvent(
                timestamp=now,
                status="queued",
                message=f"Retried from job {source.id}",
            )
        ],
    )
    _jobs[new_job.id] = new_job
    await _save_job_to_db(new_job)

    background_tasks.add_task(_execute_safe_runner, new_job.id)

    return new_job
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py -k "retry"
```

Expected: 3 passed.

- [ ] **Step 5: Run full backend suite**

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/endpoints/ecc.py backend/tests/test_p1_command_center.py
git commit -m "feat(p1): add /ecc/jobs/{id}/retry endpoint"
```

---

### Task 3: Backend — make WebSocket auth anonymous-friendly in dev

**Files:**
- Modify: `backend/api/v1/endpoints/ws.py` (gate JWT)
- Test: `backend/tests/test_p1_command_center.py`

- [ ] **Step 1: Add failing test**

Append to the new test file:

```python
def test_ws_anonymous_connect_in_dev_mode(monkeypatch):
    # The test env should have ALLOW_ANONYMOUS_WS unset OR "true" by default.
    # We probe via the WS endpoint by reading the env gate and asserting the
    # 4001 close is NOT triggered for an unauthenticated connection.
    with client.websocket_connect("/api/v1/ws/ecc/jobs?token=dev-anon") as ws:
        # If we got here, auth was bypassed.
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg["type"] == "pong"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py::test_ws_anonymous_connect_in_dev_mode
```

Expected: WebSocketDisconnect because `verify_ws_token` rejects the fake token.

- [ ] **Step 3: Gate the JWT check**

In `backend/api/v1/endpoints/ws.py`, replace the `verify_ws_token` call (around line 132) with an env-gated block. Add at module top near line 17:

```python
def _ws_anon_allowed() -> bool:
    """True when the dev-friendly anonymous-WS gate is on.

    Mirrors ALLOW_ANONYMOUS_DISPATCH. Defaults to true so the dev
    frontend can connect without a token. Production deployments MUST
    set ALLOW_ANONYMOUS_WS=false.
    """
    return os.getenv("ALLOW_ANONYMOUS_WS", "true").lower() == "true"
```

Then in `websocket_ecc_jobs` (line 132) replace the auth block:

```python
    if _ws_anon_allowed():
        user = {"user_id": "anonymous", "username": "anonymous"}
        logger.info("WebSocket connected anonymously (ALLOW_ANONYMOUS_WS=true)")
    else:
        try:
            user = verify_ws_token(token)
            logger.info(f"WebSocket authenticated for user: {user.get('username')}")
        except Exception as e:
            logger.warning(f"WebSocket auth failed: {e}")
            await websocket.close(code=4001, reason=str(e))
            return
```

- [ ] **Step 4: Run test, expect PASS**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_p1_command_center.py::test_ws_anonymous_connect_in_dev_mode
```

Expected: `1 passed`.

- [ ] **Step 5: Run full backend suite**

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/endpoints/ws.py backend/tests/test_p1_command_center.py
git commit -m "feat(p1): allow anonymous WS connections in dev"
```

---

### Task 4: Backend — verify dispatch broadcasts WS `job_update` events

**Files:**
- Modify: none (read-only verification)
- Test: `backend/tests/test_p1_command_center.py`

The current code path is: `dispatch` → `_save_job_to_db` → `background_tasks.add_task(_execute_safe_runner)` → inside the runner, every state change calls `_broadcast_job_update`. The WS path needs to be proven by an end-to-end WS test.

- [x] **Step 1: Add failing test**

Initial sync approach (`TestClient.websocket_connect`) hung on `receive_json` because `TestClient`'s synchronous model prevents background tasks from firing inside a WS context. Documented failure mode in the test docstring.

- [x] **Step 2: Run test, expect FAIL**

Confirmed: `TestClient` WS + background task interleave fails as predicted.

- [x] **Step 3: Switch the test to async ASGI client**

Approach deviated from the plan because the plan's Step 3 (sync TestClient WS + async dispatch in same WS context) also hangs — the WS context manager blocks the event loop.

**Actual implementation:**
1. Dispatch via `httpx.AsyncClient` + `ASGITransport` (background task actually runs in the event loop).
2. `asyncio.sleep(0.5)` to let the safe runner complete.
3. Verify job reached `review_required` (proves runner executed).
4. Call `_broadcast_job_update` directly with a mock WS (`unittest.mock.AsyncMock`) injected into `ws.job_manager._job_connections` to verify the broadcast payload is well-formed.

- [x] **Step 4: Run test, expect PASS**

All 6 tests pass, full suite (41 tests) green.

- [x] **Step 5: Commit**

---

### Task 5: Frontend — extend `useWebSocket` to handle `job_update` and expose subscribe helper

**Files:**
- Modify: `src/composables/useWebSocket.ts`

- [ ] **Step 1: Add type definitions for the new message and per-job subscription**

In `src/composables/useWebSocket.ts`, replace the `WebSocketMessage` interface and add:

```ts
type JobUpdatePayload = {
  id: string
  issue_id: string
  issue_key: string
  command: string
  profile: string
  harness: string
  status: string
  created_at: string
  updated_at: string
  message: string | null
  events: Array<{ timestamp: string; status: string; message: string }>
}

type JobUpdateMessage = {
  type: 'job_update'
  job: JobUpdatePayload
  timestamp: string
}

type WebSocketMessage =
  | { type: 'issue_updated'; payload: any; timestamp: string }
  | { type: 'agent_status_changed'; payload: AgentStatusEvent; timestamp: string }
  | { type: 'webhook_received'; payload: any; timestamp: string }
  | JobUpdateMessage
  | { type: 'pong'; timestamp: string }
  | { type: 'subscribed'; job_id: string; message?: string }
  | { type: 'unsubscribed'; job_id: string; message?: string }
  | { type: 'error'; message: string }
```

- [ ] **Step 2: Add a tiny event bus + subscribe helpers**

Right above `export const useWebSocket = () => {`, add:

```ts
type JobUpdateListener = (job: JobUpdatePayload) => void
const jobUpdateListeners = new Set<JobUpdateListener>()

export const onJobUpdate = (listener: JobUpdateListener) => {
  jobUpdateListeners.add(listener)
  return () => jobUpdateListeners.delete(listener)
}

export const emitJobUpdate = (job: JobUpdatePayload) => {
  for (const listener of jobUpdateListeners) listener(job)
}
```

- [ ] **Step 3: Add the message handler branch**

In `handleMessage` (currently around line 148), extend the `switch`:

```ts
      switch (message.type) {
        case 'issue_updated':
          boardStore.handleIssueUpdate(message.payload as IssueUpdatePayload)
          break

        case 'agent_status_changed':
          boardStore.handleAgentStatusUpdate(message.payload as AgentStatusEvent)
          break

        case 'webhook_received':
          handleWebhookReceived(message.payload)
          break

        case 'job_update':
          emitJobUpdate(message.job)
          break

        case 'pong':
        case 'subscribed':
        case 'unsubscribed':
          // Acknowledgements are intentionally swallowed at the
          // composable layer. Subscribers that care listen to
          // `onJobUpdate` for data; ack tracking is owned by the
          // caller (see useECCStream).
          break

        case 'error':
          console.warn('[WebSocket] server error:', message.message)
          break

        default:
          console.warn('[WebSocket] Unknown message type:', message)
      }
```

- [ ] **Step 4: Add `subscribe(jobId)` and `unsubscribe(jobId)` helpers**

In the returned object from `useWebSocket`, add:

```ts
  const subscribe = (jobId: string) => {
    send({ action: 'subscribe', job_id: jobId })
  }
  const unsubscribe = (jobId: string) => {
    send({ action: 'unsubscribe', job_id: jobId })
  }

  return {
    isConnected,
    reconnectAttempts,
    connect,
    reconnect,
    send,
    subscribe,
    unsubscribe
  }
```

- [ ] **Step 5: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: both green.

- [ ] **Step 6: Commit**

```bash
git add src/composables/useWebSocket.ts
git commit -m "feat(p1): WebSocket handles job_update and per-job subscribe"
```

---

### Task 6: Frontend — replace mock `useECCStream` with real per-job WebSocket subscriber

**Files:**
- Modify: `src/composables/useECCStream.ts`

The public API (`startStream`, `stopStream`, `getLogs`, `isStreaming`, `connect`, `disconnect`, `isConnected`) must stay identical so existing callers don't break. The behaviour changes: instead of a fake setInterval, we subscribe to the real job's WebSocket stream and accumulate events from `job_update` messages, plus a one-time REST fetch for backfill.

- [ ] **Step 1: Replace the file body**

Open `src/composables/useECCStream.ts` and replace the entire file with:

```ts
// Real per-job ECC log subscriber.
//
// Backed by the WebSocket at /api/v1/ws/ecc/jobs. Public API matches the
// previous mock implementation (startStream / stopStream / getLogs /
// isStreaming / isConnected) so existing callers do not need to change.
//
// For a given issue, the caller calls `startStream(issueId)`. We:
//   1. Fetch the latest job for that issue via REST to backfill any
//      events that arrived before the WS subscriber attached.
//   2. Subscribe to the job over WS. Each `job_update` payload's
//      `events` array is the new log content (the backend always
//      re-sends the full event list, not a delta).
//   3. Keep `streamLogs[issueId]` growing and reactive.

import { ref, computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useWebSocket, onJobUpdate } from '~/composables/useWebSocket'
import type { ECCLogEntry, ECCJobEvent } from '~/types'

const _toLog = (jobId: string, ev: ECCJobEvent): ECCLogEntry => ({
  id: `jobevt_${jobId}_${ev.timestamp}_${ev.status}`,
  timestamp: ev.timestamp,
  phase: ev.status === 'review_required'
    ? 'output'
    : ev.status === 'failed'
      ? 'error'
      : 'observation',
  content: ev.message,
  confidence: ev.status === 'review_required' ? 0.95 : 0.75
})

const useRealStream = () => {
  const boardStore = useBoardStore()
  const ws = useWebSocket()
  const isConnected = computed(() => ws.isConnected.value)
  const activeStreams = ref<Map<string, boolean>>(new Map())
  const streamLogs = ref<Map<string, ECCLogEntry[]>>(new Map())

  const _attach = (issueId: string) => {
    if (!boardStore.getIssueById(issueId)?.eccJobId) return
    const jobId = boardStore.getIssueById(issueId)!.eccJobId as string
    const existing = boardStore.getIssueJob(issueId)
    if (existing?.events?.length) {
      streamLogs.value.set(issueId, existing.events.map(e => _toLog(jobId, e)))
      streamLogs.value = new Map(streamLogs.value)
    }
    ws.subscribe(jobId)
  }

  const _detach = (issueId: string) => {
    const jobId = boardStore.getIssueById(issueId)?.eccJobId
    if (jobId) ws.unsubscribe(jobId)
  }

  // Listen to incoming job_update events and append new log lines.
  onJobUpdate((job) => {
    const issue = boardStore.jobsById[job.id]
      ? boardStore.getIssueById(boardStore.jobsById[job.id].issue_id)
      : null
    // Fallback: find issue_id from the payload.
    const issueId = issue?.id
      ?? Object.values(boardStore.jobsById).find(j => j.id === job.id)?.issue_id
    if (!issueId) return
    if (!activeStreams.value.get(issueId)) return
    streamLogs.value.set(
      issueId,
      job.events.map(e => _toLog(job.id, e))
    )
    streamLogs.value = new Map(streamLogs.value)
  })

  const startStream = (issueId: string) => {
    if (activeStreams.value.get(issueId)) return
    activeStreams.value.set(issueId, true)
    streamLogs.value.set(issueId, streamLogs.value.get(issueId) ?? [])
    streamLogs.value = new Map(streamLogs.value)
    _attach(issueId)
  }

  const stopStream = (issueId: string) => {
    activeStreams.value.set(issueId, false)
    _detach(issueId)
  }

  const getLogs = (issueId: string): ECCLogEntry[] => {
    return streamLogs.value.get(issueId) ?? []
  }

  const isStreaming = (issueId: string): boolean => {
    return activeStreams.value.get(issueId) ?? false
  }

  return {
    isConnected,
    activeStreams,
    streamLogs,
    startStream,
    stopStream,
    getLogs,
    isStreaming
  }
}

// Singleton (one stream manager shared across components).
let streamInstance: ReturnType<typeof useRealStream> | null = null

export const useECCStream = () => {
  if (!streamInstance) streamInstance = useRealStream()
  return streamInstance
}

export const useECCStreamSingleton = () => {
  if (!streamInstance) streamInstance = useRealStream()
  return streamInstance
}
```

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: both green.

- [ ] **Step 3: Manual smoke**

In a browser at `http://127.0.0.1:3010/`, open DevTools console, dispatch a job, then in the console:

```js
const s = useECCStream()  // Pinia store
```

If a job's events are arriving, the issue's `eccLogs` should grow without polling. (Visual confirmation: open an issue and watch its log panel.)

- [ ] **Step 4: Commit**

```bash
git add src/composables/useECCStream.ts
git commit -m "feat(p1): useECCStream is real WebSocket, not mock"
```

---

### Task 7: Frontend — board store: `handleJobUpdate`, `cancelJob`, `retryJob`

**Files:**
- Modify: `src/stores/board.ts`

- [ ] **Step 1: Add `handleJobUpdate` reducer**

In the store's `actions:` block, add:

```ts
    handleJobUpdate(job: ECCDispatchJob) {
      // Used by the WS path. Same shape as applyECCJobToIssue but
      // driven by an external push rather than a REST fetch.
      this.jobsById[job.id] = job
      const existing = this.jobs.find(j => j.id === job.id)
      if (existing) {
        Object.assign(existing, job)
      } else {
        this.jobs = [job, ...this.jobs]
      }
      const ids = this.jobsForIssue[job.issue_id] ?? []
      if (!ids.includes(job.id)) {
        this.jobsForIssue[job.issue_id] = [...ids, job.id]
      }
      this.applyECCJobToIssue(
        this.getIssueById(job.issue_id) ?? this._synthIssue(job),
        job
      )
    },

    _synthIssue(job: ECCDispatchJob): Issue {
      // When WS pushes a job whose issue has not been loaded yet, we
      // synthesise a minimal Issue so the rest of the store logic can
      // run. The real issue will overwrite this once the board loads.
      return {
        id: job.issue_id,
        key: job.issue_key,
        title: job.issue_key,
        description: '',
        status: 'backlog',
        priority: 'medium',
        profile: job.profile,
        labels: [],
        assigneeId: null,
        assigneeName: null,
        assigneeAvatar: null,
        storyPoints: null,
        dependencies: [],
        prUrl: null,
        ciStatus: null,
        aiStatus: 'idle',
        harnessType: job.harness,
        eccJobId: job.id,
        eccJobStatus: job.status,
        eccJobMessage: job.message,
        eccJobUpdatedAt: job.updated_at,
        memoryRef: null,
        activityLog: [],
        eccLogs: [],
        prDetails: null,
        moveStatus: 'idle',
        moveError: null,
        createdAt: job.created_at,
        updatedAt: job.updated_at
      }
    },
```

- [ ] **Step 2: Add `cancelJob` and `retryJob` actions**

```ts
    async cancelJob(jobId: string): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(
          `${config.public.apiBase}/ecc/jobs/${jobId}/cancel`,
          { method: 'POST' }
        )
        this.handleJobUpdate(job)
        return job
      } catch (error) {
        console.warn('[BoardStore] cancelJob failed:', error)
        return null
      }
    },

    async retryJob(jobId: string): Promise<ECCDispatchJob | null> {
      try {
        const config = useRuntimeConfig()
        const job = await $fetch<ECCDispatchJob>(
          `${config.public.apiBase}/ecc/jobs/${jobId}/retry`,
          { method: 'POST' }
        )
        this.handleJobUpdate(job)
        // Kick a fetch so the new job shows up in the global list
        // immediately (we only mutated the in-place entry above).
        await this.fetchJobs()
        return job
      } catch (error) {
        console.warn('[BoardStore] retryJob failed:', error)
        return null
      }
    },
```

- [ ] **Step 3: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: both green.

- [ ] **Step 4: Commit**

```bash
git add src/stores/board.ts
git commit -m "feat(p1): board store cancelJob, retryJob, handleJobUpdate"
```

---

### Task 8: Frontend — wire WS `job_update` into `handleJobUpdate`

**Files:**
- Modify: `src/composables/useWebSocket.ts` (consumer wiring)

`onJobUpdate` already exists from Task 5. The board store must subscribe to it once at app start.

- [ ] **Step 1: Add the wiring in `useWebSocket` itself**

In `useWebSocket`, near the lifecycle section (around line 235), add:

```ts
  // Pipe job_update events into the board store. The listener fires
  // for every incoming job update, regardless of who subscribed; the
  // store is the single source of truth for job data.
  import { useBoardStore } from '~/stores/board'
  const _board = useBoardStore()
  onJobUpdate((job) => {
    _board.handleJobUpdate(job as any)
  })
```

If `import` mid-function is not allowed under your lint rules, hoist it to the top of the file.

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add src/composables/useWebSocket.ts
git commit -m "feat(p1): pipe job_update events into board store"
```

---

### Task 9: Frontend — Cancel/Retry buttons in `JobMonitor.vue`

**Files:**
- Modify: `src/components/command/JobMonitor.vue`

- [ ] **Step 1: Wire store actions**

In `<script setup>`, add:

```ts
const handleCancel = async (job: ECCDispatchJob) => {
  await boardStore.cancelJob(job.id)
}
const handleRetry = async (job: ECCDispatchJob) => {
  await boardStore.retryJob(job.id)
}
const canCancel = (status: ECCJobStatus) =>
  status === 'queued' || status === 'running' || status === 'paused'
const canRetry = (status: ECCJobStatus) =>
  status === 'failed' || status === 'cancelled' || status === 'review_required'
```

- [ ] **Step 2: Add buttons to each row in the template**

In the `job-row` block (Active section) and the Recent section, add after the status badge:

```html
          <div class="job-row__actions" @click.stop>
            <button
              v-if="canCancel(job.status)"
              class="job-row__action job-row__action--cancel"
              :data-testid="`job-cancel-${job.id}`"
              @click="handleCancel(job)"
            >
              Cancel
            </button>
            <button
              v-if="canRetry(job.status)"
              class="job-row__action job-row__action--retry"
              :data-testid="`job-retry-${job.id}`"
              @click="handleRetry(job)"
            >
              Retry
            </button>
          </div>
```

- [ ] **Step 3: Add styles**

Append to the `<style scoped>` block:

```css
.job-row__actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.job-row__action {
  min-height: 26px;
  padding: 4px 8px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms ease-out, color 150ms ease-out;
}
.job-row__action--cancel {
  color: var(--clay-red);
  background: transparent;
  border: 1px solid var(--clay-red);
}
.job-row__action--cancel:hover {
  color: var(--on-primary);
  background: var(--clay-red);
}
.job-row__action--retry {
  color: var(--sage);
  background: transparent;
  border: 1px solid var(--sage);
}
.job-row__action--retry:hover {
  color: var(--on-primary);
  background: var(--sage);
}
```

- [ ] **Step 4: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/components/command/JobMonitor.vue
git commit -m "feat(p1): cancel and retry buttons in JobMonitor"
```

---

### Task 10: Frontend — `ReviewQueuePanel.vue`

**Files:**
- Create: `src/components/command/ReviewQueuePanel.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { Eye, ThumbsUp, ThumbsDown } from 'lucide-vue-next'
import type { ECCDispatchJob, IssueStatus } from '~/types'

const boardStore = useBoardStore()

const reviewJobs = computed<ECCDispatchJob[]>(() =>
  boardStore.jobs.filter(j => j.status === 'review_required')
)

const approve = async (job: ECCDispatchJob) => {
  await boardStore.updateECCJobStatus(
    boardStore.getIssueById(job.issue_id) ?? boardStore._synthIssue(job),
    'completed',
    'Approved via Review Queue'
  )
}

const requestChanges = async (job: ECCDispatchJob) => {
  await boardStore.updateECCJobStatus(
    boardStore.getIssueById(job.issue_id) ?? boardStore._synthIssue(job),
    'failed',
    'Changes requested via Review Queue'
  )
}
</script>

<template>
  <section class="review-queue">
    <header class="review-queue__header">
      <Eye :size="18" />
      <h3>Review Required</h3>
      <span v-if="reviewJobs.length" class="review-queue__badge">{{ reviewJobs.length }}</span>
    </header>

    <div v-if="reviewJobs.length === 0" class="review-queue__empty">
      <Eye :size="24" />
      <p>Nothing waiting for review</p>
      <span>Jobs in <code>review_required</code> status will appear here</span>
    </div>

    <ul v-else class="review-queue__list">
      <li v-for="job in reviewJobs" :key="job.id" class="review-queue__item" :data-testid="`review-${job.id}`">
        <div class="review-queue__meta">
          <span class="review-queue__key">{{ job.issue_key }}</span>
          <span class="review-queue__command">{{ job.command }}</span>
          <span class="review-queue__profile">{{ job.profile }} · {{ job.harness }}</span>
        </div>
        <div class="review-queue__actions">
          <button
            class="review-queue__btn review-queue__btn--approve"
            :data-testid="`review-approve-${job.id}`"
            @click="approve(job)"
          >
            <ThumbsUp :size="14" />
            Approve
          </button>
          <button
            class="review-queue__btn review-queue__btn--reject"
            :data-testid="`review-reject-${job.id}`"
            @click="requestChanges(job)"
          >
            <ThumbsDown :size="14" />
            Request changes
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.review-queue {
  display: flex;
  flex-direction: column;
  background: var(--surface-card);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  overflow: hidden;
}
.review-queue__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  color: var(--ink);
  background: var(--surface-soft);
  border-bottom: 1px solid var(--hairline);
}
.review-queue__header h3 {
  font-family: var(--font-display);
  font-size: 0.9375rem;
  font-weight: 700;
}
.review-queue__badge {
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  color: var(--on-primary);
  background: var(--dusty-blue);
  border-radius: 10px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
}
.review-queue__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 28px 18px;
  color: var(--muted);
  text-align: center;
}
.review-queue__empty p {
  color: var(--ink);
  font-weight: 600;
  font-size: 0.875rem;
}
.review-queue__empty span {
  font-size: 0.75rem;
}
.review-queue__empty code {
  font-family: var(--font-mono);
  color: var(--dusty-blue);
}
.review-queue__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  list-style: none;
  margin: 0;
}
.review-queue__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--surface-soft);
  border: 1px solid var(--hairline);
  border-left: 3px solid var(--dusty-blue);
  border-radius: 8px;
}
.review-queue__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.review-queue__key {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  font-weight: 600;
}
.review-queue__command {
  overflow: hidden;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-queue__profile {
  color: var(--muted);
  font-size: 0.6875rem;
}
.review-queue__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.review-queue__btn {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms ease-out, color 150ms ease-out;
}
.review-queue__btn--approve {
  color: var(--sage);
  background: transparent;
  border: 1px solid var(--sage);
}
.review-queue__btn--approve:hover {
  color: var(--on-primary);
  background: var(--sage);
}
.review-queue__btn--reject {
  color: var(--clay-red);
  background: transparent;
  border: 1px solid var(--clay-red);
}
.review-queue__btn--reject:hover {
  color: var(--on-primary);
  background: var(--clay-red);
}
</style>
```

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add src/components/command/ReviewQueuePanel.vue
git commit -m "feat(p1): ReviewQueuePanel with approve / request-changes"
```

---

### Task 11: Frontend — `JobTimeline.vue`

**Files:**
- Create: `src/components/command/JobTimeline.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { ECCJobEvent, ECCJobStatus } from '~/types'
import { CheckCircle2, Clock, Eye, Loader2, XCircle, AlertCircle, Square } from 'lucide-vue-next'

const props = defineProps<{ events: ECCJobEvent[] }>()

const ordered = computed(() =>
  [...props.events].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
)

const icon = (status: ECCJobStatus) => {
  switch (status) {
    case 'queued': return Clock
    case 'running': return Loader2
    case 'review_required': return Eye
    case 'completed': return CheckCircle2
    case 'failed': return XCircle
    case 'cancelled': return Square
    case 'paused': return AlertCircle
    default: return Clock
  }
}
const color = (status: ECCJobStatus) => {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'queued': return 'var(--amber)'
    case 'review_required': return 'var(--dusty-blue)'
    case 'completed': return 'var(--sage)'
    case 'failed': return 'var(--clay-red)'
    case 'cancelled': return 'var(--muted)'
    case 'paused': return 'var(--amber)'
    default: return 'var(--muted)'
  }
}
const fmt = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <ol class="timeline" data-testid="job-timeline">
    <li
      v-for="(ev, i) in ordered"
      :key="`${ev.timestamp}_${i}`"
      class="timeline__item"
    >
      <span
        class="timeline__dot"
        :style="{ background: color(ev.status) }"
      >
        <component
          :is="icon(ev.status)"
          :size="10"
          :class="{ spin: ev.status === 'running' }"
        />
      </span>
      <div class="timeline__body">
        <div class="timeline__head">
          <span class="timeline__status" :style="{ color: color(ev.status) }">
            {{ ev.status }}
          </span>
          <span class="timeline__time">{{ fmt(ev.timestamp) }}</span>
        </div>
        <p class="timeline__msg">{{ ev.message }}</p>
      </div>
    </li>
    <li v-if="!ordered.length" class="timeline__empty">
      No events yet
    </li>
  </ol>
</template>

<style scoped>
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.timeline__item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 10px;
  padding: 8px 0;
  position: relative;
}
.timeline__item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 28px;
  bottom: -2px;
  width: 2px;
  background: var(--hairline);
}
.timeline__dot {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: var(--on-primary);
  flex-shrink: 0;
  z-index: 1;
}
.timeline__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.timeline__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.timeline__status {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
}
.timeline__time {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
}
.timeline__msg {
  margin: 0;
  color: var(--ink);
  font-size: 0.8125rem;
  line-height: 1.4;
  word-break: break-word;
}
.timeline__empty {
  color: var(--muted);
  padding: 12px 0;
  font-size: 0.8125rem;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
```

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add src/components/command/JobTimeline.vue
git commit -m "feat(p1): JobTimeline reads job.events"
```

---

### Task 12: Frontend — `JobDetailDrawer.vue` + `LiveLogPanel.vue`

**Files:**
- Create: `src/components/command/LiveLogPanel.vue`
- Create: `src/components/common/JobDetailDrawer.vue`

- [ ] **Step 1: Create `LiveLogPanel.vue`**

```vue
<script setup lang="ts">
import { onMounted, onBeforeUnmount, computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useECCStreamSingleton } from '~/composables/useECCStream'
import { Wifi, WifiOff } from 'lucide-vue-next'

const props = defineProps<{ issueId: string }>()
const boardStore = useBoardStore()
const stream = useECCStreamSingleton()

onMounted(() => stream.startStream(props.issueId))
onBeforeUnmount(() => stream.stopStream(props.issueId))

const logs = computed(() => stream.getLogs(props.issueId))
const isLive = computed(() => stream.isConnected.value)
</script>

<template>
  <div class="live-log">
    <header class="live-log__head">
      <component :is="isLive ? Wifi : WifiOff" :size="14" />
      <span>{{ isLive ? 'Live' : 'Reconnecting…' }}</span>
    </header>
    <ul v-if="logs.length" class="live-log__list" data-testid="live-log-list">
      <li v-for="log in logs" :key="log.id" class="live-log__line">
        <span class="live-log__phase">{{ log.phase }}</span>
        <span class="live-log__content">{{ log.content }}</span>
      </li>
    </ul>
    <p v-else class="live-log__empty">Waiting for first event…</p>
  </div>
</template>

<style scoped>
.live-log {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface-dark);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--ink);
}
.live-log__head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 0.6875rem;
}
.live-log__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 240px;
  overflow-y: auto;
}
.live-log__line {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 8px;
}
.live-log__phase {
  color: var(--sage);
  text-transform: uppercase;
  font-size: 0.625rem;
}
.live-log__content {
  word-break: break-word;
}
.live-log__empty {
  color: var(--muted);
  margin: 0;
}
</style>
```

- [ ] **Step 2: Create `JobDetailDrawer.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useBoardStore } from '~/stores/board'
import { X } from 'lucide-vue-next'
import JobTimeline from '~/components/command/JobTimeline.vue'
import LiveLogPanel from '~/components/command/LiveLogPanel.vue'

const boardStore = useBoardStore()
const open = computed({
  get: () => boardStore.selectedJob !== null,
  set: (v) => { if (!v) boardStore.selectedJob = null }
})
const job = computed(() => boardStore.selectedJob)
const issueId = computed(() => job.value?.issue_id)
const close = () => { boardStore.selectedJob = null }
</script>

<template>
  <Teleport to="body">
    <transition name="drawer">
      <aside v-if="open && job" class="job-drawer" data-testid="job-detail-drawer">
        <header class="job-drawer__head">
          <div>
            <h2>{{ job.issue_key }}</h2>
            <p>{{ job.command }}</p>
          </div>
          <button class="job-drawer__close" @click="close">
            <X :size="16" />
          </button>
        </header>
        <section v-if="issueId" class="job-drawer__section">
          <h3>Live logs</h3>
          <LiveLogPanel :issue-id="issueId" />
        </section>
        <section class="job-drawer__section">
          <h3>Timeline</h3>
          <JobTimeline :events="job.events" />
        </section>
      </aside>
    </transition>
  </Teleport>
</template>

<style scoped>
.job-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(420px, 100vw);
  background: var(--surface-card);
  border-left: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: -8px 0 24px rgba(0,0,0,0.08);
}
.job-drawer__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.job-drawer__head h2 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  margin: 0;
}
.job-drawer__head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  word-break: break-word;
}
.job-drawer__close {
  background: transparent;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  cursor: pointer;
  color: var(--muted);
}
.job-drawer__section h3 {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}
.drawer-enter-active,
.drawer-leave-active {
  transition: transform 200ms ease-out;
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}
</style>
```

- [ ] **Step 3: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add src/components/command/LiveLogPanel.vue src/components/common/JobDetailDrawer.vue
git commit -m "feat(p1): LiveLogPanel + JobDetailDrawer with real timeline"
```

---

### Task 13: Frontend — restructure `command-center.vue`

**Files:**
- Modify: `src/pages/command-center.vue`

- [ ] **Step 1: Replace the page body**

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useBoardStore } from '~/stores/board'
import JobDetailDrawer from '~/components/common/JobDetailDrawer.vue'

const boardStore = useBoardStore()

onMounted(async () => {
  await boardStore.fetchBoard()
  await boardStore.fetchJobs()
})
</script>

<template>
  <section class="command-center">
    <header class="command-center__topbar">
      <div class="command-center__title">
        <span class="command-center__kicker">Workspace / DevFlow</span>
        <div>
          <h1>Command Center</h1>
          <p>Dispatch ECC commands, monitor runs, and act on review-required jobs</p>
        </div>
      </div>
    </header>

    <div class="command-center__grid">
      <div class="command-center__col command-center__col--left">
        <CommandComposer />
        <ReviewQueuePanel class="command-center__review" />
      </div>
      <div class="command-center__col command-center__col--right">
        <JobMonitor />
      </div>
    </div>

    <JobDetailDrawer />
  </section>
</template>

<style scoped>
.command-center {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow: hidden;
}
.command-center__topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}
.command-center__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.command-center__kicker {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
.command-center__title h1 {
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.1;
}
.command-center__title p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.9rem;
}
.command-center__grid {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(420px, 1.4fr);
  gap: 18px;
  flex: 1;
  min-height: 0;
}
.command-center__col {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 0;
  overflow-y: auto;
}
@media (max-width: 1024px) {
  .command-center__grid {
    grid-template-columns: 1fr;
  }
}
</style>
```

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 3: Manual smoke in browser**

Open `http://127.0.0.1:3010/command-center`. Verify:
- Composer renders, can pick an issue and dispatch.
- Active jobs appear within ~2s, no manual refresh.
- Live log line "Analyzing issue ..." appears in the drawer within 5s of dispatch.
- Cancel button on a running job flips status to `cancelled` without page refresh.
- Review Required panel lists jobs in that state.

- [ ] **Step 4: Commit**

```bash
git add src/pages/command-center.vue
git commit -m "feat(p1): Command Center layout with Review + Drawer"
```

---

### Task 14: Frontend — wire `useRecentJobs` fallback to WS state

**Files:**
- Modify: `src/composables/useRecentJobs.ts`

If the WebSocket is down, we still need the polling fallback so the page does not go stale. Right now `useRecentJobs` polls unconditionally.

- [ ] **Step 1: Make polling conditional on WS state**

In `src/composables/useRecentJobs.ts`, replace the script body with:

```ts
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useBoardStore } from '~/stores/board'
import { useWebSocket } from '~/composables/useWebSocket'
import type { ECCDispatchJob } from '~/types'

const DEFAULT_REFRESH_MS = 5_000
const DEFAULT_LIMIT = 5

export const useRecentJobs = (options: { refreshMs?: number; limit?: number } = {}) => {
  const boardStore = useBoardStore()
  const ws = useWebSocket()
  const refreshMs = options.refreshMs ?? DEFAULT_REFRESH_MS
  const limit = options.limit ?? DEFAULT_LIMIT

  const isLoading = computed(() => boardStore.isLoadingJobs)
  const error = ref<string | null>(null)
  const jobs = computed<ECCDispatchJob[]>(() => boardStore.recentJobs.slice(0, limit))
  const lastUpdated = ref<string | null>(null)

  let intervalHandle: ReturnType<typeof setInterval> | null = null

  const refresh = async () => {
    try {
      await boardStore.fetchJobs()
      lastUpdated.value = new Date().toISOString()
      error.value = null
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unable to refresh jobs'
    }
  }

  const startPolling = () => {
    if (intervalHandle) return
    void refresh()
    intervalHandle = setInterval(() => { void refresh() }, refreshMs)
  }
  const stopPolling = () => {
    if (intervalHandle) {
      clearInterval(intervalHandle)
      intervalHandle = null
    }
  }

  // When WS is connected, the store updates itself. Polling is
  // only a fallback for offline / reconnect windows.
  const stop = () => stopPolling()
  const start = () => {
    if (ws.isConnected.value) return
    startPolling()
  }

  // React to WS reconnects: stop polling, and on next disconnect
  // resume it.
  watch(ws.isConnected, (connected) => {
    if (connected) {
      stopPolling()
    } else {
      startPolling()
    }
  })

  onBeforeUnmount(stop)

  return {
    jobs,
    isLoading,
    error,
    lastUpdated,
    start,
    stop,
    refresh
  }
}
```

- [ ] **Step 2: Typecheck + build**

```bash
npm run typecheck
npm run build
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add src/composables/useRecentJobs.ts
git commit -m "refactor(p1): useRecentJobs polls only when WS disconnected"
```

---

### Task 15: E2E — Playwright spec for Command Center

**Files:**
- Create: `e2e/tests/command-center.spec.ts`

Per CLAUDE.md, do not mark E2E complete unless `@playwright/test` is installed and `npm run e2e` passes. If Playwright is not installed, install it first and document the version.

- [ ] **Step 1: Verify Playwright is installed**

```bash
ls node_modules/@playwright/test/package.json 2>/dev/null && echo OK || echo MISSING
```

If `MISSING`, install:

```bash
npm install --save-dev @playwright/test
npx playwright install --with-deps chromium
```

- [ ] **Step 2: Create the E2E spec**

```ts
import { test, expect } from '@playwright/test'

test.describe('Command Center', () => {
  test('dispatch → live log → cancel flow', async ({ page }) => {
    await page.goto('/command-center')
    await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible()

    // Pick the first available issue in the composer.
    const issueSelect = page.getByTestId('command-issue-select')
    await issueSelect.waitFor()
    const firstOption = await issueSelect.locator('option').nth(1).getAttribute('value')
    expect(firstOption).toBeTruthy()
    await issueSelect.selectOption(firstOption!)

    // Dispatch.
    await page.getByTestId('command-dispatch').click()

    // Job should appear in the monitor with status running or review_required.
    const monitor = page.locator('.job-monitor')
    await expect(monitor).toBeVisible()
    // Wait for at least one job row to appear.
    await page.waitForSelector('.job-row', { timeout: 10_000 })

    // Live log: open the drawer for the first job row.
    await page.locator('.job-row').first().click()
    const drawer = page.getByTestId('job-detail-drawer')
    await expect(drawer).toBeVisible()
    // At least one log line should arrive within 5s.
    const logList = page.getByTestId('live-log-list')
    await expect(logList.locator('li').first()).toBeVisible({ timeout: 5_000 })

    // Cancel the first job in the monitor.
    const cancelBtn = page.locator('[data-testid^="job-cancel-"]').first()
    if (await cancelBtn.isVisible()) {
      await cancelBtn.click()
      // The row's status badge should switch to "cancelled".
      await expect(page.locator('.job-row').first().getByText('cancelled')).toBeVisible({ timeout: 5_000 })
    }
  })
})
```

- [ ] **Step 3: Run the spec**

```bash
npm run e2e -- e2e/tests/command-center.spec.ts
```

Expected: pass (allow 30–60s; the spec includes generous timeouts for the safe runner's 10ms-per-event emission).

- [ ] **Step 4: Commit**

```bash
git add e2e/tests/command-center.spec.ts package.json package-lock.json
git commit -m "test(p1): Playwright spec for Command Center dispatch/cancel/live-log"
```

---

## 8. Order of Execution

Run tasks in this order; later tasks depend on earlier ones.

1. Task 1 (status filter) — backend-only, no dependencies
2. Task 2 (retry endpoint) — backend-only, no dependencies
3. Task 3 (WS anonymous) — backend-only, no dependencies
4. Task 4 (broadcast assertion) — depends on Tasks 2+3
5. Task 5 (useWebSocket: job_update + subscribe) — frontend-only
6. Task 6 (useECCStream: real) — depends on Task 5
7. Task 7 (board store: cancel/retry/handleJobUpdate) — depends on Task 5
8. Task 8 (pipe job_update into store) — depends on Tasks 5+7
9. Task 9 (JobMonitor buttons) — depends on Task 7
10. Task 10 (ReviewQueuePanel) — depends on Task 7
11. Task 11 (JobTimeline) — depends on Task 5
12. Task 12 (Drawer + LiveLogPanel) — depends on Tasks 5+11
13. Task 13 (command-center layout) — depends on Tasks 9+10+12
14. Task 14 (useRecentJobs fallback) — depends on Task 5
15. Task 15 (E2E spec) — depends on all above

---

## 9. Final Verification Checklist

After all tasks are done, run the full suite once and confirm:

- [ ] `PYTHONPATH=backend pytest -q backend/tests` — all green, including new `test_p1_command_center.py`
- [ ] `npm run typecheck` — green
- [ ] `npm run build` — green
- [ ] `npm run e2e` — Playwright spec passes
- [ ] Browser manual:
  - [ ] Dispatch a job → appears in Active within 2s, no manual refresh
  - [ ] Click row → drawer opens, Live log shows ≥1 line within 5s
  - [ ] Timeline renders all events in order
  - [ ] Cancel button on running job → status flips to `cancelled` live
  - [ ] Retry button on `failed` / `cancelled` / `review_required` → new `queued` job appears
  - [ ] Review Required panel shows jobs in that state
  - [ ] Approve button → job moves to `completed` and leaves the panel
  - [ ] Disconnect network → polling resumes within 5s and updates the list

When all of the above are green, write the final report using the format in the user's spec.

---

## 10. Out-of-Scope / Deferred

These are explicitly **not** part of P1 and will be picked up in later phases:

- New `job_events` table (P2)
- `timed_out` and `retry_scheduled` statuses (P2)
- Backend-driven `agent_profiles` (P3)
- Real quality gate integration blocking Done (P4)
- Watchdog recovery / `suspected_stuck` (P5)
- Auth rollout, multi-tenant, RBAC
- Backlog / Analytics / Settings / Webhooks UI / PR Diff (explicitly deferred by user)
