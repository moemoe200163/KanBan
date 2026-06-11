"""add folder_path to artifacts (virtual folder support)

Revision ID: 0014_artifact_folder_path
Revises: 0013_artifacts
Create Date: 2026-06-11

Splits the original /artifacts page concept into two distinct
products (Uploads vs Deliveries) and gives user uploads a virtual
folder taxonomy stored as DB metadata — no filesystem moves.

- Adds folder_path column with default '/Uploads'
- Index for cheap folder filter
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_artifact_folder_path"
down_revision = "0013_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("folder_path", sa.String(512), nullable=False, server_default="/Uploads"),
    )
    op.create_index("ix_artifacts_folder_path", "artifacts", ["folder_path"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_folder_path", table_name="artifacts")
    op.drop_column("artifacts", "folder_path")
