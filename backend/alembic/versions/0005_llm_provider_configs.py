"""add llm_provider_configs table

Revision ID: 0005_llm_provider_configs
Revises: 0004_add_board_id_and_handoffs
Create Date: 2026-06-04

Adds persistent LLM provider configuration storage:
- API keys (encrypted), base URLs, model selections
- Health check results (status, latency, errors)
- Replaces the in-memory registry stub
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_llm_provider_configs"
down_revision = "0004_add_board_id_and_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider_id", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("endpoint_path", sa.String(128), nullable=True),
        sa.Column("api_shape", sa.String(32), nullable=True),
        sa.Column("auth_type", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("api_key_encrypted", sa.String(1024), nullable=True),
        sa.Column("api_key_prefix", sa.String(16), nullable=True),
        sa.Column("api_key_last4", sa.String(8), nullable=True),
        sa.Column("last_test_status", sa.String(32), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(32), nullable=True),
        sa.Column("last_error_message", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_llm_provider_configs_provider_id",
        "llm_provider_configs",
        ["provider_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_provider_configs_provider_id", table_name="llm_provider_configs")
    op.drop_table("llm_provider_configs")
