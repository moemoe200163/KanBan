"""Shared test fixtures for auth rollout."""
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from db.models import User as UserModel


async def seed_test_user(sessionmaker: async_sessionmaker) -> dict:
    """Create a test user and return auth headers for JWT auth.

    Returns {"Authorization": "Bearer <token>"} dict.
    """
    from api.v1.endpoints.auth import hash_password, create_jwt_token

    now = datetime.now(timezone.utc)
    async with sessionmaker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(UserModel).where(UserModel.username == "testuser")
        )
        existing = result.scalar_one_or_none()
        if not existing:
            pwd_hash, _ = hash_password("testpass123")
            session.add(UserModel(
                id="user_test_1",
                username="testuser",
                email="test@example.com",
                password_hash=pwd_hash,
                role="admin",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()

    token, _ = create_jwt_token("user_test_1", "testuser")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers():
    """Provide auth headers. Call seed_test_user() in your fresh_db fixture first."""
    # This is a placeholder — actual token comes from seed_test_user in fresh_db.
    # Tests should use the auth_headers returned by their fresh_db fixture.
    return {}
