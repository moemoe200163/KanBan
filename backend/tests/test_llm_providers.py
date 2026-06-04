"""Tests for enhanced LLM Provider API endpoints.

Covers:
- GET /providers (list)
- GET /providers/{id} (single)
- PUT /providers/{id}/config (update with DB persistence)
- POST /providers/{id}/test (health check)
- POST /providers/{id}/select (set active)
- GET /active (current provider)
- Auth enforcement on write endpoints
- API key never returned in full
"""

import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database, repository as repo
from db.models import Base
from core.llm import registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_registry_defaults():
    """Reset in-memory registry defaults before each test."""
    registry._defaults.update({
        "provider_id": "safe-runner",
        "model_id": "",
        "harness": "safe-runner",
        "max_runtime_seconds": "300",
        "token_budget": "",
        "cost_budget": "",
        "streaming_logs": "true",
    })
    yield


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test for full endpoint testing."""
    import asyncio
    from fastapi.testclient import TestClient
    import main

    db_path = tmp_path / "test_llm_providers.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(database, "engine", new_engine, raising=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(database, "_db_initialized", False, raising=False)
    monkeypatch.setattr(database, "DATABASE_URL", new_url, raising=False)

    # Create tables (use asyncio.run for Python 3.9 compat)
    async def _create_tables():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_create_tables())
    finally:
        loop.close()
    database._db_initialized = True

    # Use TestClient which runs the app lifespan (seeds data, etc.)
    client = TestClient(main.app)
    yield client

    # Cleanup
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(new_engine.dispose())
    finally:
        loop.close()


def _register_and_login(client) -> str:
    """Register a test user and return a JWT token."""
    # Register
    client.post("/api/v1/auth/register", json={
        "username": "llmtest",
        "password": "testpass123",
        "email": "llmtest@example.com",
    })
    # Login
    resp = client.post("/api/v1/auth/token", json={
        "username": "llmtest",
        "password": "testpass123",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. GET /providers returns list
# ---------------------------------------------------------------------------

def test_list_providers_returns_200(fresh_db):
    resp = fresh_db.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)
    assert len(body["providers"]) > 0


# ---------------------------------------------------------------------------
# 2. GET /providers/{id} returns provider
# ---------------------------------------------------------------------------

def test_get_provider_returns_200(fresh_db):
    resp = fresh_db.get("/api/v1/llm/providers/safe-runner")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "safe-runner"


# ---------------------------------------------------------------------------
# 3. GET /providers/{id} 404 for unknown
# ---------------------------------------------------------------------------

def test_get_provider_returns_404_for_unknown(fresh_db):
    resp = fresh_db.get("/api/v1/llm/providers/nonexistent-provider")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. PUT /config requires auth
# ---------------------------------------------------------------------------

def test_update_config_requires_auth(fresh_db):
    resp = fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"model": "MiniMax-M3"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. PUT /config updates DB
# ---------------------------------------------------------------------------

def test_update_config_updates_db(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"model": "MiniMax-M3-v2", "baseUrl": "https://custom.api.io/v1"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "MiniMax-M3-v2"
    assert body["baseUrl"] == "https://custom.api.io/v1"
    assert body["providerId"] == "minimax"

    # Verify via GET
    get_resp = fresh_db.get("/api/v1/llm/providers/minimax")
    assert get_resp.status_code == 200
    assert get_resp.json()["model"] == "MiniMax-M3-v2"


# ---------------------------------------------------------------------------
# 6. PUT /config encrypts API key
# ---------------------------------------------------------------------------

def test_update_config_encrypts_api_key(fresh_db):
    token = _register_and_login(fresh_db)
    test_key = "sk-test-1234567890abcdef"

    resp = fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"apiKey": test_key},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()

    # Full key must never appear in response
    assert test_key not in str(body)

    # Masked key should be present
    assert body.get("apiKeyPrefix") is not None
    assert body.get("apiKeyLast4") is not None
    assert len(body["apiKeyLast4"]) == 4

    # Verify encrypted value is stored in DB (not plaintext)
    import asyncio
    from db.repository import get_llm_provider_config

    loop = asyncio.new_event_loop()
    try:
        config = loop.run_until_complete(get_llm_provider_config("minimax"))
    finally:
        loop.close()
    # The DB row should have the encrypted key, not the plaintext
    # We can't check api_key_encrypted directly from to_dict (it's excluded),
    # but we can verify the mask matches
    assert config["apiKeyPrefix"] == test_key[:8]
    assert config["apiKeyLast4"] == test_key[-4:]


# ---------------------------------------------------------------------------
# 7. POST /test requires auth
# ---------------------------------------------------------------------------

def test_test_provider_requires_auth(fresh_db):
    resp = fresh_db.post("/api/v1/llm/providers/minimax/test")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. POST /test not_configured when no key
# ---------------------------------------------------------------------------

def test_test_provider_not_configured_without_key(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.post(
        "/api/v1/llm/providers/minimax/test",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_configured"
    assert body["ok"] is False
    assert body["safeError"] == "not_configured"
    assert body["provider"] == "minimax"


# ---------------------------------------------------------------------------
# 9. POST /test healthy (mocked health check)
# ---------------------------------------------------------------------------

def test_test_provider_healthy_with_mock(fresh_db):
    token = _register_and_login(fresh_db)

    # First configure the provider with a fake key and base URL
    fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={
            "apiKey": "sk-test-fake-key-for-mock",
            "baseUrl": "https://api.minimax.io/v1",
        },
        headers=_auth_header(token),
    )

    # Mock the health check to return healthy
    mock_result = {
        "status": "healthy",
        "ok": True,
        "latencyMs": 812,
        "message": "Provider responded successfully.",
        "safeError": None,
    }

    with patch("api.v1.endpoints.llm.run_health_check", new_callable=AsyncMock, return_value=mock_result):
        resp = fresh_db.post(
            "/api/v1/llm/providers/minimax/test",
            headers=_auth_header(token),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "minimax"
    assert body["status"] == "healthy"
    assert body["ok"] is True
    assert body["latencyMs"] == 812
    assert body["model"] == "MiniMax-M3"
    assert "checkedAt" in body
    assert body["safeError"] is None

    # Verify health was persisted to DB
    import asyncio
    from db.repository import get_llm_provider_config

    loop = asyncio.new_event_loop()
    try:
        config = loop.run_until_complete(get_llm_provider_config("minimax"))
    finally:
        loop.close()
    assert config["lastTestStatus"] == "healthy"
    assert config["lastLatencyMs"] == 812


# ---------------------------------------------------------------------------
# 10. POST /select requires auth
# ---------------------------------------------------------------------------

def test_select_provider_requires_auth(fresh_db):
    resp = fresh_db.post("/api/v1/llm/providers/minimax/select")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 11. POST /select sets active
# ---------------------------------------------------------------------------

def test_select_provider_sets_active(fresh_db):
    token = _register_and_login(fresh_db)

    resp = fresh_db.post(
        "/api/v1/llm/providers/minimax/select",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["providerId"] == "minimax"

    # Verify via defaults
    defaults = fresh_db.get("/api/v1/llm/defaults").json()
    assert defaults["providerId"] == "minimax"


# ---------------------------------------------------------------------------
# 12. GET /active returns current
# ---------------------------------------------------------------------------

def test_get_active_provider(fresh_db):
    token = _register_and_login(fresh_db)

    # Select minimax first
    fresh_db.post(
        "/api/v1/llm/providers/minimax/select",
        headers=_auth_header(token),
    )

    resp = fresh_db.get("/api/v1/llm/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["providerId"] == "minimax"
    assert "defaults" in body


# ---------------------------------------------------------------------------
# 13. API key never in response
# ---------------------------------------------------------------------------

def test_api_key_never_in_get_response(fresh_db):
    token = _register_and_login(fresh_db)

    # Configure with a known API key
    test_key = "sk-secret-api-key-12345678"
    fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"apiKey": test_key},
        headers=_auth_header(token),
    )

    # Check GET /providers (list)
    list_resp = fresh_db.get("/api/v1/llm/providers")
    assert list_resp.status_code == 200
    for provider in list_resp.json()["providers"]:
        provider_str = str(provider)
        assert test_key not in provider_str, f"Full API key found in list response for {provider.get('id')}"

    # Check GET /providers/minimax (single)
    single_resp = fresh_db.get("/api/v1/llm/providers/minimax")
    assert single_resp.status_code == 200
    single_str = str(single_resp.json())
    assert test_key not in single_str, "Full API key found in single provider response"

    # Check PUT /config response (should not contain full key)
    put_resp = fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"model": "MiniMax-M3"},
        headers=_auth_header(token),
    )
    assert put_resp.status_code == 200
    put_str = str(put_resp.json())
    assert test_key not in put_str, "Full API key found in PUT response"

    # Verify masked format
    single = single_resp.json()
    assert single.get("maskedSecret") is not None or single.get("apiKeyPrefix") is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_update_config_returns_404_for_unknown_provider(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.put(
        "/api/v1/llm/providers/nonexistent/config",
        json={"model": "test"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 404


def test_select_returns_404_for_unknown_provider(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.post(
        "/api/v1/llm/providers/nonexistent/select",
        headers=_auth_header(token),
    )
    assert resp.status_code == 404


def test_update_config_disabled(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.put(
        "/api/v1/llm/providers/minimax/config",
        json={"enabled": False},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Verify via GET
    get_resp = fresh_db.get("/api/v1/llm/providers/minimax")
    assert get_resp.json()["enabled"] is False


def test_defaults_requires_auth_for_update(fresh_db):
    resp = fresh_db.put(
        "/api/v1/llm/defaults",
        json={"providerId": "minimax"},
    )
    assert resp.status_code == 401


def test_defaults_update_and_get(fresh_db):
    token = _register_and_login(fresh_db)
    resp = fresh_db.put(
        "/api/v1/llm/defaults",
        json={"providerId": "minimax", "harness": "safe-runner"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["providerId"] == "minimax"

    get_resp = fresh_db.get("/api/v1/llm/defaults")
    assert get_resp.status_code == 200
    assert get_resp.json()["providerId"] == "minimax"


def test_list_provider_models(fresh_db):
    resp = fresh_db.get("/api/v1/llm/providers/openai/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["providerId"] == "openai"
    assert isinstance(body["models"], list)
    assert "gpt-4o" in body["models"]
