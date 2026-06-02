"""
LLM Provider Management API

Endpoints for listing providers, checking health, discovering models,
and managing execution defaults. Secrets are never returned to the frontend.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from core.llm import registry

router = APIRouter(prefix="/llm")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProviderConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    defaultModel: Optional[str] = None


class DefaultsUpdate(BaseModel):
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    harness: Optional[str] = None
    maxRuntimeSeconds: Optional[int] = None
    tokenBudget: Optional[int] = None
    costBudget: Optional[float] = None
    streamingLogs: Optional[bool] = None


# ---------------------------------------------------------------------------
# GET /api/v1/llm/providers
# ---------------------------------------------------------------------------

@router.get("/providers")
async def list_providers():
    """Return all known providers with status and masked secrets."""
    return {"providers": registry.list_providers()}


# ---------------------------------------------------------------------------
# GET /api/v1/llm/providers/{provider_id}
# ---------------------------------------------------------------------------

@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str):
    """Return a single provider's status."""
    provider = registry.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return provider


# ---------------------------------------------------------------------------
# PUT /api/v1/llm/providers/{provider_id}/config
# ---------------------------------------------------------------------------

@router.put("/providers/{provider_id}/config")
async def update_provider_config(provider_id: str, body: ProviderConfigUpdate):
    """
    Update provider configuration (enabled/default model).
    This is an in-memory stub for P0/P1; real persistence comes later.
    """
    provider = registry.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    # P1 stub: accept the update, return current provider state
    if body.enabled is not None:
        provider["enabled"] = body.enabled
    if body.defaultModel is not None:
        provider["defaultModel"] = body.defaultModel
    return provider


# ---------------------------------------------------------------------------
# POST /api/v1/llm/providers/{provider_id}/health
# ---------------------------------------------------------------------------

@router.post("/providers/{provider_id}/health")
async def check_provider_health(provider_id: str):
    """Check provider health (env var verification for P0/P1)."""
    result = registry.check_health(provider_id)
    return {
        "providerId": provider_id,
        "status": result["status"],
        "error": result["error"],
    }


# ---------------------------------------------------------------------------
# GET /api/v1/llm/providers/{provider_id}/models
# ---------------------------------------------------------------------------

@router.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: str):
    """Return available models for a provider."""
    models = registry.list_models(provider_id)
    if models is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return {"providerId": provider_id, "models": models}


# ---------------------------------------------------------------------------
# GET /api/v1/llm/defaults
# ---------------------------------------------------------------------------

@router.get("/defaults")
async def get_defaults():
    """Return current execution defaults."""
    return registry.get_defaults()


# ---------------------------------------------------------------------------
# PUT /api/v1/llm/defaults
# ---------------------------------------------------------------------------

@router.put("/defaults")
async def update_defaults(body: DefaultsUpdate):
    """Update execution defaults."""
    data = body.model_dump(exclude_none=True)
    return registry.update_defaults(data)
