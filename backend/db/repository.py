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
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select, func, text

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID
from db import database as _db
from db.models import (
    Issue as IssueModel,
    IssueHandoff,
    JobModel,
    AuditLog,
    IssueEvent,
    IssueComment,
    IssueArtifact,
    AgentWorker,
    AgentRun,
    AgentRunEvent,
    AgentSession,
    AgentRole,
    Artifact as ArtifactModel,
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
    "update_issue_pr_url",
    "update_issue_ci_status",
    "find_issue_by_key",
    "list_handoffs_by_status",
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
    "find_active_runs_for_job_id",
    "update_run_status",
    "append_run_event",
    "list_run_events",
    # Agent Roles
    "seed_default_roles",
    "list_agent_roles",
    "get_agent_role",
    "create_agent_role",
    "update_agent_role",
    "set_agent_role_enabled",
    "count_active_handoffs_for_role",
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
    """Serialize an Issue row to the API's camelCase shape.

    The board endpoint, the cycle-reports handler, and the front-end
    all expect camelCase keys (e.g. ``parentId``, ``acceptanceCriteria``,
    ``createdAt``). Historically the repository returned snake_case
    and only the board endpoint manually rebuilt the shape; callers
    like the new ``/issues/{id}/children`` and ``/issues/{id}``
    endpoints that go straight through this function were returning
    the snake_case shape, which broke the front-end.

    We delegate to the SQLAlchemy model's own ``to_dict()`` so the
    serialization rule lives in one place. The audit script that
    parses the model file was written against the same columns, so
    the public contract is unchanged from the model's perspective.
    """
    return issue.to_dict()


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
        "board_id": job.board_id,
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


async def list_issues(board_id: Optional[str] = None) -> List[dict]:
    """Return issues as frontend-shaped dicts (sorted by id for stability).

    Args:
        board_id: If provided, only return issues belonging to this board.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(IssueModel).order_by(IssueModel.id)
            if board_id is not None:
                stmt = stmt.where(IssueModel.board_id == board_id)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_issue_model_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issues: {e}")
        return []


async def list_issue_children(parent_id: str) -> List[dict]:
    """All issues whose ``parent_id`` equals ``parent_id``.

    Used by the epic-tree page. The list is ordered by
    ``created_at`` (newest first) so the page renders deterministically.
    We don't filter by status here because the page groups by status
    visually; filtering can be added on top if it becomes a hotspot.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(IssueModel)
                .where(IssueModel.parent_id == parent_id)
                .order_by(IssueModel.created_at.desc())
            )
            return [_issue_model_to_dict(r) for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"list_issue_children({parent_id}) failed: {e}")
        return []


