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

from sqlalchemy import select

from db import database as _db
from db.models import Issue as IssueModel, JobModel


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


async def list_jobs(issue_id: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    """List all jobs, optionally filtered by issue_id and/or status.

    Sorted by created_at DESC (newest first) for stable ordering.
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
