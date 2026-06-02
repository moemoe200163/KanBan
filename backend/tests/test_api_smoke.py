from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_health_and_ready_checks():
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_ecc_dispatch_accepts_valid_control_plane_job():
    response = client.post(
        "/api/v1/ecc/dispatch",
        json={
            "issue_id": "issue-1",
            "issue_key": "DEV-001",
            "command": "/loop-start --profile=frontend",
            "profile": "frontend",
            "harness": "codex",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("ecc_")
    assert body["status"] == "queued"
    assert body["events"][0]["status"] == "queued"


def test_ecc_job_lifecycle_can_be_updated_and_cancelled():
    response = client.post(
        "/api/v1/ecc/dispatch",
        json={
            "issue_id": "issue-2",
            "issue_key": "DEV-002",
            "command": "/loop-start --profile=backend",
            "profile": "backend",
            "harness": "claude-code",
        },
    )
    job_id = response.json()["id"]

    update = client.patch(
        f"/api/v1/ecc/jobs/{job_id}",
        json={"status": "review_required", "message": "Quality gate waiting for human review"},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "review_required"
    assert update.json()["message"] == "Quality gate waiting for human review"

    cancel = client.post(f"/api/v1/ecc/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_issue_status_contract_matches_frontend_workflow():
    response = client.get("/api/v1/issues", params={"status": "review"})

    assert response.status_code == 400
    assert "human_review" in response.json()["detail"]


def test_ecc_job_lifecycle_produces_events():
    """Dispatch + safe runner must populate the in-memory job with events
    so the frontend can render ECC Logs after polling /api/v1/ecc/jobs/{id}.
    """
    response = client.post(
        "/api/v1/ecc/dispatch",
        json={
            "issue_id": "issue-lifecycle",
            "issue_key": "DEV-LIFECYCLE",
            "command": "/loop-start --profile=frontend",
            "profile": "frontend",
            "harness": "claude-code",
        },
    )
    assert response.status_code == 200
    job_id = response.json()["id"]

    # Safe runner emits queued + running transitions + 4 inner events + final.
    # The BackgroundTask finishes well within 1s on the test client.
    import time
    time.sleep(1)

    job_response = client.get(f"/api/v1/ecc/jobs/{job_id}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert len(job["events"]) >= 4, f"expected >=4 events, got {len(job['events'])}"
    assert job["status"] == "review_required"
