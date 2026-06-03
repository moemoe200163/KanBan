"""
Dev-mode management endpoints.

Provides a full database reset for local development.  Gated on one of:

1. ``E2E=1`` env var (E2E mode), **or**
2. No ``DATABASE_URL`` set (default SQLite at ``backend/devflow.db``).

In production (PostgreSQL with E2E != 1), these endpoints return 404.
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


def _is_dev_mode() -> bool:
    """Return True when running in dev or E2E mode (safe for destructive ops)."""
    if os.getenv("E2E") == "1":
        return True

    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        # No DATABASE_URL → using default SQLite devflow.db → dev mode
        return True

    return False


def _get_db_name() -> str:
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        return "devflow.db (default SQLite)"
    normalized = raw_url
    for suffix in ("+asyncpg", "+aiosqlite", "+psycopg", "+psycopg2"):
        normalized = normalized.replace(suffix, "", 1)
    try:
        return urlparse(normalized).path.lstrip("/")
    except ValueError:
        return "unknown"


# Tables to clean during dev reset, in dependency order.
# Child tables (FK references) are deleted before parent tables.
_TABLES_TO_CLEAN = [
    "issue_handoffs",
    "issue_artifacts",
    "issue_comments",
    "issue_events",
    "quality_gate_results",
    "ecc_jobs",
    "audit_logs",
    "issues",
]


@router.post(
    "/dev/reset",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def dev_reset():
    """Full dev reset: truncate all data tables and re-seed.

    Returns 404 when not in dev/E2E mode.  On success returns per-table
    counts and the number of issues seeded.
    """
    if not _is_dev_mode():
        return JSONResponse(
            content={"detail": "Not Found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    db_name = _get_db_name()
    logger.warning("[dev-reset] resetting database %s", db_name)

    from db import repository as repo

    counts: dict[str, int] = {}
    async with _db.AsyncSessionLocal() as session:
        for table in _TABLES_TO_CLEAN:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            counts[table] = result.scalar_one() or 0
            await session.execute(text(f"DELETE FROM {table}"))
        await session.commit()

    seeded = await repo.seed_if_empty()

    return {
        "status": "reset",
        "deleted": counts,
        "total_deleted": sum(counts.values()),
        "seeded": seeded,
        "database": db_name,
    }


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
)
async def get_stats():
    """Return record counts for key tables.

    Always available (not gated) so the frontend can display data volume.
    """
    try:
        async with _db.AsyncSessionLocal() as session:
            counts: dict[str, int] = {}
            for table in _TABLES_TO_CLEAN + ["agents"]:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar_one() or 0
            return {"counts": counts}
    except Exception as e:
        logger.warning(f"Failed to get stats: {e}")
        return {"counts": {}, "error": str(e)}
