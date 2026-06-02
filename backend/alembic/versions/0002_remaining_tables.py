"""remaining tables: agents, audit_logs, webhook_events, quality_gate_results, users

Revision ID: 0002_remaining_tables
Revises: 0001_initial
Create Date: 2026-06-02

Creates the five tables that ``0001_initial`` did not cover but that the
SQLAlchemy models in ``db.models`` declare. Without this migration the
Postgres path is missing schema for ``agents``, ``audit_logs``,
``webhook_events``, ``quality_gate_results``, and ``users``; any query
that touches those tables blows up at runtime.

JSON columns use ``JSONB`` on Postgres and plain ``JSON`` on SQLite,
matching the precedent set by ``0001_initial`` for ``ecc_jobs.events``.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0002_remaining_tables"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type(is_pg: bool):
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    is_pg = _is_postgres()

    # ------------------------------------------------------------------ agents
    op.create_table(
        "agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("agent_type", sa.String(32), nullable=True),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("capabilities", _json_type(is_pg), nullable=True),
        sa.Column("agent_metadata", _json_type(is_pg), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agents_email", "agents", ["email"], unique=True)
    op.create_index("ix_agents_agent_type", "agents", ["agent_type"])
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_agents_status_available", "agents", ["status", "is_available"])
    op.create_index("ix_agents_created_at", "agents", ["created_at"])

    # -------------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=True),
        sa.Column("agent_name", sa.String(128), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("details", _json_type(is_pg), nullable=True),
        sa.Column("changes", _json_type(is_pg), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_agent_id", "audit_logs", ["agent_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_resource_action", "audit_logs", ["resource", "action"])
    op.create_index("ix_audit_logs_agent_timestamp", "audit_logs", ["agent_id", "timestamp"])
    op.create_index("ix_audit_logs_timestamp_desc", "audit_logs", ["timestamp"])

    # ----------------------------------------------------------- webhook_events
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("webhook_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", _json_type(is_pg), nullable=False),
        sa.Column("headers", _json_type(is_pg), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_events_webhook_id", "webhook_events", ["webhook_id"])
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("ix_webhook_events_status", "webhook_events", ["status"])
    op.create_index("ix_webhook_events_status_next_retry", "webhook_events", ["status", "next_retry_at"])
    op.create_index("ix_webhook_events_created_at", "webhook_events", ["created_at"])

    # ------------------------------------------------- quality_gate_results
    op.create_table(
        "quality_gate_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("issue_id", sa.String(64), nullable=True),
        sa.Column("issue_key", sa.String(32), nullable=True),
        sa.Column("coverage_threshold", sa.String(8), nullable=False),
        sa.Column("max_lint_errors", sa.String(8), nullable=False),
        sa.Column("actual_coverage", sa.String(8), nullable=True),
        sa.Column("actual_lint_errors", sa.String(8), nullable=True),
        sa.Column("actual_test_pass_rate", sa.String(8), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failed_checks", sa.String(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_gate_results_job_id", "quality_gate_results", ["job_id"])
    op.create_index("ix_quality_gate_results_issue_id", "quality_gate_results", ["issue_id"])
    op.create_index("ix_quality_gate_results_verified_at", "quality_gate_results", ["verified_at"])

    # ------------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("password_hash", sa.String(128), nullable=True),
        sa.Column("api_key_fingerprint", sa.String(64), nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username_unique", "users", ["username"], unique=True)
    op.create_index("ix_users_email_unique", "users", ["email"], unique=True)
    op.create_index("ix_users_api_key_fingerprint", "users", ["api_key_fingerprint"])
    op.create_index("ix_users_created_at", "users", ["created_at"])


def downgrade() -> None:
    # users
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_api_key_fingerprint", table_name="users")
    op.drop_index("ix_users_email_unique", table_name="users")
    op.drop_index("ix_users_username_unique", table_name="users")
    op.drop_table("users")

    # quality_gate_results
    op.drop_index("ix_quality_gate_results_verified_at", table_name="quality_gate_results")
    op.drop_index("ix_quality_gate_results_issue_id", table_name="quality_gate_results")
    op.drop_index("ix_quality_gate_results_job_id", table_name="quality_gate_results")
    op.drop_table("quality_gate_results")

    # webhook_events
    op.drop_index("ix_webhook_events_created_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_status_next_retry", table_name="webhook_events")
    op.drop_index("ix_webhook_events_status", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_index("ix_webhook_events_webhook_id", table_name="webhook_events")
    op.drop_table("webhook_events")

    # audit_logs
    op.drop_index("ix_audit_logs_timestamp_desc", table_name="audit_logs")
    op.drop_index("ix_audit_logs_agent_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_agent_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    # agents
    op.drop_index("ix_agents_created_at", table_name="agents")
    op.drop_index("ix_agents_status_available", table_name="agents")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_agent_type", table_name="agents")
    op.drop_index("ix_agents_email", table_name="agents")
    op.drop_table("agents")