async def get_epic_chain(issue_id: str, max_depth: int = 10) -> List[dict]:
    """Walk ``parent_id`` up to a root epic, return the chain.

    The list is ordered ``[root, ..., self]`` so a caller can render
    a breadcrumb or a tree without re-sorting. ``max_depth`` bounds
    the walk to defend against pathological self-cycles or
    accidentally re-parented subtrees — at the first repetition we
    stop and return what we have.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            chain: list[IssueModel] = []
            seen: set[str] = set()
            current_id: Optional[str] = issue_id
            for _ in range(max_depth):
                if not current_id or current_id in seen:
                    break
                seen.add(current_id)
                result = await session.execute(
                    select(IssueModel).where(IssueModel.id == current_id)
                )
                row = result.scalar_one_or_none()
                if not row:
                    break
                chain.append(row)
                current_id = row.parent_id
            # Reverse so the root is first, the original issue last.
            chain.reverse()
            return [_issue_model_to_dict(r) for r in chain]
    except Exception as e:
        logger.warning(f"get_epic_chain({issue_id}) failed: {e}")
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
            if "board_id" in issue_data:
                existing.board_id = issue_data["board_id"]
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
                board_id=issue_data.get("board_id", DEFAULT_BOARD_ID),
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


async def update_issue_pr_url(issue_id: str, pr_url: str) -> Optional[dict]:
    """Update issue PR URL. Returns updated dict or None if not found."""
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
            issue.pr_url = pr_url
            issue.updated_at = now
            await session.commit()
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning(f"Failed to update issue {issue_id} pr_url: {e}")
        return None


async def update_issue(issue_id: str, updates: dict) -> Optional[dict]:
    """Patch a subset of issue columns. Returns updated dict or None.

    Only columns the cycle-reports endpoint needs are wired up here;
    extend the whitelist if a new caller wants to mutate a different
    field. We deliberately do NOT allow ``status`` to be patched here
    — that has its own dedicated function with broadcast + auto-promote
    semantics, and routing it through this generic function would
    silently bypass both.
    """
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

            ALLOWED = {
                "parent_id", "acceptance_criteria", "title", "description",
                "priority", "assignee_id", "assignee_name", "labels",
            }
            for key, value in updates.items():
                if key not in ALLOWED:
                    continue
                setattr(issue, key, value)
            issue.updated_at = now
            await session.commit()
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning(f"Failed to update issue {issue_id} fields {list(updates.keys())}: {e}")
        return None


# ---------------------------------------------------------------------------
# Cycle reports — Mavis-style handoffs captured after a worker pass.
# ---------------------------------------------------------------------------

def _cycle_report_to_dict(row) -> dict:
    return {
        "id": row.id,
        "issueId": row.issue_id,
        "jobId": row.job_id,
        "authorId": row.author_id,
        "authorName": row.author_name,
        "plan": row.plan,
        "progressLog": row.progress_log or [],
        "deliverableSummary": row.deliverable_summary,
        "verdict": row.verdict,
        "verdictReason": row.verdict_reason,
        "boardId": row.board_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


async def upsert_cycle_report(report: dict) -> dict:
    """Create a cycle report. The id is the natural key."""
    from db.models import CycleReport as CycleReportModel

    try:
        await _ensure_init()()
        now = datetime.now(timezone.utc)
        async with _get_sessionmaker()() as session:
            row = CycleReportModel(
                id=report["id"],
                issue_id=report["issue_id"],
                job_id=report.get("job_id"),
                author_id=report.get("author_id"),
                author_name=report.get("author_name"),
                plan=report["plan"],
                progress_log=report.get("progress_log") or [],
                deliverable_summary=report.get("deliverable_summary"),
                verdict=report.get("verdict", "pending"),
                verdict_reason=report.get("verdict_reason"),
                board_id=report.get("board_id", DEFAULT_BOARD_ID),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            return _cycle_report_to_dict(row)
    except Exception as e:
        logger.error(f"upsert_cycle_report failed: {e}", exc_info=True)
        raise


async def list_cycle_reports(issue_id: str, limit: int = 50) -> List[dict]:
    from db.models import CycleReport as CycleReportModel

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(CycleReportModel)
                .where(CycleReportModel.issue_id == issue_id)
                .order_by(CycleReportModel.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [_cycle_report_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"list_cycle_reports({issue_id}) failed: {e}")
        return []


async def list_pending_cycle_reports(board_id: Optional[str] = None, limit: int = 100) -> List[dict]:
    """Cycle reports awaiting leader review (pending + auto_passed).

    Joins the issue table so the leader can see the issue's key and
    title without a second round-trip. Used by the leader dashboard
    /reviews page and the sidebar ``Review (N)`` badge.
    """
    from db.models import CycleReport as CycleReportModel, Issue as IssueModel

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            # Newest cycle first. Filter to the active verdicts the
            # leader still needs to act on. We exclude ``pass``/``fail``/
            # ``blocked`` here because those are terminal — once a
            # leader flipped a cycle, it shouldn't show up in the
            # pending queue again.
            stmt = (
                select(CycleReportModel, IssueModel)
                .join(IssueModel, CycleReportModel.issue_id == IssueModel.id)
                .where(CycleReportModel.verdict.in_(["pending", "auto_passed"]))
                .order_by(CycleReportModel.created_at.desc())
                .limit(limit)
            )
            if board_id is not None:
                stmt = stmt.where(CycleReportModel.board_id == board_id)
            result = await session.execute(stmt)
            out: list[dict] = []
            for cr, issue in result.all():
                d = _cycle_report_to_dict(cr)
                # Inline the bits the leader needs to triage. The
                # front-end list doesn't have to do a follow-up
                # /issues/{id} call to know what to review.
                d["issueKey"] = issue.key
                d["issueTitle"] = issue.title
                d["issueStatus"] = issue.status
                out.append(d)
            return out
    except Exception as e:
        logger.warning(f"list_pending_cycle_reports failed: {e}")
        return []


async def count_pending_cycle_reports(board_id: Optional[str] = None) -> int:
    """Cheap COUNT for the sidebar badge — no row materialization."""
    from db.models import CycleReport as CycleReportModel

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(func.count())
                .select_from(CycleReportModel)
                .where(CycleReportModel.verdict.in_(["pending", "auto_passed"]))
            )
            if board_id is not None:
                stmt = stmt.where(CycleReportModel.board_id == board_id)
            result = await session.execute(stmt)
            return int(result.scalar() or 0)
    except Exception as e:
        logger.warning(f"count_pending_cycle_reports failed: {e}")
        return 0


async def get_cycle_report(report_id: str) -> Optional[dict]:
    from db.models import CycleReport as CycleReportModel

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(CycleReportModel).where(CycleReportModel.id == report_id)
            )
            row = result.scalar_one_or_none()
            return _cycle_report_to_dict(row) if row else None
    except Exception as e:
        logger.warning(f"get_cycle_report({report_id}) failed: {e}")
        return None


async def update_cycle_report(report_id: str, updates: dict) -> Optional[dict]:
    from db.models import CycleReport as CycleReportModel

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(CycleReportModel).where(CycleReportModel.id == report_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            ALLOWED = {"verdict", "verdict_reason", "deliverable_summary", "progress_log"}
            for key, value in updates.items():
                if key in ALLOWED:
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return _cycle_report_to_dict(row)
    except Exception as e:
        logger.warning(f"update_cycle_report({report_id}) failed: {e}")
        return None


async def update_issue_ci_status(issue_id: str, ci_status: str) -> Optional[dict]:
    """Update issue CI status. Returns updated dict or None if not found."""
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
            issue.ci_status = ci_status
            issue.updated_at = now
            await session.commit()
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning(f"Failed to update issue {issue_id} ci_status: {e}")
        return None


async def find_issue_by_key(key: str, board_id: "str | None" = None) -> "Optional[dict]":
    """Find issue by exact key (e.g. DEV-123). Returns dict or None.

    Args:
        key: Issue key to search for
        board_id: Optional board ID to scope the search (prevents cross-board collisions)
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(IssueModel).where(IssueModel.key == key)
            if board_id:
                stmt = stmt.where(IssueModel.board_id == board_id)
            result = await session.execute(stmt)
            issue = result.scalar_one_or_none()
            if not issue:
                return None
            return _issue_model_to_dict(issue)
    except Exception as e:
        logger.warning(f"Failed to find issue by key {key}: {e}")
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
                    board_id=job_data.get("board_id", DEFAULT_BOARD_ID),
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
    board_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """List jobs, optionally filtered by issue_id, status, board_id, and/or limit.

    Sorted by created_at DESC (newest first) for stable ordering.
    When *limit* is set, only that many rows are returned.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(JobModel)
            if board_id:
                stmt = stmt.where(JobModel.board_id == board_id)
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


async def load_all_jobs_into_memory(board_id: Optional[str] = None) -> List[dict]:
    """Load all jobs from DB as dicts (for in-memory hot path).

    If *board_id* is provided, only jobs belonging to that board are
    returned.  Returns list of job dicts. The caller is responsible for
    converting to Pydantic ECCDispatchJob objects.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(JobModel)
            if board_id is not None:
                stmt = stmt.where(JobModel.board_id == board_id)
            result = await session.execute(stmt)
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

