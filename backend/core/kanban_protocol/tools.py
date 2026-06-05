"""Kanban Tool Protocol — semantic tool layer for agent interactions.

Provides named tool functions that agents can call to interact with the
Kanban board. Each tool maps to existing handoff/issue/artifact APIs
under the hood, giving agents a clean semantic interface instead of
requiring them to guess REST URL patterns.

Every tool accepts a KanbanToolContext with:
- board_id: which board this operation targets
- issue_id / issue_key: the issue to operate on
- actor: who is performing the action
- agent_role: the role of the agent calling the tool
- profile: the execution profile
- payload: additional data for the operation
- artifacts: artifact references to attach
- next_role: for handoff routing
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from db import repository as repo

logger = logging.getLogger(__name__)


@dataclass
class KanbanToolContext:
    """Standard context for all Kanban tool invocations."""
    board_id: str = "board-default"
    issue_id: Optional[str] = None
    issue_key: Optional[str] = None
    actor: str = "system"
    agent_role: str = "safe-runner"
    profile: str = "general"
    payload: Optional[Dict[str, Any]] = None
    artifacts: Optional[List[Dict[str, Any]]] = None
    next_role: Optional[str] = None


@dataclass
class ToolResult:
    """Standard result from a Kanban tool invocation."""
    ok: bool
    tool: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def kanban_list(ctx: KanbanToolContext) -> ToolResult:
    """List issues on a board, optionally filtered by status."""
    try:
        status_filter = (ctx.payload or {}).get("status")
        issues = await repo.list_issues(board_id=ctx.board_id)
        if status_filter:
            issues = [i for i in issues if i.get("status") == status_filter]
        return ToolResult(ok=True, tool="kanban_list", data={"issues": issues, "total": len(issues)})
    except Exception as exc:
        logger.warning("kanban_list failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_list", error=str(exc))


async def kanban_show(ctx: KanbanToolContext) -> ToolResult:
    """Show detailed information about a single issue."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_show", error="Issue not found")

        # Enrich with handoffs and artifacts
        handoffs = await repo.list_issue_handoffs(issue_id=issue["id"], board_id=ctx.board_id)
        artifacts = await repo.list_issue_artifacts(issue_id=issue["id"])

        return ToolResult(ok=True, tool="kanban_show", data={
            "issue": issue,
            "handoffs": handoffs,
            "artifacts": artifacts,
        })
    except Exception as exc:
        logger.warning("kanban_show failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_show", error=str(exc))


async def kanban_create(ctx: KanbanToolContext) -> ToolResult:
    """Create a new issue on the board."""
    try:
        import uuid
        payload = ctx.payload or {}
        title = payload.get("title")
        if not title:
            return ToolResult(ok=False, tool="kanban_create", error="payload.title is required")

        new_id = str(uuid.uuid4())
        new_key = await repo.next_issue_key()

        issue = await repo.upsert_issue({
            "id": new_id,
            "key": new_key,
            "board_id": ctx.board_id,
            "title": title,
            "description": payload.get("description", ""),
            "status": payload.get("status", "backlog"),
            "priority": payload.get("priority", "medium"),
            "profile": ctx.profile,
        })

        # Attach artifacts if provided
        if ctx.artifacts:
            for artifact in ctx.artifacts:
                await repo.create_issue_artifact(
                    issue_id=issue["id"],
                    artifact_type=artifact.get("type", "file"),
                    title=artifact.get("title", ""),
                    path_or_url=artifact.get("url", ""),
                    metadata=artifact.get("metadata"),
                    board_id=ctx.board_id,
                )

        logger.info("kanban_create: issue %s created by %s", issue.get("key"), ctx.actor)
        return ToolResult(ok=True, tool="kanban_create", data={"issue": issue})
    except Exception as exc:
        logger.warning("kanban_create failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_create", error=str(exc))


async def kanban_comment(ctx: KanbanToolContext) -> ToolResult:
    """Add a comment to an issue."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_comment", error="Issue not found")

        payload = ctx.payload or {}
        body = payload.get("body", "")
        if not body:
            return ToolResult(ok=False, tool="kanban_comment", error="payload.body is required")

        comment = await repo.create_issue_comment(
            issue_id=issue["id"],
            body=body,
            author_id=ctx.actor,
            author_name=ctx.actor,
            comment_type=ctx.agent_role,
        )

        return ToolResult(ok=True, tool="kanban_comment", data={"comment": comment})
    except Exception as exc:
        logger.warning("kanban_comment failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_comment", error=str(exc))


async def kanban_block(ctx: KanbanToolContext) -> ToolResult:
    """Block an issue with a reason."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_block", error="Issue not found")

        payload = ctx.payload or {}
        reason = payload.get("reason", "Blocked by agent")
        block_type = payload.get("type", "agent_block")

        # Find the active handoff and block it
        handoffs = await repo.list_issue_handoffs(issue_id=issue["id"], board_id=ctx.board_id)
        active = [h for h in handoffs if h["status"] in ("pending", "accepted", "in_progress")]

        if active:
            from core.kanban_protocol.handoff import HandoffService
            svc = HandoffService()
            for h in active:
                await svc.block(handoff_id=h["id"], actor=ctx.actor, reason=reason)

        # Update issue status to blocked
        await repo.upsert_issue({
            "id": issue["id"],
            "key": issue["key"],
            "title": issue["title"],
            "status": "blocked",
            "board_id": ctx.board_id,
        })

        logger.info("kanban_block: issue %s blocked by %s", issue.get("key"), ctx.actor)
        return ToolResult(ok=True, tool="kanban_block", data={"issue_id": issue["id"], "reason": reason})
    except Exception as exc:
        logger.warning("kanban_block failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_block", error=str(exc))


