"""queue hardening — retry, heartbeat, max runtime

Revision ID: 0009_queue_hardening
Revises: 0008_add_issue_ci_status
Create Date: 2026-06-05

Adds durability fields to agent_runs for:
- Retry with backoff: retry_count, max_retries, next_retry_at
- Run-level heartbeat: last_heartbeat_at
- Max runtime enforcement: max_runtime_seconds

Adds stale-worker detection to agent_workers:
- stale_threshold_seconds config (stored in extra_metadata)
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_queue_hardening"
down_revision = "0008_add_issue_ci_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_runs: retry + heartbeat + max runtime ---
    op.add_column(
        "agent_runs",
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("max_runtime_seconds", sa.Integer, nullable=True),
    )
    op.create_index(
        "ix_agent_runs_retry",
        "agent_runs",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_retry", table_name="agent_runs")
    op.drop_column("agent_runs", "max_runtime_seconds")
    op.drop_column("agent_runs", "last_heartbeat_at")
    op.drop_column("agent_runs", "next_retry_at")
    op.drop_column("agent_runs", "max_retries")
    op.drop_column("agent_runs", "retry_count")
