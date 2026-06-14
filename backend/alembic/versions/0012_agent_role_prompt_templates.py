"""add prompt template fields to agent_roles

Revision ID: 0012_agent_role_prompt_templates
Revises: 0011_agent_roles
Create Date: 2026-06-09

Adds system_prompt, task_prompt_template, and review_prompt_template
columns to agent_roles for DB-backed prompt customization.
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_agent_role_prompt_templates"
down_revision = "0011_agent_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_roles", sa.Column("system_prompt", sa.Text, server_default=""))
    op.add_column("agent_roles", sa.Column("task_prompt_template", sa.Text, server_default=""))
    op.add_column("agent_roles", sa.Column("review_prompt_template", sa.Text, server_default=""))


def downgrade() -> None:
    op.drop_column("agent_roles", "review_prompt_template")
    op.drop_column("agent_roles", "task_prompt_template")
    op.drop_column("agent_roles", "system_prompt")
