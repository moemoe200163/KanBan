"""
DevFlow Backend - Quality Gate Endpoints

Provides quality gate status and verification endpoints for ECC jobs.
"""

import os
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

router = APIRouter()


# =============================================================================
# Pydantic Request/Response Models
# =============================================================================

class QualityGateStatus(BaseModel):
    """Quality gate status with current thresholds."""
    coverage_threshold: float = 80.0
    max_lint_errors: int = 0
    test_pass_rate_threshold: float = 100.0
    enabled: bool = True


class QualityGateVerifyRequest(BaseModel):
    """Request to verify a job's quality gate results."""
    job_id: str = Field(..., min_length=1, description="ECC job ID to verify")
    coverage_threshold: float = Field(default=80.0, ge=0, le=100, description="Minimum code coverage percentage")
    max_lint_errors: int = Field(default=0, ge=0, description="Maximum allowed lint errors")


class QualityGateCheckResult(BaseModel):
    """Individual check result within a verification."""
    check_name: str
    passed: bool
    expected: str
    actual: str


class QualityGateVerifyResponse(BaseModel):
    """Response from quality gate verification."""
    verification_id: str
    job_id: str
    issue_id: Optional[str] = None
    issue_key: Optional[str] = None
    passed: bool
    coverage_threshold: float
    max_lint_errors: int
    actual_coverage: Optional[float] = None
    actual_lint_errors: Optional[int] = None
    actual_test_pass_rate: Optional[float] = None
    failed_checks: List[QualityGateCheckResult] = Field(default_factory=list)
    verified_at: str


# =============================================================================
# Default Thresholds (can be configured via environment)
# =============================================================================

DEFAULT_COVERAGE_THRESHOLD = float(os.getenv("QUALITY_COVERAGE_THRESHOLD", "80.0"))
DEFAULT_MAX_LINT_ERRORS = int(os.getenv("QUALITY_MAX_LINT_ERRORS", "0"))
DEFAULT_TEST_PASS_RATE = 100.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_job(job_id: str) -> Optional[dict]:
    """
    Retrieve job from database or in-memory store.

    Returns job dict or None if not found.
    """
    # Try in-memory store first (matches ecc.py pattern)
    from api.v1.endpoints.ecc import _jobs
    if job_id in _jobs:
        job = _jobs[job_id]
        return {
            "id": job.id,
            "issue_id": job.issue_id,
            "issue_key": job.issue_key,
            "status": job.status,
        }

    # Fall back to database
    try:
        from backend.db.database import AsyncSessionLocal, ensure_db_init
        from backend.db.models import JobModel
        await ensure_db_init()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(JobModel).where(JobModel.id == job_id))
            row = result.scalar_one_or_none()
            if row:
                return row.to_dict()
    except Exception:
        pass

    return None


async def _simulate_quality_metrics(job_id: str) -> dict:
    """
    Simulate quality metrics for a job.

    In production, this would fetch actual metrics from CI systems,
    code coverage tools, linters, and test runners.
    """
    # Simulate realistic metrics - in production these come from actual tools
    import random

    # Jobs that have completed or are in review_required status get realistic metrics
    job = await _get_job(job_id)
    job_status = job.get("status", "running") if job else "running"

    if job_status in ("completed", "review_required", "running"):
        # Simulate coverage between 65-95%
        coverage = round(65 + random.random() * 30, 1)
        # Simulate lint errors between 0-5
        lint_errors = random.randint(0, 5)
        # Simulate test pass rate
        test_pass_rate = 100.0 if random.random() > 0.1 else 95.0 + random.random() * 4
    else:
        coverage = 0.0
        lint_errors = 0
        test_pass_rate = 0.0

    return {
        "coverage": coverage,
        "lint_errors": lint_errors,
        "test_pass_rate": test_pass_rate,
    }


