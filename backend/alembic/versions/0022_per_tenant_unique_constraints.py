"""per-tenant unique constraints for LLMProviderConfig and AgentRole (Plan J phase 2)

Revision ID: 0022_per_tenant_unique_constraints
Revises: 0021_tenants_and_tenant_id
Create Date: 2026-06-13

Plan J multi-tenant refactor — phase 2 (per-tenant uniqueness).

The J-1 migration 0021 added a nullable ``tenant_id`` column to
``llm_provider_configs.provider_id`` and ``agent_roles.key`` but
left the *global* ``UNIQUE`` constraint in place. The pre-J model
was a single-tenant world, so a global unique made sense: there
could be only one ``provider_id="minimax"`` row, period. The Plan
J data model is multi-tenant, so the same constraint now blocks
two tenants from both configuring the same provider — which is
exactly what we want to allow.

This migration drops the global unique and replaces it with a
composite ``(tenant_id, key)`` unique constraint. The plan lists
two specific tables (``llm_provider_configs`` and ``agent_roles``);
both share the same shape: a global identifier column that needs
to be unique *within* a tenant.

Why this is a separate migration instead of a follow-up
=======================================================

The plan called this out: the J-1 worker noted the global
unique would need to be revisited before J-3 wires the per-tenant
write paths. Doing it in J-2 means J-3 can land its codemod
without an extra migration in the middle of the change window.

Dialect handling (Plan G 0018 pattern)
======================================

* **Postgres** — ``ALTER TABLE ... DROP CONSTRAINT ...`` then
  ``ADD CONSTRAINT ... UNIQUE (tenant_id, ...)``. Drop+add is one
  transaction; Postgres doesn't need a table rebuild.
* **SQLite** — SQLite can't ``DROP CONSTRAINT`` until 3.35 for
  ``ALTER TABLE ... DROP COLUMN``, but it *can* drop+recreate a
  unique *index* with ``DROP INDEX`` + ``CREATE UNIQUE INDEX``.
  The composite index gives the same guarantee; the model
  declaration (``UniqueConstraint`` in ``models.py``) is
  informational on SQLite because the model-level constraint
  is only used by ``create_all``, not by Alembic.

Idempotency
===========

* ``DROP CONSTRAINT IF EXISTS`` / ``DROP INDEX IF EXISTS`` is
  the Postgres + SQLite safe-rewrite.
* ``CREATE UNIQUE INDEX IF NOT EXISTS`` is portable across both.
* Re-running on a DB that already has the composite index is a
  no-op (the IF NOT EXISTS guards).

Backfill safety
===============

The J-1 migration backfilled every row's ``tenant_id`` to
``tnt_default``. With one tenant, dropping the global unique and
re-creating it as composite is a no-op on the data (every row
in the same tenant must still have a unique key). On a fresh DB
with no data, the migration just changes the schema.

If a future DB is running on a J-1 install with multiple tenants
already sharing the same ``provider_id`` (which would be the
"Plan J is broken" case), this migration will *fail* with a
duplicate-key error. The operator must clean the data first;
that's the intended behavior — silently truncating to satisfy a
uniqueness invariant would be worse.
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_per_tenant_unique_constraints"
down_revision = "0021_tenants_and_tenant_id"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drop_unique_constraint_if_exists(table: str, constraint_name: str) -> None:
    """Drop a named UNIQUE constraint if it exists.

    Postgres speaks ``DROP CONSTRAINT IF EXISTS``; SQLite doesn't
    support that exact form. We branch on the dialect and use the
    right syntax for each.
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}"
        )
    else:
        # SQLite — drop the index that backs the constraint.
        # The auto-generated index name follows the
        # ``<table>_<column>_unique`` pattern that SQLAlchemy
        # uses for ``Column(..., unique=True)``.
        op.execute(f"DROP INDEX IF EXISTS {table}_{_guess_unique_index_col(table)}_{constraint_name}")


def _guess_unique_index_col(table: str) -> str:
    """Return the column that backs the global unique index for
    a known table. Used only on the SQLite path where we need
    to spell out the index name.

    Mapped from the model definitions in ``db/models.py``.
    """
    return {
        "llm_provider_configs": "provider_id",
        "agent_roles": "key",
    }.get(table, "")


def _create_composite_unique(
    table: str,
    columns: list[str],
    index_name: str,
) -> None:
    """Create ``UNIQUE (col1, col2)`` on ``table``.

    Both dialects use the index form because:
      * Postgres — ``CREATE UNIQUE INDEX`` creates the same
        constraint as ``ADD CONSTRAINT ... UNIQUE`` and is
        easier to express conditionally.
      * SQLite — index is the only form.
    """
    cols = ", ".join(columns)
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"
    )


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # llm_provider_configs.provider_id
    # ------------------------------------------------------------------
    # The pre-J model declared ``provider_id = Column(String(32),
    # unique=True, ...)`` which created a global UNIQUE on
    # ``provider_id``. We drop it and replace it with a composite
    # UNIQUE on ``(tenant_id, provider_id)`` so two tenants can
    # both register a ``provider_id="minimax"`` row.
    _drop_unique_constraint_if_exists(
        "llm_provider_configs", "llm_provider_configs_provider_id_key"
    )
    _create_composite_unique(
        "llm_provider_configs",
        ["tenant_id", "provider_id"],
        "uq_llm_provider_configs_tenant_provider",
    )

    # ------------------------------------------------------------------
    # agent_roles.key
    # ------------------------------------------------------------------
    # Same shape as the LLM provider — global unique on ``key``
    # is replaced with composite ``(tenant_id, key)`` so two
    # tenants can both define a ``key="backend-dev"`` agent
    # role.
    _drop_unique_constraint_if_exists(
        "agent_roles", "agent_roles_key_key"
    )
    _create_composite_unique(
        "agent_roles",
        ["tenant_id", "key"],
        "uq_agent_roles_tenant_key",
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Reverse: drop the composite indexes and recreate the global
    # uniques. The drop is idempotent; the recreate is NOT — if
    # the DB still has two rows in different tenants with the
    # same key, the unique creation will fail. That's the
    # intended behavior (mirroring the upgrade's fail-on-data
    # invariant).
    op.execute("DROP INDEX IF EXISTS uq_llm_provider_configs_tenant_provider")
    op.execute("DROP INDEX IF EXISTS uq_agent_roles_tenant_key")

    # Re-add the global uniques. Use ``CREATE UNIQUE INDEX`` on
    # both dialects for the same reason as the upgrade.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_llm_provider_configs_provider_id_global "
        "ON llm_provider_configs (provider_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_agent_roles_key_global ON agent_roles (key)"
    )
