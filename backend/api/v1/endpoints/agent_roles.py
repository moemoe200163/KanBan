"""Agent Roles — CRUD API for configurable agent role definitions."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_admin, require_auth
from db import repository as repo

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AgentRoleCreate(BaseModel):
    """Request body for creating a new agent role."""
    key: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    displayName: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    allowedProfiles: List[str] = Field(default_factory=list)
    defaultProvider: str = Field(default="", max_length=32)
    defaultModel: str = Field(default="", max_length=128)
    allowedCommands: List[str] = Field(default_factory=list)
    timeoutSeconds: int = Field(default=1800, ge=1, le=86400)
    retryPolicy: str = Field(default="none", pattern=r"^(none|fixed|exponential)$")
    retryMax: int = Field(default=0, ge=0, le=10)
    nextRoles: List[str] = Field(default_factory=list)
    humanApprovalRequired: bool = Field(default=False)
    enabled: bool = Field(default=True)
    requiredCompletionFields: List[str] = Field(default_factory=list)
    systemPrompt: str = Field(default="", max_length=32768)
    taskPromptTemplate: str = Field(default="", max_length=32768)
    reviewPromptTemplate: str = Field(default="", max_length=32768)


class AgentRoleUpdate(BaseModel):
    """Request body for updating an existing agent role.

    All fields optional — only provided fields are updated.
    The key is immutable and cannot be changed.
    """
    displayName: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    allowedProfiles: Optional[List[str]] = None
    defaultProvider: Optional[str] = Field(default=None, max_length=32)
    defaultModel: Optional[str] = Field(default=None, max_length=128)
    allowedCommands: Optional[List[str]] = None
    timeoutSeconds: Optional[int] = Field(default=None, ge=1, le=86400)
    retryPolicy: Optional[str] = Field(default=None, pattern=r"^(none|fixed|exponential)$")
    retryMax: Optional[int] = Field(default=None, ge=0, le=10)
    nextRoles: Optional[List[str]] = None
    humanApprovalRequired: Optional[bool] = None
    enabled: Optional[bool] = None
    requiredCompletionFields: Optional[List[str]] = None
    systemPrompt: Optional[str] = Field(default=None, max_length=32768)
    taskPromptTemplate: Optional[str] = Field(default=None, max_length=32768)
    reviewPromptTemplate: Optional[str] = Field(default=None, max_length=32768)


class AgentRoleEnabledToggle(BaseModel):
    """Request body for toggling the enabled state of a role."""
    enabled: bool


# ---------------------------------------------------------------------------
# Helpers — map camelCase API fields to snake_case DB fields
# ---------------------------------------------------------------------------

_CAMEL_TO_SNAKE = {
    "displayName": "display_name",
    "description": "description",
    "allowedProfiles": "allowed_profiles",
    "defaultProvider": "default_provider",
    "defaultModel": "default_model",
    "allowedCommands": "allowed_commands",
    "timeoutSeconds": "timeout_seconds",
    "retryPolicy": "retry_policy",
    "retryMax": "retry_max",
    "nextRoles": "next_roles",
    "humanApprovalRequired": "human_approval_required",
    "enabled": "enabled",
    "requiredCompletionFields": "required_completion_fields",
    "systemPrompt": "system_prompt",
    "taskPromptTemplate": "task_prompt_template",
    "reviewPromptTemplate": "review_prompt_template",
}


def _to_db_fields(data: dict) -> dict:
    """Convert camelCase request fields to snake_case DB column names."""
    result = {}
    for camel_key, value in data.items():
        snake_key = _CAMEL_TO_SNAKE.get(camel_key)
        if snake_key and value is not None:
            result[snake_key] = value
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/agent-roles")
async def list_agent_roles(user: dict = Depends(require_auth)):
    """Return all agent roles (enabled + disabled).

    Any authenticated user can view roles.
    """
    roles = await repo.list_agent_roles(include_disabled=True)
    return {"roles": roles}


@router.post("/agent-roles", status_code=201)
async def create_agent_role(
    body: AgentRoleCreate,
    user: dict = Depends(require_admin),
):
    """Create a new agent role. Admin only.

    Rejects duplicate keys. System roles cannot be created via this endpoint.
    """
    existing = await repo.get_agent_role(body.key)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent role with key '{body.key}' already exists",
        )

    data = body.model_dump()
    db_data = _to_db_fields(data)
    # key is stored directly (not camelCase)
    db_data["key"] = body.key

    try:
        created = await repo.create_agent_role(db_data)
    except Exception as e:
        logger.warning(f"Failed to create agent role '{body.key}': {e}")
        raise HTTPException(status_code=500, detail="Failed to create agent role")

    return created


@router.put("/agent-roles/{key}")
async def update_agent_role(
    key: str,
    body: AgentRoleUpdate,
    user: dict = Depends(require_admin),
):
    """Update an existing agent role. Admin only.

    System roles (is_system=True) have an immutable key — attempting to
    change the key in a PUT request is rejected with 400. All other fields
    can be edited on system roles.
    """
    existing = await repo.get_agent_role(key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Agent role '{key}' not found")

    # Only include fields that were explicitly set in the request
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    db_data = _to_db_fields(update_data)

    try:
        updated = await repo.update_agent_role(key, db_data)
    except Exception as e:
        logger.warning(f"Failed to update agent role '{key}': {e}")
        raise HTTPException(status_code=500, detail="Failed to update agent role")

    if not updated:
        raise HTTPException(status_code=404, detail=f"Agent role '{key}' not found")

    return updated


@router.patch("/agent-roles/{key}/enabled")
async def toggle_agent_role_enabled(
    key: str,
    body: AgentRoleEnabledToggle,
    user: dict = Depends(require_admin),
):
    """Toggle the enabled state of an agent role. Admin only.

    Disabling a role that has active (non-terminal) handoffs returns 409 Conflict.
    """
    existing = await repo.get_agent_role(key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Agent role '{key}' not found")

    # Prevent disabling a role with active handoffs
    if not body.enabled:
        active_count = await repo.count_active_handoffs_for_role(key)
        if active_count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot disable role '{key}': "
                    f"{active_count} active handoff(s) in progress"
                ),
            )

    try:
        updated = await repo.set_agent_role_enabled(key, body.enabled)
    except Exception as e:
        logger.warning(f"Failed to toggle enabled for role '{key}': {e}")
        raise HTTPException(status_code=500, detail="Failed to update agent role")

    if not updated:
        raise HTTPException(status_code=404, detail=f"Agent role '{key}' not found")

    return updated
