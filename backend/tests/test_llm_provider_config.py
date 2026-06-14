"""Tests for LLMProviderConfig DB model and repository functions."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from db import database, repository as repo
from db.models import Base


@pytest_asyncio.fixture
async def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test using monkeypatch for clean teardown."""
    db_path = tmp_path / "test_llm.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(
        new_engine, class_=AsyncSession, expire_on_commit=False
    )

    monkeypatch.setattr(database, "engine", new_engine, raising=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(database, "_db_initialized", False, raising=False)
    monkeypatch.setattr(database, "DATABASE_URL", new_url, raising=False)

    async with new_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._db_initialized = True

    yield

    await new_engine.dispose()


@pytest.mark.asyncio
async def test_upsert_creates_new_config(fresh_db):
    result = await repo.upsert_llm_provider_config(
        provider_id="minimax",
        display_name="MiniMax",
        base_url="https://api.minimax.io/v1",
        endpoint_path="/chat/completions",
        api_shape="openai-chat",
        auth_type="bearer",
        model="MiniMax-M3",
    )
    assert result["providerId"] == "minimax"
    assert result["displayName"] == "MiniMax"
    assert result["baseUrl"] == "https://api.minimax.io/v1"
    assert result["model"] == "MiniMax-M3"
    # api_key_encrypted must never appear in to_dict
    assert "apiKeyEncrypted" not in result


@pytest.mark.asyncio
async def test_upsert_updates_existing(fresh_db):
    await repo.upsert_llm_provider_config(
        provider_id="openai", display_name="OpenAI", model="gpt-4o",
    )
    updated = await repo.upsert_llm_provider_config(
        provider_id="openai", display_name="OpenAI", model="gpt-4o-mini",
    )
    assert updated["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_upsert_with_api_key(fresh_db):
    result = await repo.upsert_llm_provider_config(
        provider_id="minimax",
        display_name="MiniMax",
        api_key_encrypted="encrypted-value",
        api_key_prefix="sk-cp-mO",
        api_key_last4="cLYY",
    )
    assert result["apiKeyPrefix"] == "sk-cp-mO"
    assert result["apiKeyLast4"] == "cLYY"
    # Encrypted key must NOT appear in to_dict
    assert "apiKeyEncrypted" not in result


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(fresh_db):
    result = await repo.get_llm_provider_config("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_returns_all(fresh_db):
    await repo.upsert_llm_provider_config(provider_id="a", display_name="A")
    await repo.upsert_llm_provider_config(provider_id="b", display_name="B")
    configs = await repo.list_llm_provider_configs()
    assert len(configs) == 2


@pytest.mark.asyncio
async def test_update_health(fresh_db):
    await repo.upsert_llm_provider_config(provider_id="minimax", display_name="MiniMax")
    result = await repo.update_llm_provider_health(
        "minimax", status="healthy", latency_ms=812,
    )
    assert result["lastTestStatus"] == "healthy"
    assert result["lastLatencyMs"] == 812
    assert result["lastTestAt"] is not None


@pytest.mark.asyncio
async def test_update_health_on_missing_returns_none(fresh_db):
    result = await repo.update_llm_provider_health("nonexistent", status="healthy")
    assert result is None


@pytest.mark.asyncio
async def test_seed_creates_defaults(fresh_db):
    count = await repo.seed_llm_provider_configs()
    assert count == 5
    configs = await repo.list_llm_provider_configs()
    ids = {c["providerId"] for c in configs}
    assert ids == {"minimax", "openai", "anthropic", "xiaomi", "ollama"}


@pytest.mark.asyncio
async def test_seed_idempotent(fresh_db):
    await repo.seed_llm_provider_configs()
    count = await repo.seed_llm_provider_configs()
    assert count == 0  # already seeded
