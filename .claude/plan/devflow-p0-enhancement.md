# DevFlow P0.5 Enhancement Plan

## Task Type
- [x] Frontend (→ Gemini)
- [x] Backend (→ Codex)
- [ ] Fullstack (→ Parallel)

## Context Summary

### Current State
- **Board API** returns 8 seed issues across 5 columns (backlog:2, in_progress:2, blocked:1, human_review:1, done:2)
- **ECC dispatch** creates job in `queued` status, safe runner runs in background producing events
- **Frontend IssueDetail** has ECC Logs tab but shows empty state because `issue.eccLogs` is never populated
- **Sidebar Recent Jobs** fetches from `/api/v1/ecc/jobs` but no auto-refresh after dispatch
- **Job persistence** `_save_job_to_db()` is `pass` - events not saved to DB
- **All 15 backend tests pass** when run correctly (`python3 -m pytest backend/tests`)

### Root Causes
1. Frontend `boardStore.moveIssueWithUnlock()` calls dispatch but doesn't fetch job events after
2. Backend job events exist only in memory `_jobs` dict, not persisted
3. No WebSocket subscription in frontend to receive job updates
4. `IssueDetail` reads `issue.eccLogs` which is never populated from job events

## Technical Solution

### Phase 1: Backend - Job Event Persistence & WebSocket Broadcast

**Problem**: Events produced by safe runner exist only in memory. Frontend can't see them.

**Solution**: Persist job events to SQLite and broadcast via WebSocket so frontend can subscribe and receive updates.

1. Implement `_save_job_to_db()` properly using `async_session.run_sync()` to avoid greenlet issue
2. Broadcast job events via WebSocket in `_broadcast_job_update()`
3. Frontend subscribes to job-specific WebSocket channel after dispatch

### Phase 2: Frontend - Job Event Sync & Auto-Refresh

**Problem**: `IssueDetail.eccLogs` is empty even though backend produces events.

**Solution**:
1. After dispatch, frontend subscribes to WebSocket for job updates
2. When job updates arrive, populate `issue.eccLogs` from job events
3. Sidebar Recent Jobs polls or subscribes to update when new jobs appear

## Implementation Steps

### Step 1: Implement `_save_job_to_db()` properly

**File**: `backend/api/v1/endpoints/ecc.py`

```python
async def _save_job_to_db(job: ECCDispatchJob) -> None:
    """Persist job state to SQLite database."""
    try:
        from db.database import AsyncSessionLocal, ensure_db_init
        from db.models import JobModel
        await ensure_db_init()

        # Check if job exists (update) or new (insert)
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(JobModel).where(JobModel.id == job.id)
            )
            existing = result.scalar_one_or_none()

            # Serialize events
            events_data = [e.model_dump() for e in job.events]

            if existing:
                # Update
                existing.status = job.status
                existing.message = job.message
                existing.updated_at = job.updated_at
                existing.events = events_data
            else:
                # Insert
                job_model = JobModel(
                    id=job.id,
                    issue_id=job.issue_id,
                    issue_key=job.issue_key,
                    command=job.command,
                    profile=job.profile,
                    harness=job.harness,
                    status=job.status,
                    message=job.message,
                    events=events_data,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                )
                session.add(job_model)

            await session.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to save job to DB: {e}")
```

**Key change**: Use `await session.run_sync()` if needed for any blocking operations. Events JSON serialization must handle `ECCJobEvent` objects.

### Step 2: Verify safe runner WebSocket broadcast

**File**: `backend/api/v1/endpoints/ecc.py`

The `_broadcast_job_update()` already calls `job_manager.broadcast_to_job()`. Verify the WebSocket subscription model works:

```python
# In _broadcast_job_update:
await job_manager.broadcast_to_job(job_id, {
    "type": "job_update",
    "job": job_data  # job.model_dump()
})
```

**Verification**: Add test that dispatch produces job events in `_jobs` dict and events are broadcastable.

### Step 3: Frontend WebSocket subscription after dispatch

**File**: `src/composables/useECCStream.ts`

Current `useECCStream` simulates SSE. We need actual WebSocket subscription:

```typescript
// After dispatch, subscribe to job-specific channel
async subscribeToJob(jobId: string) {
  const wsUrl = `${this.config.public.apiBase.replace('http', 'ws')}/ws/ecc/jobs`
  this.ws = new WebSocket(`${wsUrl}?token=${this.getToken()}`)

  this.ws.onopen = () => {
    this.ws?.send(JSON.stringify({
      type: 'subscribe',
      job_id: jobId
    }))
  }

  this.ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'job_update') {
      this.handleJobUpdate(data.job)
    }
  }
}

handleJobUpdate(job: ECCDispatchJob) {
  // Update board store with job info
  // Populate issue.eccLogs from job.events
  // Update issue.eccJobStatus, .eccJobMessage, .eccJobUpdatedAt
}
```

