"""Worker Lane read-only API."""
from fastapi import APIRouter

from core.kanban_protocol.lanes import WORKER_LANES

router = APIRouter()


@router.get("/lanes")
async def list_lanes():
    """Return the code-defined worker lane registry."""
    lanes = [
        {
            "key": lane.key,
            "displayName": lane.display_name,
            "description": lane.description,
            "allowedProfiles": lane.allowed_profiles,
            "defaultProvider": lane.default_provider,
            "defaultModel": lane.default_model,
            "allowedCommands": lane.allowed_commands,
            "requiredCompletionFields": lane.required_completion_fields,
            "timeoutSeconds": lane.timeout_seconds,
            "retryPolicy": lane.retry_policy,
            "retryMax": lane.retry_max,
            "nextLanes": lane.next_lanes,
            "humanApprovalRequired": lane.human_approval_required,
        }
        for lane in WORKER_LANES.values()
    ]
    return {"lanes": lanes}
