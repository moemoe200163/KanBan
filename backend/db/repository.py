"""
DevFlow Backend - Database Repository

All SQLAlchemy I/O lives here. Endpoints should never import from
db.models directly. This keeps the surface small and lets us:
- Mock storage in tests
- Swap backends (SQLite <-> Postgres) without touching endpoints
- Centralize error handling (DB failures don't break API responses)

Errors are logged and swallowed at the function boundary. Reads return
empty/None on failure; writes raise so the caller can decide how to react.
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select, func

from db import database as _db
from db.models import (
    Issue as IssueModel,
    JobModel,
    AuditLog,
    IssueEvent,
    IssueComment,
    IssueArtifact,
    AgentWorker,
    AgentRun,
    AgentRunEvent,
)


def _get_sessionmaker():
    """Return the current AsyncSessionLocal from db.database.

    This indirection lets tests swap the engine/sessionmaker via
    `monkeypatch.setattr(db.database, "AsyncSessionLocal", ...)` without
    the repository needing to be re-imported.
    """
    return _db.AsyncSessionLocal


def _ensure_init():
    """Return the current ensure_db_init from db.database."""
    return _db.ensure_db_init

logger = logging.getLogger(__name__)

__all__ = [
    "SEED_ISSUES",
    "seed_if_empty",
    "list_issues",
    "get_issue",
    "upsert_issue",
    "update_issue_status",
    "next_issue_key",
    "upsert_job",
    "get_job",
    "list_jobs",
    "load_all_jobs_into_memory",
    "seed_audit_logs_from_jobs",
    "list_audit_logs",
    "get_audit_log_stats",
    # P2: Issue Collaboration Records
    "list_issue_events",
    "create_issue_event",
    "list_issue_comments",
    "create_issue_comment",
    "list_issue_artifacts",
    "create_issue_artifact",
    # LLM Provider Config
    "get_llm_provider_config",
    "list_llm_provider_configs",
    "upsert_llm_provider_config",
    "update_llm_provider_health",
    "seed_llm_provider_configs",
    # Agent Runtime
    "upsert_worker",
    "get_worker",
    "list_workers_by_board",
    "update_worker_status",
    "update_worker_heartbeat",
    "create_run",
    "get_run",
    "list_runs_by_board",
    "list_runs_by_worker",
    "update_run_status",
    "append_run_event",
    "list_run_events",
]


# ============================================================================
# Seed data
# ============================================================================

SEED_ISSUES = [
    {"title": "Implement user authentication flow", "status": "done", "priority": "high", "profile": "backend"},
    {"title": "Build Kanban board drag-and-drop", "status": "in_progress", "priority": "high", "profile": "frontend"},
    {"title": "Set up CI/CD pipeline", "status": "in_progress", "priority": "medium", "profile": "backend"},
    {"title": "Design system documentation", "status": "backlog", "priority": "medium", "profile": "frontend"},
    {"title": "API rate limiting implementation", "status": "backlog", "priority": "high", "profile": "backend"},
    {"title": "Mobile responsive fixes", "status": "blocked", "priority": "medium", "profile": "frontend"},
    {"title": "Security audit for auth module", "status": "human_review", "priority": "critical", "profile": "security"},
    {"title": "Database migration script", "status": "done", "priority": "medium", "profile": "backend"},
]


# ============================================================================
# Helpers
# ============================================================================

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_model_to_dict(issue: IssueModel) -> dict:
    return {
        "id": issue.id,
        "key": issue.key,
        "title": issue.title,
        "description": issue.description or "",
        "status": issue.status,
        "priority": issue.priority or "medium",
        "profile": issue.profile or "general",
        "created_at": issue.created_at.isoformat() if issue.created_at else _utc_now(),
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else _utc_now(),
    }


def _job_model_to_dict(job: JobModel) -> dict:
    # JSON column deserializes to list on both SQLite and Postgres.
    events = job.events if isinstance(job.events, list) else []
    return {
        "id": job.id,
        "issue_id": job.issue_id,
        "issue_key": job.issue_key,
        "command": job.command,
        "profile": job.profile,
        "harness": job.harness,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "message": job.message,
        "events": events,
    }


# ============================================================================
# Issue repository
# ============================================================================

async def seed_if_empty() -> int:
    """Seed the database with initial issues if the issues table is empty.

    Returns the number of issues inserted (0 if already seeded).
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(select(IssueModel))
            if result.scalars().first() is not None:
                return 0

            now = datetime.now(timezone.utc)
            for i, data in enumerate(SEED_ISSUES, start=1):
                session.add(IssueModel(
                    id=f"seed-{i}",
                    key=f"DEV-{i:03d}",
                    title=data["title"],
                    description="",
                    status=data["status"],
                    priority=data["priority"],
                    profile=data["profile"],
                    created_at=now,
                    updated_at=now,
                ))
            await session.commit()
            logger.info(f"Seeded {len(SEED_ISSUES)} initial issues")
            return len(SEED_ISSUES)
    except Exception as e:
        logger.warning(f"Failed to seed database: {e}")
        return 0


