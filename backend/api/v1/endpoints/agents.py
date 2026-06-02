from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List

router = APIRouter()

# Agent profiles available for dispatch
AGENT_PROFILES = ["frontend", "backend", "security", "refactor", "debug"]


class AgentDispatchRequest(BaseModel):
    issue_id: str
    profile: str


class AgentStatus(BaseModel):
    status: str  # idle, busy, error
    current_task: Optional[str] = None


# In-memory agent registry (in production, use Redis or similar)
_agent_registry: Dict[str, AgentStatus] = {
    profile: AgentStatus(status="idle", current_task=None)
    for profile in AGENT_PROFILES
}


@router.get("/agents/status")
async def get_agent_status():
    """
    Get all agent statuses.

    Returns the current status of all registered agents including:
    - idle: Agent is available
    - busy: Agent is currently handling a task
    - error: Agent encountered an error

    Returns:
        Dictionary mapping agent profiles to their status objects
    """
    return {
        "frontend": _agent_registry["frontend"].model_dump(),
        "backend": _agent_registry["backend"].model_dump(),
        "security": _agent_registry["security"].model_dump(),
        "refactor": _agent_registry["refactor"].model_dump(),
        "debug": _agent_registry["debug"].model_dump()
    }


@router.post("/agents/dispatch")
async def dispatch_agent(request: AgentDispatchRequest):
    """
    Dispatch an agent to handle an issue.

    Selects an agent based on the requested profile and assigns
    the issue to them for processing.

    Args:
        request: Contains issue_id and the agent profile to dispatch

    Returns:
        Dispatch confirmation with agent_id

    Raises:
        HTTPException 400: If agent profile is invalid
        HTTPException 409: If agent is already busy
    """
    # Validate agent profile
    if request.profile not in AGENT_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent profile. Available: {AGENT_PROFILES}"
        )

    # Check if agent is available
    agent = _agent_registry.get(request.profile)
    if not agent:
        raise HTTPException(
            status_code=400,
            detail=f"Agent profile '{request.profile}' not found"
        )

    if agent.status == "busy":
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{request.profile}' is currently busy with task: {agent.current_task}"
        )

    # Dispatch the agent (update status to busy)
    agent.status = "busy"
    agent.current_task = request.issue_id

    # TODO: Integrate with task queue (e.g., Celery, Redis)
    # This would typically enqueue a task for the agent to process

    return {
        "status": "dispatched",
        "agent_id": request.profile,
        "assigned_issue": request.issue_id
    }


@router.post("/agents/terminate")
async def terminate_agent(agent_id: str):
    """
    Terminate a running agent.

    Forces termination of an agent's current task and sets
    the agent back to idle status.

    Args:
        agent_id: The agent profile to terminate

    Returns:
        Termination confirmation

    Raises:
        HTTPException 400: If agent_id is invalid
    """
    if agent_id not in AGENT_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent profile. Available: {AGENT_PROFILES}"
        )

    agent = _agent_registry[agent_id]

    # Reset agent status
    previous_task = agent.current_task
    agent.status = "idle"
    agent.current_task = None

    # TODO: Cancel any pending tasks in the queue

    return {
        "status": "terminated",
        "agent_id": agent_id,
        "released_task": previous_task
    }


# Test cases for get_agent_status
# - Should return all agent statuses when called
# - Should return idle status for all agents initially

# Test cases for dispatch_agent
# - Should return dispatched when valid profile and issue_id provided
# - Should return 400 when invalid agent profile
# - Should return 409 when agent is already busy
# - Should update agent status to busy after dispatch

# Test cases for terminate_agent
# - Should return terminated when valid agent_id
# - Should return 400 when invalid agent_id
# - Should reset agent status to idle after termination
