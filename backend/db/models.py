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
    BigInteger,
    LargeBinary,
    Index,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID


def _utcnow():
    return datetime.now(timezone.utc)


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
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    profile = Column(String(32), nullable=True, index=True)
    labels = Column(JSON, nullable=True, default=list)
    assignee_id = Column(String(64), nullable=True, index=True)
    assignee_name = Column(String(128), nullable=True)
    story_points = Column(String(8), nullable=True)
    dependencies = Column(JSON, nullable=True, default=list)
    pr_url = Column(String(512), nullable=True)
    ci_status = Column(String(32), nullable=True, index=True)  # pending | passed | failed
    # Mavis-collaboration fields: epics + structured acceptance criteria.
    # ``parent_id`` is a self-FK so an issue can belong to an epic.
    # ``acceptance_criteria`` is a list of {id, text, done} entries; the
    # front-end renders the checklist, and a future AI agent can use
    # it as a completion gate.
    parent_id = Column(String(64), ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True)
    acceptance_criteria = Column(JSON, nullable=True, default=list)
    # Soft-delete columns. ``is_archived`` is the fast filter the
    # board endpoint hits; ``archived_at`` is the audit trail.
    is_archived = Column(Boolean, nullable=False, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
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
            "boardId": self.board_id,
            "profile": self.profile,
            "labels": self.labels or [],
            "assigneeId": self.assignee_id,
            "assigneeName": self.assignee_name,
            "storyPoints": self.story_points,
            "dependencies": self.dependencies or [],
            "prUrl": self.pr_url,
            "ciStatus": self.ci_status,
            "parentId": self.parent_id,
            "acceptanceCriteria": self.acceptance_criteria or [],
            "isArchived": bool(self.is_archived),
            "archivedAt": self.archived_at.isoformat() if self.archived_at else None,
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
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)

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
            "boardId": self.board_id,
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


# ---------------------------------------------------------------------------
# P2: Issue Collaboration Records
# ---------------------------------------------------------------------------


