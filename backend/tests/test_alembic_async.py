"""
T8.1 — alembic-in-async-loop safety.

Confirms that ``db_module.init_db()`` does not raise
``RuntimeError: asyncio.run() cannot be called from a running event loop``
when the alembic path is exercised from inside a running event loop.

This is the regression test for the fix that wrapped
``_run_alembic_upgrade_head()`` in ``asyncio.to_thread()`` so the sync
alembic CLI can create its own event loop in a worker thread.
"""

import asyncio

from db import database as db_module


def test_init_db_does_not_raise_when_alembic_runs_inside_running_loop(
    monkeypatch,
):
    # Force the postgres path so init_db() takes the alembic branch.
    monkeypatch.setattr(db_module, "is_postgres", lambda: True)

    # Replace the alembic runner with a no-op so we don't depend on a
    # live Postgres for this test. The point is to prove the wrapping
    # in asyncio.to_thread works, not that alembic itself works.
    called = {"count": 0}

    def _fake_run():
        called["count"] += 1

    monkeypatch.setattr(db_module, "_run_alembic_upgrade_head", _fake_run)
    # Reset the lazy-init guard so init_db() actually runs.
    monkeypatch.setattr(db_module, "_db_initialized", False)

    # Call init_db() from inside a running loop. Before the fix this
    # would raise RuntimeError("asyncio.run() cannot be called from a
    # running event loop") synchronously inside the lifespan.
    async def _exercise():
        await db_module.init_db()

    asyncio.run(_exercise())

    # The wrapped alembic call should have actually run, and the init
    # flag should now be True (idempotency contract).
    assert called["count"] == 1
    assert db_module._db_initialized is True


def test_init_db_idempotent_after_first_call(monkeypatch):
    """A second init_db() call inside the same process must short-circuit
    and not invoke the alembic runner a second time."""
    monkeypatch.setattr(db_module, "is_postgres", lambda: True)

    called = {"count": 0}

    def _fake_run():
        called["count"] += 1

    monkeypatch.setattr(db_module, "_run_alembic_upgrade_head", _fake_run)
    monkeypatch.setattr(db_module, "_db_initialized", False)

    async def _exercise():
        await db_module.init_db()
        await db_module.init_db()
        await db_module.init_db()

    asyncio.run(_exercise())
    assert called["count"] == 1, "alembic runner must be invoked exactly once"
