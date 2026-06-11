"""
Deliveries router — read-only cross-issue view of handoff / completion
artifacts.

The data lives in ``issue_artifacts`` (different concept from the
global ``artifacts`` blob table; that one is for user uploads only).
This view aggregates them across issues and enriches each row with
the parent issue's key/title/status so the front-end can render a
flat delivery list without a per-row fetch.
"""
from typing import Optional

from fastapi import APIRouter, Query

from db import repository as repo
from db import database as db_module


router = APIRouter()


def _sessionmaker():
    """Dynamic sessionmaker lookup so test monkeypatches are honored
    (mirrors the pattern in artifacts.py)."""
    return db_module.AsyncSessionLocal


@router.get("/deliveries")
async def list_deliveries(
    issue_id: Optional[str] = Query(None, description="Filter to one issue's deliveries"),
    artifact_type: Optional[str] = Query(None, description="Filter by artifact_type (e.g. screenshot, test_log)"),
    source: Optional[str] = Query(None, description="Filter by source (e.g. handoff_complete, dispatch)"),
    board_id: Optional[str] = Query(None, description="Filter by board_id"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Return a flat list of delivery rows (IssueArtifact enriched with
    issue summary). No binary content — that's the /artifacts table's
    job. Blob is intentionally excluded to keep the deliveries view
    snappy and to enforce the product split: this view is for
    metadata/URLs/summaries only.
    """
    async with _sessionmaker()() as session:
        rows = await repo.list_all_issue_artifacts(
            board_id=board_id,
            artifact_type=artifact_type,
            source=source,
            issue_id=issue_id,
            limit=limit,
            offset=offset,
        )

    # Enrich with issue summary; dedupe lookups by caching per issue_id.
    issue_cache: dict = {}
    enriched = []
    missing_issue_ids = 0
    for r in rows:
        if r.issue_id in issue_cache:
            summary = issue_cache[r.issue_id]
        else:
            summary = await repo.get_issue_summary(r.issue_id)
            issue_cache[r.issue_id] = summary
            if summary is None:
                missing_issue_ids += 1
        base = r.to_dict()
        enriched.append({
            **base,
            "issueKey": summary.get("key") if summary else None,
            "issueTitle": summary.get("title") if summary else None,
            "issueStatus": summary.get("status") if summary else None,
        })
    return {
        "items": enriched,
        "count": len(enriched),
        "missingIssues": missing_issue_ids,
    }


@router.get("/deliveries/types")
async def list_delivery_types():
    """
    Enumerate distinct artifact_type values currently present in
    issue_artifacts. Used by the front-end filter dropdown.
    """
    async with _sessionmaker()() as session:
        rows = await repo.list_all_issue_artifacts(limit=1000, offset=0)
    seen = set()
    for r in rows:
        if r.artifact_type:
            seen.add(r.artifact_type)
    return {"types": sorted(seen), "count": len(seen)}


@router.get("/deliveries/sources")
async def list_delivery_sources():
    """Enumerate distinct source values for the filter dropdown."""
    async with _sessionmaker()() as session:
        rows = await repo.list_all_issue_artifacts(limit=1000, offset=0)
    seen = set()
    for r in rows:
        if r.source:
            seen.add(r.source)
    return {"sources": sorted(seen), "count": len(seen)}
