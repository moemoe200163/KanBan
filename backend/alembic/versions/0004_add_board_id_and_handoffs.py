"""add board_id columns and issue_handoffs table

Revision ID: 0004_add_board_id_and_handoffs
Revises: 0003_issue_collaboration_records
Create Date: 2026-06-03

Adds the schema pieces for Kanban Protocol:
- ``board_id`` column on every Kanban-Protocol-aware table, defaulting to
  ``"board-default"`` so the migration is non-destructive on existing rows.
- ``issue_handoffs`` table: durable queue items with a status machine
  (pending / accepted / in_progress / completed / blocked / cancelled).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_add_board_id_and_handoffs"
down_revision = "0003_issue_collaboration_records"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type(is_pg: bool):
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    is_pg = _is_postgres()
    default_board = "board-default"

    # ---------------------------------------------------------------- board_id
    # Add board_id to every Kanban-Protocol-aware table. Nullable for safety
    # on pre-migration rows; we backfill below.
    tables_with_board = [
        "issues",
        "issue_events",
        "issue_comments",
        "issue_artifacts",
        "ecc_jobs",
    ]
    for table in tables_with_board:
        if is_pg:
            # 3-step pattern: add nullable, backfill, alter to NOT NULL.
            op.add_column(
                table,
                sa.Column(
                    "board_id",
                    sa.String(64),
                    nullable=True,
                ),
            )
            op.execute(
                f"UPDATE {table} SET board_id = '{default_board}' "
                f"WHERE board_id IS NULL"
            )
            op.alter_column(
                table,
                "board_id",
                nullable=False,
                server_default=default_board,
            )
        else:
            # SQLite does not support ``ALTER TABLE ... ALTER COLUMN ...
            # SET NOT NULL`` and the project's env.py keeps batch mode off,
            # so add the column with NOT NULL + server_default in a single
            # ADD COLUMN. The server_default populates existing rows.
            op.add_column(
                table,
                sa.Column(
                    "board_id",
                    sa.String(64),
                    nullable=False,
                    server_default=default_board,
                ),
            )
        op.create_index(
            f"ix_{table}_board_id",
            table,
            ["board_id"],
        )

    # ---------------------------------------------------------------- handoffs
    op.create_table(
        "issue_handoffs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default=default_board),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("from_lane", sa.String(32), nullable=True),
        sa.Column("to_lane", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("payload", _json_type(is_pg), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("accepted_by", sa.String(128), nullable=True),
        sa.Column("dispatched_by", sa.String(128), nullable=True),
        sa.Column("completed_by", sa.String(128), nullable=True),
        sa.Column("cancelled_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_issue_handoffs_board_id", "issue_handoffs", ["board_id"])
    op.create_index("ix_issue_handoffs_issue_id", "issue_handoffs", ["issue_id"])
    op.create_index("ix_issue_handoffs_status", "issue_handoffs", ["status"])
    op.create_index(
        "ix_issue_handoffs_board_status",
        "issue_handoffs",
        ["board_id", "status"],
    )
    op.create_index(
        "ix_issue_handoffs_issue_created",
        "issue_handoffs",
        ["issue_id", "created_at"],
    )
    op.create_index(
        "ix_issue_handoffs_to_lane_status",
        "issue_handoffs",
        ["to_lane", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_issue_handoffs_to_lane_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_issue_created", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_board_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_issue_id", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_board_id", table_name="issue_handoffs")
    op.drop_table("issue_handoffs")

    for table in [
        "ecc_jobs", "issue_artifacts", "issue_comments", "issue_events", "issues",
    ]:
        op.drop_index(f"ix_{table}_board_id", table_name=table)
        op.drop_column(table, "board_id")