async def list_issue_events(issue_id: str, limit: int = 100, board_id: Optional[str] = None) -> List[dict]:
    """Return events for an issue, newest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueEvent)
                .where(IssueEvent.issue_id == issue_id)
            )
            if board_id:
                stmt = stmt.where(IssueEvent.board_id == board_id)
            stmt = stmt.order_by(IssueEvent.created_at.desc()).limit(limit)
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
    board_id: str = DEFAULT_BOARD_ID,
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
        board_id=board_id,
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(event)
        await session.commit()
        return event.to_dict()


# ============================================================================
# P2: Issue Collaboration Records - Comments
# ============================================================================

async def list_issue_comments(issue_id: str, limit: int = 100, board_id: Optional[str] = None) -> List[dict]:
    """Return comments for an issue, oldest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueComment)
                .where(IssueComment.issue_id == issue_id)
            )
            if board_id:
                stmt = stmt.where(IssueComment.board_id == board_id)
            stmt = stmt.order_by(IssueComment.created_at.asc()).limit(limit)
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
    board_id: str = DEFAULT_BOARD_ID,
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
        board_id=board_id,
        created_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(comment)
        await session.commit()
        return comment.to_dict()


# ============================================================================
# P2: Issue Collaboration Records - Artifacts
# ============================================================================

