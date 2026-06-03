"""
Analytics API endpoint.

Provides computed KPIs and aggregated statistics for the dashboard.
Data is derived from existing tables (issues, ecc_jobs, audit_logs,
quality_gate_results) without introducing new storage.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from db import database as _db
from db.models import Issue, JobModel, AuditLog, QualityGateResult

router = APIRouter()


def _parse_iso_datetime(value: str, param_name: str) -> datetime:
    """Parse an ISO 8601 string into a datetime. Raises 422 on failure.

    If the string has no timezone info, it is treated as UTC.
    Handles the ``Z`` suffix for UTC on Python < 3.11 where
    ``datetime.fromisoformat`` does not recognise it.
    """
    try:
        normalised = value.rstrip() if isinstance(value, str) else value
        if isinstance(normalised, str) and normalised.endswith("Z"):
            normalised = normalised[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ISO 8601 value for {param_name}: {value!r}",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_date_range(
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> None:
    """Raise 422 if date_from is after date_to."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be before date_to",
        )


@router.get("/analytics/stats")
async def get_analytics_stats(
    date_from: Optional[str] = Query(None, description="ISO 8601 start time (inclusive)"),
    date_to: Optional[str] = Query(None, description="ISO 8601 end time (inclusive)"),
):
    """Return computed dashboard KPIs."""
    try:
        # Parse and validate date parameters
        parsed_from = _parse_iso_datetime(date_from, "date_from") if date_from else None
        parsed_to = _parse_iso_datetime(date_to, "date_to") if date_to else None
        _validate_date_range(parsed_from, parsed_to)

        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            # --- Issue stats (filter by Issue.created_at) ---
            issue_stmt = select(Issue)
            if parsed_from:
                issue_stmt = issue_stmt.where(Issue.created_at >= parsed_from)
            if parsed_to:
                issue_stmt = issue_stmt.where(Issue.created_at <= parsed_to)
            issue_result = await session.execute(issue_stmt)
            issues = issue_result.scalars().all()

            total_issues = len(issues)
            by_status = {}
            for issue in issues:
                by_status[issue.status] = by_status.get(issue.status, 0) + 1

            by_priority = {}
            for issue in issues:
                by_priority[issue.priority or "medium"] = by_priority.get(issue.priority or "medium", 0) + 1

            by_profile = {}
            for issue in issues:
                by_profile[issue.profile or "general"] = by_profile.get(issue.profile or "general", 0) + 1

            # --- Job stats (filter by JobModel.created_at, a string column) ---
            # JobModel.created_at is stored as String(32), so we filter in Python
            # after fetching all rows. This matches the existing analytics pattern.
            job_result = await session.execute(select(JobModel))
            all_jobs = job_result.scalars().all()

            if parsed_from or parsed_to:
                jobs = []
                for job in all_jobs:
                    try:
                        job_created = datetime.fromisoformat(job.created_at)
                        if job_created.tzinfo is None:
                            job_created = job_created.replace(tzinfo=timezone.utc)
                        if parsed_from and job_created < parsed_from:
                            continue
                        if parsed_to and job_created > parsed_to:
                            continue
                        jobs.append(job)
                    except (ValueError, TypeError):
                        # Keep jobs with unparseable dates to avoid silent data loss
                        jobs.append(job)
            else:
                jobs = all_jobs

            total_jobs = len(jobs)
            jobs_by_status = {}
            for job in jobs:
                jobs_by_status[job.status] = jobs_by_status.get(job.status, 0) + 1

            jobs_by_profile = {}
            for job in jobs:
                jobs_by_profile[job.profile] = jobs_by_profile.get(job.profile, 0) + 1

            # --- Quality gate stats (filter by QualityGateResult.verified_at) ---
            qg_stmt = select(QualityGateResult)
            if parsed_from:
                qg_stmt = qg_stmt.where(QualityGateResult.verified_at >= parsed_from)
            if parsed_to:
                qg_stmt = qg_stmt.where(QualityGateResult.verified_at <= parsed_to)
            qg_result = await session.execute(qg_stmt)
            qg_rows = qg_result.scalars().all()

            total_qg = len(qg_rows)
            qg_passed = sum(1 for r in qg_rows if r.passed)
            avg_coverage = 0.0
            if qg_rows:
                coverages = [float(r.actual_coverage) for r in qg_rows if r.actual_coverage]
                avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

            # --- Audit log stats (filter by AuditLog.timestamp) ---
            audit_stmt = select(func.count(AuditLog.id))
            if parsed_from:
                audit_stmt = audit_stmt.where(AuditLog.timestamp >= parsed_from)
            if parsed_to:
                audit_stmt = audit_stmt.where(AuditLog.timestamp <= parsed_to)
            audit_result = await session.execute(audit_stmt)
            total_audit = audit_result.scalar() or 0

            # --- Computed KPIs ---
            completed = jobs_by_status.get("completed", 0)
            failed = jobs_by_status.get("failed", 0)
            cancelled = jobs_by_status.get("cancelled", 0)
            running = jobs_by_status.get("running", 0)
            review = jobs_by_status.get("review_required", 0)
            terminal = completed + failed + cancelled

            ai_success_rate = round(completed / terminal * 100, 1) if terminal > 0 else 0
            throughput = completed + failed  # total finished jobs

            # Cycle time: average time from created to terminal status
            # (simplified — using string ISO dates)
            cycle_times = []
            for job in jobs:
                if job.status in ("completed", "failed", "cancelled"):
                    try:
                        created = datetime.fromisoformat(job.created_at)
                        updated = datetime.fromisoformat(job.updated_at)
                        cycle_times.append((updated - created).total_seconds())
                    except (ValueError, TypeError):
                        pass
            avg_cycle_time_s = sum(cycle_times) / len(cycle_times) if cycle_times else 0
            avg_cycle_time_min = round(avg_cycle_time_s / 60, 1)

            return {
                "issues": {
                    "total": total_issues,
                    "byStatus": by_status,
                    "byPriority": by_priority,
                    "byProfile": by_profile,
                },
                "jobs": {
                    "total": total_jobs,
                    "byStatus": jobs_by_status,
                    "byProfile": jobs_by_profile,
                    "running": running,
                    "inReview": review,
                },
                "quality": {
                    "total": total_qg,
                    "passed": qg_passed,
                    "avgCoverage": round(avg_coverage, 1),
                },
                "audit": {
                    "total": total_audit,
                },
                "kpis": {
                    "aiSuccessRate": ai_success_rate,
                    "throughput": throughput,
                    "avgCycleTimeMin": avg_cycle_time_min,
                    "totalIssues": total_issues,
                    "totalJobs": total_jobs,
                    "activeRuns": running,
                    "inReview": review,
                },
            }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to get analytics stats: {e}")
        return {
            "issues": {"total": 0, "byStatus": {}, "byPriority": {}, "byProfile": {}},
            "jobs": {"total": 0, "byStatus": {}, "byProfile": {}, "running": 0, "inReview": 0},
            "quality": {"total": 0, "passed": 0, "avgCoverage": 0},
            "audit": {"total": 0},
            "kpis": {"aiSuccessRate": 0, "throughput": 0, "avgCycleTimeMin": 0, "totalIssues": 0, "totalJobs": 0, "activeRuns": 0, "inReview": 0},
        }