async def kanban_unblock(ctx: KanbanToolContext) -> ToolResult:
    """Unblock a blocked issue."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_unblock", error="Issue not found")

        # Find blocked handoffs and unblock them
        handoffs = await repo.list_issue_handoffs(issue_id=issue["id"], board_id=ctx.board_id)
        blocked = [h for h in handoffs if h["status"] == "blocked"]

        if blocked:
            from core.kanban_protocol.handoff import HandoffService
            svc = HandoffService()
            for h in blocked:
                await svc.unblock(handoff_id=h["id"], actor=ctx.actor)

        # Restore issue status to in_progress
        await repo.upsert_issue({
            "id": issue["id"],
            "key": issue["key"],
            "title": issue["title"],
            "status": "in_progress",
            "board_id": ctx.board_id,
        })

        logger.info("kanban_unblock: issue %s unblocked by %s", issue.get("key"), ctx.actor)
        return ToolResult(ok=True, tool="kanban_unblock", data={"issue_id": issue["id"]})
    except Exception as exc:
        logger.warning("kanban_unblock failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_unblock", error=str(exc))


async def kanban_complete(ctx: KanbanToolContext) -> ToolResult:
    """Complete work on an issue — creates completion handoff with evidence."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_complete", error="Issue not found")

        payload = ctx.payload or {}

        # Create a completion handoff to review lane
        from core.kanban_protocol.handoff import HandoffService
        svc = HandoffService()
        handoff = await svc.create(
            issue_id=issue["id"],
            board_id=ctx.board_id,
            from_lane=payload.get("from_lane", ctx.profile),
            to_lane="review",
            payload={
                "result_summary": payload.get("result_summary", "Work complete"),
                "completion_evidence": payload.get("evidence", []),
                "next_role": ctx.next_role,
                "actor": ctx.actor,
            },
            created_by=ctx.actor,
        )

        # Attach artifacts
        if ctx.artifacts:
            for artifact in ctx.artifacts:
                await repo.create_issue_artifact(
                    issue_id=issue["id"],
                    artifact_type=artifact.get("type", "file"),
                    title=artifact.get("title", ""),
                    path_or_url=artifact.get("url", ""),
                    metadata=artifact.get("metadata"),
                    board_id=ctx.board_id,
                )

        logger.info("kanban_complete: issue %s → review (handoff %s)", issue.get("key"), handoff.get("id"))
        return ToolResult(ok=True, tool="kanban_complete", data={"handoff": handoff})
    except Exception as exc:
        logger.warning("kanban_complete failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_complete", error=str(exc))


async def kanban_heartbeat(ctx: KanbanToolContext) -> ToolResult:
    """Send a heartbeat for a running worker or agent."""
    try:
        payload = ctx.payload or {}
        worker_id = payload.get("worker_id")
        run_id = payload.get("run_id")

        if worker_id:
            await repo.update_worker_heartbeat(worker_id)
        if run_id:
            await repo.update_run_heartbeat(run_id)

        return ToolResult(ok=True, tool="kanban_heartbeat", data={
            "worker_id": worker_id,
            "run_id": run_id,
        })
    except Exception as exc:
        logger.warning("kanban_heartbeat failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_heartbeat", error=str(exc))


async def kanban_link(ctx: KanbanToolContext) -> ToolResult:
    """Link an artifact, PR, or external resource to an issue."""
    try:
        issue = await _resolve_issue(ctx)
        if not issue:
            return ToolResult(ok=False, tool="kanban_link", error="Issue not found")

        payload = ctx.payload or {}
        artifact_type = payload.get("type", "link")
        title = payload.get("title", "")
        url = payload.get("url", "")

        if not url:
            return ToolResult(ok=False, tool="kanban_link", error="payload.url is required")

        artifact = await repo.create_issue_artifact(
            issue_id=issue["id"],
            artifact_type=artifact_type,
            title=title,
            path_or_url=url,
            metadata=payload.get("metadata"),
            board_id=ctx.board_id,
        )

        return ToolResult(ok=True, tool="kanban_link", data={"artifact": artifact})
    except Exception as exc:
        logger.warning("kanban_link failed: %s", exc)
        return ToolResult(ok=False, tool="kanban_link", error=str(exc))


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

KANBAN_TOOLS = {
    "kanban_list": kanban_list,
    "kanban_show": kanban_show,
    "kanban_create": kanban_create,
    "kanban_comment": kanban_comment,
    "kanban_block": kanban_block,
    "kanban_unblock": kanban_unblock,
    "kanban_complete": kanban_complete,
    "kanban_heartbeat": kanban_heartbeat,
    "kanban_link": kanban_link,
}


async def invoke_tool(tool_name: str, ctx: KanbanToolContext) -> ToolResult:
    """Invoke a kanban tool by name. Returns ToolResult."""
    tool_fn = KANBAN_TOOLS.get(tool_name)
    if not tool_fn:
        return ToolResult(ok=False, tool=tool_name, error=f"Unknown tool: {tool_name}")
    return await tool_fn(ctx)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_issue(ctx: KanbanToolContext) -> Optional[dict]:
    """Resolve an issue from context by id or key."""
    if ctx.issue_id:
        return await repo.get_issue(ctx.issue_id)
    if ctx.issue_key:
        issues = await repo.list_issues(board_id=ctx.board_id)
        for i in issues:
            if i.get("key") == ctx.issue_key:
                return i
    return None
