"""
Cycle reports — Mavis-style handoffs captured after a worker pass.

Endpoints:

- ``POST   /api/v1/issues/{issue_id}/cycle-reports``  — write a cycle report
- ``GET    /api/v1/issues/{issue_id}/cycle-reports``  — list all reports for an issue
- ``GET    /api/v1/issues/{issue_id}/cycle-reports/{report_id}``  — fetch one
- ``PATCH  /api/v1/issues/{issue_id}/cycle-reports/{report_id}``  — leader override verdict
- ``PATCH  /api/v1/issues/{issue_id}/acceptance-criteria``  — update structured AC
- ``PATCH  /api/v1/issues/{issue_id}/parent``  — link / unlink an epic parent

Reports are also auto-written by the auto-promote hook in the ECC
endpoints when a job reaches a terminal success state, so most
operator traffic is read-only: the leader looks at the report,
overrides the verdict if needed, and the issue auto-promotes to
``done`` once a leader flips the report to ``pass``.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.v1.auth_deps import require_auth
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
