"""
DevFlow Backend - Async SQLAlchemy Database Setup

Supports SQLite (aiosqlite) and Postgres (asyncpg) via ``DATABASE_URL``.
If a driver suffix is missing, it is auto-added based on the scheme so
users can write either:

  - ``DATABASE_URL=postgresql://user:pass@host:5432/db``
  - ``DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db``
  - ``DATABASE_URL=sqlite:///./devflow.db``
  - ``DATABASE_URL=sqlite+aiosqlite:///./devflow.db``

Schema bootstrap rules:

- **Postgres (official dev / production path)**: ``init_db`` runs
  Alembic migrations to head. The schema is owned by
  ``backend/alembic/versions`` and is the only way to evolve tables.
- **SQLite (pytest / local fallback)**: ``init_db`` falls back to
  ``create_all`` for speed, so tests do not have to round-trip through
  Alembic on every fixture.
"""

import asyncio
import os
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

# Use absolute path for SQLite default to avoid cwd issues
_default_db_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "devflow.db"
)

_raw_db_url = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_default_db_path}")


def _normalize_database_url(url: str) -> str:
    """Add async driver suffix if missing.

    Examples:
      postgresql://...        -> postgresql+asyncpg://...
      postgres://...          -> postgresql+asyncpg://...
      postgresql+psycopg://...-> postgresql+asyncpg://...
      sqlite:///...           -> sqlite+aiosqlite:///...
      sqlite+aiosqlite:///... -> sqlite+aiosqlite:///
    """
    if not url:
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite:///" + url[len("sqlite://"):]
    return url


DATABASE_URL = _normalize_database_url(_raw_db_url)
"""Normalized, resolved database URL (always uses the async driver)."""


def is_postgres() -> bool:
    """Return True when the configured URL targets Postgres.

    Used by ``init_db`` to decide between running Alembic (Postgres) and
    ``create_all`` (SQLite fallback for pytest / local dev).
    """
    return DATABASE_URL.startswith("postgresql+asyncpg://") or DATABASE_URL.startswith(
        "postgresql://"
    )


# Create async engine. SQLite + aiosqlite uses NullPool internally, so no
# pool_size/max_overflow tweaks needed.
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

# Async session factory
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def _run_alembic_upgrade_head() -> None:
    """Run ``alembic upgrade head`` programmatically.

    Used by ``init_db`` on the Postgres path so the FastAPI lifespan
    owns schema bootstrap and ``docker compose up`` is enough to get a
    working database.

    Importing alembic lazily keeps the dependency optional for the
    SQLite-only pytest path.
    """
    from alembic import command
    from alembic.config import Config

    from pathlib import Path

    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option(
        "script_location", str(backend_dir / "alembic")
    )
    cfg.set_main_option("sqlalchemy.url", _raw_db_url)

    command.upgrade(cfg, "head")


def _is_e2e_sqlite_target() -> bool:
    """Return True when this process is targeting a test/automation SQLite db.

    E2E databases (any SQLite file whose name contains ``_e2e``) must drop
    and recreate tables on init so the schema always matches the current
    model. ``create_all(checkfirst=True)`` is a no-op when the table
    already exists, which leaves stale schemas in place when models gain
    new columns (the classic "no such column: issues.board_id" failure).
    """
    if is_postgres():
        return False
    if os.getenv("E2E") != "1":
        return False
    return "_e2e" in (DATABASE_URL.rsplit("/", 1)[-1] or "")


async def init_db() -> None:
    """Initialize the database schema.

    - **Postgres**: run Alembic migrations to ``head`` so the schema is
      versioned and reproducible across environments.
    - **E2E SQLite** (``_e2e`` db name, ``E2E=1``): drop and recreate all
      tables so the schema always matches the current model. The data
      is then re-seeded by the caller (``seed_if_empty``).
    - **SQLite (default)**: fall back to ``Base.metadata.create_all`` for
      fast test setup. Tests still go through this entry point unless
      they bypass lifespan management (see ``backend/tests/test_persistence.py``).

    Idempotent via the module-level ``_db_initialized`` flag.
    """
    global _db_initialized
    if _db_initialized:
        return

    if is_postgres():
        try:
            # Run the sync alembic CLI in a worker thread so it can
            # create its own event loop via env.py's asyncio.run(). Calling
            # _run_alembic_upgrade_head() directly from the uvicorn loop
            # raises "asyncio.run() cannot be called from a running event
            # loop" -- the outer lifespan try/except in main.py would then
            # swallow it and the schema would never be created on Postgres.
            await asyncio.to_thread(_run_alembic_upgrade_head)
        except Exception as e:
            logger.error(f"Alembic upgrade failed: {e}")
            raise
    else:
        from db.models import Base

        async with engine.begin() as conn:
            if _is_e2e_sqlite_target():
                # Drop first so newly-added columns take effect on the
                # next ``create_all`` call.
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True)
            )

    _db_initialized = True


async def ensure_db_init() -> None:
    """Ensure tables exist before any DB operation. Lazy-init pattern."""
    async with _db_init_lock:
        if not _db_initialized:
            await init_db()


_db_initialized: bool = False
_db_init_lock = asyncio.Lock()
