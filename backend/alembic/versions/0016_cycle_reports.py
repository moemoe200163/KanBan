"""cycle reports + issue parent linkage + acceptance criteria

Revision ID: 0016_cycle_reports
Revises: 0015_issue_artifact_extra_data
Create Date: 2026-06-11

Adds three things to the schema to support the Mavis-style collaboration
model on the Kanban board:

1. ``cycle_reports`` — one row per worker pass on an issue. Captures the
   plan, the progress log (jsonb list of {ts, message}), the deliverable
   summary, and the verdict (pass | fail | blocked). Auto-written by
   the auto-promote hook when an ECC job reaches a terminal success
   state, and also writable manually by the leader when overriding.

2. ``issues.parent_id`` — every issue can declare a parent. Used to
   group work into epics / Mavis-team parallel tracks without forcing
   a full hierarchy view. Self-referencing FK; parent must belong to
   the same board.

3. ``issues.acceptance_criteria`` — jsonb list of {id, text, done} for
   structured AC. Front-end renders the checklist; safe-runner and
   future AI agents use it to gate completion.

Down revision drops the cycle_reports table and the two new issue
columns. The audit_schema_drift script is the safety net that
catches any future drift between model and migration.
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_cycle_reports"
down_revision = "0015_issue_artifact_extra_data"
branch_labels = None
depends_on = None


def _json_type(is_pg: bool):
    from sqlalchemy.dialects import postgresql
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_t = _json_type(is_pg)

    # -------------------------------------------------------------- cycle_reports
    op.create_table(
        "cycle_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False, index=True),
        sa.Column("job_id", sa.String(64), nullable=True, index=True),
        sa.Column("author_id", sa.String(64), nullable=True),
        sa.Column("author_name", sa.String(128), nullable=True),
        # ``plan`` is the worker's stated plan at the start of the cycle.
        # Free-form text — typically 1-3 sentences. Required because a
        # report without a plan is not a useful handoff.
        sa.Column("plan", sa.Text(), nullable=False),
        # ``progress_log`` is an append-only list of timestamped events
        # captured during execution. Same shape as the ECCJobEvent list
        # so a future migration can lift the safe-runner events into
        # here without translation.
        sa.Column("progress_log", json_t, nullable=True, default=list),
        # ``deliverable_summary`` is what the worker produced — usually
        # a link to an artifact or a short prose summary. Nullable so
        # cycles that fail before producing anything are still valid.
        sa.Column("deliverable_summary", sa.Text(), nullable=True),
        # ``verdict`` is the leader decision: pass | fail | blocked.
        # ``auto_passed`` is reserved for the auto-promote hook.
        sa.Column("verdict", sa.String(32), nullable=False, default="pending", index=True),
        sa.Column("verdict_reason", sa.Text(), nullable=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default="board-default", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_cycle_reports_issue_created", "cycle_reports", ["issue_id", "created_at"])

    # -------------------------------------------------------------- issues.parent_id
    # Self-referencing FK. The board_id match check is enforced at the
    # application layer; SQLAlchemy / Alembic don't support composite
    # FKs against the same table in a portable way across Postgres
    # and SQLite (the test DB).
    op.add_column(
        "issues",
        sa.Column("parent_id", sa.String(64), sa.ForeignKey("issues.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_issues_parent_id", "issues", ["parent_id"])

    # -------------------------------------------------------------- issues.acceptance_criteria
    op.add_column(
        "issues",
        sa.Column("acceptance_criteria", json_t, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("issues", "acceptance_criteria")
    op.drop_index("ix_issues_parent_id", table_name="issues")
    op.drop_column("issues", "parent_id")
    op.drop_index("ix_cycle_reports_issue_created", table_name="cycle_reports")
    op.drop_table("cycle_reports")
