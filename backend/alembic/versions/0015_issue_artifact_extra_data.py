"""add extra_data to issue_artifacts (model/migration drift fix)

Revision ID: 0015_issue_artifact_extra_data
Revises: 0014_artifact_folder_path
Create Date: 2026-06-11

The IssueArtifact SQLAlchemy model declares an ``extra_data`` JSON
column, but the original migration ``0003_issue_collaboration_records``
created the table with a column named ``metadata``. The two have been
out of sync since the model was first written, and any code path that
actually reads or writes through SQLAlchemy (rather than hand-written
SQL) explodes with ``UndefinedColumnError`` at runtime — e.g. the
``/api/v1/deliveries`` list endpoint.

We resolve the drift by adding the missing ``extra_data`` column on
Postgres (jsonb, default empty object) and SQLite (JSON). Both the
column on the model and the column on the database now exist, and
the application's serialization layer (``to_dict``) continues to
expose the field as ``metadata`` for clients so the public API is
unchanged.

Down revision removes the column, restoring the original drift.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_issue_artifact_extra_data"
down_revision = "0014_artifact_folder_path"
branch_labels = None
depends_on = None


def _json_type(is_pg: bool):
    # ``JSON`` on SQLite stores the value as TEXT under the hood; on
    # Postgres we get the real ``jsonb`` with binary storage and
    # operator support. The application only ever reads/writes dict
    # values, so either backend is fine.
    from sqlalchemy.dialects import postgresql
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def upgrade() -> None:
    # Detect the dialect lazily — `op.get_bind()` returns a proxy that
    # is only valid inside a migration callback, never at module
    # import time.
    is_pg = op.get_bind().dialect.name == "postgresql"
    op.add_column(
        "issue_artifacts",
        sa.Column("extra_data", _json_type(is_pg), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("issue_artifacts", "extra_data")
