from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_get_lanes_returns_eight_lanes():
    response = client.get("/api/v1/lanes")
    assert response.status_code == 200
    body = response.json()
    assert "lanes" in body
    keys = {lane["key"] for lane in body["lanes"]}
    assert keys == {
        "triage", "product", "architect", "frontend",
        "backend", "qa", "review", "delivery",
    }
    # every lane exposes the fields the Lane Matrix needs
    for lane in body["lanes"]:
        assert "displayName" in lane
        assert "defaultProvider" in lane
        assert "defaultModel" in lane
        assert "requiredCompletionFields" in lane
        assert "humanApprovalRequired" in lane
