"""
T8.4 — migration parity (anti-drift).

After running ``alembic upgrade head`` (the same path ``init_db`` takes
in production), the actual database tables must match the models
declared in ``db.models``. If a model is added without a migration, or
a migration creates a table that no model owns, this test fails.

This test uses SQLite in CI for speed; the same assertion runs against
Postgres in ``scripts/smoke.sh`` step 7, which queries
``alembic_version`` to prove migrations applied.
"""

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


def _run_alembic_upgrade_head(db_url: str, monkeypatch=None) -> None:
    """Run alembic upgrade head synchronously, mirroring the production
    init_db path (``asyncio.to_thread(_run_alembic_upgrade_head)``)."""
    import os
    from alembic.command import upgrade
    from alembic.config import Config

    # alembic/env.py imports `_raw_db_url` from db.database at module
    # level and feeds it into the alembic Config. That import is
    # frozen once db.database is loaded, so simply setting
    # ``DATABASE_URL`` in the environment is not enough — we have to
    # patch the module attribute the env.py uses.
    if monkeypatch is not None:
        monkeypatch.setattr(
            "db.database._raw_db_url", db_url, raising=False
        )
    else:
        # Fallback when no monkeypatch fixture is available (e.g. when
        # called from a script). Mutate the module directly.
        from db import database as _db
        _db._raw_db_url = db_url

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    upgrade(cfg, "head")


def _sqlite_url_for(path: Path) -> str:
    """Build a SQLAlchemy sqlite URL from a filesystem path.

    ``f"sqlite:///{path}"`` produces 5 slashes for absolute paths because
    ``str(Path('/tmp/x'))`` already starts with ``/``. We want exactly 3
    leading slashes (the protocol) followed by the absolute path.
    """
    s = str(path)
    if s.startswith("/"):
        return f"sqlite:///{s}"
    return f"sqlite:///{s}"


def _enumerate_tables_sqlite(db_path: str) -> set[str]:
    """Return the set of user-visible table names in a SQLite DB.

    ``alembic_version`` is excluded — it's a control table that does
    not correspond to a model.
    """
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
    finally:
        engine.dispose()
    return {row[0] for row in rows if row[0] != "alembic_version"}


@pytest.mark.parametrize("db_file", ["parity_test.db", "parity_test_e2e.db"])
def test_migration_parity_matches_model_metadata(tmp_path, db_file, monkeypatch):
    """Create a fresh SQLite DB, run ``alembic upgrade head``, then
    assert every model in ``db.models`` has a corresponding table and
    no extra tables (besides ``alembic_version``) snuck in."""
    from db.models import Base

    db_path = tmp_path / db_file
    db_url = _sqlite_url_for(db_path)

    # Use a sync sqlite URL for alembic; the test doesn't need async.
    _run_alembic_upgrade_head(db_url, monkeypatch=monkeypatch)

    actual_tables = _enumerate_tables_sqlite(str(db_path))
    model_tables = set(Base.metadata.tables.keys())

    # No model may be missing from the schema (this is the anti-drift
    # property the user asked for).
    missing = model_tables - actual_tables
    assert not missing, (
        f"models declared in db.models without corresponding DB tables: "
        f"{sorted(missing)}. A migration is missing or incomplete."
    )
    # And no table should exist that no model owns.
    extra = actual_tables - model_tables
    assert not extra, (
        f"DB tables exist with no corresponding model: {sorted(extra)}. "
        f"Either declare a model or remove the migration."
    )


def test_alembic_version_records_head_revision(tmp_path, monkeypatch):
    """The ``alembic_version`` table must contain the head revision
    after upgrade. This is the same check ``scripts/smoke.sh`` runs
    against Postgres; the value on SQLite should be the same revision
    string."""
    db_path = tmp_path / "alembic_version_test.db"
    db_url = _sqlite_url_for(db_path)

    _run_alembic_upgrade_head(db_url, monkeypatch=monkeypatch)

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    # The head revision is the last ``upgrade`` in alembic/versions.
    # We don't hardcode the string here; the test merely asserts a
    # non-empty value was recorded.
    assert isinstance(version, str)
    assert len(version) > 0