async def list_issues() -> List[dict]:
    """Return all issues as frontend-shaped dicts (sorted by id for stability)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(select(IssueModel).order_by(IssueModel.id))
            rows = result.scalars().all()
            return [_issue_model_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issues: {e}")
        return []


async def get_issue(issue_id: str) -> Optional[dict]:
    """Return a single issue as dict, or None if not found."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(IssueModel).where(IssueModel.id == issue_id)
            )
            row = result.scalar_one_or_none()
            return _issue_model_to_dict(row) if row else None
    except Exception as e:
        logger.warning(f"Failed to get issue {issue_id}: {e}")
        return None


async def upsert_issue(issue_data: dict) -> dict:
    """Create or update an issue. Returns the issue as dict.

    Required keys: id, key, title, status.
    Optional: description, priority, profile.
    Raises on DB failure (caller decides how to react).
    """
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    async with _get_sessionmaker()() as session:
        result = await session.execute(
            select(IssueModel).where(IssueModel.id == issue_data["id"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title = issue_data["title"]
            existing.description = issue_data.get("description", "")
            existing.status = issue_data["status"]
            existing.priority = issue_data.get("priority", "medium")
            existing.profile = issue_data.get("profile", "general")
            existing.updated_at = now
            issue = existing
        else:
            issue = IssueModel(
                id=issue_data["id"],
                key=issue_data["key"],
                title=issue_data["title"],
                description=issue_data.get("description", ""),
                status=issue_data["status"],
                priority=issue_data.get("priority", "medium"),
                profile=issue_data.get("profile", "general"),
                created_at=now,
                updated_at=now,
            )
            session.add(issue)

        await session.commit()
        return _issue_model_to_dict(issue)


async def update_issue_status(issue_id: str, status: str) -> Optional[dict]:
    """Update issue status. Returns updated dict or None if not found."""
    try:
        await _ensure_init()()
        now = datetime.now(timezone.utc)
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(IssueModel).where(IssueModel.id == issue_id)
            )
            issue = result.scalar_one_or_none()
            if not issue:
                return None
            issue.status = status
            issue.updated_at = now
            await session.commit()
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning(f"Failed to update issue {issue_id} status: {e}")
        return None


async def next_issue_key() -> str:
    """Generate the next DEV-NNN key based on the max existing numeric key.

    Falls back to DEV-001 if no existing issues match the pattern.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(select(IssueModel.key))
            keys = [row[0] for row in result.all()]
        max_num = 0
        for key in keys:
            m = re.match(r"^DEV-(\d+)$", key or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"DEV-{max_num + 1:03d}"
    except Exception as e:
        logger.warning(f"Failed to compute next issue key: {e}")
        return f"DEV-{int(datetime.now(timezone.utc).timestamp())}"


# ============================================================================
# Job repository
# ============================================================================

async def upsert_job(job_data: dict) -> None:
    """Create or update a job. job_data['events'] must be a list of dicts.

    Required keys: id, issue_id, issue_key, command, profile, harness,
    status, created_at, updated_at, events.
    Optional: message.
    """
    try:
        await _ensure_init()()
        events = job_data.get("events", [])
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_data["id"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.status = job_data["status"]
                existing.message = job_data.get("message")
                existing.updated_at = job_data["updated_at"]
                existing.events = events
            else:
                session.add(JobModel(
                    id=job_data["id"],
                    issue_id=job_data["issue_id"],
                    issue_key=job_data["issue_key"],
                    command=job_data["command"],
                    profile=job_data["profile"],
                    harness=job_data["harness"],
                    status=job_data["status"],
                    created_at=job_data["created_at"],
                    updated_at=job_data["updated_at"],
                    message=job_data.get("message"),
                    events=events,
                ))

            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to upsert job {job_data.get('id')}: {e}")


async def get_job(job_id: str) -> Optional[dict]:
    """Return a single job as dict, or None if not found."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_id)
            )
            row = result.scalar_one_or_none()
            return _job_model_to_dict(row) if row else None
    except Exception as e:
        logger.warning(f"Failed to get job {job_id}: {e}")
        return None


async def list_jobs(
    issue_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """List jobs, optionally filtered by issue_id, status, and/or limit.

    Sorted by created_at DESC (newest first) for stable ordering.
    When *limit* is set, only that many rows are returned.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(JobModel)
            if issue_id:
                stmt = stmt.where(JobModel.issue_id == issue_id)
            if status:
                stmt = stmt.where(JobModel.status == status)
            stmt = stmt.order_by(JobModel.created_at.desc())
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_job_model_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list jobs: {e}")
        return []


async def load_all_jobs_into_memory() -> List[dict]:
    """Load all jobs from DB as dicts (for in-memory hot path).

    Returns list of job dicts. The caller is responsible for converting
    to Pydantic ECCDispatchJob objects.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(select(JobModel))
            rows = result.scalars().all()
            return [_job_model_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to load all jobs from DB: {e}")
        return []


# ============================================================================
# Audit Log repository
# ============================================================================

async def seed_audit_logs_from_jobs() -> int:
    """Generate audit log entries from existing ECC jobs (one-time seed).

    Creates action entries for each job transition event. Returns the
    number of entries inserted (0 if already seeded or on error).
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            # Check if audit logs already exist
            existing = await session.execute(select(func.count(AuditLog.id)))
            if (existing.scalar() or 0) > 0:
                return 0

            # Load all jobs to generate audit entries
            result = await session.execute(select(JobModel))
            jobs = result.scalars().all()

            now = datetime.now(timezone.utc)
            count = 0
            for job in jobs:
                events = job.events if isinstance(job.events, list) else []
                for event in events:
                    entry = AuditLog(
                        id=f"audit_{uuid4().hex[:12]}",
                        agent_id=None,
                        agent_name="system",
                        action=event.get("status", "unknown"),
                        resource="ecc_job",
                        resource_id=job.id,
                        details={
                            "issueKey": job.issue_key,
                            "command": job.command,
                            "profile": job.profile,
                            "harness": job.harness,
                        },
                        changes={"message": event.get("message", "")},
                        timestamp=now,
                    )
                    session.add(entry)
                    count += 1

                # Add a dispatch entry for job creation
                dispatch_entry = AuditLog(
                    id=f"audit_{uuid4().hex[:12]}",
                    agent_id=None,
                    agent_name="user",
                    action="dispatch",
                    resource="ecc_job",
                    resource_id=job.id,
                    details={
                        "issueKey": job.issue_key,
                        "command": job.command,
                        "profile": job.profile,
                        "harness": job.harness,
                    },
                    changes={"status": job.status},
                    timestamp=now,
                )
                session.add(dispatch_entry)
                count += 1

            # Add seed issue entries
            for i, issue_data in enumerate(SEED_ISSUES, start=1):
                entry = AuditLog(
                    id=f"audit_{uuid4().hex[:12]}",
                    agent_id=None,
                    agent_name="system",
                    action="created",
                    resource="issue",
                    resource_id=f"seed-{i}",
                    details={
                        "key": f"DEV-{i:03d}",
                        "title": issue_data["title"],
                        "priority": issue_data["priority"],
                        "profile": issue_data["profile"],
                    },
                    changes={"status": issue_data["status"]},
                    timestamp=now,
                )
                session.add(entry)
                count += 1

            await session.commit()
            logger.info(f"Seeded {count} audit log entries")
            return count
    except Exception as e:
        logger.warning(f"Failed to seed audit logs: {e}")
        return 0


async def list_audit_logs(
    action: Optional[str] = None,
    resource: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[List[dict], int]:
    """List audit log entries, newest first. Returns (entries, total_count)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(AuditLog)
            if action:
                stmt = stmt.where(AuditLog.action == action)
            if resource:
                stmt = stmt.where(AuditLog.resource == resource)
            stmt = stmt.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            count_stmt = select(func.count(AuditLog.id))
            if action:
                count_stmt = count_stmt.where(AuditLog.action == action)
            if resource:
                count_stmt = count_stmt.where(AuditLog.resource == resource)
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            return [
                {
                    "id": r.id,
                    "agentId": r.agent_id,
                    "agentName": r.agent_name,
                    "action": r.action,
                    "resource": r.resource,
                    "resourceId": r.resource_id,
                    "details": r.details or {},
                    "changes": r.changes or {},
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                }
                for r in rows
            ], total
    except Exception as e:
        logger.warning(f"Failed to list audit logs: {e}")
        return [], 0


async def get_audit_log_stats() -> dict:
    """Return aggregated audit log statistics."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            action_stmt = select(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action)
            action_result = await session.execute(action_stmt)
            by_action = {row[0]: row[1] for row in action_result.all()}

            resource_stmt = select(AuditLog.resource, func.count(AuditLog.id)).group_by(AuditLog.resource)
            resource_result = await session.execute(resource_stmt)
            by_resource = {row[0]: row[1] for row in resource_result.all()}

            total_result = await session.execute(select(func.count(AuditLog.id)))
            total = total_result.scalar() or 0

            return {"total": total, "byAction": by_action, "byResource": by_resource}
    except Exception as e:
        logger.warning(f"Failed to get audit log stats: {e}")
        return {"total": 0, "byAction": {}, "byResource": {}}


# ============================================================================
# P2: Issue Collaboration Records - Events
# ============================================================================

async def list_issue_events(issue_id: str, limit: int = 100) -> List[dict]:
    """Return events for an issue, newest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueEvent)
                .where(IssueEvent.issue_id == issue_id)
                .order_by(IssueEvent.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issue events for {issue_id}: {e}")
        return []


async def create_issue_event(
    issue_id: str,
    event_type: str,
    summary: str,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    """Create an event for an issue. Returns the created event."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    event = IssueEvent(
        id=f"evt-{uuid4().hex[:12]}",
        issue_id=issue_id,
        event_type=event_type,
        actor_id=actor_id,
        actor_name=actor_name,
        summary=summary,
        details=details or {},
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(event)
        await session.commit()
        return event.to_dict()


# ============================================================================
# P2: Issue Collaboration Records - Comments
# ============================================================================

async def list_issue_comments(issue_id: str, limit: int = 100) -> List[dict]:
    """Return comments for an issue, oldest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueComment)
                .where(IssueComment.issue_id == issue_id)
                .order_by(IssueComment.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issue comments for {issue_id}: {e}")
        return []


async def create_issue_comment(
    issue_id: str,
    body: str,
    author_id: Optional[str] = None,
    author_name: Optional[str] = None,
    comment_type: str = "comment",
    metadata: Optional[dict] = None,
) -> dict:
    """Create a comment on an issue. Returns the created comment."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    comment = IssueComment(
        id=f"cmt-{uuid4().hex[:12]}",
        issue_id=issue_id,
        author_id=author_id,
        author_name=author_name,
        body=body,
        comment_type=comment_type,
        extra_data=metadata or {},
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(comment)
        await session.commit()
        return comment.to_dict()


# ============================================================================
# P2: Issue Collaboration Records - Artifacts
# ============================================================================

async def list_issue_artifacts(issue_id: str, limit: int = 100) -> List[dict]:
    """Return artifacts for an issue, newest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueArtifact)
                .where(IssueArtifact.issue_id == issue_id)
                .order_by(IssueArtifact.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issue artifacts for {issue_id}: {e}")
        return []


async def create_issue_artifact(
    issue_id: str,
    title: str,
    artifact_type: str,
    job_id: Optional[str] = None,
    source: Optional[str] = None,
    path_or_url: Optional[str] = None,
    sensitivity: str = "public",
    summary: Optional[str] = None,
    metadata: Optional[dict] = None,
    created_by_id: Optional[str] = None,
    created_by_name: Optional[str] = None,
) -> dict:
    """Create an artifact metadata record. Returns the created artifact."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    artifact = IssueArtifact(
        id=f"art-{uuid4().hex[:12]}",
        issue_id=issue_id,
        job_id=job_id,
        title=title,
        artifact_type=artifact_type,
        source=source,
        path_or_url=path_or_url,
        sensitivity=sensitivity,
        summary=summary,
        extra_data=metadata or {},
        created_by_id=created_by_id,
        created_by_name=created_by_name,
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(artifact)
        await session.commit()
        return artifact.to_dict()


# ============================================================================
# IssueHandoff — Kanban Protocol
# ============================================================================

async def create_issue_handoff(
    *,
    id: str,
    board_id: str,
    issue_id: str,
    from_lane: Optional[str],
    to_lane: str,
    payload: Optional[dict],
    created_by: Optional[str],
) -> dict:
    """Insert a new IssueHandoff in 'pending' status and return its dict form."""
    from db.models import IssueHandoff

    row = IssueHandoff(
        id=id,
        board_id=board_id,
        issue_id=issue_id,
        from_lane=from_lane,
        to_lane=to_lane,
        status="pending",
        payload=payload or {},
        created_by=created_by,
    )
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()


async def get_issue_handoff(handoff_id: str) -> Optional[dict]:
    from db.models import IssueHandoff

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(IssueHandoff, handoff_id)
            return row.to_dict() if row else None
    except Exception as e:
        logger.warning(f"Failed to get issue handoff {handoff_id}: {e}")
        return None


async def list_issue_handoffs(
    *,
    issue_id: str,
    board_id: str,
    limit: int = 100,
) -> list[dict]:
    from sqlalchemy import select
    from db.models import IssueHandoff

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueHandoff)
                .where(IssueHandoff.issue_id == issue_id)
                .where(IssueHandoff.board_id == board_id)
                .order_by(IssueHandoff.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issue handoffs for {issue_id}/{board_id}: {e}")
        return []


async def update_issue_handoff(
    handoff_id: str,
    *,
    status: str,
    block_reason: Optional[str] = None,
    payload: Optional[dict] = None,
    actor_field: Optional[str] = None,
    actor_value: Optional[str] = None,
    set_completed_at: bool = False,
    decision: Optional[str] = None,
    review_comment: Optional[str] = None,
    reviewed_by: Optional[str] = None,
    set_reviewed_at: bool = False,
) -> Optional[dict]:
    """Update a handoff's status and optional audit fields."""
    from datetime import datetime, timezone
    from db.models import IssueHandoff

    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(IssueHandoff, handoff_id)
        if not row:
            return None
        row.status = status
        if block_reason is not None:
            row.block_reason = block_reason
        if payload is not None:
            row.payload = payload
        if actor_field and actor_value is not None:
            setattr(row, actor_field, actor_value)
        if set_completed_at:
            row.completed_at = datetime.now(timezone.utc)
        # Review gate fields
        if decision is not None:
            row.decision = decision
        if review_comment is not None:
            row.review_comment = review_comment
        if reviewed_by is not None:
            row.reviewed_by = reviewed_by
        if set_reviewed_at:
            row.reviewed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()


async def create_ecc_job_safe_runner(
    *,
    issue_id: str,
    issue_key: str,
    command: str,
    profile: str,
    harness: str,
    handoff_id: Optional[str] = None,
) -> dict:
    """Create a JobModel row that runs through the P0 safe runner.

    Used by the Kanban Protocol dispatch path so handoffs always produce
    a queued job without invoking real Claude/Codex execution by
    default. The actor is captured in the audit message rather than on
    the JobModel itself (the model has no actor column).
    """
    job_id = f"ecc_{uuid4().hex[:12]}"
    now = _utc_now()
    row = JobModel(
        id=job_id,
        board_id="board-default",
        issue_id=issue_id,
        issue_key=issue_key,
        command=command,
        profile=profile,
        harness=harness,
        status="queued",
        created_at=now,
        updated_at=now,
        message=f"Created by Kanban Protocol handoff {handoff_id or '<unknown>'}",
        events=[
            {
                "timestamp": now,
                "status": "queued",
                "message": "Job created by Kanban Protocol dispatch",
            }
        ],
    )
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()


# ---------------------------------------------------------------------------
# LLM Provider Config
# ---------------------------------------------------------------------------

async def get_llm_provider_config(provider_id: str) -> Optional[dict]:
    """Get a provider config by provider_id (e.g. 'minimax')."""
    from db.models import LLMProviderConfig

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.execute(
                select(LLMProviderConfig).where(LLMProviderConfig.provider_id == provider_id)
            )
            result = row.scalar_one_or_none()
            return result.to_dict() if result else None
    except Exception as e:
        logger.warning(f"Failed to get LLM provider config {provider_id}: {e}")
        return None


async def list_llm_provider_configs() -> list[dict]:
    """List all provider configs."""
    from db.models import LLMProviderConfig

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            rows = await session.execute(
                select(LLMProviderConfig).order_by(LLMProviderConfig.provider_id)
            )
            return [r.to_dict() for r in rows.scalars()]
    except Exception as e:
        logger.warning(f"Failed to list LLM provider configs: {e}")
        return []


async def upsert_llm_provider_config(
    *,
    provider_id: str,
    display_name: str,
    enabled: bool = True,
    base_url: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    api_shape: Optional[str] = None,
    auth_type: Optional[str] = None,
    model: Optional[str] = None,
    api_key_encrypted: Optional[str] = None,
    api_key_prefix: Optional[str] = None,
    api_key_last4: Optional[str] = None,
) -> dict:
    """Create or update a provider config."""
    from db.models import LLMProviderConfig

    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.execute(
            select(LLMProviderConfig).where(LLMProviderConfig.provider_id == provider_id)
        )
        existing = row.scalar_one_or_none()

        if existing:
            existing.display_name = display_name
            existing.enabled = enabled
            if base_url is not None:
                existing.base_url = base_url
            if endpoint_path is not None:
                existing.endpoint_path = endpoint_path
            if api_shape is not None:
                existing.api_shape = api_shape
            if auth_type is not None:
                existing.auth_type = auth_type
            if model is not None:
                existing.model = model
            if api_key_encrypted is not None:
                existing.api_key_encrypted = api_key_encrypted
                existing.api_key_prefix = api_key_prefix
                existing.api_key_last4 = api_key_last4
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(existing)
            return existing.to_dict()
        else:
            new_id = f"llm_{provider_id}"
            new_row = LLMProviderConfig(
                id=new_id,
                provider_id=provider_id,
                display_name=display_name,
                enabled=enabled,
                base_url=base_url,
                endpoint_path=endpoint_path,
                api_shape=api_shape,
                auth_type=auth_type,
                model=model,
                api_key_encrypted=api_key_encrypted,
                api_key_prefix=api_key_prefix,
                api_key_last4=api_key_last4,
            )
            session.add(new_row)
            await session.commit()
            await session.refresh(new_row)
            return new_row.to_dict()


async def update_llm_provider_health(
    provider_id: str,
    *,
    status: str,
    latency_ms: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[dict]:
    """Update health check results for a provider."""
    from db.models import LLMProviderConfig

    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.execute(
            select(LLMProviderConfig).where(LLMProviderConfig.provider_id == provider_id)
        )
        existing = row.scalar_one_or_none()
        if not existing:
            return None
        existing.last_test_status = status
        existing.last_test_at = datetime.now(timezone.utc)
        existing.last_latency_ms = latency_ms
        existing.last_error_code = error_code
        existing.last_error_message = error_message
        existing.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        return existing.to_dict()


async def seed_llm_provider_configs() -> int:
    """Seed default provider configs if none exist. Returns count of seeded rows."""
    from db.models import LLMProviderConfig

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            count = await session.execute(select(func.count(LLMProviderConfig.id)))
            if count.scalar() > 0:
                return 0

            defaults = [
                ("minimax", "MiniMax", "https://api.minimax.io/v1", "/chat/completions", "openai-chat", "bearer", "MiniMax-M3"),
                ("openai", "OpenAI", "https://api.openai.com/v1", "/responses", "openai-responses", "bearer", "gpt-4o"),
                ("anthropic", "Anthropic", "https://api.anthropic.com/v1", "/messages", "anthropic-messages", "x-api-key", "claude-sonnet-4-20250514"),
                ("xiaomi", "Xiaomi MiMo", "https://api.xiaomimimo.com/v1", "/chat/completions", "openai-chat", "api-key", "MiMo-7B"),
                ("ollama", "Ollama", "http://localhost:11434", "/api/tags", "ollama", "none", "llama3"),
            ]

            for pid, name, base, endpoint, shape, auth, model in defaults:
                session.add(LLMProviderConfig(
                    id=f"llm_{pid}",
                    provider_id=pid,
                    display_name=name,
                    enabled=True,
                    base_url=base,
                    endpoint_path=endpoint,
                    api_shape=shape,
                    auth_type=auth,
                    model=model,
                ))
            await session.commit()
            return len(defaults)
    except Exception as e:
        logger.warning(f"Failed to seed LLM provider configs: {e}")
        return 0


# ---------------------------------------------------------------------------
# Agent Runtime — Worker / Run / Event
# ---------------------------------------------------------------------------

async def upsert_worker(
    *,
    id: str,
    board_id: str = "board-default",
    worker_type: str,
    harness: Optional[str] = None,
    status: str = "idle",
    capabilities: Optional[list] = None,
    max_concurrency: int = 1,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Create or update a worker record. Returns the worker as dict."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        existing = await session.get(AgentWorker, id)
        now = datetime.now(timezone.utc)
        if existing:
            existing.worker_type = worker_type
            existing.harness = harness
            existing.status = status
            if capabilities is not None:
                existing.capabilities = capabilities
            existing.max_concurrency = max_concurrency
            if extra_metadata is not None:
                existing.extra_metadata = extra_metadata
            existing.updated_at = now
            await session.commit()
            await session.refresh(existing)
            return existing.to_dict()
        else:
            row = AgentWorker(
                id=id,
                board_id=board_id,
                worker_type=worker_type,
                harness=harness,
                status=status,
                capabilities=capabilities or [],
                max_concurrency=max_concurrency,
                extra_metadata=extra_metadata or {},
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()


async def get_worker(worker_id: str) -> Optional[dict]:
    """Return a single worker as dict, or None."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentWorker, worker_id)
            return row.to_dict() if row else None
    except Exception as e:
        logger.warning(f"Failed to get worker {worker_id}: {e}")
        return None


async def list_workers_by_board(board_id: str = "board-default") -> List[dict]:
    """List all workers for a board, ordered by created_at DESC."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(AgentWorker)
                .where(AgentWorker.board_id == board_id)
                .order_by(AgentWorker.created_at.desc())
            )
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to list workers for board {board_id}: {e}")
        return []


async def update_worker_status(
    worker_id: str,
    status: str,
    *,
    active_run_id: Optional[str] = None,
    error_message: Optional[str] = None,
    claimed_at: Optional[datetime] = None,
    started_at: Optional[datetime] = None,
    stopped_at: Optional[datetime] = None,
) -> Optional[dict]:
    """Update worker status and optional timestamps. Returns updated dict."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentWorker, worker_id)
        if not row:
            return None
        row.status = status
        row.updated_at = datetime.now(timezone.utc)
        # Clear active_run_id when worker is idle or stopped
        if status in ("idle", "stopped"):
            row.active_run_id = None
        elif active_run_id is not None:
            row.active_run_id = active_run_id
        if error_message is not None:
            row.error_message = error_message
        if claimed_at is not None:
            row.claimed_at = claimed_at
        if started_at is not None:
            row.started_at = started_at
        if stopped_at is not None:
            row.stopped_at = stopped_at
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def update_worker_heartbeat(worker_id: str) -> Optional[dict]:
    """Update the worker's last_heartbeat_at to now. Returns updated dict."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentWorker, worker_id)
        if not row:
            return None
        row.last_heartbeat_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


# ---------------------------------------------------------------------------
# Agent Run
# ---------------------------------------------------------------------------

async def create_run(
    *,
    id: str,
    board_id: str = "board-default",
    worker_id: Optional[str] = None,
    issue_id: Optional[str] = None,
    issue_key: Optional[str] = None,
    job_id: Optional[str] = None,
    command: Optional[str] = None,
    profile: Optional[str] = None,
    harness: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Create a new run. Returns the run as dict."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    row = AgentRun(
        id=id,
        board_id=board_id,
        worker_id=worker_id,
        issue_id=issue_id,
        issue_key=issue_key,
        job_id=job_id,
        status="pending",
        command=command,
        profile=profile,
        harness=harness,
        provider=provider,
        model=model,
        extra_metadata=extra_metadata or {},
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def get_run(run_id: str) -> Optional[dict]:
    """Return a single run as dict, or None."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentRun, run_id)
            return row.to_dict() if row else None
    except Exception as e:
        logger.warning(f"Failed to get run {run_id}: {e}")
        return None


async def list_runs_by_board(
    board_id: str = "board-default",
    issue_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    order: str = "desc",
) -> List[dict]:
    """List runs for a board. Optional filters for issue_id and status.

    order: 'desc' (newest first, default) or 'asc' (oldest first, for FIFO claiming).
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(AgentRun).where(AgentRun.board_id == board_id)
            if issue_id:
                stmt = stmt.where(AgentRun.issue_id == issue_id)
            if status:
                stmt = stmt.where(AgentRun.status == status)
            if order == "asc":
                stmt = stmt.order_by(AgentRun.created_at.asc())
            else:
                stmt = stmt.order_by(AgentRun.created_at.desc())
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to list runs for board {board_id}: {e}")
        return []


async def list_runs_by_worker(
    worker_id: str,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    """List runs for a worker, newest first. Optional status filter."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(AgentRun).where(AgentRun.worker_id == worker_id)
            if status:
                stmt = stmt.where(AgentRun.status == status)
            stmt = stmt.order_by(AgentRun.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to list runs for worker {worker_id}: {e}")
        return []


async def update_run_status(
    run_id: str,
    status: str,
    *,
    worker_id: Optional[str] = None,
    result_summary: Optional[str] = None,
    error_message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> Optional[dict]:
    """Update run status and optional fields. Returns updated dict."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentRun, run_id)
        if not row:
            return None
        row.status = status
        if worker_id is not None:
            row.worker_id = worker_id
        if result_summary is not None:
            row.result_summary = result_summary
        if error_message is not None:
            row.error_message = error_message
        if started_at is not None:
            row.started_at = started_at
        if completed_at is not None:
            row.completed_at = completed_at
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


# ---------------------------------------------------------------------------
# Agent Run Events
# ---------------------------------------------------------------------------

async def append_run_event(
    *,
    id: str,
    run_id: str,
    event_type: str,
    message: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Append an event to a run. Returns the created event."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    row = AgentRunEvent(
        id=id,
        run_id=run_id,
        event_type=event_type,
        message=message,
        extra_metadata=extra_metadata or {},
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def list_run_events(run_id: str, limit: int = 500) -> List[dict]:
    """List events for a run, ordered by created_at ASC (oldest first)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == run_id)
                .order_by(AgentRunEvent.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to list events for run {run_id}: {e}")
        return []
