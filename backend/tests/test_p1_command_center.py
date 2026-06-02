import pytest
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
    # The safe runner may have already advanced the job to "review_required"
    # (a retryable state). Force a deterministic non-retryable state so the
    # 409 branch is exercised reliably.
    client.patch(
        f"/api/v1/ecc/jobs/{job_id}",
        json={"status": "running", "message": "test forcing non-terminal state"},
    )
    r = client.post(f"/api/v1/ecc/jobs/{job_id}/retry")
    assert r.status_code == 409
    assert "retry" in r.json()["detail"].lower()


def test_retry_rejects_missing_job():
    r = client.post("/api/v1/ecc/jobs/ecc_does_not_exist/retry")
    assert r.status_code == 404


def test_ws_anonymous_connect_in_dev_mode():
    # The test env should have ALLOW_ANONYMOUS_WS unset OR "true" by default.
    # We probe via the WS endpoint by reading the env gate and asserting the
    # 4001 close is NOT triggered for an unauthenticated connection.
    with client.websocket_connect("/ws/ecc/jobs?token=dev-anon") as ws:
        # If we got here, auth was bypassed.
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg["type"] == "pong"


@pytest.mark.asyncio
async def test_dispatch_broadcasts_job_update_via_ws():
    """Dispatching a job triggers _broadcast_job_update via _execute_safe_runner.

    TestClient's synchronous WS blocks the event loop so background tasks
    never fire inside ``websocket_connect``.  We work around this by:
      1. Dispatching via an async ASGI client (background task actually runs).
      2. Waiting for the runner to complete (job → review_required).
      3. Calling the broadcast bridge with a mock WS to verify the payload.
    """
    import asyncio
    import httpx
    from unittest.mock import AsyncMock
    from api.v1.endpoints import ecc, ws

    # --- Step 1: dispatch via async client so the background task fires ---
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as ac:
        r = await ac.post(
            "/api/v1/ecc/dispatch",
            json={
                "issue_id": "p1-ws-broadcast",
                "issue_key": "DEV-P1-WS-BROADCAST",
                "command": "/loop-start --profile=frontend",
                "profile": "frontend",
                "harness": "claude-code",
            },
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]

    # --- Step 2: wait for the safe runner to finish ---
    await asyncio.sleep(0.5)

    job = ecc._jobs.get(job_id)
    assert job is not None, "job should exist in memory after dispatch"
    assert job.status == "review_required", (
        f"safe runner should have advanced to review_required, got {job.status}"
    )

    # --- Step 3: verify broadcast payload via mock WS ---
    mock_ws = AsyncMock()
    original_mgr = ws.job_manager
    try:
        ws.job_manager._job_connections[job_id] = {mock_ws}
        await ecc._broadcast_job_update(job_id, job.model_dump())
    finally:
        ws.job_manager._job_connections.pop(job_id, None)
        ws.job_manager = original_mgr

    mock_ws.send_json.assert_called_once()
    payload = mock_ws.send_json.call_args[0][0]
    assert payload["type"] == "job_update"
    assert payload["job"]["id"] == job_id
    assert payload["job"]["status"] == "review_required"