async def list_issue_artifacts(issue_id: str, limit: int = 100, board_id: Optional[str] = None) -> List[dict]:
    """Return artifacts for an issue, newest first."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueArtifact)
                .where(IssueArtifact.issue_id == issue_id)
            )
            if board_id:
                stmt = stmt.where(IssueArtifact.board_id == board_id)
            stmt = stmt.order_by(IssueArtifact.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list issue artifacts for {issue_id}: {e}")
        return []


async def list_all_issue_artifacts(
    board_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    source: Optional[str] = None,
    issue_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List:
    """
    Cross-issue IssueArtifact list for the /deliveries view.

    Filters: artifact_type, source, issue_id, board_id (all exact match
    except board_id which is also exact). Returns the IssueArtifact
    model instances (not dicts) so the router can join issue context
    without an extra round-trip per row.
    """
    from sqlalchemy import select as _select
    async with _get_sessionmaker()() as session:
        stmt = _select(IssueArtifact)
        if board_id:
            stmt = stmt.where(IssueArtifact.board_id == board_id)
        if artifact_type:
            stmt = stmt.where(IssueArtifact.artifact_type == artifact_type)
        if source:
            stmt = stmt.where(IssueArtifact.source == source)
        if issue_id:
            stmt = stmt.where(IssueArtifact.issue_id == issue_id)
        stmt = stmt.order_by(IssueArtifact.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_issue_summary(issue_id: str) -> Optional[dict]:
    """Return the minimum issue fields needed by the /deliveries view:
    key, title, status. None if the issue doesn't exist (or was deleted
    while an IssueArtifact still references it).
    """
    from sqlalchemy import select as _select
    async with _get_sessionmaker()() as session:
        stmt = _select(IssueModel).where(IssueModel.id == issue_id)
        result = await session.execute(stmt)
        issue = result.scalar_one_or_none()
        if not issue:
            return None
        return {
            "id": issue.id,
            "key": issue.key,
            "title": issue.title,
            "status": issue.status,
        }


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
    board_id: str = DEFAULT_BOARD_ID,
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
        board_id=board_id,
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


async def list_handoffs_by_status(
    *,
    status: str,
    board_id: str = DEFAULT_BOARD_ID,
    limit: int = 100,
) -> list[dict]:
    """Find all handoffs with a given status on a board.

    Used by the autopilot scheduler to find accepted/in_progress handoffs
    that need processing.
    """
    from sqlalchemy import select
    from db.models import IssueHandoff

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(IssueHandoff)
                .where(IssueHandoff.status == status)
                .where(IssueHandoff.board_id == board_id)
                .order_by(IssueHandoff.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list handoffs with status {status}: {e}")
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
    board_id: str = DEFAULT_BOARD_ID,
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
        board_id=board_id,
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
    """Get a provider config by provider_id (e.g. 'minimax').

    Returns the masked dict (no api_key_encrypted) safe for API responses.
    """
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


async def get_llm_provider_config_with_key(provider_id: str) -> Optional[dict]:
    """Get a provider config including api_key_encrypted (internal use only).

    Used by APIModelExecutor to retrieve the encrypted key for LLM API calls.
    Never expose this in API responses.
    """
    from db.models import LLMProviderConfig

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.execute(
                select(LLMProviderConfig).where(LLMProviderConfig.provider_id == provider_id)
            )
            result = row.scalar_one_or_none()
            if not result:
                return None
            d = result.to_dict()
            d["api_key_encrypted"] = result.api_key_encrypted or ""
            return d
    except Exception as e:
        logger.warning(f"Failed to get LLM provider config (with key) {provider_id}: {e}")
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
                ("minimax", "MiniMax", "https://api.minimax.io/anthropic", "/v1/messages", "anthropic-messages", "x-api-key", "MiniMax-M3"),
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
    required_role: Optional[str] = None,
    max_retries: int = 0,
    max_runtime_seconds: Optional[int] = None,
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
        required_role=required_role,
        retry_count=0,
        max_retries=max_retries,
        max_runtime_seconds=max_runtime_seconds,
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
    job_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    order: str = "desc",
) -> List[dict]:
    """List runs for a board. Optional filters for issue_id, job_id, and status.

    order: 'desc' (newest first, default) or 'asc' (oldest first, for FIFO claiming).
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(AgentRun).where(AgentRun.board_id == board_id)
            if issue_id:
                stmt = stmt.where(AgentRun.issue_id == issue_id)
            if job_id:
                stmt = stmt.where(AgentRun.job_id == job_id)
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


