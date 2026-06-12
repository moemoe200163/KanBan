"""drop legacy metadata columns on issue_artifacts and issue_comments

Revision ID: 0019_drop_legacy_metadata
Revises: 0018_resolve_known_drift
Create Date: 2026-06-12

The original migration 0003 created the column as ``metadata``
on ``issue_artifacts`` and ``issue_comments``, but the SQLAlchemy
model later declared it as ``extra_data``. 0018 added the
``extra_data`` column on both tables so the model writes now
hit the correct field; this migration removes the now-orphan
``metadata`` column to close out the audit drift.

The application serialization (``IssueArtifact.to_dict``,
``IssueComment.to_dict``) reads from ``extra_data`` and exposes
it to clients as ``metadata`` (camelCase), so the public API
shape is unchanged. The legacy column on the DB is internal
only.

Down revision restores the column with the same JSONB shape
it had pre-drop. We don't preserve data — the column is empty
in practice (model has only ever written to ``extra_data``).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_drop_legacy_metadata"
down_revision = "0018_resolve_known_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the orphan column. Cross-dialect safe: ``IF EXISTS`` is
    # Postgres-only and SQLite would error on it, so we check the
    # inspector first. ``op.batch_alter_table`` handles SQLite's
    # 3.35+ ``DROP COLUMN`` automatically.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("issue_artifacts", "issue_comments"):
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "metadata" in existing:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column("metadata")


def downgrade() -> None:
    # Restore the column on rollback. No data to recover — the
    # model never wrote to it — so the type is enough.
    op.add_column(
        "issue_artifacts",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "issue_comments",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
