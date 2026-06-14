"""Plan I — AI Studio conversations + messages

Revision ID: 0024_ai_studio
Revises: 0023_widen_alembic_version
Create Date: 2026-06-14

Plan I Phase 1 lands the persistence layer for the AI Studio
chat-style feature. Two new tables, both tenant-aware so the J-2
SQLAlchemy listener scopes every query correctly.

* ``ai_studio_conversations`` — one row per chat. ``user_id`` FK
  cascades on user delete. ``tenant_id`` is nullable + indexed so
  the existing 727 tests that don't seed a tenant still work — the
  listener falls back to the default tenant for un-scoped rows.
* ``ai_studio_messages`` — append-only message log. ``type`` is
  free-form (the plan §三 2 lists ``user / assistant / thinking /
  tool_call / tool_result``; we store the string verbatim and let
  the SSE driver decide which values are valid).

Dialect
=======

Postgres and SQLite both support ``CREATE TABLE IF NOT EXISTS``,
``FOREIGN KEY ... ON DELETE CASCADE``, and ``JSON`` columns. The
only divergence is the JSON type itself: Postgres uses ``JSONB``
(``postgresql.JSONB(astext_type=Text)``), SQLite uses plain
``JSON`` and stores it as TEXT under the hood. We use the same
``_json_type(is_pg)`` helper that 0021 introduced so the DDL is
identical-on-the-wire for the dev / CI / production paths.

We do NOT backfill ``tenant_id`` for the AI Studio rows — the table
is empty at the time this migration lands, so the column just needs
to exist with the right shape. The same goes for the FK
constraints: they're strict (CASCADE on user / conversation
delete) because the AI Studio feature is greenfield and there are
no legacy rows to migrate.

Why no ``_safe_add_column`` dance
=================================

There is no prior version of these tables; this is a fresh
``CREATE TABLE``. The 0021 / 0023 ``IF NOT EXISTS`` / batch-alter
workarounds exist to make migrations idempotent on a DB that's
been upgraded mid-way. A pure additive migration only needs the
``IF NOT EXISTS`` guard on table creation — the standard SQL
``CREATE TABLE IF NOT EXISTS`` — so the migration can be re-run
on a partial-upgrade DB without exploding.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_ai_studio"
down_revision = "0023_widen_alembic_version"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_type(is_pg: bool):
    """JSONB on Postgres, JSON on SQLite — same JSON serialised."""
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    """Create the named index if it doesn't already exist.

    Plan G pattern — ``CREATE INDEX IF NOT EXISTS`` is portable
    across Postgres and SQLite, and the only sane way to make the
    migration re-runnable without an explicit ``DROP INDEX``.
    """
    cols = ", ".join(columns)
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"
    )


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_t = _json_type(is_pg)

    # ------------------------------------------------------------------
    # ai_studio_conversations
    # ------------------------------------------------------------------
    op.create_table(
        "ai_studio_conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False, server_default="New chat"),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(64), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=False, server_default="minimax"),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    _create_index_if_missing(
        "ai_studio_conversations", "ix_ai_studio_conversations_user_id", ["user_id"]
    )
    _create_index_if_missing(
        "ai_studio_conversations", "ix_ai_studio_conversations_tenant_id", ["tenant_id"]
    )

    # ------------------------------------------------------------------
    # ai_studio_messages
    # ------------------------------------------------------------------
    op.create_table(
        "ai_studio_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("ai_studio_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_args", json_t, nullable=True),
        sa.Column("tool_result", sa.Text(), nullable=True),
        sa.Column("agent_role", sa.String(32), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    _create_index_if_missing(
        "ai_studio_messages",
        "ix_ai_studio_messages_conversation_id",
        ["conversation_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_ai_studio_messages_conversation_id",
        table_name="ai_studio_messages",
    )
    op.drop_table("ai_studio_messages")

    op.drop_index(
        "ix_ai_studio_conversations_tenant_id",
        table_name="ai_studio_conversations",
    )
    op.drop_index(
        "ix_ai_studio_conversations_user_id",
        table_name="ai_studio_conversations",
    )
    op.drop_table("ai_studio_conversations")