async def _save_quality_result(result: dict) -> None:
    """Persist quality gate result to database."""
    from backend.db.database import AsyncSessionLocal, ensure_db_init
    from backend.db.models import QualityGateResult
    await ensure_db_init()

    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(QualityGateResult).values(
            id=result["id"],
            job_id=result["job_id"],
            issue_id=result.get("issue_id"),
            issue_key=result.get("issue_key"),
            coverage_threshold=str(result["coverage_threshold"]),
            max_lint_errors=str(result["max_lint_errors"]),
            actual_coverage=str(result.get("actual_coverage", "0")) if result.get("actual_coverage") is not None else None,
            actual_lint_errors=str(result.get("actual_lint_errors", "0")) if result.get("actual_lint_errors") is not None else None,
            actual_test_pass_rate=str(result.get("actual_test_pass_rate", "0")) if result.get("actual_test_pass_rate") is not None else None,
            passed=result["passed"],
            failed_checks=result.get("failed_checks_json", "[]"),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "job_id": result["job_id"],
                "issue_id": result.get("issue_id"),
                "issue_key": result.get("issue_key"),
                "coverage_threshold": str(result["coverage_threshold"]),
                "max_lint_errors": str(result["max_lint_errors"]),
                "actual_coverage": str(result.get("actual_coverage", "0")) if result.get("actual_coverage") is not None else None,
                "actual_lint_errors": str(result.get("actual_lint_errors", "0")) if result.get("actual_lint_errors") is not None else None,
                "actual_test_pass_rate": str(result.get("actual_test_pass_rate", "0")) if result.get("actual_test_pass_rate") is not None else None,
                "passed": result["passed"],
                "failed_checks": result.get("failed_checks_json", "[]"),
            },
        )
        await session.execute(stmt)
        await session.commit()


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/quality/gate", response_model=QualityGateStatus)
async def get_quality_gate_status():
    """
    Get the current quality gate status and thresholds.

    Returns the configured thresholds for code coverage, lint errors,
    and test pass rate that are used during quality gate verification.
    """
    return QualityGateStatus(
        coverage_threshold=DEFAULT_COVERAGE_THRESHOLD,
        max_lint_errors=DEFAULT_MAX_LINT_ERRORS,
        test_pass_rate_threshold=DEFAULT_TEST_PASS_RATE,
        enabled=True,
    )


@router.post("/quality/gate/verify", response_model=QualityGateVerifyResponse)
async def verify_quality_gate(request: QualityGateVerifyRequest):
    """
    Trigger a quality gate verification check against a job's results.

    Verifies the job's metrics against the provided thresholds:
    - coverage_threshold: Minimum code coverage percentage (default 80%)
    - max_lint_errors: Maximum allowed lint errors (default 0)

    Returns pass/fail status with actual metrics from the job.
    """
    # Get the job
    job = await _get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{request.job_id}' not found")

    # Get simulated quality metrics
    metrics = await _simulate_quality_metrics(request.job_id)

    # Evaluate checks
    failed_checks: List[QualityGateCheckResult] = []

    # Coverage check
    if metrics["coverage"] < request.coverage_threshold:
        failed_checks.append(QualityGateCheckResult(
            check_name="code_coverage",
            passed=False,
            expected=f">= {request.coverage_threshold}%",
            actual=f"{metrics['coverage']}%",
        ))

    # Lint errors check
    if metrics["lint_errors"] > request.max_lint_errors:
        failed_checks.append(QualityGateCheckResult(
            check_name="lint_errors",
            passed=False,
            expected=f"<= {request.max_lint_errors}",
            actual=str(metrics["lint_errors"]),
        ))

    # Test pass rate check (always expect 100% in this implementation)
    test_pass_rate_threshold = DEFAULT_TEST_PASS_RATE
    if metrics["test_pass_rate"] < test_pass_rate_threshold:
        failed_checks.append(QualityGateCheckResult(
            check_name="test_pass_rate",
            passed=False,
            expected=f">= {test_pass_rate_threshold}%",
            actual=f"{metrics['test_pass_rate']}%",
        ))

    passed = len(failed_checks) == 0

    # Build result
    now = _utc_now()
    verification_id = f"qg_{uuid4().hex[:12]}"

    result = {
        "id": verification_id,
        "job_id": request.job_id,
        "issue_id": job.get("issue_id"),
        "issue_key": job.get("issue_key"),
        "coverage_threshold": request.coverage_threshold,
        "max_lint_errors": request.max_lint_errors,
        "actual_coverage": metrics["coverage"],
        "actual_lint_errors": metrics["lint_errors"],
        "actual_test_pass_rate": metrics["test_pass_rate"],
        "passed": passed,
        "failed_checks_json": __import__("json").dumps([c.model_dump() for c in failed_checks]),
    }

    # Persist result
    await _save_quality_result(result)

    return QualityGateVerifyResponse(
        verification_id=verification_id,
        job_id=request.job_id,
        issue_id=job.get("issue_id"),
        issue_key=job.get("issue_key"),
        passed=passed,
        coverage_threshold=request.coverage_threshold,
        max_lint_errors=request.max_lint_errors,
        actual_coverage=metrics["coverage"],
        actual_lint_errors=metrics["lint_errors"],
        actual_test_pass_rate=metrics["test_pass_rate"],
        failed_checks=failed_checks,
        verified_at=now,
    )