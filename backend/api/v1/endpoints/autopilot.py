"""Autopilot API — control and monitor the background scheduler."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.v1.auth_deps import require_admin

from core.kanban_protocol.autopilot import scheduler

router = APIRouter()


class AutopilotStatusResponse(BaseModel):
    enabled: bool
    running: bool
    tickInterval: int
    lastTickAt: Optional[str] = None
    lastTickResult: Optional[dict] = None
    totalDispatched: int
    totalTimedOut: int


class AutopilotToggleRequest(BaseModel):
    enabled: bool


@router.get("/autopilot/status", response_model=AutopilotStatusResponse)
async def get_autopilot_status():
    """Return the current autopilot scheduler state."""
    s = scheduler.status
    return AutopilotStatusResponse(**s)


@router.post("/autopilot/status", response_model=AutopilotStatusResponse)
async def set_autopilot_status(body: AutopilotToggleRequest, current_user: dict = Depends(require_admin)):
    """Enable or disable the autopilot scheduler."""
    if body.enabled:
        result = scheduler.enable()
    else:
        result = scheduler.disable()
    return AutopilotStatusResponse(**result)


@router.post("/autopilot/tick")
async def trigger_autopilot_tick(current_user: dict = Depends(require_admin)):
    """Manually trigger one autopilot cycle (for testing/debugging)."""
    result = await scheduler.tick()
    return {"status": "ok", "result": result}
