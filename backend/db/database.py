"""
DevFlow Backend - Async SQLAlchemy Database Setup

SQLite with aiosqlite for async support.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Use absolute path for SQLite default to avoid cwd issues
_default_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "devflow.db")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{_default_db_path}"
)

# Create async engine (SQLite + aiosqlite uses NullPool, no pool_size/max_overflow)
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Dependency for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """
    Initialize the database - create all tables.
    Called on FastAPI startup via main.py lifespan.
    Uses cached _db_initialized flag to avoid re-creating tables.
    """
    global _db_initialized
    if _db_initialized:
        return
    from db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
    _db_initialized = True


async def ensure_db_init():
    """Ensure tables exist before any DB operation. Lazy-init pattern."""
    global _db_initialized
    if not _db_initialized:
        await init_db()


_db_initialized = False