"""initial schema: issues and ecc_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-01

Creates the two tables that the FastAPI control plane relies on for
persistent state. Mirrors the SQLAlchemy models in ``db.models``:

- ``issues`` tracks kanban cards (status, priority, profile, etc.).
- ``ecc_jobs`` tracks ECC control-plane jobs and their event timeline.

On Postgres the ``events`` column is created as ``JSONB`` so we can
query into it later. SQLite has no native JSONB so we fall back to
plain ``JSON`` (stored as ``TEXT``), which matches what ``create_all``
emits in the SQLite pytest path.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()

    op.create_table(
        "issues",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("profile", sa.String(32), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=True),
        sa.Column("assignee_id", sa.String(64), nullable=True),
        sa.Column("assignee_name", sa.String(128), nullable=True),
        sa.Column("story_points", sa.String(8), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=True),
        sa.Column("pr_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issues_key", "issues", ["key"], unique=True)
    op.create_index("ix_issues_status", "issues", ["status"])
    op.create_index("ix_issues_priority", "issues", ["priority"])
    op.create_index("ix_issues_profile", "issues", ["profile"])
    op.create_index("ix_issues_assignee_id", "issues", ["assignee_id"])
    op.create_index("ix_issues_status_priority", "issues", ["status", "priority"])
    op.create_index("ix_issues_assignee_status", "issues", ["assignee_id", "status"])
    op.create_index("ix_issues_created_at", "issues", ["created_at"])

    events_type = JSONB() if is_pg else sa.JSON()
    if is_pg:
        events_default = sa.text("'[]'::jsonb")
    else:
        events_default = None  # SQLite has no JSON literal default; app supplies it.

    op.create_table(
        "ecc_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("issue_id", sa.String(64), nullable=False),
        sa.Column("issue_key", sa.String(32), nullable=False),
        sa.Column("command", sa.String(128), nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("harness", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("message", sa.String(512), nullable=True),
        sa.Column("events", events_type, nullable=False, server_default=events_default),
    )
    op.create_index("ix_ecc_jobs_issue_id", "ecc_jobs", ["issue_id"])
    op.create_index("ix_ecc_jobs_issue_key", "ecc_jobs", ["issue_key"])
    op.create_index("ix_ecc_jobs_status", "ecc_jobs", ["status"])
    op.create_index("ix_ecc_jobs_created_at", "ecc_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ecc_jobs_created_at", table_name="ecc_jobs")
    op.drop_index("ix_ecc_jobs_status", table_name="ecc_jobs")
    op.drop_index("ix_ecc_jobs_issue_key", table_name="ecc_jobs")
    op.drop_index("ix_ecc_jobs_issue_id", table_name="ecc_jobs")
    op.drop_table("ecc_jobs")

    op.drop_index("ix_issues_created_at", table_name="issues")
    op.drop_index("ix_issues_assignee_status", table_name="issues")
    op.drop_index("ix_issues_status_priority", table_name="issues")
    op.drop_index("ix_issues_assignee_id", table_name="issues")
    op.drop_index("ix_issues_profile", table_name="issues")
    op.drop_index("ix_issues_priority", table_name="issues")
    op.drop_index("ix_issues_status", table_name="issues")
    op.drop_index("ix_issues_key", table_name="issues")
    op.drop_table("issues")
