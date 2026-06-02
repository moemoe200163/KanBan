"""Alembic environment for the DevFlow backend.

Uses the same async engine and Base metadata as the running app, so a
single set of migrations drives both SQLite (pytest) and Postgres
(docker dev / production).

The connection URL is read from the ``DATABASE_URL`` environment
variable when present, falling back to a local SQLite file. This keeps
``alembic upgrade head`` and the FastAPI lifespan consistent without
needing to maintain a separate alembic.ini entry for each environment.
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make `db` importable from the alembic CLI regardless of CWD.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from db.database import _normalize_database_url, _raw_db_url  # noqa: E402
from db.models import Base  # noqa: E402

# Alembic Config object.
config = context.config

# Inject the env-driven URL (async driver suffix auto-applied).
config.set_main_option("sqlalchemy.url", _normalize_database_url(_raw_db_url))

# Configure Python logging from the ini file (if a section is present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to stdout without requiring a live DB connection. Useful
    for code review and CI diffs.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite + alembic have known quirks with batch mode; keep the
        # default (no batch) and let the migration author emit dialect
        # specific DDL where it matters (e.g. JSONB on Postgres).
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against an async engine (asyncpg / aiosqlite)."""
    section = config.get_section(config.config_ini_section, {}) or {}
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