class IssueEvent(Base):
    """
    IssueEvent records everything that happens to an issue: status changes,
    handoffs, decisions, command runs, etc.

    Provides a durable audit trail for agent collaboration.
    """
    __tablename__ = "issue_events"

    id = Column(String(64), primary_key=True)
    issue_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    actor_id = Column(String(64), nullable=True)
    actor_name = Column(String(128), nullable=True)
    summary = Column(Text, nullable=True)
    details = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)

    __table_args__ = (
        Index("ix_issue_events_issue_created", "issue_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "issueId": self.issue_id,
            "eventType": self.event_type,
            "actorId": self.actor_id,
            "actorName": self.actor_name,
            "summary": self.summary,
            "details": self.details or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "boardId": self.board_id,
        }


class IssueComment(Base):
    """
    IssueComment stores human/agent notes and discussion on issues.

    comment_type can be: 'comment', 'note', 'decision', 'review', 'handoff'
    """
    __tablename__ = "issue_comments"

    id = Column(String(64), primary_key=True)
    issue_id = Column(String(64), nullable=False, index=True)
    author_id = Column(String(64), nullable=True, index=True)
    author_name = Column(String(128), nullable=True)
    body = Column(Text, nullable=False)
    comment_type = Column(String(32), nullable=False, default="comment", index=True)
    extra_data = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)

    __table_args__ = (
        Index("ix_issue_comments_issue_created", "issue_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "issueId": self.issue_id,
            "authorId": self.author_id,
            "authorName": self.author_name,
            "body": self.body,
            "commentType": self.comment_type,
            "metadata": self.extra_data or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "boardId": self.board_id,
        }


class IssueArtifact(Base):
    """
    IssueArtifact stores metadata about files, outputs, and evidence
    linked to issues.

    v1 is metadata-only: no binary storage, no upload pipeline.
    artifact_type can be: 'file', 'screenshot', 'test_log', 'pr_link',
    'design_doc', 'diff_summary', 'command_output'
    sensitivity can be: 'public', 'internal', 'confidential', 'secret'
    """
    __tablename__ = "issue_artifacts"

    id = Column(String(64), primary_key=True)
    issue_id = Column(String(64), nullable=False, index=True)
    job_id = Column(String(64), nullable=True, index=True)
    title = Column(String(512), nullable=False)
    artifact_type = Column(String(64), nullable=False, index=True)
    source = Column(String(128), nullable=True)
    path_or_url = Column(String(1024), nullable=True)
    sensitivity = Column(String(32), nullable=False, default="public")
    summary = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True, default=dict)
    created_by_id = Column(String(64), nullable=True)
    created_by_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)

    __table_args__ = (
        Index("ix_issue_artifacts_issue_created", "issue_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "issueId": self.issue_id,
            "jobId": self.job_id,
            "title": self.title,
            "artifactType": self.artifact_type,
            "source": self.source,
            "pathOrUrl": self.path_or_url,
            "sensitivity": self.sensitivity,
            "summary": self.summary,
            "metadata": self.extra_data or {},
            "createdById": self.created_by_id,
            "createdByName": self.created_by_name,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "boardId": self.board_id,
        }


class CycleReport(Base):
    """
    CycleReport — a Mavis-style handoff captured after a worker pass.

    One row per cycle on an issue. Written by:

    - The auto-promote hook when an ECC job reaches a terminal success
      state (``review_required`` or ``completed``); the ``verdict`` is
      set to ``auto_passed`` and the progress log mirrors the ECC job
      events. A leader can later override the verdict.
    - The leader manually when overriding the auto decision, e.g.
      when AC are partially met and the issue needs to bounce back to
      ``in_progress``.

    A cycle report is the single artifact that ties together the plan
    the worker started with, what happened during execution, what was
    produced, and whether the leader accepts the result. The Kanban
    detail drawer renders it as the primary review surface.
    """
    __tablename__ = "cycle_reports"

    id = Column(String(64), primary_key=True)
    issue_id = Column(String(64), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(64), nullable=True, index=True)
    author_id = Column(String(64), nullable=True)
    author_name = Column(String(128), nullable=True)
    plan = Column(Text, nullable=False)
    # ``progress_log`` mirrors the ECCJobEvent shape: a list of
    # ``{ts, status, message}`` dicts. Stored as JSON so the safe
    # runner can append incrementally.
    progress_log = Column(JSON, nullable=True, default=list)
    deliverable_summary = Column(Text, nullable=True)
    # Verdict values: pending | pass | fail | blocked | auto_passed.
    # ``auto_passed`` is the auto-promote hook's signature; a leader
    # can later flip it to ``pass`` (with their own reason) or ``fail``.
    verdict = Column(String(32), nullable=False, default="pending", index=True)
    verdict_reason = Column(Text, nullable=True)
    # Plan G: identifies the writer of this report.
    #   ``auto``     — written by the safe-runner auto-promote hook
    #   ``mavis_auto`` — written by Mavis pushing review_required
    #   ``leader``   — written by a leader override
    #   ``None``     — legacy rows from before Plan G
    source = Column(String(32), nullable=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Review gate fields — populated by ``POST /cycle-reports/{id}/review``
    # (see migration 0020). Distinct from the ``verdict`` column:
    # ``verdict`` is the leader's binary accept/reject of the work
    # product, ``decision`` is the leader's *review* of the report
    # itself (approve the report, or send the worker back). A report
    # can carry both — e.g. ``verdict=pass, decision=approved`` after
    # the leader accepts, or ``verdict=pending, decision=changes_requested``
    # when the leader wants the worker to revise.
    decision = Column(String(32), nullable=True)  # 'approved' | 'changes_requested'
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_by_id = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_cycle_reports_issue_created", "issue_id", "created_at"),
        Index("ix_cycle_reports_board_decision", "board_id", "decision"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "issueId": self.issue_id,
            "jobId": self.job_id,
            "authorId": self.author_id,
            "authorName": self.author_name,
            "plan": self.plan,
            "progressLog": self.progress_log or [],
            "deliverableSummary": self.deliverable_summary,
            "verdict": self.verdict,
            "verdictReason": self.verdict_reason,
            "boardId": self.board_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "decision": self.decision,
            "reviewComment": self.review_comment,
            "reviewedAt": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewedBy": self.reviewed_by,
            "reviewedById": self.reviewed_by_id,
        }


class IssueHandoff(Base):
    """
    Durable queue item for Kanban Protocol.

    A handoff is created when an issue is moved from one worker lane to
    another. It carries its own status machine, payload, and audit fields
    so the transition is durable and replayable.
    """
    __tablename__ = "issue_handoffs"

    id = Column(String(64), primary_key=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    issue_id = Column(String(64), ForeignKey("issues.id"), nullable=False, index=True)
    from_lane = Column(String(32), nullable=True)
    to_lane = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    payload = Column(JSON, nullable=True, default=dict)
    block_reason = Column(Text, nullable=True)
    created_by = Column(String(128), nullable=True)
    accepted_by = Column(String(128), nullable=True)
    dispatched_by = Column(String(128), nullable=True)
    completed_by = Column(String(128), nullable=True)
    cancelled_by = Column(String(128), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Review gate fields — nullable, populated only after a review decision.
    decision = Column(String(32), nullable=True)  # 'approve' | 'reject' | 'request_changes'
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_issue_handoffs_board_status", "board_id", "status"),
        Index("ix_issue_handoffs_issue_created", "issue_id", "created_at"),
        Index("ix_issue_handoffs_to_lane_status", "to_lane", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "boardId": self.board_id,
            "issueId": self.issue_id,
            "fromLane": self.from_lane,
            "toLane": self.to_lane,
            "status": self.status,
            "payload": self.payload if isinstance(self.payload, dict) else {},
            "blockReason": self.block_reason or None,
            "createdBy": self.created_by,
            "acceptedBy": self.accepted_by,
            "dispatchedBy": self.dispatched_by,
            "completedBy": self.completed_by,
            "cancelledBy": self.cancelled_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "decision": self.decision,
            "reviewComment": self.review_comment,
            "reviewedAt": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewedBy": self.reviewed_by,
        }


class LLMProviderConfig(Base):
    """
    Persistent LLM provider configuration.

    Stores API keys (encrypted), base URLs, model selections, and
    health check results. Replaces the in-memory stub in registry.py.
    """
    __tablename__ = "llm_provider_configs"

    id = Column(String(64), primary_key=True)  # e.g. "llm_minimax"
    provider_id = Column(String(32), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    base_url = Column(String(512), nullable=True)
    endpoint_path = Column(String(128), nullable=True)
    api_shape = Column(String(32), nullable=True)  # openai-chat | openai-responses | anthropic-messages | ollama
    auth_type = Column(String(32), nullable=True)   # bearer | x-api-key | api-key | none
    model = Column(String(128), nullable=True)
    api_key_encrypted = Column(String(1024), nullable=True)
    api_key_prefix = Column(String(16), nullable=True)
    api_key_last4 = Column(String(8), nullable=True)
    last_test_status = Column(String(32), nullable=True)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    last_latency_ms = Column(Integer, nullable=True)
    last_error_code = Column(String(32), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "providerId": self.provider_id,
            "displayName": self.display_name,
            "enabled": self.enabled,
            "baseUrl": self.base_url,
            "endpointPath": self.endpoint_path,
            "apiShape": self.api_shape,
            "authType": self.auth_type,
            "model": self.model,
            "apiKeyPrefix": self.api_key_prefix,
            "apiKeyLast4": self.api_key_last4,
            "lastTestStatus": self.last_test_status,
            "lastTestAt": self.last_test_at.isoformat() if self.last_test_at else None,
            "lastLatencyMs": self.last_latency_ms,
            "lastErrorCode": self.last_error_code,
            "lastErrorMessage": self.last_error_message,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Agent Runtime — Multi-Agent Worker System
# ---------------------------------------------------------------------------


class AgentWorker(Base):
    """
    Tracks agent worker processes.

    A worker is a long-lived process that claims and executes runs.
    Workers register on startup, send heartbeats, and report status.
    Every worker belongs to a board (board_id) for isolation.
    """
    __tablename__ = "agent_workers"

    id = Column(String(64), primary_key=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    worker_type = Column(String(32), nullable=False, index=True)  # claude-code, codex, safe-runner, etc.
    harness = Column(String(32), nullable=True)  # claude-code, codex, cursor, etc.
    status = Column(String(32), nullable=False, default="idle", index=True)  # idle, claimed, starting, running, stopping, stopped, error
    capabilities = Column(JSON, nullable=True, default=list)
    max_concurrency = Column(Integer, nullable=False, default=1)
    active_run_id = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String(512), nullable=True)
    extra_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_agent_workers_board_status", "board_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "boardId": self.board_id,
            "workerType": self.worker_type,
            "harness": self.harness,
            "status": self.status,
            "capabilities": self.capabilities or [],
            "maxConcurrency": self.max_concurrency,
            "activeRunId": self.active_run_id,
            "claimedAt": self.claimed_at.isoformat() if self.claimed_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "stoppedAt": self.stopped_at.isoformat() if self.stopped_at else None,
            "lastHeartbeatAt": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            "errorMessage": self.error_message,
            "metadata": self.extra_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentRun(Base):
    """
    Tracks execution runs assigned to workers.

    A run is a single execution attempt of a command against an issue.
    It references both the worker that runs it and optionally the ECC job.
    """
    __tablename__ = "agent_runs"

    id = Column(String(64), primary_key=True)
    worker_id = Column(String(64), nullable=True, index=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    issue_id = Column(String(64), nullable=True, index=True)
    issue_key = Column(String(32), nullable=True)
    job_id = Column(String(64), nullable=True, index=True)  # links to ecc_jobs.id
    session_id = Column(String(64), nullable=True, index=True)  # soft ref to agent_sessions.id
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, claimed, running, completed, failed, cancelled
    command = Column(String(128), nullable=True)
    profile = Column(String(32), nullable=True)
    harness = Column(String(32), nullable=True)
    provider = Column(String(32), nullable=True)
    model = Column(String(128), nullable=True)
    required_role = Column(String(32), nullable=True)  # role-based dispatch: backend-dev, frontend-dev, code-reviewer, etc.
    result_summary = Column(Text, nullable=True)
    error_message = Column(String(512), nullable=True)
    # Queue hardening: retry + heartbeat + max runtime
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    max_runtime_seconds = Column(Integer, nullable=True)
    extra_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_board_status", "board_id", "status"),
        Index("ix_agent_runs_worker_status", "worker_id", "status"),
        Index("ix_agent_runs_retry", "status", "next_retry_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workerId": self.worker_id,
            "boardId": self.board_id,
            "issueId": self.issue_id,
            "issueKey": self.issue_key,
            "jobId": self.job_id,
            "sessionId": self.session_id,
            "status": self.status,
            "command": self.command,
            "profile": self.profile,
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "requiredRole": self.required_role,
            "resultSummary": self.result_summary,
            "errorMessage": self.error_message,
            "retryCount": self.retry_count,
            "maxRetries": self.max_retries,
            "nextRetryAt": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "lastHeartbeatAt": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            "maxRuntimeSeconds": self.max_runtime_seconds,
            "metadata": self.extra_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
        }


# AgentRunEvent event_type constants
class RunEventType:
    STATUS_CHANGE = "status_change"
    LOG = "log"
    ERROR = "error"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    WORKER_LOST = "worker_lost"
    HEARTBEAT = "heartbeat"


class AgentRunEvent(Base):
    """
    Logs events within a run (status changes, log lines, errors).

    Events are append-only and ordered by created_at for streaming.
    """
    __tablename__ = "agent_run_events"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)  # status_change, log, error, heartbeat
    message = Column(Text, nullable=True)
    extra_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_agent_run_events_run_created", "run_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "runId": self.run_id,
            "eventType": self.event_type,
            "message": self.message,
            "metadata": self.extra_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AgentSession(Base):
    """Groups multiple runs into a resumable conversation."""
    __tablename__ = "agent_sessions"

    id = Column(String(64), primary_key=True)
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    issue_id = Column(String(64), nullable=True, index=True)
    issue_key = Column(String(32), nullable=True)

    harness = Column(String(32), nullable=True)
    provider = Column(String(32), nullable=True)
    model = Column(String(128), nullable=True)

    status = Column(String(32), nullable=False, default="active", index=True)

    conversation_history = Column(JSON, nullable=True, default=list)
    checkpoint_data = Column(JSON, nullable=True, default=dict)
    provider_resume_ref = Column(String(512), nullable=True)

    total_runs = Column(Integer, nullable=False, default=1)
    total_tokens = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    expires_at = Column(DateTime(timezone=True), nullable=True)
    extra_metadata = Column(JSON, nullable=True, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_sessions_board_status", "board_id", "status"),
        Index("ix_agent_sessions_issue", "issue_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "boardId": self.board_id,
            "issueId": self.issue_id,
            "issueKey": self.issue_key,
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "conversationHistory": self.conversation_history,
            "checkpointData": self.checkpoint_data,
            "providerResumeRef": self.provider_resume_ref,
            "totalRuns": self.total_runs,
            "totalTokens": self.total_tokens,
            "lastError": self.last_error,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.extra_metadata or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "lastRunAt": self.last_run_at.isoformat() if self.last_run_at else None,
        }


# ---------------------------------------------------------------------------
# Agent Roles — configurable role definitions for dispatch and completion
# ---------------------------------------------------------------------------


class AgentRole(Base):
    """
    Configurable agent role definition.

    Seeded from WORKER_LANES on startup; admin-editable at runtime.
    Controls dispatch routing, allowed providers, completion payload
    requirements, and human-approval gates.
    """
    __tablename__ = "agent_roles"

    id = Column(String(64), primary_key=True)
    key = Column(String(32), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    description = Column(String(512), default="")
    allowed_profiles = Column(JSON, default=list)
    default_provider = Column(String(32), default="")
    default_model = Column(String(128), default="")
    allowed_commands = Column(JSON, default=list)
    timeout_seconds = Column(Integer, default=1800)
    retry_policy = Column(String(16), default="none")
    retry_max = Column(Integer, default=0)
    next_roles = Column(JSON, default=list)
    human_approval_required = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)
    required_completion_fields = Column(JSON, default=list)
    system_prompt = Column(Text, default="")
    task_prompt_template = Column(Text, default="")
    review_prompt_template = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "displayName": self.display_name,
            "description": self.description,
            "allowedProfiles": self.allowed_profiles or [],
            "defaultProvider": self.default_provider,
            "defaultModel": self.default_model,
            "allowedCommands": self.allowed_commands or [],
            "timeoutSeconds": self.timeout_seconds,
            "retryPolicy": self.retry_policy,
            "retryMax": self.retry_max,
            "nextRoles": self.next_roles or [],
            "humanApprovalRequired": self.human_approval_required,
            "enabled": self.enabled,
            "isSystem": self.is_system,
            "requiredCompletionFields": self.required_completion_fields or [],
            "systemPrompt": self.system_prompt or "",
            "taskPromptTemplate": self.task_prompt_template or "",
            "reviewPromptTemplate": self.review_prompt_template or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class Artifact(Base):
    """
    Stored file artifact (deliverable, screenshot, log, etc.).

    Each upload is its own row; re-uploading the same logical name with
    ``parent_id`` set creates a version chain. Tags are stored as a JSON
    array on the row for cheap filtering without a join table.
    Blob bytes live inline (``content`` LargeBinary) — the user explicitly
    chose Postgres blob over filesystem for this iteration.
    """
    __tablename__ = "artifacts"

    id = Column(String(64), primary_key=True)
    name = Column(String(512), nullable=False, index=True)
    mime_type = Column(String(256), nullable=False, default="application/octet-stream")
    size_bytes = Column(BigInteger, nullable=False, default=0)
    content = Column(LargeBinary, nullable=False)
    tags = Column(JSON, nullable=False, default=list)
    description = Column(Text, nullable=True, default="")
    uploader = Column(String(128), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(String(64), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True)
    folder_path = Column(String(512), nullable=False, default="/Uploads", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mime_type,
            "sizeBytes": self.size_bytes,
            "tags": self.tags or [],
            "description": self.description or "",
            "uploader": self.uploader or "",
            "version": self.version,
            "parentId": self.parent_id,
            "folderPath": self.folder_path or "/Uploads",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
