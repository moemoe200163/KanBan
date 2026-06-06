"""add agent_sessions table and agent_runs.session_id

Revision ID: 0010_agent_sessions
Revises: 0009_queue_hardening
Create Date: 2026-06-06

Adds the agent_sessions table for session resume support, and a soft-ref
session_id column on agent_runs linking back to agent_sessions.id.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_agent_sessions"
down_revision = "0009_queue_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_sessions table ---
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default="board-default"),
        sa.Column("issue_id", sa.String(64), nullable=True),
        sa.Column("issue_key", sa.String(32), nullable=True),
        sa.Column("harness", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("conversation_history", sa.JSON, nullable=True),
        sa.Column("checkpoint_data", sa.JSON, nullable=True),
        sa.Column("provider_resume_ref", sa.String(512), nullable=True),
        sa.Column("total_runs", sa.Integer, nullable=False, server_default="1"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_sessions_board_id", "agent_sessions", ["board_id"])
    op.create_index("ix_agent_sessions_issue_id", "agent_sessions", ["issue_id"])
    op.create_index("ix_agent_sessions_status", "agent_sessions", ["status"])
    op.create_index(
        "ix_agent_sessions_board_status",
        "agent_sessions",
        ["board_id", "status"],
    )
    op.create_index(
        "ix_agent_sessions_issue",
        "agent_sessions",
        ["issue_id", "status"],
    )

    # --- agent_runs: add session_id soft ref ---
    op.add_column(
        "agent_runs",
        sa.Column("session_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_session_id", table_name="agent_runs")
    op.drop_column("agent_runs", "session_id")

    op.drop_index("ix_agent_sessions_issue", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_board_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_issue_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_board_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
