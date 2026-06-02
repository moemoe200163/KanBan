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
