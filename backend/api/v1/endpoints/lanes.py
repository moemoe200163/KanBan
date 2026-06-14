"""Worker Lane read-only API.

Reads from the agent_roles database table. On startup, default roles are
seeded from the code-defined WORKER_LANES registry via seed_default_roles().
"""
import logging

from fastapi import APIRouter

from db import repository as repo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/lanes")
async def list_lanes():
    """Return enabled agent roles in the legacy lanes response shape.

    The response shape is kept identical to the original WORKER_LANES-based
    response for backward compatibility. The key difference:
    DB column ``next_roles`` is mapped to ``nextLanes`` in the response.
    """
    roles = await repo.list_agent_roles(include_disabled=False)

    lanes = []
    for role in roles:
        lanes.append({
            "key": role["key"],
            "displayName": role["displayName"],
            "description": role["description"],
            "allowedProfiles": role["allowedProfiles"],
            "defaultProvider": role["defaultProvider"],
            "defaultModel": role["defaultModel"],
            "allowedCommands": role["allowedCommands"],
            "requiredCompletionFields": role["requiredCompletionFields"],
            "timeoutSeconds": role["timeoutSeconds"],
            "retryPolicy": role["retryPolicy"],
            "retryMax": role["retryMax"],
            "nextLanes": role["nextRoles"],
            "humanApprovalRequired": role["humanApprovalRequired"],
        })

    return {"lanes": lanes}
