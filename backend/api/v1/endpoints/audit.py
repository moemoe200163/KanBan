"""
Audit Log API endpoint.

Provides read-only access to the audit_logs table.
The audit log tracks all significant system actions: issue changes,
ECC job dispatches, quality gate results, and review decisions.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func, or_

from db import database as _db
from db.models import AuditLog

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


async def log_audit_event(
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    details: Optional[dict] = None,
    changes: Optional[dict] = None,
) -> None:
    """Write an audit log entry. Called from other endpoints on significant actions."""
    try:
        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            entry = AuditLog(
                id=f"audit_{uuid4().hex[:12]}",
                agent_id=agent_id,
                agent_name=agent_name,
                action=action,
                resource=resource,
                resource_id=resource_id,
                details=details or {},
                changes=changes or {},
                timestamp=datetime.now(timezone.utc),
            )
            session.add(entry)
            await session.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).warning(f"Failed to write audit log: action={action} resource={resource}")


def _audit_to_dict(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "agentId": entry.agent_id,
        "agentName": entry.agent_name,
        "action": entry.action,
        "resource": entry.resource,
        "resourceId": entry.resource_id,
        "details": entry.details or {},
        "changes": entry.changes or {},
        "ipAddress": entry.ip_address,
        "userAgent": entry.user_agent,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }


@router.get("/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(None, description="Exact match on resource_id column"),
    date_from: Optional[str] = Query(None, description="ISO 8601 start time (inclusive)"),
    date_to: Optional[str] = Query(None, description="ISO 8601 end time (inclusive)"),
    q: Optional[str] = Query(None, description="Keyword search across action, resource, resource_id, agent_name"),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List audit log entries, newest first. Supports filtering by action, resource, date range, and keyword search."""
    try:
        # Parse and validate date parameters
        parsed_from = _parse_iso_datetime(date_from, "date_from") if date_from else None
        parsed_to = _parse_iso_datetime(date_to, "date_to") if date_to else None
        _validate_date_range(parsed_from, parsed_to)

        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            stmt = select(AuditLog)
            if action:
                stmt = stmt.where(AuditLog.action == action)
            if resource:
                stmt = stmt.where(AuditLog.resource == resource)
            if resource_id:
                stmt = stmt.where(AuditLog.resource_id == resource_id)
            if parsed_from:
                stmt = stmt.where(AuditLog.timestamp >= parsed_from)
            if parsed_to:
                stmt = stmt.where(AuditLog.timestamp <= parsed_to)
            if q:
                like_pattern = f"%{q}%"
                stmt = stmt.where(
                    or_(
                        AuditLog.action.ilike(like_pattern),
                        AuditLog.resource.ilike(like_pattern),
                        AuditLog.resource_id.ilike(like_pattern),
                        AuditLog.agent_name.ilike(like_pattern),
                    )
                )
            stmt = stmt.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            # Get total count for pagination (same filters)
            count_stmt = select(func.count(AuditLog.id))
            if action:
                count_stmt = count_stmt.where(AuditLog.action == action)
            if resource:
                count_stmt = count_stmt.where(AuditLog.resource == resource)
            if resource_id:
                count_stmt = count_stmt.where(AuditLog.resource_id == resource_id)
            if parsed_from:
                count_stmt = count_stmt.where(AuditLog.timestamp >= parsed_from)
            if parsed_to:
                count_stmt = count_stmt.where(AuditLog.timestamp <= parsed_to)
            if q:
                like_pattern = f"%{q}%"
                count_stmt = count_stmt.where(
                    or_(
                        AuditLog.action.ilike(like_pattern),
                        AuditLog.resource.ilike(like_pattern),
                        AuditLog.resource_id.ilike(like_pattern),
                        AuditLog.agent_name.ilike(like_pattern),
                    )
                )
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            return {
                "entries": [_audit_to_dict(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to list audit logs: {e}")
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/audit-logs/stats")
async def audit_log_stats(
    date_from: Optional[str] = Query(None, description="ISO 8601 start time (inclusive)"),
    date_to: Optional[str] = Query(None, description="ISO 8601 end time (inclusive)"),
):
    """Return aggregated audit log statistics for the analytics dashboard."""
    try:
        # Parse and validate date parameters
        parsed_from = _parse_iso_datetime(date_from, "date_from") if date_from else None
        parsed_to = _parse_iso_datetime(date_to, "date_to") if date_to else None
        _validate_date_range(parsed_from, parsed_to)

        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            # Build optional timestamp filter
            timestamp_filters = []
            if parsed_from:
                timestamp_filters.append(AuditLog.timestamp >= parsed_from)
            if parsed_to:
                timestamp_filters.append(AuditLog.timestamp <= parsed_to)

            # Count by action
            action_stmt = select(AuditLog.action, func.count(AuditLog.id))
            for f in timestamp_filters:
                action_stmt = action_stmt.where(f)
            action_stmt = action_stmt.group_by(AuditLog.action)
            action_result = await session.execute(action_stmt)
            by_action = {row[0]: row[1] for row in action_result.all()}

            # Count by resource
            resource_stmt = select(AuditLog.resource, func.count(AuditLog.id))
            for f in timestamp_filters:
                resource_stmt = resource_stmt.where(f)
            resource_stmt = resource_stmt.group_by(AuditLog.resource)
            resource_result = await session.execute(resource_stmt)
            by_resource = {row[0]: row[1] for row in resource_result.all()}

            # Total count
            total_stmt = select(func.count(AuditLog.id))
            for f in timestamp_filters:
                total_stmt = total_stmt.where(f)
            total_result = await session.execute(total_stmt)
            total = total_result.scalar() or 0

            return {
                "total": total,
                "byAction": by_action,
                "byResource": by_resource,
            }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to get audit log stats: {e}")
        return {"total": 0, "byAction": {}, "byResource": {}}