async def find_active_runs_for_job_id(job_id: str) -> List[dict]:
    """Find runs linked to a job that are in an active (non-terminal) state."""
    ACTIVE_STATES = ("pending", "claimed", "running")
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = (
                select(AgentRun)
                .where(AgentRun.job_id == job_id)
                .where(AgentRun.status.in_(ACTIVE_STATES))
                .order_by(AgentRun.created_at.desc())
            )
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to find active runs for job {job_id}: {e}")
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
# Queue Hardening — atomic claim, stale reclaim, heartbeat, retry
# ---------------------------------------------------------------------------

async def atomic_claim_run(
    worker_id: str,
    board_id: str = "board-default",
    capabilities: Optional[list] = None,
) -> Optional[dict]:
    """Atomically claim the oldest pending run for a worker.

    Uses a SELECT-then-UPDATE pattern with optimistic concurrency:
    after the UPDATE we verify the row was actually in 'pending' state
    (via the WHERE clause). If another worker claimed it first, the UPDATE
    touches 0 rows and we try the next candidate.

    Role matching: a run is claimed if its required_role is NULL (any worker)
    or if required_role is in the worker's capabilities list.
    """
    await _ensure_init()()
    now = datetime.now(timezone.utc)

    # Build list of roles to match: specific capabilities first, then None (any role)
    roles_to_try = list(capabilities or []) + [None]

    for role in roles_to_try:
        async with _get_sessionmaker()() as session:
            # Find oldest pending run matching this role
            stmt = select(AgentRun).where(
                AgentRun.board_id == board_id,
                AgentRun.status == "pending",
                AgentRun.required_role == (role if role is not None else None),
                (AgentRun.next_retry_at.is_(None)) | (AgentRun.next_retry_at <= now),
            ).order_by(AgentRun.created_at.asc()).limit(1)

            result = await session.execute(stmt)
            candidate = result.scalar_one_or_none()
            if not candidate:
                continue

            # Atomic claim: UPDATE only if still pending
            from sqlalchemy import update as sa_update
            update_stmt = (
                sa_update(AgentRun)
                .where(AgentRun.id == candidate.id, AgentRun.status == "pending")
                .values(status="claimed", worker_id=worker_id, started_at=now)
            )
            update_result = await session.execute(update_stmt)
            await session.commit()

            if update_result.rowcount > 0:
                # Claim succeeded — re-read to get the updated row
                async with _get_sessionmaker()() as verify_session:
                    claimed = await verify_session.get(AgentRun, candidate.id)
                    if claimed:
                        return claimed.to_dict()

    return None


async def reclaim_stale_runs(
    stale_threshold_seconds: int = 300,
    max_retries: int = 3,
    board_id: Optional[str] = None,
) -> List[dict]:
    """Detect runs stuck in 'claimed' or 'running' and reclaim them.

    A run is stale if its last_heartbeat_at (or started_at) is older than
    stale_threshold_seconds. Stale runs are either:
    - Requeued to 'pending' if retry_count < max_retries
    - Marked as 'failed' if retry_count >= max_retries

    Returns a list of reclaimed run dicts.
    """
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    threshold = now - timedelta(seconds=stale_threshold_seconds)
    reclaimed = []
    # Collect runs whose linked issues should be auto-blocked after commit
    runs_needing_auto_block: list = []

    async with _get_sessionmaker()() as session:
        # Find stale runs in claimed or running state
        where_clauses = [
            AgentRun.status.in_(["claimed", "running"]),
            # Use last_heartbeat_at if set, otherwise started_at
            ((AgentRun.last_heartbeat_at.is_(None)) & (AgentRun.started_at < threshold))
            | (AgentRun.last_heartbeat_at < threshold),
        ]
        if board_id is not None:
            where_clauses.append(AgentRun.board_id == board_id)
        stmt = select(AgentRun).where(*where_clauses)
        result = await session.execute(stmt)
        stale_runs = result.scalars().all()

        for run in stale_runs:
            if run.retry_count < (run.max_retries or max_retries):
                # Requeue with retry
                run.status = "pending"
                run.retry_count += 1
                run.worker_id = None
                run.started_at = None
                run.last_heartbeat_at = None
                run.next_retry_at = now + timedelta(seconds=min(30 * (2 ** run.retry_count), 600))
                reclaimed.append(run.to_dict())
                logger.warning(
                    "Reclaimed stale run %s (attempt %d/%d), requeued",
                    run.id, run.retry_count, run.max_retries or max_retries,
                )
            else:
                # Max retries exceeded — mark as failed
                run.status = "failed"
                run.error_message = f"Stale after {stale_threshold_seconds}s, max retries exhausted"
                run.completed_at = now
                reclaimed.append(run.to_dict())
                logger.warning(
                    "Stale run %s exceeded max retries (%d), marking failed",
                    run.id, run.max_retries or max_retries,
                )
                # Collect for auto-blocking after commit
                if run.issue_id:
                    runs_needing_auto_block.append(run)

        await session.commit()

    # Auto-block linked issues for runs that exhausted retries.
    # This happens after the session commit so that each auto_block call
    # uses its own session and never conflicts with the reclaimed batch.
    for run in runs_needing_auto_block:
        await auto_block_issue_on_failure(
            issue_id=run.issue_id,
            issue_key=run.issue_key,
            board_id=run.board_id,
            run_id=run.id,
            retry_count=run.retry_count,
            max_retries=run.max_retries or max_retries,
        )

    return reclaimed


