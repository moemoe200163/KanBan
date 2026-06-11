"""issues.archive — soft-delete support for the Kanban board

Revision ID: 0017_issues_archive
Revises: 0016_cycle_reports
Create Date: 2026-06-11

Adds two columns to ``issues``:

- ``is_archived`` (boolean, default false) — fast-path flag the
  board endpoint filters on. Cheaper than ``archived_at IS NULL``
  for the common case where most rows are live.
- ``archived_at`` (timestamp, nullable) — the soft-delete
  timestamp. We set it together with ``is_archived`` so audit
  queries ("when did we archive this?") have the answer.

Why soft-delete instead of a hard DELETE:
- Issue has many FKs pointing at it (cycle_reports, handoffs,
  artifacts, agent_runs, issue_events). A hard delete cascades
  and destroys the audit trail that the Mavis collab model
  relies on for the /reviews page and the cycle report flow.
- The board's primary job is to show current work; archived
  issues belong to a "history" surface that operators can
  reach via a toggle, not the main view.
- Reversibility matters: a misclick on Archive shouldn't lose
  the issue's data. ``Unarchive`` is a one-call PATCH.

The hard DELETE endpoint still exists for the admin path —
see the ``DELETE /issues/{id}`` handler added in this commit —
but it's deliberately gated behind admin auth so a regular
operator can't reach it.
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_issues_archive"
down_revision = "0016_cycle_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "issues",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index on ``is_archived`` so the board endpoint's
    # ``WHERE is_archived = false`` clause uses the index.
    op.create_index(
        "ix_issues_is_archived",
        "issues",
        ["is_archived"],
    )
    # Composite index covers the most common board query:
    # ``WHERE board_id = ? AND is_archived = false``.
    op.create_index(
        "ix_issues_board_archived",
        "issues",
        ["board_id", "is_archived"],
    )


def downgrade() -> None:
    op.drop_index("ix_issues_board_archived", table_name="issues")
    op.drop_index("ix_issues_is_archived", table_name="issues")
    op.drop_column("issues", "archived_at")
    op.drop_column("issues", "is_archived")
