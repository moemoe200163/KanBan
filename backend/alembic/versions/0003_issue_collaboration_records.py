"""issue collaboration records: issue_events, issue_comments, issue_artifacts

Revision ID: 0003_issue_collaboration_records
Revises: 0002_remaining_tables
Create Date: 2026-06-03

Adds the three tables that support P2 (Issue as Agent Collaboration Record):
- ``issue_events``: timeline of all issue-related events (status changes,
  handoffs, decisions, command runs, etc.)
- ``issue_comments``: human/agent notes and discussion on issues
- ``issue_artifacts``: metadata about files, outputs, and evidence linked
  to issues (metadata-only, no binary storage in v1)

JSON columns follow the established pattern: ``JSONB`` on Postgres, plain
``JSON`` on SQLite.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_issue_collaboration_records"
down_revision = "0002_remaining_tables"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type(is_pg: bool):
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    is_pg = _is_postgres()

    # ---------------------------------------------------------------- issue_events
    # Unified timeline for everything that happens to an issue:
    # status changes, handoffs, decisions, command runs, etc.
    op.create_table(
        "issue_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("actor_name", sa.String(128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", _json_type(is_pg), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issue_events_issue_id", "issue_events", ["issue_id"])
    op.create_index("ix_issue_events_event_type", "issue_events", ["event_type"])
    op.create_index("ix_issue_events_created_at", "issue_events", ["created_at"])
    op.create_index(
        "ix_issue_events_issue_created",
        "issue_events",
        ["issue_id", "created_at"],
    )

    # -------------------------------------------------------------- issue_comments
    # Human/agent notes and discussion threads on issues.
    op.create_table(
        "issue_comments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=True),
        sa.Column("author_name", sa.String(128), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("comment_type", sa.String(32), nullable=False, default="comment"),
        sa.Column("metadata", _json_type(is_pg), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_issue_comments_issue_id", "issue_comments", ["issue_id"])
    op.create_index("ix_issue_comments_author_id", "issue_comments", ["author_id"])
    op.create_index("ix_issue_comments_comment_type", "issue_comments", ["comment_type"])
    op.create_index(
        "ix_issue_comments_issue_created",
        "issue_comments",
        ["issue_id", "created_at"],
    )

    # ------------------------------------------------------------- issue_artifacts
    # Metadata about files, outputs, and evidence linked to issues.
    # v1 is metadata-only: no binary storage, no upload pipeline.
    op.create_table(
        "issue_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("path_or_url", sa.String(1024), nullable=True),
        sa.Column("sensitivity", sa.String(32), nullable=False, default="public"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata", _json_type(is_pg), nullable=True),
        sa.Column("created_by_id", sa.String(64), nullable=True),
        sa.Column("created_by_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issue_artifacts_issue_id", "issue_artifacts", ["issue_id"])
    op.create_index("ix_issue_artifacts_job_id", "issue_artifacts", ["job_id"])
    op.create_index("ix_issue_artifacts_artifact_type", "issue_artifacts", ["artifact_type"])
    op.create_index("ix_issue_artifacts_created_at", "issue_artifacts", ["created_at"])
    op.create_index(
        "ix_issue_artifacts_issue_created",
        "issue_artifacts",
        ["issue_id", "created_at"],
    )


def downgrade() -> None:
    # issue_artifacts
    op.drop_index("ix_issue_artifacts_issue_created", table_name="issue_artifacts")
    op.drop_index("ix_issue_artifacts_created_at", table_name="issue_artifacts")
    op.drop_index("ix_issue_artifacts_artifact_type", table_name="issue_artifacts")
    op.drop_index("ix_issue_artifacts_job_id", table_name="issue_artifacts")
    op.drop_index("ix_issue_artifacts_issue_id", table_name="issue_artifacts")
    op.drop_table("issue_artifacts")

    # issue_comments
    op.drop_index("ix_issue_comments_issue_created", table_name="issue_comments")
    op.drop_index("ix_issue_comments_comment_type", table_name="issue_comments")
    op.drop_index("ix_issue_comments_author_id", table_name="issue_comments")
    op.drop_index("ix_issue_comments_issue_id", table_name="issue_comments")
    op.drop_table("issue_comments")

    # issue_events
    op.drop_index("ix_issue_events_issue_created", table_name="issue_events")
    op.drop_index("ix_issue_events_created_at", table_name="issue_events")
    op.drop_index("ix_issue_events_event_type", table_name="issue_events")
    op.drop_index("ix_issue_events_issue_id", table_name="issue_events")
    op.drop_table("issue_events")
