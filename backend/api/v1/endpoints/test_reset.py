"""
E2E-only reset endpoint.

WARNING: This endpoint is **destructive**. It TRUNCATES the `issues` and
`ecc_jobs` tables and re-seeds the database. It is gated on **two
independent conditions** to keep it from being accidentally enabled in
non-E2E environments:

1. ``E2E`` env var must be exactly ``"1"``.
2. ``DATABASE_URL`` database name (last path segment) must contain ``_e2e``.

If either condition fails, the endpoint returns 404 so it is not even
discoverable in ``/docs`` and is not advertised in the OpenAPI schema.
"""

import logging
import os
from urllib.parse import urlparse

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import database as _db

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_reset_enabled() -> bool:
    """Return True only when both E2E gating conditions hold.

    The database-name check is intentionally a substring match (not a
    full equality) so something like ``devflow_e2e`` *or* ``dev_e2e_smoke``
    both pass. The premise: nobody names a real production DB with
    ``_e2e`` in it, so this catches every realistic misconfiguration.
    """
    if os.getenv("E2E") != "1":
        return False

    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        return False

    # DATABASE_URL may have an asyncpg/aiosqlite driver suffix; strip it
    # so the parser sees a plain ``scheme://...`` URL.
    normalized = raw_url
    for suffix in ("+asyncpg", "+aiosqlite", "+psycopg", "+psycopg2"):
        normalized = normalized.replace(suffix, "", 1)

    try:
        parsed = urlparse(normalized)
    except ValueError:
        return False

    db_name = parsed.path.lstrip("/")
    return "_e2e" in db_name


@router.post(
    "/test/reset",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def reset_e2e_database():
    """Truncate ``issues`` and ``ecc_jobs``, then re-seed.

    Returns 404 when E2E gating fails. On success returns the database
    name (proving the gating actually checked the right thing) and the
    number of issues seeded.
    """
    if not _is_reset_enabled():
        return JSONResponse(
            content={"detail": "Not Found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    raw_url = os.getenv("DATABASE_URL", "")
    normalized = raw_url
    for suffix in ("+asyncpg", "+aiosqlite", "+psycopg", "+psycopg2"):
        normalized = normalized.replace(suffix, "", 1)
    db_name = urlparse(normalized).path.lstrip("/")

    logger.warning(
        "[e2e-reset] resetting database %s (E2E=1, db name contains _e2e)",
        db_name,
    )

    # Import here so we don't force db init at import time.
    from db import repository as repo

    async with _db.AsyncSessionLocal() as session:
        # Use DELETE (not TRUNCATE) so the same statement works on
        # SQLite (test) and Postgres (E2E). The endpoints are gated to
        # _e2e databases, so performance is not a concern here.
        # Order doesn't matter because there are no FKs between
        # ``issues`` and ``ecc_jobs``.
        await session.execute(text("DELETE FROM ecc_jobs"))
        await session.execute(text("DELETE FROM issues"))
        await session.commit()

    seeded = await repo.seed_if_empty()

    # Seed E2E test users (admin + member) for auth-gated tests.
    # These users have fixed credentials so E2E tests can log in reliably.
    await _seed_e2e_users()

    return {
        "status": "reset",
        "seeded": seeded,
        "database": db_name,
    }


async def _seed_e2e_users() -> None:
    """Create or update E2E test users (e2e_admin, e2e_member).

    The admin user is needed for tests that exercise admin-only endpoints
    (provider config, agent roles CRUD, etc.). The member user is for
    tests that need a logged-in non-admin user.
    """
    import uuid
    from datetime import datetime, timezone

    from db import database as _db
    from db.models import User
    from sqlalchemy import select

    from .auth import hash_password

    password_hash, _ = hash_password("testpass123")

    async with _db.AsyncSessionLocal() as session:
        for username, role in [("e2e_admin", "admin"), ("e2e_member", "member")]:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update role if user exists (handles case where member was promoted to admin)
                existing.role = role
                logger.info(f"[e2e-reset] updated user {username} role={role}")
            else:
                user = User(
                    id=f"user_{uuid.uuid4().hex[:12]}",
                    username=username,
                    password_hash=password_hash,
                    role=role,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(user)
                logger.info(f"[e2e-reset] created user {username} role={role}")

        await session.commit()
