"""Kanban Tool Protocol — REST API endpoints.

Provides a unified REST interface for the kanban tool functions.
Agents can call these endpoints instead of guessing individual
issue/handoff/artifact API patterns.

Each POST /kanban/{tool} call maps to the corresponding tool function
in core.kanban_protocol.tools.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth
from fastapi import Depends
from core.kanban_protocol.board_scope import assert_board_id_allowed
from core.kanban_protocol.tools import (
    KanbanToolContext,
    ToolResult,
    invoke_tool,
    KANBAN_TOOLS,
)
from db import repository as repo

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# JSON Schema definitions for each kanban tool
# ---------------------------------------------------------------------------

_BASE_PROPERTIES: Dict[str, Any] = {
    "board_id": {"type": "string", "description": "Board this operation targets", "default": "board-default"},
    "issue_id": {"type": "string", "description": "Issue ID to operate on"},
    "issue_key": {"type": "string", "description": "Issue key to operate on"},
    "actor": {"type": "string", "description": "Who is performing the action"},
    "agent_role": {"type": "string", "description": "Role of the calling agent"},
    "profile": {"type": "string", "description": "Execution profile"},
}

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "kanban_list": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by issue status"},
                },
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_show": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_create": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Issue title"},
                    "description": {"type": "string", "description": "Issue description"},
                    "status": {"type": "string", "description": "Initial status"},
                    "priority": {"type": "string", "description": "Issue priority"},
                },
                "required": ["title"],
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_comment": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "Comment body"},
                },
                "required": ["body"],
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_block": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Reason for blocking", "default": "Blocked by agent"},
                    "type": {"type": "string", "description": "Block type"},
                },
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_unblock": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_complete": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "result_summary": {"type": "string", "description": "Summary of the result"},
                    "evidence": {"type": "array", "items": {"type": "object"}, "description": "Evidence references"},
                    "from_lane": {"type": "string", "description": "Lane the issue is completing from"},
                },
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_heartbeat": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "worker_id": {"type": "string", "description": "Worker identifier"},
                    "run_id": {"type": "string", "description": "Run identifier"},
                },
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
    "kanban_link": {
        "type": "object",
        "properties": {
            **_BASE_PROPERTIES,
            "payload": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Link URL"},
                    "type": {"type": "string", "description": "Link type"},
                    "title": {"type": "string", "description": "Link title"},
                    "metadata": {"type": "object", "description": "Additional metadata"},
                },
                "required": ["url"],
            },
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "next_role": {"type": "string"},
            "run_id": {"type": "string", "description": "Associated run ID for audit trail"},
        },
    },
}


class KanbanToolRequest(BaseModel):
    """Standard request body for kanban tool calls."""
    board_id: str = Field(default="board-default", description="Board this operation targets")
    issue_id: Optional[str] = Field(default=None, description="Issue ID to operate on")
    issue_key: Optional[str] = Field(default=None, description="Issue key to operate on")
    actor: str = Field(default="agent", description="Who is performing the action")
    agent_role: str = Field(default="safe-runner", description="Role of the calling agent")
    profile: str = Field(default="general", description="Execution profile")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Additional data for the operation")
    artifacts: Optional[List[Dict[str, Any]]] = Field(default=None, description="Artifact references to attach")
    next_role: Optional[str] = Field(default=None, description="For handoff routing")
    run_id: Optional[str] = Field(default=None, description="Associated run ID for audit trail")


class KanbanToolResponse(BaseModel):
    """Standard response from kanban tool calls."""
    ok: bool
    tool: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/kanban/tools")
async def list_kanban_tools():
    """List all available kanban tools."""
    tools = []
    for name, fn in KANBAN_TOOLS.items():
        doc = fn.__doc__ or ""
        tools.append({
            "name": name,
            "description": doc.strip().split("\n")[0] if doc else "",
            "input_schema": TOOL_SCHEMAS.get(name, {}),
        })
    return {"tools": tools}


@router.post("/kanban/{tool_name}", response_model=KanbanToolResponse)
async def call_kanban_tool(
    tool_name: str,
    request: KanbanToolRequest,
    current_user: dict = Depends(require_auth),
):
    """Call a kanban tool by name.

    Available tools: kanban_list, kanban_show, kanban_create, kanban_comment,
    kanban_block, kanban_unblock, kanban_complete, kanban_heartbeat, kanban_link.
    """
    if tool_name not in KANBAN_TOOLS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool: {tool_name}. Available: {sorted(KANBAN_TOOLS.keys())}",
        )

    try:
        assert_board_id_allowed(request.board_id)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ctx = KanbanToolContext(
        board_id=request.board_id,
        issue_id=request.issue_id,
        issue_key=request.issue_key,
        actor=current_user.get("username", request.actor),
        agent_role=request.agent_role,
        profile=request.profile,
        payload=request.payload,
        artifacts=request.artifacts,
        next_role=request.next_role,
    )

    result: ToolResult = await invoke_tool(tool_name, ctx)

    # -- tool-call audit trail --------------------------------------------------
    event_type = "tool_call_completed" if result.ok else "tool_call_failed"
    event_meta: Dict[str, Any] = {
        "tool_name": tool_name,
        "actor": ctx.actor,
        "agent_role": ctx.agent_role,
        "board_id": ctx.board_id,
        "ok": result.ok,
    }
    if ctx.issue_id:
        event_meta["issue_id"] = ctx.issue_id
    if ctx.issue_key:
        event_meta["issue_key"] = ctx.issue_key
    if result.error:
        event_meta["error"] = result.error

    if request.run_id:
        try:
            await repo.append_run_event(
                id=str(uuid.uuid4()),
                run_id=request.run_id,
                event_type=event_type,
                message=f"tool={tool_name} ok={result.ok}",
                extra_metadata=event_meta,
            )
        except Exception:
            logger.warning(
                "Failed to write tool-call audit event for run %s",
                request.run_id,
            )
    # ---------------------------------------------------------------------------

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)

    return KanbanToolResponse(
        ok=result.ok,
        tool=result.tool,
        data=result.data,
        error=result.error,
    )
