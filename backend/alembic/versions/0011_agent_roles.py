"""add agent_roles table

Revision ID: 0011_agent_roles
Revises: 0010_agent_sessions
Create Date: 2026-06-08

Adds the agent_roles table for configurable role definitions used in
dispatch routing, completion validation, and human-approval gates.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_agent_roles"
down_revision = "0010_agent_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_roles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), server_default=""),
        sa.Column("allowed_profiles", sa.JSON, nullable=True),
        sa.Column("default_provider", sa.String(32), server_default=""),
        sa.Column("default_model", sa.String(128), server_default=""),
        sa.Column("allowed_commands", sa.JSON, nullable=True),
        sa.Column("timeout_seconds", sa.Integer, server_default="1800"),
        sa.Column("retry_policy", sa.String(16), server_default="none"),
        sa.Column("retry_max", sa.Integer, server_default="0"),
        sa.Column("next_roles", sa.JSON, nullable=True),
        sa.Column("human_approval_required", sa.Boolean, server_default="0"),
        sa.Column("enabled", sa.Boolean, server_default="1"),
        sa.Column("is_system", sa.Boolean, server_default="0"),
        sa.Column("required_completion_fields", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_roles_key", "agent_roles", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_roles_key", table_name="agent_roles")
    op.drop_table("agent_roles")
