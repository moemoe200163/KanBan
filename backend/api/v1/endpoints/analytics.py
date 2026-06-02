"""
Analytics API endpoint.

Provides computed KPIs and aggregated statistics for the dashboard.
Data is derived from existing tables (issues, ecc_jobs, audit_logs,
quality_gate_results) without introducing new storage.
"""

from fastapi import APIRouter
from sqlalchemy import select, func

from db import database as _db
from db.models import Issue, JobModel, AuditLog, QualityGateResult

router = APIRouter()


@router.get("/analytics/stats")
async def get_analytics_stats():
    """Return computed dashboard KPIs."""
    try:
        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            # --- Issue stats ---
            issue_result = await session.execute(select(Issue))
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

            # --- Job stats ---
            job_result = await session.execute(select(JobModel))
            jobs = job_result.scalars().all()

            total_jobs = len(jobs)
            jobs_by_status = {}
            for job in jobs:
                jobs_by_status[job.status] = jobs_by_status.get(job.status, 0) + 1

            jobs_by_profile = {}
            for job in jobs:
                jobs_by_profile[job.profile] = jobs_by_profile.get(job.profile, 0) + 1

            # --- Quality gate stats ---
            qg_result = await session.execute(select(QualityGateResult))
            qg_rows = qg_result.scalars().all()

            total_qg = len(qg_rows)
            qg_passed = sum(1 for r in qg_rows if r.passed)
            avg_coverage = 0.0
            if qg_rows:
                coverages = [float(r.actual_coverage) for r in qg_rows if r.actual_coverage]
                avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

            # --- Audit log stats ---
            audit_result = await session.execute(select(func.count(AuditLog.id)))
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
                        from datetime import datetime
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
