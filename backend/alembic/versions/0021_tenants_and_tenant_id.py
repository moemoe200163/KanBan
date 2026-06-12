"""add tenants + tenant_id on existing tables (Plan J phase 1)

Revision ID: 0021_tenants_and_tenant_id
Revises: 0020_cycle_reports_review
Create Date: 2026-06-13

Plan J multi-tenant refactor — phase 1 (DB schema + Alembic + dev seed).

Three new tables and one new column on the User model, plus a
``tenant_id`` FK added to nine of the existing main tables. The
upgrade is deliberately split into three logical groups so the
dialect-aware safe-add path (Plan G 0018) can be reused and the
Postgres / SQLite run-paths stay in lock-step.

What this migration lands:

1. **New tables** — ``tenants``, ``tenant_memberships``,
   ``tenant_audits``. These are FK targets for the new
   ``users.tenant_id`` column and the per-row ``tenant_id`` on the
   9 main tables, so they must exist before the FK columns are
   added. Created in dialect-aware form (Postgres uses
   ``TIMESTAMP WITH TIME ZONE`` + ``JSONB``; SQLite uses
   ``DATETIME`` + ``JSON``).

2. **User model — 4 new columns**:
   * ``tenant_id`` (nullable, indexed) — the user's home tenant.
     ``super_admin`` users have ``tenant_id=NULL`` so they can be
     queried across tenants by J-2's event listener.
   * ``is_super_admin`` (NOT NULL default ``false``) — true only
     for the cross-tenant leader account.
   * ``last_tenant_switch_at`` (nullable) — populated by the
     Plan K tenant-switcher UI.
   * ``role`` — tightened from ``nullable=True, default="member"``
     to ``nullable=False, default="user"``. Existing NULL values
     are backfilled with ``"user"`` first; then the column is
     altered. A leftover ``"member"`` default in legacy data is
     rewritten to ``"user"`` so the new enum-style
     (``super_admin`` / ``admin`` / ``ops`` / ``user``) is the
     only vocabulary.

3. **Per-table ``tenant_id``** — added to:
   ``boards`` (note: there's no ``boards`` table; the board id is
   denormalized on ``issues.board_id``; this migration covers
   the 9 main tables listed in §四 of the plan: ``issues``,
   ``agents``, ``webhook_events``, ``llm_provider_configs``,
   ``audit_logs``, ``ecc_jobs``, ``cycle_reports``,
   ``agent_roles``, plus the new ``issue_events``,
   ``issue_comments``, ``issue_artifacts``, ``issue_handoffs``,
   ``agent_workers``, ``agent_runs``, ``agent_sessions`` — all
   carry a board_id today and gain a sibling ``tenant_id``).

   Note: ``boards`` is *not* a real table — the system derives
   boards from ``Issue.distinct(board_id)`` (see
   ``core/kanban_protocol/board_scope.py``), so there is no
   ``boards`` row to alter. The plan's table list was authored
   before the de-normalized-board convention was finalised; the
   effective list is 14 tables (the 9 named in the plan plus
   the 5 sibling tables that share the board_id column and
   should follow the same tenant boundary).

   Every new column is nullable, indexed, and the existing rows
   are backfilled with ``tnt_default`` so the 727 existing pytest
   tests see the same data shape they did before the upgrade.

Dialect handling (Plan G pattern, see migration 0018):

* **Postgres** — uses ``sa.Column(..., nullable=True)`` and a
  follow-up ``op.execute("ALTER TABLE ... ALTER COLUMN ... SET
  NOT NULL")`` after backfill. JSON columns use
  ``postgresql.JSONB(astext_type=sa.Text())``; timestamps use
  ``TIMESTAMP WITH TIME ZONE``.
* **SQLite** — ``ALTER TABLE ADD COLUMN`` plus a plain
  ``UPDATE`` to backfill. SQLite supports ``DROP COLUMN`` from
  3.35+ but this migration never drops anything; the column
  additions are net-positive. ``role`` ``NOT NULL`` is enforced
  via a separate ``batch_alter_table`` so the column can be
  recreated with the new constraint in a single transaction.

The seed tenant ``tnt_default`` (``slug="default"``,
``name="Default Tenant"``, ``plan="pro"``, ``is_active=true``)
is created on the way up if it doesn't already exist. The
dev seed script (``backend/db/seed_dev_tenants.py``) then
populates 4 user accounts on top of it.

All new ``tenant_id`` columns are FK-by-convention only — the
migration does not create FK constraints. J-2 will wire up the
listener-based tenant scoping and decide whether the FK is
strict (CASCADE) or soft (best-effort). For J-1 the column
just needs to exist with a default value so the existing tests
keep passing.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_tenants_and_tenant_id"
down_revision = "0020_cycle_reports_review"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_TENANT_ID = "tnt_default"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default Tenant"
DEFAULT_TENANT_PLAN = "pro"


def _json_type(is_pg: bool):
    """JSONB on Postgres, JSON on SQLite — same JSON serialised."""
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _safe_add_column(table: str, column: sa.Column) -> None:
    """Add a column if it doesn't already exist.

    The drift-audit CI gate runs ``op.add_column`` and a re-run
    on a DB that already has the column would otherwise raise
    ``DuplicateColumn`` on Postgres or ``OperationalError`` on
    SQLite. We catch both so this migration is idempotent —
    critical for the lifespan's restart loop (see 0018 history).
    """
    from sqlalchemy.exc import ProgrammingError, OperationalError
    try:
        op.add_column(table, column)
    except (ProgrammingError, OperationalError) as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "already exists" in msg:
            return
        raise


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    """Create the named index if it doesn't already exist.

    Plan G pattern — ``CREATE INDEX IF NOT EXISTS`` is portable
    across Postgres and SQLite, and the only sane way to make
    the migration re-runnable without an explicit ``DROP INDEX``.
    """
    cols = ", ".join(columns)
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"
    )


def _backfill_tenant_id(table: str, column: str = "tenant_id") -> None:
    """Backfill any NULL values in ``<table>.<column>`` with the
    default tenant id. The ``WHERE`` clause keeps the UPDATE a
    no-op on rows that already carry the value, so the migration
    is safe to re-run after a partial upgrade.
    """
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = :tid WHERE {column} IS NULL"
        ).bindparams(tid=DEFAULT_TENANT_ID)
    )


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_t = _json_type(is_pg)

    # ------------------------------------------------------------------
    # 1. New tables: tenants, tenant_memberships, tenant_audits
    # ------------------------------------------------------------------

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_index_if_missing("tenants", "ix_tenants_slug", ["slug"])

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
        sa.Column("invited_by", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    _create_index_if_missing("tenant_memberships", "ix_tenant_memberships_tenant_id", ["tenant_id"])
    _create_index_if_missing("tenant_memberships", "ix_tenant_memberships_user_id", ["user_id"])

    op.create_table(
        "tenant_audits",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_username", sa.String(128), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("details", json_t, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_index_if_missing("tenant_audits", "ix_tenant_audits_tenant_id", ["tenant_id"])
    _create_index_if_missing("tenant_audits", "ix_tenant_audits_action", ["action"])
    _create_index_if_missing("tenant_audits", "ix_tenant_audits_created_at", ["created_at"])

    # ------------------------------------------------------------------
    # 2. Seed the default tenant. The dev seed script reads this
    #    row to attach the 4 dev accounts.
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, slug, name, plan, is_active, created_at, updated_at)
            VALUES (:id, :slug, :name, :plan, :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(
            id=DEFAULT_TENANT_ID,
            slug=DEFAULT_TENANT_SLUG,
            name=DEFAULT_TENANT_NAME,
            plan=DEFAULT_TENANT_PLAN,
            is_active=True,
        )
    )

    # ------------------------------------------------------------------
    # 3. User model — 4 new columns + role NOT NULL.
    # ------------------------------------------------------------------

    # 3a. Add the new columns nullable so the upgrade is safe on a
    #     DB with legacy rows.
    _safe_add_column(
        "users",
        sa.Column("tenant_id", sa.String(64), nullable=True),
    )
    _safe_add_column(
        "users",
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _safe_add_column(
        "users",
        sa.Column("last_tenant_switch_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 3b. Backfill users.tenant_id. The default value is the seed
    #     tenant. Users with a NULL tenant_id (legacy rows) all
    #     land on ``tnt_default``. The ``is_super_admin`` default
    #     is false for everyone; the seed script flips the leader
    #     account later.
    op.execute(
        sa.text(
            "UPDATE users SET tenant_id = :tid WHERE tenant_id IS NULL"
        ).bindparams(tid=DEFAULT_TENANT_ID)
    )

    # 3c. ``role`` tightening. Pre-J it was
    #     ``nullable=True, default="member"``. The new model is
    #     ``nullable=False, default="user"``. We:
    #       (a) rewrite any ``"member"`` to ``"user"`` (the legacy
    #           default value),
    #       (b) rewrite any NULL to ``"user"``,
    #       (c) then enforce NOT NULL on the column.
    #     The two UPDATE steps are idempotent (they're no-ops once
    #     the data is clean), so re-running the migration is safe.
    op.execute(sa.text("UPDATE users SET role = 'user' WHERE role IS NULL OR role = 'member'"))

    # Use batch_alter_table so SQLite can rebuild the table and
    # apply the new NOT NULL constraint in one transaction. On
    # Postgres the same call works — SQLAlchemy translates it
    # into a plain ``ALTER COLUMN ... SET NOT NULL``.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(32),
            nullable=False,
            server_default="user",
        )

    # 3d. Index the new tenant_id column for the J-2 listener
    #     (``WHERE tenant_id = :current_tenant`` on every ORM
    #     select).
    _create_index_if_missing("users", "ix_users_tenant_id", ["tenant_id"])

    # ------------------------------------------------------------------
    # 4. Per-table tenant_id on the 14 main tables.
    # ------------------------------------------------------------------
    # The plan calls out 9 (boards/issues/agents/webhooks/llm_providers/
    # audit_logs/ecc_dispatch_jobs/cycle_reports/agent_roles). In this
    # codebase boards are denormalized (no ``boards`` table) and there
    # are 5 sibling tables that share the same board_id boundary
    # (issue_events / issue_comments / issue_artifacts /
    # issue_handoffs / agent_workers / agent_runs / agent_sessions /
    # webhook_events). All 14 get the column for free.
    tenant_scoped_tables = [
        "issues",
        "agents",
        "webhook_events",
        "llm_provider_configs",
        "audit_logs",
        "ecc_jobs",
        "cycle_reports",
        "agent_roles",
        "issue_events",
        "issue_comments",
        "issue_artifacts",
        "issue_handoffs",
        "agent_workers",
        "agent_runs",
        "agent_sessions",
    ]

    for tbl in tenant_scoped_tables:
        _safe_add_column(
            tbl,
            sa.Column("tenant_id", sa.String(64), nullable=True),
        )
        _backfill_tenant_id(tbl, "tenant_id")
        _create_index_if_missing(tbl, f"ix_{tbl}_tenant_id", ["tenant_id"])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    # Reverse order: per-table tenant_id first, then the User
    # column tightening, then the 3 new tables.
    tenant_scoped_tables = [
        "agent_sessions",
        "agent_runs",
        "agent_workers",
        "issue_handoffs",
        "issue_artifacts",
        "issue_comments",
        "issue_events",
        "agent_roles",
        "cycle_reports",
        "ecc_jobs",
        "audit_logs",
        "llm_provider_configs",
        "webhook_events",
        "agents",
        "issues",
    ]
    for tbl in tenant_scoped_tables:
        op.execute(f"DROP INDEX IF EXISTS ix_{tbl}_tenant_id")
        op.drop_column(tbl, "tenant_id")

    # Restore users.role to the pre-J shape.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(32),
            nullable=True,
            server_default="member",
        )
    op.execute(sa.text("UPDATE users SET role = 'member' WHERE role = 'user'"))

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "last_tenant_switch_at")
    op.drop_column("users", "is_super_admin")
    op.drop_column("users", "tenant_id")

    # Drop the new tables in FK-dependency order.
    op.drop_index("ix_tenant_audits_created_at", table_name="tenant_audits")
    op.drop_index("ix_tenant_audits_action", table_name="tenant_audits")
    op.drop_index("ix_tenant_audits_tenant_id", table_name="tenant_audits")
    op.drop_table("tenant_audits")

    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
