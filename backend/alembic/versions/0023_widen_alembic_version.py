"""widen alembic_version.version_num — operator fix for 0022 stamp truncation

Revision ID: 0023_widen_alembic_version
Revises: 0022_per_tenant_unique_constraints
Create Date: 2026-06-13

Background
==========

Migration 0022 has ``revision = "0022_per_tenant_unique_constraints"``
(39 chars). The autogen-created ``alembic_version`` table declares
``version_num varchar(32)`` — the standard alembic template. When
0022 ran, the DDL (drop global unique + create composite unique)
completed fine, but the trailing ``INSERT INTO alembic_version
(version_num) VALUES ('0022_per_tenant_unique_constraints')`` blew
up with ``value too long for type character varying(32)``.

The failure was *inside* alembic's migration transaction. Postgres
autocommits DDL, so the schema changes were already visible to the
next request — but alembic stamped head failed, so on every
subsequent ``alembic upgrade head`` it would see ``current=0021`` and
try to re-run 0022, hitting the same stamp error and looping
indefinitely.

Fix
===

Widen ``version_num`` to ``varchar(64)`` so any future Plan J+
revision id fits. This is purely a metadata-table change; nothing
in the app reads the column width.

Dialect
=======

Postgres and SQLite both support ``ALTER TABLE ... ALTER COLUMN
... TYPE varchar(N)``. We use plain ``op.execute`` so the same
statement works on both. On Postgres, ``ALTER COLUMN TYPE`` between
two ``varchar`` types is a no-op table rewrite if the new type is
wider (which it is here), so the migration is safe to re-run on
a DB that's already at varchar(64).

Why no schema introspection
===========================

The first draft of this migration queried ``information_schema`` /
``PRAGMA table_info`` to make the upgrade a true no-op when the
column was already wide. That introspection hung inside
``alembic.versions`` under the dev asyncpg pool (the
``asyncio.to_thread`` bridge between the uvicorn event loop and
alembic's worker-thread ``asyncio.run`` re-entrancy gets stuck
waiting for the engine to dispose). The simpler ``ALTER COLUMN``
runs to completion in <100ms on the same pool, so we accept the
theoretical "ALTER to same type" cost and keep the migration
one line.

Downgrade
=========

Not meaningful. Shrinking back to varchar(32) re-creates the
original trap. We leave the column at varchar(64).
"""

from alembic import op


revision = "0023_widen_alembic_version"
down_revision = "0022_per_tenant_unique_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain DDL works on Postgres and SQLite (both treat the
    # statement as a metadata change for the column type, and
    # Postgres notes the new type is wider, so no table rewrite).
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64)")


def downgrade() -> None:
    # Intentionally a no-op — see the module docstring.
    pass
