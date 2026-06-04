"""Tests for the Orchestrator module and runtime write APIs.

Covers:
- Orchestrator: create_run_for_dispatch creates pending run
- Orchestrator: claim_next_run atomically claims oldest pending run
- Orchestrator: start_run transitions to running
- Orchestrator: complete_run transitions to completed
- Orchestrator: fail_run transitions to failed
- Orchestrator: cancel_run transitions to cancelled
- Orchestrator: get_worker_stats returns correct counts
- API: POST /runtime/workers registers worker
- API: POST /runtime/workers/{id}/heartbeat updates heartbeat
- API: POST /runtime/runs/claim claims next run
- API: POST /runtime/runs/{id}/start transitions to running
- API: POST /runtime/runs/{id}/complete transitions to completed
- API: POST /runtime/runs/{id}/fail transitions to failed
- API: state machine enforcement (can't start non-claimed run, etc.)
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database, repository as repo
from db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    db_path = tmp_path / "test_orchestrator.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(database, "engine", new_engine, raising=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(database, "_db_initialized", False, raising=False)
    monkeypatch.setattr(database, "DATABASE_URL", new_url, raising=False)

    async def _init():
        pass
    monkeypatch.setattr(database, "ensure_db_init", _init, raising=False)

    import asyncio

    async def _init_db():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init_db())
    database._db_initialized = True

    yield new_engine

    loop.run_until_complete(new_engine.dispose())
    loop.close()


@pytest.fixture()
def api_client(fresh_db):
    """FastAPI TestClient with isolated DB."""
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Orchestrator — create_run_for_dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_run_for_dispatch(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch

    run = await create_run_for_dispatch(
        board_id="board-default",
        issue_id="iss-1",
        issue_key="DEV-001",
        command="/loop-start",
        profile="backend",
        harness="claude-code",
    )
    assert run["status"] == "pending"
    assert run["issueKey"] == "DEV-001"
    assert run["harness"] == "claude-code"
    assert run["boardId"] == "board-default"


# ---------------------------------------------------------------------------
# Orchestrator — claim_next_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_next_run(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(
        board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/loop-start",
    )

    claimed = await claim_next_run("wk-1", "board-default")
    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["workerId"] == "wk-1"


@pytest.mark.asyncio
async def test_claim_next_run_fifo_order(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd1")
    await create_run_for_dispatch(board_id="board-default", issue_id="i2", issue_key="DEV-002", command="/cmd2")

    claimed = await claim_next_run("wk-1", "board-default")
    assert claimed["issueKey"] == "DEV-001"  # first created = first claimed


@pytest.mark.asyncio
async def test_claim_next_run_no_pending(fresh_db):
    from core.runtime.orchestrator import claim_next_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    claimed = await claim_next_run("wk-1", "board-default")
    assert claimed is None


@pytest.mark.asyncio
async def test_claim_next_run_board_isolation(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run

    await repo.upsert_worker(id="wk-a", board_id="board-a", worker_type="claude-code")
    await repo.upsert_worker(id="wk-b", board_id="board-b", worker_type="claude-code")
    await create_run_for_dispatch(board_id="board-a", issue_id="i1", issue_key="A-001", command="/cmd")
    await create_run_for_dispatch(board_id="board-b", issue_id="i2", issue_key="B-001", command="/cmd")

    claimed_a = await claim_next_run("wk-a", "board-a")
    assert claimed_a["issueKey"] == "A-001"

    claimed_b = await claim_next_run("wk-b", "board-b")
    assert claimed_b["issueKey"] == "B-001"


# ---------------------------------------------------------------------------
# Orchestrator — start_run / complete_run / fail_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_run(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd")
    await claim_next_run("wk-1", "board-default")

    started = await start_run(run["id"], "wk-1")
    assert started["status"] == "running"


@pytest.mark.asyncio
async def test_complete_run(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd")
    await claim_next_run("wk-1", "board-default")
    await start_run(run["id"], "wk-1")

    completed = await complete_run(run["id"], "wk-1", result_summary="All tests passed")
    assert completed["status"] == "completed"
    assert completed["resultSummary"] == "All tests passed"

    # Worker should be idle
    worker = await repo.get_worker("wk-1")
    assert worker["status"] == "idle"
    assert worker["activeRunId"] is None


@pytest.mark.asyncio
async def test_fail_run(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, fail_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd")
    await claim_next_run("wk-1", "board-default")
    await start_run(run["id"], "wk-1")

    failed = await fail_run(run["id"], "wk-1", error_message="API timeout")
    assert failed["status"] == "failed"
    assert failed["errorMessage"] == "API timeout"

    # Worker should be idle with error
    worker = await repo.get_worker("wk-1")
    assert worker["status"] == "idle"


@pytest.mark.asyncio
async def test_cancel_run(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, cancel_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd")
    await claim_next_run("wk-1", "board-default")

    cancelled = await cancel_run(run["id"], "wk-1")
    assert cancelled["status"] == "cancelled"

    worker = await repo.get_worker("wk-1")
    assert worker["status"] == "idle"


# ---------------------------------------------------------------------------
# Orchestrator — stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_stats(fresh_db):
    from core.runtime.orchestrator import get_worker_stats

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code", status="idle")
    await repo.upsert_worker(id="wk-2", board_id="board-default", worker_type="codex", status="running")
    await repo.upsert_worker(id="wk-3", board_id="board-b", worker_type="claude-code", status="idle")

    stats = await get_worker_stats("board-default")
    assert stats["total"] == 2
    assert stats["byStatus"]["idle"] == 1
    assert stats["byStatus"]["running"] == 1


# ---------------------------------------------------------------------------
# Run events are appended during lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_events_during_lifecycle(fresh_db):
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    await repo.upsert_worker(id="wk-1", board_id="board-default", worker_type="claude-code")
    run = await create_run_for_dispatch(board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd")
    await claim_next_run("wk-1", "board-default")
    await start_run(run["id"], "wk-1")
    await complete_run(run["id"], "wk-1", result_summary="done")

    events = await repo.list_run_events(run["id"])
    # claim + start + complete = 3 events
    assert len(events) == 3
    assert events[0]["eventType"] == "status_change"  # claimed
    assert events[1]["eventType"] == "status_change"  # started
    assert events[2]["eventType"] == "status_change"  # completed


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestWorkerAPI:
    def test_register_worker(self, api_client):
        resp = api_client.post("/api/v1/runtime/workers", json={
            "worker_id": "wk-api-1",
            "worker_type": "claude-code",
            "board_id": "board-default",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wk-api-1"
        assert data["status"] == "idle"

    def test_heartbeat(self, api_client):
        api_client.post("/api/v1/runtime/workers", json={
            "worker_id": "wk-hb", "worker_type": "codex",
        })
        resp = api_client.post("/api/v1/runtime/workers/wk-hb/heartbeat", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["lastHeartbeatAt"] is not None

    def test_heartbeat_not_found(self, api_client):
        resp = api_client.post("/api/v1/runtime/workers/nonexistent/heartbeat", json={})
        assert resp.status_code == 404

    def test_list_workers(self, api_client):
        api_client.post("/api/v1/runtime/workers", json={
            "worker_id": "wk-list", "worker_type": "claude-code",
        })
        resp = api_client.get("/api/v1/runtime/workers?board_id=board-default")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


class TestRunLifecycleAPI:
    def test_claim_no_workers(self, api_client):
        resp = api_client.post("/api/v1/runtime/runs/claim", json={
            "board_id": "board-default",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"] is None
        assert "No idle workers" in data["message"]

    def test_claim_no_runs(self, api_client):
        api_client.post("/api/v1/runtime/workers", json={
            "worker_id": "wk-nor", "worker_type": "claude-code",
        })
        resp = api_client.post("/api/v1/runtime/runs/claim", json={
            "board_id": "board-default",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"] is None
        assert "No pending runs" in data["message"]

    def test_full_lifecycle_via_api(self, api_client):
        # Register worker
        api_client.post("/api/v1/runtime/workers", json={
            "worker_id": "wk-lc", "worker_type": "claude-code",
        })

        # Create a run via orchestrator
        import asyncio
        loop = asyncio.new_event_loop()
        from core.runtime.orchestrator import create_run_for_dispatch
        run = loop.run_until_complete(create_run_for_dispatch(
            board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd",
        ))
        loop.close()

        # Claim
        resp = api_client.post("/api/v1/runtime/runs/claim", json={
            "board_id": "board-default",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"]["status"] == "claimed"
        run_id = data["run"]["id"]

        # Start
        resp = api_client.post(f"/api/v1/runtime/runs/{run_id}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

        # Complete
        resp = api_client.post(f"/api/v1/runtime/runs/{run_id}/complete", json={
            "result_summary": "All good",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_start_non_claimed_fails(self, api_client):
        import asyncio
        loop = asyncio.new_event_loop()
        from core.runtime.orchestrator import create_run_for_dispatch
        run = loop.run_until_complete(create_run_for_dispatch(
            board_id="board-default", issue_id="i1", issue_key="DEV-001", command="/cmd",
        ))
        loop.close()

        resp = api_client.post(f"/api/v1/runtime/runs/{run['id']}/start")
        assert resp.status_code == 409
        assert "claimed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Pipeline: run completion syncs ECC job status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_run_syncs_ecc_job_to_review_required(fresh_db):
    """When a run completes, the linked ECC job status moves to review_required."""
    from datetime import datetime, timezone
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    now = datetime.now(timezone.utc).isoformat()

    # Seed a job
    await repo.upsert_job({
        "id": "job-pipe-1",
        "issue_id": "iss-pipe",
        "issue_key": "DEV-PIPE-1",
        "command": "implement",
        "profile": "backend",
        "harness": "safe-runner",
        "board_id": "board-default",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "events": [],
    })

    # Create a run linked to the job
    await repo.upsert_worker(id="wk-pipe", board_id="board-default", worker_type="safe-runner")
    run = await create_run_for_dispatch(
        board_id="board-default",
        issue_id="iss-pipe",
        issue_key="DEV-PIPE-1",
        command="implement",
        harness="safe-runner",
        job_id="job-pipe-1",
    )
    assert run["jobId"] == "job-pipe-1"

    # Claim → start → complete (real orchestrator, not mocked)
    await claim_next_run("wk-pipe", "board-default")
    await start_run(run["id"], "wk-pipe")
    completed = await complete_run(run["id"], "wk-pipe", result_summary="Implementation done")

    assert completed["status"] == "completed"

    # Verify the ECC job was synced
    job = await repo.get_job("job-pipe-1")
    assert job is not None
    assert job["status"] == "review_required"
    assert job["message"] == "Implementation done"
    # Events should include the status_change from the sync
    events = job.get("events", [])
    assert len(events) >= 1
    assert events[-1]["status"] == "review_required"
    assert "Implementation done" in events[-1]["message"]


@pytest.mark.asyncio
async def test_fail_run_syncs_ecc_job_to_failed(fresh_db):
    """When a run fails, the linked ECC job status moves to failed."""
    from datetime import datetime, timezone
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, fail_run

    now = datetime.now(timezone.utc).isoformat()

    # Seed a job
    await repo.upsert_job({
        "id": "job-pipe-2",
        "issue_id": "iss-pipe-2",
        "issue_key": "DEV-PIPE-2",
        "command": "test",
        "profile": "backend",
        "harness": "safe-runner",
        "board_id": "board-default",
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "events": [],
    })

    # Create a run linked to the job
    await repo.upsert_worker(id="wk-pipe-2", board_id="board-default", worker_type="safe-runner")
    run = await create_run_for_dispatch(
        board_id="board-default",
        issue_id="iss-pipe-2",
        issue_key="DEV-PIPE-2",
        command="test",
        harness="safe-runner",
        job_id="job-pipe-2",
    )

    # Claim → start → fail (real orchestrator)
    await claim_next_run("wk-pipe-2", "board-default")
    await start_run(run["id"], "wk-pipe-2")
    failed = await fail_run(run["id"], "wk-pipe-2", error_message="API timeout")

    assert failed["status"] == "failed"

    # Verify the ECC job was synced
    job = await repo.get_job("job-pipe-2")
    assert job is not None
    assert job["status"] == "failed"
    assert job["message"] == "API timeout"
    events = job.get("events", [])
    assert len(events) >= 1
    assert events[-1]["status"] == "failed"
    assert "API timeout" in events[-1]["message"]


@pytest.mark.asyncio
async def test_complete_run_without_job_id_skips_sync(fresh_db):
    """Run without a linked job completes normally (no sync attempted)."""
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    await repo.upsert_worker(id="wk-nojob", board_id="board-default", worker_type="safe-runner")
    run = await create_run_for_dispatch(
        board_id="board-default",
        issue_id="iss-nojob",
        issue_key="DEV-NOJOB",
        command="test",
        harness="safe-runner",
        # No job_id
    )
    assert run["jobId"] is None

    await claim_next_run("wk-nojob", "board-default")
    await start_run(run["id"], "wk-nojob")
    completed = await complete_run(run["id"], "wk-nojob", result_summary="ok")

    assert completed["status"] == "completed"
    # No crash, no job to sync


@pytest.mark.asyncio
async def test_pipeline_dispatch_to_review(fresh_db):
    """Full pipeline: dispatch → claim → start → complete → job review_required → approve."""
    from datetime import datetime, timezone
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    now = datetime.now(timezone.utc).isoformat()

    # 1. Seed a job in "queued" status
    await repo.upsert_job({
        "id": "job-full-pipe",
        "issue_id": "iss-full",
        "issue_key": "DEV-FULL",
        "command": "implement",
        "profile": "backend",
        "harness": "safe-runner",
        "board_id": "board-default",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "events": [],
    })

    # 2. Create run linked to job
    await repo.upsert_worker(id="wk-full", board_id="board-default", worker_type="safe-runner")
    run = await create_run_for_dispatch(
        board_id="board-default",
        issue_id="iss-full",
        issue_key="DEV-FULL",
        command="implement",
        harness="safe-runner",
        job_id="job-full-pipe",
    )

    # 3. Worker claims
    claimed = await claim_next_run("wk-full", "board-default")
    assert claimed["id"] == run["id"]
    assert claimed["status"] == "claimed"

    # 4. Worker starts
    started = await start_run(run["id"], "wk-full")
    assert started["status"] == "running"

    # 5. Worker completes
    completed = await complete_run(run["id"], "wk-full", result_summary="All tests passed")
    assert completed["status"] == "completed"

    # 6. Verify job synced to review_required
    job = await repo.get_job("job-full-pipe")
    assert job["status"] == "review_required"

    # 7. Verify run events
    events = await repo.list_run_events(run["id"])
    event_types = [e["eventType"] for e in events]
    assert "status_change" in event_types


# ---------------------------------------------------------------------------
# API layer: GET /ecc/jobs/{job_id} returns valid events after run sync
# ---------------------------------------------------------------------------

def test_get_ecc_job_after_run_complete_has_valid_events(api_client, fresh_db):
    """GET /api/v1/ecc/jobs/{id} returns 200 with ECCJobEvent-shaped events
    after a run completes and syncs the job status."""
    import asyncio
    from datetime import datetime, timezone
    from core.runtime.orchestrator import create_run_for_dispatch, claim_next_run, start_run, complete_run

    now = datetime.now(timezone.utc).isoformat()

    # Seed a job
    loop = asyncio.new_event_loop()
    loop.run_until_complete(repo.upsert_job({
        "id": "job-api-test",
        "issue_id": "iss-api",
        "issue_key": "DEV-API-1",
        "command": "implement",
        "profile": "backend",
        "harness": "safe-runner",
        "board_id": "board-default",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "events": [{"timestamp": now, "status": "queued", "message": "Job created"}],
    }))

    # Create + claim + start + complete run
    loop.run_until_complete(repo.upsert_worker(id="wk-api", board_id="board-default", worker_type="safe-runner"))
    run = loop.run_until_complete(create_run_for_dispatch(
        board_id="board-default", issue_id="iss-api", issue_key="DEV-API-1",
        command="implement", harness="safe-runner", job_id="job-api-test",
    ))
    loop.run_until_complete(claim_next_run("wk-api", "board-default"))
    loop.run_until_complete(start_run(run["id"], "wk-api"))
    loop.run_until_complete(complete_run(run["id"], "wk-api", result_summary="Done"))
    loop.close()

    # GET the job via API — should not crash on event parsing
    resp = api_client.get("/api/v1/ecc/jobs/job-api-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "review_required"

    # Events should be valid ECCJobEvent shape (timestamp, status, message)
    events = body["events"]
    assert len(events) >= 2
    # Last event should be the sync event
    last_event = events[-1]
    assert "status" in last_event
    assert "timestamp" in last_event
    assert "message" in last_event
    assert last_event["status"] == "review_required"