async def update_run_heartbeat(run_id: str) -> Optional[dict]:
    """Update the run's last_heartbeat_at to now. Returns updated dict."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentRun, run_id)
        if not row:
            return None
        row.last_heartbeat_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def schedule_retry(run_id: str, delay_seconds: int = 30) -> Optional[dict]:
    """Schedule a failed run for retry by setting next_retry_at.

    Returns the updated run dict, or None if the run is not retryable.
    """
    await _ensure_init()()
    from datetime import timedelta
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentRun, run_id)
        if not row:
            return None
        if row.retry_count >= (row.max_retries or 0):
            return None  # exhausted
        now = datetime.now(timezone.utc)
        row.retry_count += 1
        row.next_retry_at = now + timedelta(seconds=delay_seconds)
        row.status = "pending"
        row.worker_id = None
        row.started_at = None
        row.error_message = None
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def auto_block_issue_on_failure(
    issue_id: str,
    issue_key: str,
    board_id: str,
    run_id: str,
    retry_count: int,
    max_retries: int,
) -> None:
    """Auto-block an issue when its run exhausts all retries.

    Fetches the issue to get the title, updates status to 'blocked',
    and creates an issue event recording the auto-block. Failures are
    logged and swallowed so they never prevent the caller from continuing.
    """
    try:
        issue = await get_issue(issue_id)
        if not issue:
            logger.warning(
                "Issue %s not found for auto-block after run %s", issue_id, run_id,
            )
            return
        await update_issue_status(issue_id, "blocked")
        await create_issue_event(
            issue_id=issue_id,
            event_type="auto_blocked",
            summary=f"Auto-blocked after {max_retries} failed retries (run {run_id})",
            board_id=board_id,
        )
        logger.info(
            "Auto-blocked issue %s after %d failed retries (run %s)",
            issue_key, retry_count, run_id,
        )
    except Exception as exc:
        logger.warning("Failed to auto-block issue %s: %s", issue_key, exc)


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


# Stubs for session resume (full implementation in Task 2)

async def create_session(
    *,
    id: str,
    board_id: str = "board-default",
    issue_id: Optional[str] = None,
    issue_key: Optional[str] = None,
    harness: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Create a new agent session. Returns session as dict."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)
    row = AgentSession(
        id=id,
        board_id=board_id,
        issue_id=issue_id,
        issue_key=issue_key,
        harness=harness,
        provider=provider,
        model=model,
        status="active",
        conversation_history=[],
        checkpoint_data={},
        total_runs=1,
        total_tokens=0,
        expires_at=expires,
        created_at=now,
        updated_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def update_run_session_id(run_id: str, session_id: str) -> bool:
    """Set session_id on an AgentRun. Returns True if updated, False if not found."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        row = await session.get(AgentRun, run_id)
        if not row:
            return False
        row.session_id = session_id
        await session.commit()
        return True


async def get_session(session_id: str) -> Optional[dict]:
    """Return a single session as dict, or None."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            return row.to_dict() if row else None
    except Exception as e:
        logger.warning(f"Failed to get session {session_id}: {e}")
        return None


async def pause_session(session_id: str, last_error: Optional[str] = None) -> bool:
    """Transition session to paused (run ended, can be resumed)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            if not row:
                return False
            row.status = "paused"
            row.last_error = last_error
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to pause session {session_id}: {e}")
        return False


