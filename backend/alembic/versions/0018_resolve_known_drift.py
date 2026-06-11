"""resolve known schema drift — 7 missing/extra columns

Revision ID: 0018_resolve_known_drift
Revises: 0017_issues_archive
Create Date: 2026-06-12

Closes the three remaining model/migration drift items that
``audit_known_drift.json`` was suppressing. The drift was
historical: the IssueArtifact, IssueComment, and IssueHandoff
models declare columns that the original migration didn't
create (or created under a different name).

We don't rename anything. Adding the missing column to the
DB keeps the model honest, and the legacy ``metadata`` column
stays so any old code that still reads it doesn't break.
Application serialization (``to_dict``) already exposes
``metadata`` for clients, so the public contract is
unchanged.

The seven fixes this migration lands:

* issue_artifacts.extra_data    — was missing, model declares JSON
* issue_comments.extra_data    — was missing, model declares JSON
* issue_comments.metadata      — was orphan (model doesn't ref),
                                but kept for backward compat
* issue_handoffs.decision      — was missing, model declares String
* issue_handoffs.review_comment — was missing, model declares Text
* issue_handoffs.reviewed_at   — was missing, model declares DateTime
* issue_handoffs.reviewed_by   — was missing, model declares String

All columns are nullable so the migration is safe to run on
a DB with existing rows. After this migration, the
``audit_known_drift.json`` baseline can drop all 7 entries.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_resolve_known_drift"
down_revision = "0017_issues_archive"
branch_labels = None
depends_on = None


def _json_type(is_pg: bool):
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _safe_add_column(table: str, column: sa.Column) -> None:
    """Add a column if it doesn't already exist.

    Alembic's ``op.add_column`` will raise
    ``DuplicateColumn`` (Postgres) or ``OperationalError`` (SQLite)
    on re-run. We catch both so a re-run of this migration is
    a no-op — critical for the kind of restart loop the
    lifespan hits when the previous migration succeeded but
    failed to stamp the version (see 0018 history).
    """
    from sqlalchemy.exc import ProgrammingError, OperationalError
    try:
        op.add_column(table, column)
    except (ProgrammingError, OperationalError) as exc:
        # ``DuplicateColumn`` on Postgres, "duplicate column name"
        # on SQLite. Treat as a no-op.
        msg = str(exc).lower()
        if "duplicate" in msg or "already exists" in msg:
            return
        raise


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_t = _json_type(is_pg)

    # issue_artifacts — model declares extra_data (JSON, default dict).
    # Was added in 0015 for fresh DBs; the safe-add no-ops the
    # second run.
    _safe_add_column(
        "issue_artifacts",
        sa.Column("extra_data", json_t, nullable=True),
    )

    # issue_comments — model declares extra_data. The legacy
    # ``metadata`` column is left alone for backward compat with
    # any client that still reads it; the new column is the one
    # the model writes through.
    _safe_add_column(
        "issue_comments",
        sa.Column("extra_data", json_t, nullable=True),
    )

    # issue_handoffs — model declares 4 review-side columns the
    # original migration never created. All nullable so existing
    # rows survive the upgrade; the API path will start writing
    # to them as the leader-review flow matures.
    _safe_add_column(
        "issue_handoffs",
        sa.Column("decision", sa.String(32), nullable=True),
    )
    _safe_add_column(
        "issue_handoffs",
        sa.Column("review_comment", sa.Text(), nullable=True),
    )
    _safe_add_column(
        "issue_handoffs",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _safe_add_column(
        "issue_handoffs",
        sa.Column("reviewed_by", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("issue_handoffs", "reviewed_by")
    op.drop_column("issue_handoffs", "reviewed_at")
    op.drop_column("issue_handoffs", "review_comment")
    op.drop_column("issue_handoffs", "decision")
    op.drop_column("issue_comments", "extra_data")
    op.drop_column("issue_artifacts", "extra_data")
