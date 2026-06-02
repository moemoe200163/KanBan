"""
Audit Log API endpoint.

Provides read-only access to the audit_logs table.
The audit log tracks all significant system actions: issue changes,
ECC job dispatches, quality gate results, and review decisions.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Query
from sqlalchemy import select, func

from db import database as _db
from db.models import AuditLog

router = APIRouter()


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
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List audit log entries, newest first. Supports filtering by action and resource."""
    try:
        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            stmt = select(AuditLog)
            if action:
                stmt = stmt.where(AuditLog.action == action)
            if resource:
                stmt = stmt.where(AuditLog.resource == resource)
            stmt = stmt.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            # Get total count for pagination
            count_stmt = select(func.count(AuditLog.id))
            if action:
                count_stmt = count_stmt.where(AuditLog.action == action)
            if resource:
                count_stmt = count_stmt.where(AuditLog.resource == resource)
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            return {
                "entries": [_audit_to_dict(r) for r in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to list audit logs: {e}")
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/audit-logs/stats")
async def audit_log_stats():
    """Return aggregated audit log statistics for the analytics dashboard."""
    try:
        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            # Count by action
            action_stmt = select(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action)
            action_result = await session.execute(action_stmt)
            by_action = {row[0]: row[1] for row in action_result.all()}

            # Count by resource
            resource_stmt = select(AuditLog.resource, func.count(AuditLog.id)).group_by(AuditLog.resource)
            resource_result = await session.execute(resource_stmt)
            by_resource = {row[0]: row[1] for row in resource_result.all()}

            # Total count
            total_result = await session.execute(select(func.count(AuditLog.id)))
            total = total_result.scalar() or 0

            return {
                "total": total,
                "byAction": by_action,
                "byResource": by_resource,
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to get audit log stats: {e}")
        return {"total": 0, "byAction": {}, "byResource": {}}
