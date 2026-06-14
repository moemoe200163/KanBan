"""add ci_status to issues

Revision ID: 0008_add_issue_ci_status
Revises: 0007_agent_run_required_role
Create Date: 2026-06-05

Adds CI/PR status tracking on issues:
- ci_status on issues: pending | passed | failed (nullable)
- Enables webhooks to update issue CI state directly
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_issue_ci_status"
down_revision = "0007_agent_run_required_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("ci_status", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_issues_ci_status",
        "issues",
        ["ci_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_issues_ci_status", table_name="issues")
    op.drop_column("issues", "ci_status")
