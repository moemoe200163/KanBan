"""add artifacts table for shared deliverable storage

Revision ID: 0013_artifacts
Revises: 0012_agent_role_prompt_templates
Create Date: 2026-06-11

Adds a generic file-deliverable table for team-shared artifacts:
- Inline blob storage (Postgres bytea), JSON tags for cheap filtering
- Self-referential parent_id for version chains (re-uploads of same name)
- No auth/role gating in this iteration (調研階段先快上)
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_artifacts"
down_revision = "0012_agent_role_prompt_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(256), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uploader", sa.String(128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_id", sa.String(64), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_name", "artifacts", ["name"])
    op.create_index("ix_artifacts_parent_id", "artifacts", ["parent_id"])
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_created_at", table_name="artifacts")
    op.drop_index("ix_artifacts_parent_id", table_name="artifacts")
    op.drop_index("ix_artifacts_name", table_name="artifacts")
    op.drop_table("artifacts")
