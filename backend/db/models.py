"""
DevFlow Backend - Database Models

SQLAlchemy 2.0 models for Issue tracking, Agent management,
Audit logging, Webhook events, and ECC jobs.
"""

from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Column,
    String,
    DateTime,
    JSON,
    Text,
    Boolean,
    Integer,
    Index,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class Issue(Base):
    """
    Issue model representing a task/feature/bug in the system.
    """
    __tablename__ = "issues"

    id = Column(String(64), primary_key=True)
    key = Column(String(32), unique=True, nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="backlog", index=True)
    priority = Column(String(16), nullable=True, index=True)
    profile = Column(String(32), nullable=True, index=True)
    labels = Column(JSON, nullable=True, default=list)
    assignee_id = Column(String(64), nullable=True, index=True)
    assignee_name = Column(String(128), nullable=True)
    story_points = Column(String(8), nullable=True)
    dependencies = Column(JSON, nullable=True, default=list)
    pr_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_issues_status_priority", "status", "priority"),
        Index("ix_issues_assignee_status", "assignee_id", "status"),
        Index("ix_issues_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "profile": self.profile,
            "labels": self.labels or [],
            "assigneeId": self.assignee_id,
            "assigneeName": self.assignee_name,
            "storyPoints": self.story_points,
            "dependencies": self.dependencies or [],
            "prUrl": self.pr_url,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class Agent(Base):
    """
    Agent model representing a team member/agent in the system.
    """
    __tablename__ = "agents"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    email = Column(String(256), nullable=True, unique=True, index=True)
    agent_type = Column(String(32), nullable=True, index=True)
    role = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    is_available = Column(Boolean, nullable=False, default=True)
    capabilities = Column(JSON, nullable=True, default=list)
    agent_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agents_status_available", "status", "is_available"),
        Index("ix_agents_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "agentType": self.agent_type,
            "role": self.role,
            "status": self.status,
            "isAvailable": self.is_available,
            "capabilities": self.capabilities or [],
            "metadata": self.agent_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class AuditLog(Base):
    """
    AuditLog model for tracking all system actions and changes.
    """
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), nullable=True, index=True)
    agent_name = Column(String(128), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    resource = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(64), nullable=True, index=True)
    details = Column(JSON, nullable=True, default=dict)
    changes = Column(JSON, nullable=True, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ix_audit_logs_resource_action", "resource", "action"),
        Index("ix_audit_logs_agent_timestamp", "agent_id", "timestamp"),
        Index("ix_audit_logs_timestamp_desc", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agentId": self.agent_id,
            "agentName": self.agent_name,
            "action": self.action,
            "resource": self.resource,
            "resourceId": self.resource_id,
            "details": self.details or {},
            "changes": self.changes or {},
            "ipAddress": self.ip_address,
            "userAgent": self.user_agent,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class WebhookEvent(Base):
    """
    WebhookEvent model for storing outbound webhook deliveries.
    """
    __tablename__ = "webhook_events"

    id = Column(String(64), primary_key=True)
    webhook_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    headers = Column(JSON, nullable=True, default=dict)
    status = Column(String(16), nullable=False, default="pending", index=True)
    response_status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error_message = Column(String(512), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    sent_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_webhook_events_status_next_retry", "status", "next_retry_at"),
        Index("ix_webhook_events_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "webhookId": self.webhook_id,
            "eventType": self.event_type,
            "payload": self.payload or {},
            "headers": self.headers or {},
            "status": self.status,
            "responseStatusCode": self.response_status_code,
            "responseBody": self.response_body,
            "errorMessage": self.error_message,
            "attempts": self.attempts,
            "maxAttempts": self.max_attempts,
            "nextRetryAt": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "sentAt": self.sent_at.isoformat() if self.sent_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
        }


class JobModel(Base):
    """
    ECC Job model for persisting ECCDispatchJob state.

    Stores job state and events. The `events` column is a JSON column so it
    deserializes to a list on both SQLite (TEXT) and Postgres (JSONB).
    """
    __tablename__ = "ecc_jobs"

    id = Column(String(64), primary_key=True)
    issue_id = Column(String(64), nullable=False, index=True)
    issue_key = Column(String(32), nullable=False, index=True)
    command = Column(String(128), nullable=False)
    profile = Column(String(32), nullable=False)
    harness = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    message = Column(String(512), nullable=True)
    events = Column(JSON, nullable=False, default=list)  # JSON array of ECCJobEvent

    __table_args__ = (
        # Note: status already gets an auto-index from `Column(..., index=True)`.
        Index("ix_ecc_jobs_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        events = self.events if isinstance(self.events, list) else []
        return {
            "id": self.id,
            "issue_id": self.issue_id,
            "issue_key": self.issue_key,
            "command": self.command,
            "profile": self.profile,
            "harness": self.harness,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message": self.message,
            "events": events,
        }


class QualityGateResult(Base):
    """
    QualityGateResult model for storing quality gate verification results.

    Stores metrics from job verification including coverage, lint errors,
    test pass rate, and overall pass/fail status.
    """
    __tablename__ = "quality_gate_results"

    id = Column(String(64), primary_key=True)
    job_id = Column(String(64), nullable=False, index=True)
    issue_id = Column(String(64), nullable=True, index=True)
    issue_key = Column(String(32), nullable=True)

    # Verification thresholds
    coverage_threshold = Column(String(8), nullable=False)  # float stored as string
    max_lint_errors = Column(String(8), nullable=False)     # int stored as string

    # Actual metrics
    actual_coverage = Column(String(8), nullable=True)       # float stored as string
    actual_lint_errors = Column(String(8), nullable=True)   # int stored as string
    actual_test_pass_rate = Column(String(8), nullable=True) # float stored as string

    # Overall result
    passed = Column(Boolean, nullable=False, default=False)
    failed_checks = Column(String, nullable=True)  # JSON array of failed check names

    # Metadata
    verified_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Note: job_id and issue_id already get auto-indexes from `Column(..., index=True)`.
        Index("ix_quality_gate_results_verified_at", "verified_at"),
    )

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "job_id": self.job_id,
            "issue_id": self.issue_id,
            "issue_key": self.issue_key,
            "coverage_threshold": float(self.coverage_threshold) if self.coverage_threshold else None,
            "max_lint_errors": int(self.max_lint_errors) if self.max_lint_errors else None,
            "actual_coverage": float(self.actual_coverage) if self.actual_coverage else None,
            "actual_lint_errors": int(self.actual_lint_errors) if self.actual_lint_errors else None,
            "actual_test_pass_rate": float(self.actual_test_pass_rate) if self.actual_test_pass_rate else None,
            "passed": self.passed,
            "failed_checks": json.loads(self.failed_checks) if self.failed_checks else [],
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """
    User model for authentication and user management.

    Stores user credentials (password hash or API key fingerprint),
    profile information, and authentication metadata.
    """
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    username = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(256), unique=True, nullable=True, index=True)
    password_hash = Column(String(128), nullable=True)  # PBKDF2-SHA256 hash
    api_key_fingerprint = Column(String(64), nullable=True, index=True)  # SHA256 of API key

    # User profile
    avatar_url = Column(String(512), nullable=True)
    full_name = Column(String(256), nullable=True)
    role = Column(String(32), nullable=True, default="member")

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_users_username_unique", "username", unique=True),
        Index("ix_users_email_unique", "email", unique=True),
        Index("ix_users_created_at", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "avatarUrl": self.avatar_url,
            "fullName": self.full_name,
            "role": self.role,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "lastLoginAt": self.last_login_at.isoformat() if self.last_login_at else None,
        }
