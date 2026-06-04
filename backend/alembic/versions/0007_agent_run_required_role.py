"""add required_role to agent_runs

Revision ID: 0007_agent_run_required_role
Revises: 0006_agent_runtime_tables
Create Date: 2026-06-04

Adds role-based dispatch support:
- required_role on agent_runs: specifies what role/capability is needed
- Enables workers to only claim runs matching their capabilities
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_agent_run_required_role"
down_revision = "0006_agent_runtime_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("required_role", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_agent_runs_board_status_role",
        "agent_runs",
        ["board_id", "status", "required_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_board_status_role", table_name="agent_runs")
    op.drop_column("agent_runs", "required_role")
