"""Kanban Tool Protocol — REST API endpoints.

Provides a unified REST interface for the kanban tool functions.
Agents can call these endpoints instead of guessing individual
issue/handoff/artifact API patterns.

Each POST /kanban/{tool} call maps to the corresponding tool function
in core.kanban_protocol.tools.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth
from fastapi import Depends
from core.kanban_protocol.tools import (
    KanbanToolContext,
    ToolResult,
    invoke_tool,
    KANBAN_TOOLS,
)

router = APIRouter()


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

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)

    return KanbanToolResponse(
        ok=result.ok,
        tool=result.tool,
        data=result.data,
        error=result.error,
    )