async def complete_session(session_id: str) -> bool:
    """Transition session to completed (terminal, no more resumption)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            if not row:
                return False
            row.status = "completed"
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to complete session {session_id}: {e}")
        return False


async def expire_session(session_id: str) -> bool:
    """Expire a session and purge conversation_history."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            if not row:
                return False
            row.status = "expired"
            row.conversation_history = None  # purge
            row.checkpoint_data = {}
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to expire session {session_id}: {e}")
        return False


async def update_session_checkpoint(
    session_id: str,
    *,
    conversation_history: Optional[list] = None,
    checkpoint_data: Optional[dict] = None,
    provider_resume_ref: Optional[str] = None,
    total_tokens: Optional[int] = None,
) -> bool:
    """Update session checkpoint data. Uses full reassignment, not mutation."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            if not row:
                return False
            if conversation_history is not None:
                row.conversation_history = conversation_history
            if checkpoint_data is not None:
                row.checkpoint_data = checkpoint_data
            if provider_resume_ref is not None:
                row.provider_resume_ref = provider_resume_ref
            if total_tokens is not None:
                row.total_tokens = total_tokens
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to update checkpoint for session {session_id}: {e}")
        return False


async def resume_session(session_id: str) -> bool:
    """Transition session from paused to active (resume started)."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            row = await session.get(AgentSession, session_id)
            if not row or row.status != "paused":
                return False
            row.status = "active"
            row.total_runs += 1
            row.last_run_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to resume session {session_id}: {e}")
        return False


