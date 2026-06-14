"""add agent runtime tables

Revision ID: 0006_agent_runtime_tables
Revises: 0005_llm_provider_configs
Create Date: 2026-06-04

Adds the multi-agent runtime schema:
- agent_workers: tracks worker processes (heartbeat, status, board isolation)
- agent_runs: tracks execution runs (linked to workers and ECC jobs)
- agent_run_events: append-only log of run events
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_agent_runtime_tables"
down_revision = "0005_llm_provider_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_workers ---
    op.create_table(
        "agent_workers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default="board-default"),
        sa.Column("worker_type", sa.String(32), nullable=False),
        sa.Column("harness", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_run_id", sa.String(64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_workers_board_id", "agent_workers", ["board_id"])
    op.create_index("ix_agent_workers_worker_type", "agent_workers", ["worker_type"])
    op.create_index("ix_agent_workers_status", "agent_workers", ["status"])
    op.create_index("ix_agent_workers_board_status", "agent_workers", ["board_id", "status"])

    # --- agent_runs ---
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default="board-default"),
        sa.Column("issue_id", sa.String(64), nullable=True),
        sa.Column("issue_key", sa.String(32), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("command", sa.String(128), nullable=True),
        sa.Column("profile", sa.String(32), nullable=True),
        sa.Column("harness", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_worker_id", "agent_runs", ["worker_id"])
    op.create_index("ix_agent_runs_board_id", "agent_runs", ["board_id"])
    op.create_index("ix_agent_runs_issue_id", "agent_runs", ["issue_id"])
    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_board_status", "agent_runs", ["board_id", "status"])
    op.create_index("ix_agent_runs_worker_status", "agent_runs", ["worker_id", "status"])

    # --- agent_run_events ---
    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
    op.create_index("ix_agent_run_events_event_type", "agent_run_events", ["event_type"])
    op.create_index("ix_agent_run_events_run_created", "agent_run_events", ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_run_events")
    op.drop_table("agent_runs")
    op.drop_table("agent_workers")
