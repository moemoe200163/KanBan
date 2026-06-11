"""add review fields to cycle_reports

Revision ID: 0020_cycle_reports_review
Revises: 0019_drop_legacy_metadata
Create Date: 2026-06-12

The P0/P1 cycle review flow lets a leader approve or request
changes on a cycle report. The 0018 migration added the same
fields to ``issue_handoffs`` (the Kanban Protocol handoffs), but
the review endpoint at ``/cycle-reports/{id}/review`` writes to
the Mavis-style ``cycle_reports`` table — they are separate
concepts (one is the auto-promote worker handoff, the other is
the explicit kanban-protocol lane handoff) and live in separate
tables without a foreign key.

Adds five columns, all nullable, all defaulted to NULL so
existing rows survive the upgrade:

* ``decision``        — ``approved`` | ``changes_requested`` | NULL
* ``review_comment``  — free-form reviewer note (text)
* ``reviewed_at``     — UTC timestamp the review landed
* ``reviewed_by``     — username of the reviewer (string)
* ``reviewed_by_id``  — user-id of the reviewer (string, for joins)

Decision values mirror the task brief: ``approved`` (green light)
or ``changes_requested`` (worker needs another pass). The
endpoint enforces this enum and rejects any other value with
422. A NULL ``decision`` means the report hasn't been reviewed
yet (matches the existing ``pending`` verdict semantic).

A composite index on ``(board_id, decision)`` makes the
/pending vs. /reviewed split on the reviews page a single
index scan instead of a full table read once the table grows.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_cycle_reports_review"
down_revision = "0019_drop_legacy_metadata"
branch_labels = None
depends_on = None


def _safe_add_column(table: str, column: sa.Column) -> None:
    """Add a column if it doesn't already exist.

    The drift-audit CI gate runs ``op.add_column`` and a re-run
    on a DB that already has the column would otherwise raise
    ``DuplicateColumn`` on Postgres. We catch the equivalent
    errors so this migration is idempotent — critical for the
    lifespan's restart loop (see 0018 history).
    """
    from sqlalchemy.exc import ProgrammingError, OperationalError
    try:
        op.add_column(table, column)
    except (ProgrammingError, OperationalError) as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "already exists" in msg:
            return
        raise


def upgrade() -> None:
    # ``decision`` is short (32 chars) — only the enum literals
    # land here, not free-form text. ``review_comment`` is
    # unbounded so reviewers can leave detailed feedback.
    _safe_add_column(
        "cycle_reports",
        sa.Column("decision", sa.String(32), nullable=True),
    )
    _safe_add_column(
        "cycle_reports",
        sa.Column("review_comment", sa.Text(), nullable=True),
    )
    _safe_add_column(
        "cycle_reports",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _safe_add_column(
        "cycle_reports",
        sa.Column("reviewed_by", sa.String(128), nullable=True),
    )
    _safe_add_column(
        "cycle_reports",
        sa.Column("reviewed_by_id", sa.String(64), nullable=True),
    )

    # Composite index — the reviews page splits cycle reports
    # by ``decision IS NULL`` vs ``decision IS NOT NULL`` and
    # filters to a single board. Indexing ``(board_id,
    # decision)`` makes both queries a single index scan.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cycle_reports_board_decision "
        "ON cycle_reports (board_id, decision)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cycle_reports_board_decision")
    op.drop_column("cycle_reports", "reviewed_by_id")
    op.drop_column("cycle_reports", "reviewed_by")
    op.drop_column("cycle_reports", "reviewed_at")
    op.drop_column("cycle_reports", "review_comment")
    op.drop_column("cycle_reports", "decision")