async def list_sessions(
    *,
    board_id: Optional[str] = None,
    issue_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list:
    """List sessions with optional filters."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            query = select(AgentSession)
            if board_id:
                query = query.where(AgentSession.board_id == board_id)
            if issue_id:
                query = query.where(AgentSession.issue_id == issue_id)
            if status:
                query = query.where(AgentSession.status == status)
            query = query.order_by(AgentSession.created_at.desc()).limit(limit)
            result = await session.execute(query)
            rows = result.scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as e:
        logger.warning(f"Failed to list sessions: {e}")
        return []


# ---------------------------------------------------------------------------
# Agent Roles
# ---------------------------------------------------------------------------


async def seed_default_roles() -> int:
    """Seed default agent roles from WORKER_LANES.

    Upserts each lane into the agent_roles table. System roles that
    already exist (same key + is_system=True) are skipped. Returns the
    number of rows inserted (0 if all already exist or on error).
    """
    from core.kanban_protocol.lanes import WORKER_LANES

    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            count = 0
            for lane in WORKER_LANES.values():
                # Skip if a system role with this key already exists
                existing = await session.execute(
                    select(AgentRole).where(
                        AgentRole.key == lane.key,
                        AgentRole.is_system == True,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                # Compute required_completion_fields from LANE_PAYLOADS
                completion_fields: list[str] = []
                try:
                    from core.kanban_protocol.payloads import LANE_PAYLOADS
                    if lane.key in LANE_PAYLOADS:
                        completion_fields = list(
                            LANE_PAYLOADS[lane.key].model_fields.keys()
                        )
                except Exception:
                    pass  # payloads not available; leave empty

                row = AgentRole(
                    id=f"role_{lane.key}",
                    key=lane.key,
                    display_name=lane.display_name,
                    description=lane.description,
                    allowed_profiles=lane.allowed_profiles,
                    default_provider=lane.default_provider,
                    default_model=lane.default_model,
                    allowed_commands=lane.allowed_commands,
                    timeout_seconds=lane.timeout_seconds,
                    retry_policy=lane.retry_policy,
                    retry_max=lane.retry_max,
                    next_roles=lane.next_lanes,
                    human_approval_required=lane.human_approval_required,
                    enabled=True,
                    is_system=True,
                    required_completion_fields=completion_fields,
                )
                session.add(row)
                count += 1

            if count > 0:
                await session.commit()
            return count
    except Exception as e:
        logger.warning(f"Failed to seed default agent roles: {e}")
        return 0


async def list_agent_roles(include_disabled: bool = True) -> list[dict]:
    """Return all agent roles ordered by key.

    If include_disabled is False, only enabled roles are returned.
    """
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(AgentRole).order_by(AgentRole.key)
            if not include_disabled:
                stmt = stmt.where(AgentRole.enabled == True)
            result = await session.execute(stmt)
            return [r.to_dict() for r in result.scalars().all()]
    except Exception as e:
        logger.warning(f"Failed to list agent roles: {e}")
        return []


async def get_agent_role(key: str) -> Optional[dict]:
    """Return a single agent role by key, or None."""
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            result = await session.execute(
                select(AgentRole).where(AgentRole.key == key)
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None
    except Exception as e:
        logger.warning(f"Failed to get agent role {key}: {e}")
        return None


async def create_agent_role(data: dict) -> dict:
    """Insert a new agent role. Returns the created role as dict."""
    await _ensure_init()()
    now = datetime.now(timezone.utc)
    row = AgentRole(
        id=f"role_{uuid4().hex[:12]}",
        key=data["key"],
        display_name=data["display_name"],
        description=data.get("description", ""),
        allowed_profiles=data.get("allowed_profiles", []),
        default_provider=data.get("default_provider", ""),
        default_model=data.get("default_model", ""),
        allowed_commands=data.get("allowed_commands", []),
        timeout_seconds=data.get("timeout_seconds", 1800),
        retry_policy=data.get("retry_policy", "none"),
        retry_max=data.get("retry_max", 0),
        next_roles=data.get("next_roles", []),
        human_approval_required=data.get("human_approval_required", False),
        enabled=data.get("enabled", True),
        is_system=data.get("is_system", False),
        required_completion_fields=data.get("required_completion_fields", []),
        system_prompt=data.get("system_prompt", ""),
        task_prompt_template=data.get("task_prompt_template", ""),
        review_prompt_template=data.get("review_prompt_template", ""),
        created_at=now,
        updated_at=now,
    )
    async with _get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def update_agent_role(key: str, data: dict) -> Optional[dict]:
    """Update fields on an existing agent role. Returns updated dict or None."""
    await _ensure_init()()
    async with _get_sessionmaker()() as session:
        result = await session.execute(
            select(AgentRole).where(AgentRole.key == key)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        # Update only provided fields
        _FIELDS = (
            "display_name", "description", "allowed_profiles",
            "default_provider", "default_model", "allowed_commands",
            "timeout_seconds", "retry_policy", "retry_max",
            "next_roles", "human_approval_required", "enabled",
            "is_system", "required_completion_fields",
            "system_prompt", "task_prompt_template", "review_prompt_template",
        )
        for field in _FIELDS:
            if field in data:
                setattr(row, field, data[field])

        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


async def set_agent_role_enabled(key: str, enabled: bool) -> Optional[dict]:
    """Toggle the enabled field on an agent role. Returns updated dict or None."""
    return await update_agent_role(key, {"enabled": enabled})


async def count_active_handoffs_for_role(role_key: str) -> int:
    """Count non-terminal handoffs targeting the given role lane.

    Terminal statuses: approved, rejected, cancelled.
    """
    TERMINAL = ("approved", "rejected", "cancelled")
    try:
        await _ensure_init()()
        async with _get_sessionmaker()() as session:
            stmt = select(func.count(IssueHandoff.id)).where(
                IssueHandoff.to_lane == role_key,
                IssueHandoff.status.notin_(TERMINAL),
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
    except Exception as e:
        logger.warning(f"Failed to count handoffs for role {role_key}: {e}")
        return 0


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------

async def list_artifacts(session, limit: int = 200, offset: int = 0) -> list:
    """Return artifacts newest-first. Caller is responsible for any
    tag/name post-filtering (SQLite JSON support is limited, so we
    filter in Python to keep the same code path on Postgres and SQLite).
    """
    from sqlalchemy import select as _select
    stmt = _select(ArtifactModel).order_by(ArtifactModel.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_artifact(session, artifact_id: str):
    """Return one artifact by id (or None). Includes the blob bytes."""
    from sqlalchemy import select as _select
    stmt = _select(ArtifactModel).where(ArtifactModel.id == artifact_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_artifacts_by_parent(session, parent_id: str) -> list:
    """All artifact rows whose parent_id equals ``parent_id``."""
    from sqlalchemy import select as _select
    stmt = _select(ArtifactModel).where(ArtifactModel.parent_id == parent_id).order_by(ArtifactModel.version.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_artifact(session, artifact) -> ArtifactModel:
    """Persist a new artifact. Caller builds the ArtifactModel instance."""
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def delete_artifact(session, artifact_id: str) -> bool:
    """Hard-delete a single artifact by id. Returns True if a row was removed."""
    from sqlalchemy import delete as _delete
    stmt = _delete(ArtifactModel).where(ArtifactModel.id == artifact_id)
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0