### Step 4: Populate IssueDetail.eccLogs from job events

**File**: `src/stores/board.ts`

When job update arrives via WebSocket:

```typescript
updateIssueFromJob(job: ECCDispatchJob) {
  // Find issue by issue_id
  const issue = this.columns
    .flatMap(c => c.issues)
    .find(i => i.id === job.issue_id)

  if (issue) {
    issue.eccJobId = job.id
    issue.eccJobStatus = job.status
    issue.eccJobMessage = job.message
    issue.eccJobUpdatedAt = job.updated_at

    // Map job.events to issue.eccLogs
    issue.eccLogs = job.events.map(e => ({
      id: crypto.randomUUID(),
      phase: this.inferPhaseFromEvent(e),
      timestamp: e.timestamp,
      content: e.message,
      confidence: e.status === 'review_required' ? 0.95 : 0.75
    }))
  }
}
```

### Step 5: Sidebar Recent Jobs auto-refresh

**File**: `src/components/sidebar/Sidebar.vue`

```typescript
// Poll every 5 seconds or subscribe to /ws/ecc/jobs
const refreshJobs = async () => {
  const { data } = await useFetch(`${config.public.apiBase}/ecc/jobs`)
  if (data.value) {
    recentJobs.value = data.value.jobs.slice(0, 10)
  }
}

// Auto-refresh
let interval: ReturnType<typeof setInterval>
onMounted(() => {
  refreshJobs()
  interval = setInterval(refreshJobs, 5000)
})
onUnmounted(() => clearInterval(interval))
```

### Step 6: Backend test for job lifecycle

**File**: `backend/tests/test_api_smoke.py`

```python
def test_ecc_job_lifecycle_produces_events():
    """Test that dispatch produces job events visible via API."""
    response = client.post("/api/v1/ecc/dispatch", json={
        "issue_id": "issue-test",
        "issue_key": "DEV-TEST",
        "command": "/loop-start --profile=frontend",
        "profile": "frontend",
        "harness": "claude-code",
    })
    assert response.status_code == 200
    job_id = response.json()["id"]

    # Wait for safe runner to complete (100ms delays * 4 events = ~500ms)
    import time; time.sleep(1)

    # Fetch job and verify events
    job_response = client.get(f"/api/v1/ecc/jobs/{job_id}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert len(job["events"]) >= 4  # 4 safe runner events
    assert job["status"] == "review_required"
```

## Key Files

| File | Operation | Description |
|------|-----------|-------------|
| `backend/api/v1/endpoints/ecc.py:161-166` | Modify | Implement `_save_job_to_db()` with proper async handling |
| `backend/api/v1/endpoints/ecc.py:72-84` | Verify | `_broadcast_job_update()` already broadcasts |
| `src/composables/useECCStream.ts` | Modify | Add WebSocket subscription for job updates |
| `src/stores/board.ts` | Modify | `updateIssueFromJob()` to populate eccLogs from job events |
| `src/components/sidebar/Sidebar.vue` | Modify | Auto-refresh Recent Jobs every 5s |
| `backend/tests/test_api_smoke.py` | Add | `test_ecc_job_lifecycle_produces_events()` |

## Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| aiosqlite greenlet issue persists | Use `await conn.run_sync()` if sync access needed; keep as `pass` fallback if DB fails |
| WebSocket connection fails | Fallback to polling `/api/v1/ecc/jobs/{job_id}` every 2s after dispatch |
| Frontend job subscription race | Wait 500ms after dispatch before subscribing |
| Events not deserialized properly | Ensure `ECCJobEvent(**dict)` works in `load_jobs_from_db()` |

## SESSION_ID (for /ccg:execute use)
- CODEX_SESSION: N/A (analyzer prompt not used - this is plan synthesis)
- GEMINI_SESSION: N/A (analyzer prompt not used - this is plan synthesis)

## Validation Commands

After implementation:

```bash
# Backend tests
python3 -m pytest backend/tests -v

# Frontend typecheck and build
npm run typecheck && npm run build

# Manual verification
# 1. Start backend: python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
# 2. Start frontend: npm run dev
# 3. Open http://127.0.0.1:3010
# 4. Drag any card to "In Progress"
# 5. Click the card to open IssueDetail
# 6. Check ECC Logs tab - should show 4 events from safe runner
# 7. Check Sidebar Recent Jobs - should show the new job
```