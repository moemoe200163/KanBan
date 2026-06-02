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
