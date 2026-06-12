"""
Cycle reports — Mavis-style handoffs captured after a worker pass.

Endpoints:

- ``POST   /api/v1/issues/{issue_id}/cycle-reports``  — write a cycle report
- ``GET    /api/v1/issues/{issue_id}/cycle-reports``  — list all reports for an issue
- ``GET    /api/v1/issues/{issue_id}/cycle-reports/{report_id}``  — fetch one
- ``PATCH  /api/v1/issues/{issue_id}/cycle-reports/{report_id}``  — leader override verdict
- ``POST   /api/v1/cycle-reports/{report_id}/review``  — leader review (approve / request changes)
- ``GET    /api/v1/cycle-reports/reviewed``           — list reviewed reports (filter by board + status)
- ``PATCH  /api/v1/issues/{issue_id}/acceptance-criteria``  — update structured AC
- ``PATCH  /api/v1/issues/{issue_id}/parent``  — link / unlink an epic parent

Reports are also auto-written by the auto-promote hook in the ECC
endpoints when a job reaches a terminal success state, so most
operator traffic is read-only: the leader looks at the report,
overrides the verdict if needed, and the issue auto-promotes to
``done`` once a leader flips the report to ``pass``.

The ``/review`` endpoint is the leader's *review of the report
itself* (approve, or send the worker back with feedback) — a
separate concept from the verdict override. Both can coexist on
the same report (e.g. ``verdict=pass, decision=approved``).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.v1.auth_deps import require_auth
from api.v1.endpoints.audit import log_audit_event
from db import repository as repo
from db.database import AsyncSessionLocal
from db.models import CycleReport, Issue


router = APIRouter()


# ----------------------------------------------------------------------------
# Pydantic schemas
# ----------------------------------------------------------------------------

class CycleReportCreate(BaseModel):
    plan: str = Field(..., min_length=1, max_length=8000)
    progress_log: List[Dict[str, Any]] = Field(default_factory=list)
    deliverable_summary: Optional[str] = Field(default=None, max_length=8000)
    verdict: str = Field(default="pending")  # pending | pass | fail | blocked
    verdict_reason: Optional[str] = Field(default=None, max_length=8000)
    job_id: Optional[str] = None
    author_name: Optional[str] = None


class CycleReportUpdate(BaseModel):
    verdict: Optional[str] = None  # pass | fail | blocked | auto_passed
    verdict_reason: Optional[str] = None
    deliverable_summary: Optional[str] = None
    progress_log: Optional[List[Dict[str, Any]]] = None


class CycleReportReviewRequest(BaseModel):
    """Body for ``POST /cycle-reports/{id}/review``.

    ``decision`` mirrors the task brief: ``approved`` (green light)
    or ``changes_requested`` (worker needs another pass). The
    endpoint enforces this enum and rejects any other value with
    422 — keeping the writer side strict so a typo can't be
    silently stored on the report.
    """
    decision: Literal["approved", "changes_requested"]
    comment: Optional[str] = Field(default=None, max_length=8000)


class AcceptanceCriteriaUpdate(BaseModel):
    criteria: List[Dict[str, Any]] = Field(..., description="List of {id, text, done}")


class ParentUpdate(BaseModel):
    parent_id: Optional[str] = None  # null to unlink


# ----------------------------------------------------------------------------
# Cycle report endpoints
# ----------------------------------------------------------------------------

@router.post("/issues/{issue_id}/cycle-reports")
async def create_cycle_report(
    issue_id: str = Path(...),
    body: CycleReportCreate = Body(...),
    current_user: dict = Depends(require_auth),
):
    """Write a new cycle report against an issue.

    Validates the verdict value and that the issue exists. Returns the
    created row. Most callers are the auto-promote hook, which sets
    ``author_name="auto-promote"`` and verdict ``auto_passed``.
    """
    if body.verdict not in {"pending", "pass", "fail", "blocked", "auto_passed"}:
        raise HTTPException(status_code=400, detail=f"Invalid verdict: {body.verdict}")

    # Make sure the issue exists before writing — a dangling FK is the
    # whole reason this script exists.
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")

    new_id = f"cr_{uuid.uuid4().hex[:16]}"
    report = {
        "id": new_id,
        "issue_id": issue_id,
        "job_id": body.job_id,
        "author_id": current_user.get("user_id"),
        "author_name": body.author_name or current_user.get("username") or "operator",
        "plan": body.plan,
        "progress_log": body.progress_log or [],
        "deliverable_summary": body.deliverable_summary,
        "verdict": body.verdict,
        "verdict_reason": body.verdict_reason,
        "board_id": issue.get("board_id", "board-default"),
    }
    created = await repo.upsert_cycle_report(report)
    return created


@router.get("/issues/{issue_id}/cycle-reports")
async def list_cycle_reports(
    issue_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_auth),
):
    """List cycle reports for an issue, newest first."""
    reports = await repo.list_cycle_reports(issue_id, limit=limit)
    return {"cycleReports": reports, "total": len(reports)}


# ---------------------------------------------------------------------------
# Leader dashboard — top-level endpoints for the /reviews queue.
#
# Mounted at the router root (no /issues/{id} prefix) so the leader can
# pull all boards at once for the badge and the queue page. Both are
# cheap: a single query with a verdict filter and an index on
# ``verdict`` (added in migration 0016).
# ---------------------------------------------------------------------------

@router.get("/cycle-reports/pending")
async def list_pending_cycle_reports(
    board_id: Optional[str] = Query(default=None, description="Filter to a single board; omit for all-boards view"),
    limit: int = Query(default=100, ge=1, le=500),
    priority: Optional[str] = Query(default=None, description="Filter by issue priority: critical|high|medium|low"),
    author: Optional[str] = Query(default=None, description="Filter by report author (e.g. 'auto-promote' or a worker name)"),
    since: Optional[str] = Query(default=None, description="ISO-8601 lower bound on report.createdAt, e.g. 2026-06-01T00:00:00Z"),
    current_user: dict = Depends(require_auth),
):
    """All cycle reports awaiting leader review.

    Includes the parent issue's key/title/status inline so the
    /reviews page can render rows without a follow-up fetch. Reports
    in terminal verdicts (pass/fail/blocked) are excluded — once a
    leader has decided, that cycle is no longer pending.

    Optional filters: ``priority`` matches on the parent issue's
    priority field, ``author`` matches on the cycle report's
    ``authorName``, and ``since`` is an ISO-8601 lower bound on
    the report's ``createdAt``. The filters compose with
    AND-semantics and are applied in the repository so the
    underlying SQL stays bounded by the same index scan.
    """
    reports = await repo.list_pending_cycle_reports(
        board_id=board_id,
        limit=limit,
        priority=priority,
        author=author,
        since=since,
    )
    count = await repo.count_pending_cycle_reports(
        board_id=board_id,
        priority=priority,
        author=author,
        since=since,
    )
    return {"cycleReports": reports, "total": count}


@router.get("/cycle-reports/pending/count")
async def count_pending_cycle_reports(
    board_id: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    author: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    current_user: dict = Depends(require_auth),
):
    """Cheap count for the sidebar Review badge.

    Separate endpoint from the list so the badge can poll every
    few seconds without pulling the full row payload. Same auth
    as the rest of the cycle report API. Filter params mirror
    the list endpoint.
    """
    count = await repo.count_pending_cycle_reports(
        board_id=board_id,
        priority=priority,
        author=author,
        since=since,
    )
    return {"count": count}


@router.get("/issues/{issue_id}/cycle-reports/{report_id}")
async def get_cycle_report(
    issue_id: str,
    report_id: str,
    current_user: dict = Depends(require_auth),
):
    report = await repo.get_cycle_report(report_id)
    if not report or report.get("issueId") != issue_id:
        raise HTTPException(status_code=404, detail="Cycle report not found")
    return report


@router.patch("/issues/{issue_id}/cycle-reports/{report_id}")
async def update_cycle_report(
    issue_id: str,
    report_id: str,
    body: CycleReportUpdate = Body(...),
    current_user: dict = Depends(require_auth),
):
    """Leader override — change verdict, deliverable, or progress log.

    Side effect: when verdict transitions to ``pass``, the linked
    issue is auto-promoted to ``done`` if it's still in a "needs
    review" lane. This mirrors the auto-promote hook on ECC jobs
    but is triggered by the leader instead of by the runner.
    """
    existing = await repo.get_cycle_report(report_id)
    if not existing or existing.get("issueId") != issue_id:
        raise HTTPException(status_code=404, detail="Cycle report not found")

    if body.verdict is not None and body.verdict not in {"pending", "pass", "fail", "blocked", "auto_passed"}:
        raise HTTPException(status_code=400, detail=f"Invalid verdict: {body.verdict}")

    updates: Dict[str, Any] = {}
    if body.verdict is not None:
        updates["verdict"] = body.verdict
    if body.verdict_reason is not None:
        updates["verdict_reason"] = body.verdict_reason
    if body.deliverable_summary is not None:
        updates["deliverable_summary"] = body.deliverable_summary
    if body.progress_log is not None:
        updates["progress_log"] = body.progress_log

    updated = await repo.update_cycle_report(report_id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update cycle report")

    # If the leader flipped to pass, kick the issue forward. This is
    # the manual equivalent of the ECC auto-promote path so the leader
    # doesn't have to remember to also drag the card.
    if body.verdict == "pass" and existing.get("verdict") != "pass":
        from db import repository as _repo
        await _repo.update_issue_status(issue_id, "done")

        # Plan D: also drop a deliverable artifact on the issue so
        # the /deliveries view + IssueDetail Worker tab surface
        # something concrete. The artifact's summary comes from the
        # cycle report's deliverable_summary (or the report id if
        # the leader didn't write one). ``source=cycle_report_pass``
        # makes it filterable in the front-end.
        try:
            deliverable = (
                body.deliverable_summary
                or existing.get("deliverable_summary")
                or f"Cycle report {report_id} approved by {current_user.get('username', 'leader')}"
            )
            await _repo.create_issue_artifact(
                issue_id=issue_id,
                title=f"Cycle report approved: {deliverable[:120]}",
                artifact_type="cycle_report",
                source="cycle_report_pass",
                summary=deliverable,
                sensitivity="public",
                metadata={
                    "reportId": report_id,
                    "jobId": existing.get("jobId"),
                    "verdict": body.verdict,
                },
                created_by_id=current_user.get("user_id"),
                created_by_name=current_user.get("username"),
                board_id=updated.get("board_id", "board-default"),
            )
        except Exception as exc:  # noqa: BLE001
            # The lane transition is the user-visible contract; the
            # artifact is bookkeeping. Log but don't fail the request.
            import logging
            logging.getLogger(__name__).warning(
                "Failed to create cycle_report_pass artifact for %s: %s",
                issue_id, exc,
            )
        try:
            from main import manager
            import datetime as _dt
            await manager.broadcast({
                "type": "issue_updated",
                "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
                "payload": {"issueId": issue_id, "changes": {"status": "done"}},
            })
        except Exception:
            pass

    return updated


# ---------------------------------------------------------------------------
# Review endpoint
# ---------------------------------------------------------------------------
#
# The ``/review`` endpoint is the leader's *review of the report
# itself* (approve, or send the worker back with feedback).
# Distinct from the ``PATCH /cycle-reports/{id}`` verdict
# override: verdict is about whether the work product is
# accepted, decision is about whether the report (and the worker
# who wrote it) needs to do another pass. Both can coexist on
# the same report.
#
# Authorisation rules:
# - require_auth (401 if no token)
# - self-review guard: a non-admin reviewer cannot review a
#   report they wrote. We compare the reviewer's user_id
#   against the report's author_id; if they match, the request
#   is rejected with 403 unless the reviewer is also an admin.
#   Admins can review any report (the platform's audit team
#   includes the original author's lead).

async def _is_admin(user_id: str) -> bool:
    """Return True if the user has the ``admin`` role.

    Centralised here so the role check is consistent across the
    review endpoint and any future admin-gated flows. Cached
    in the request scope is unnecessary — admins are rare and
    the role table is small.
    """
    from db.database import AsyncSessionLocal
    from db.models import User

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            return bool(user and user.role == "admin")
    except Exception:
        # Fail closed — if we can't read the user record we
        # don't want to grant admin bypass on a guess.
        return False


@router.post("/cycle-reports/{report_id}/review")
async def review_cycle_report(
    report_id: str = Path(..., description="Cycle report id, e.g. ``cr_abc123...``"),
    body: CycleReportReviewRequest = Body(...),
    current_user: dict = Depends(require_auth),
):
    """Record a review decision on a cycle report.

    Body: ``{"decision": "approved" | "changes_requested", "comment": str | null}``

    Side effects:
    - Persists ``decision``, ``review_comment``, ``reviewed_at``,
      ``reviewed_by`` and ``reviewed_by_id`` on the cycle report
      (see migration 0020).
    - Emits an audit log entry with action
      ``cycle_report.review`` so the trail shows who decided
      what, when, and why. The audit resource id is the cycle
      report id; the audit ``details`` carries the decision
      literal, the optional comment, and the linked issue id
      so a single audit row is enough to navigate from log
      -> report -> issue.
    - Idempotent on repeat: a second call overwrites the
      earlier review. The first review still appears in the
      audit log (we never delete entries), so the trail
      captures the change-of-mind.

    Authorization:
    - 401 if not authenticated.
    - 403 if the reviewer is also the report's author and not
      an admin (self-review guard).
    - 404 if the report id is unknown.
    """
    existing = await repo.get_cycle_report(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Cycle report '{report_id}' not found")

    reviewer_id = current_user.get("user_id")
    reviewer_name = current_user.get("username") or "unknown"

    # Self-review guard. A worker reviewing their own report is
    # a classic 4-eyes control violation; we enforce it at the
    # API edge so the rule is in one place, not duplicated in
    # every UI that calls this endpoint.
    is_admin = await _is_admin(reviewer_id) if reviewer_id else False
    report_author_id = existing.get("authorId")
    if (
        report_author_id
        and reviewer_id
        and report_author_id == reviewer_id
        and not is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Cannot review a cycle report you authored (self-review guard)",
        )

    updated = await repo.set_cycle_report_review(
        report_id,
        decision=body.decision,
        review_comment=body.comment,
        reviewed_by=reviewer_name,
        reviewed_by_id=reviewer_id or "unknown",
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to record review")

    # Audit trail. ``log_audit_event`` is fire-and-forget — a
    # failed write logs a warning but does not roll back the
    # review, because the review is the user-visible action and
    # the audit is a side channel.
    await log_audit_event(
        action="cycle_report.review",
        resource="cycle_report",
        resource_id=report_id,
        agent_id=reviewer_id,
        agent_name=reviewer_name,
        details={
            "decision": body.decision,
            "comment": body.comment,
            "issueId": existing.get("issueId"),
        },
    )

    return updated


@router.get("/cycle-reports/reviewed")
async def list_reviewed_cycle_reports(
    board_id: Optional[str] = Query(default=None, description="Filter to a single board; omit for all-boards view"),
    status: str = Query(default="all", description="``pending`` (decision IS NULL), ``reviewed`` (decision IS NOT NULL), or ``all``"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(require_auth),
):
    """List cycle reports filtered by review status.

    The leader's ``/reviews`` page uses this to split the queue
    into "awaiting review" and "already reviewed" sections. The
    default ``status='all'`` is convenient for the queue page's
    "everything" filter; the ``pending`` / ``reviewed`` values
    match the cycle report review flow exactly.

    The query joins the issue table so the UI can render key,
    title, status, and priority inline without a follow-up
    fetch (same contract as ``/cycle-reports/pending``).
    """
    if status not in {"pending", "reviewed", "all"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'; must be pending, reviewed, or all",
        )
    reports = await repo.list_cycle_reports_with_status(
        board_id=board_id,
        status=status,
        limit=limit,
    )
    return {"cycleReports": reports, "total": len(reports)}


# ----------------------------------------------------------------------------
# Acceptance criteria endpoint
# ----------------------------------------------------------------------------

@router.patch("/issues/{issue_id}/acceptance-criteria")
async def update_acceptance_criteria(
    issue_id: str,
    body: AcceptanceCriteriaUpdate = Body(...),
    current_user: dict = Depends(require_auth),
):
    """Replace the structured AC list on an issue.

    Each entry is ``{id, text, done}``; ``id`` is client-assigned and
    used to track toggle state. Returns the updated issue.
    """
    # Sanity check each entry has the right shape — don't trust the client.
    for i, ac in enumerate(body.criteria):
        if not isinstance(ac, dict) or "text" not in ac or "done" not in ac:
            raise HTTPException(
                status_code=400,
                detail=f"criteria[{i}] must be {{id?, text, done}}",
            )
    cleaned = [
        {
            "id": ac.get("id") or f"ac_{uuid.uuid4().hex[:8]}",
            "text": ac["text"],
            "done": bool(ac["done"]),
        }
        for ac in body.criteria
    ]
    updated = await repo.update_issue(issue_id, {"acceptance_criteria": cleaned})
    if not updated:
        raise HTTPException(status_code=404, detail="Issue not found")
    return updated


# ----------------------------------------------------------------------------
# Parent linkage endpoint
# ----------------------------------------------------------------------------

@router.patch("/issues/{issue_id}/parent")
async def update_parent(
    issue_id: str,
    body: ParentUpdate = Body(...),
    current_user: dict = Depends(require_auth),
):
    """Link an issue to an epic parent, or unlink with ``parent_id: null``.

    The parent must exist and belong to the same board. We also
    defend against **transitive cycles** — if A's parent chain
    passes through ``issue_id`` at any depth, setting
    ``issue_id.parent_id = A`` would create a cycle in the
    parent graph. The check is bounded at 10 levels deep (the
    same bound as ``get_epic_chain``) to keep a corrupted
    chain from spinning out of control.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if body.parent_id is not None:
        if body.parent_id == issue_id:
            raise HTTPException(status_code=400, detail="An issue cannot be its own parent")
        parent = await repo.get_issue(body.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent issue '{body.parent_id}' not found")
        if parent.get("boardId") != issue.get("boardId"):
            raise HTTPException(status_code=400, detail="Parent must be on the same board")
        # Walk the candidate parent's chain to see if it
        # already contains ``issue_id`` somewhere upstream. If
        # it does, linking would create a cycle.
        chain = await repo.get_epic_chain(body.parent_id, max_depth=10)
        chain_ids = {row["id"] for row in chain}
        if issue_id in chain_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Linking would create a cycle: issue {issue_id} is already "
                    f"an ancestor of {body.parent_id}"
                ),
            )

    updated = await repo.update_issue(issue_id, {"parent_id": body.parent_id})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update parent")
    return updated
