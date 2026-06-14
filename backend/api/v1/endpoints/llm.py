"""
LLM Provider Management API

Endpoints for listing providers, checking health, discovering models,
and managing execution defaults. Secrets are never returned to the frontend.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from api.v1.endpoints.auth import get_current_user, get_optional_user
from api.v1.auth_deps import require_admin
from core.llm import registry
from core.llm.crypto import encrypt_api_key, decrypt_api_key, mask_api_key
from core.llm.health_check import run_health_check
from db import database as _db
from db.models import AuditLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm")


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------
#
# Per-invocation token usage is NOT yet persisted in its own table. The
# /llm/usage endpoint reads from ``audit_logs`` where ``action='llm.invoke'``;
# future LLM call sites should call ``log_audit_event('llm.invoke', ...)`` with
# token counts in ``details`` and the aggregation below will pick them up.
# When no such rows exist (the current state), the endpoint returns an empty
# ``daily`` array with a ``note`` explaining the wiring. We do not create a
# new table for this — keeping the data flow on the existing audit log
# avoids a migration for what is, at the moment, observational metadata.


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProviderConfigUpdate(BaseModel):
    """Fields that can be updated on a provider config."""
    baseUrl: Optional[str] = None
    model: Optional[str] = None
    apiKey: Optional[str] = None
    enabled: Optional[bool] = None
    endpointPath: Optional[str] = None


class DefaultsUpdate(BaseModel):
    providerId: Optional[str] = None
    modelId: Optional[str] = None
    harness: Optional[str] = None
    maxRuntimeSeconds: Optional[int] = None
    tokenBudget: Optional[int] = None
    costBudget: Optional[float] = None
    streamingLogs: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_provider_config_dict(provider_id: str) -> Optional[dict]:
    """Get provider config from DB, with fallback to static defaults.

    Returns a dict suitable for API responses. Never includes the full
    API key -- only the masked prefix/suffix.
    """
    from db.repository import get_llm_provider_config

    config = await get_llm_provider_config(provider_id)
    if config:
        return config

    # Fallback to static definition
    p = registry.get_provider_def(provider_id)
    if not p:
        return None
    return {
        "providerId": p.id,
        "displayName": p.name,
        "enabled": p.enabled,
        "baseUrl": "",
        "model": p.default_model or "",
        "apiShape": p.adapter,
        "authType": p.auth_type,
        "lastTestStatus": "not_configured",
    }


def _safe_provider_response(provider_dict: Optional[dict]) -> Optional[dict]:
    """Strip sensitive fields and normalize keys for client consumption.

    - Removes api_key_encrypted
    - Adds providerId from id if missing
    - Adds model from defaultModel if missing
    """
    if provider_dict is None:
        return None
    safe = {k: v for k, v in provider_dict.items() if k != "apiKeyEncrypted"}
    # Normalize registry keys to API keys
    if "id" in safe and "providerId" not in safe:
        safe["providerId"] = safe["id"]
    if "defaultModel" in safe and "model" not in safe:
        safe["model"] = safe["defaultModel"]
    return safe


# ---------------------------------------------------------------------------
# GET /api/v1/llm/providers
# ---------------------------------------------------------------------------

@router.get("/providers")
async def list_providers():
    """Return all known providers with status and masked secrets."""
    try:
        providers = await registry.list_providers_from_db()
    except Exception:
        providers = registry.list_providers()
    return {"providers": [_safe_provider_response(p) for p in providers]}


# ---------------------------------------------------------------------------
# GET /api/v1/llm/providers/{provider_id}
# ---------------------------------------------------------------------------

@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str):
    """Return a single provider's status."""
    provider = await registry.get_provider_from_db(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return _safe_provider_response(provider)


# ---------------------------------------------------------------------------
# PUT /api/v1/llm/providers/{provider_id}/config
# ---------------------------------------------------------------------------

@router.put("/providers/{provider_id}/config")
async def update_provider_config(
    provider_id: str,
    body: ProviderConfigUpdate,
    current_user: dict = Depends(require_admin),
):
    """Update provider configuration with DB persistence.

    Accepts baseUrl, model, apiKey, enabled, and endpointPath.
    The API key is encrypted before storage and never returned in full.
    """
    # 1. Check provider exists in static PROVIDERS
    provider_def = registry.get_provider_def(provider_id)
    if not provider_def:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    # 2. Get existing DB config (or create new via upsert)
    from db.repository import get_llm_provider_config, upsert_llm_provider_config
    existing = await get_llm_provider_config(provider_id)

    # 3. Prepare API key fields
    api_key_encrypted = None
    api_key_prefix = None
    api_key_last4 = None
    if body.apiKey is not None and body.apiKey:
        api_key_encrypted = encrypt_api_key(body.apiKey)
        api_key_prefix, api_key_last4 = mask_api_key(body.apiKey)

    # 4. Determine fields to persist
    display_name = provider_def.name
    enabled = body.enabled if body.enabled is not None else (existing["enabled"] if existing else True)
    base_url = body.baseUrl if body.baseUrl is not None else (existing["baseUrl"] if existing else None)
    model = body.model if body.model is not None else (existing["model"] if existing else provider_def.default_model)
    endpoint_path = body.endpointPath if body.endpointPath is not None else (existing.get("endpointPath") if existing else None)
    api_shape = existing.get("apiShape") if existing else provider_def.adapter
    auth_type = existing.get("authType") if existing else provider_def.auth_type

    # 5. Upsert to DB
    result = await upsert_llm_provider_config(
        provider_id=provider_id,
        display_name=display_name,
        enabled=enabled,
        base_url=base_url,
        endpoint_path=endpoint_path,
        api_shape=api_shape,
        auth_type=auth_type,
        model=model,
        api_key_encrypted=api_key_encrypted,
        api_key_prefix=api_key_prefix,
        api_key_last4=api_key_last4,
    )

    return _safe_provider_response(result)


# ---------------------------------------------------------------------------
# POST /api/v1/llm/providers/{provider_id}/test
# ---------------------------------------------------------------------------

@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    current_user: dict = Depends(require_admin),
):
    """Run a real health check against the provider's API endpoint.

    Decrypts the stored API key, calls the provider with a minimal prompt,
    and persists the result. Returns a safe response with status, latency,
    and masked error details.
    """
    # 1. Check provider exists
    provider_def = registry.get_provider_def(provider_id)
    if not provider_def:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    # 2. Get DB config
    from db.repository import get_llm_provider_config
    config = await get_llm_provider_config(provider_id)

    # 3. Determine auth type and API key
    auth_type = config.get("authType") if config else provider_def.auth_type
    api_key = None

    if auth_type != "none":
        encrypted = config.get("apiKeyPrefix") if config else None
        # We need the actual encrypted key from DB, not just the mask
        # Re-read the raw model to get api_key_encrypted
        from db.models import LLMProviderConfig as LLMProviderConfigModel
        from db.database import AsyncSessionLocal, ensure_db_init
        from sqlalchemy import select

        await ensure_db_init()
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(LLMProviderConfigModel).where(
                    LLMProviderConfigModel.provider_id == provider_id
                )
            )
            db_row = row.scalar_one_or_none()

            if db_row and db_row.api_key_encrypted:
                api_key = decrypt_api_key(db_row.api_key_encrypted)
            else:
                # No API key configured -- return not_configured
                return {
                    "provider": provider_id,
                    "status": "not_configured",
                    "ok": False,
                    "latencyMs": 0,
                    "model": (config.get("model") if config else None) or provider_def.default_model or "",
                    "baseUrl": (config.get("baseUrl") if config else None) or "",
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "message": "API key not configured. Save an API key first.",
                    "safeError": "not_configured",
                }

    # 4. Determine base URL, endpoint path, model
    base_url = (config.get("baseUrl") if config else None) or ""
    endpoint_path = (config.get("endpointPath") if config else None) or ""
    model = (config.get("model") if config else None) or provider_def.default_model or ""
    api_shape = (config.get("apiShape") if config else None) or provider_def.adapter

    # If no base URL is configured, return not_configured
    if not base_url:
        return {
            "provider": provider_id,
            "status": "not_configured",
            "ok": False,
            "latencyMs": 0,
            "model": model,
            "baseUrl": "",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "message": "Base URL not configured. Save provider config first.",
            "safeError": "not_configured",
        }

    # 5. Run health check
    try:
        result = await run_health_check(
            api_shape=api_shape,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
            api_key=api_key,
            auth_type=auth_type,
        )
    except Exception as exc:
        logger.error(f"Health check failed for {provider_id}: {exc}")
        result = {
            "status": "unknown_error",
            "ok": False,
            "latencyMs": 0,
            "message": str(exc),
            "safeError": "unknown_error",
        }

    # 6. Persist result to DB
    from db.repository import update_llm_provider_health
    await update_llm_provider_health(
        provider_id,
        status=result["status"],
        latency_ms=result.get("latencyMs"),
        error_code=result.get("safeError"),
        error_message=result.get("message") if not result.get("ok") else None,
    )

    # 7. Return safe response
    return {
        "provider": provider_id,
        "status": result["status"],
        "ok": result["ok"],
        "latencyMs": result.get("latencyMs", 0),
        "model": model,
        "baseUrl": base_url,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "message": result.get("message", ""),
        "safeError": result.get("safeError"),
    }


# ---------------------------------------------------------------------------
# POST /api/v1/llm/providers/{provider_id}/select
# ---------------------------------------------------------------------------

@router.post("/providers/{provider_id}/select")
async def select_provider(
    provider_id: str,
    current_user: dict = Depends(require_admin),
):
    """Set the given provider as the active/default provider."""
    provider_def = registry.get_provider_def(provider_id)
    if not provider_def:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    # Update registry defaults to mark this as the active provider
    registry.update_defaults({"providerId": provider_id})

    # Return the selected provider with its current config
    provider = await registry.get_provider_from_db(provider_id)
    return _safe_provider_response(provider) or {
        "providerId": provider_id,
        "name": provider_def.name,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/llm/active
# ---------------------------------------------------------------------------

@router.get("/active")
async def get_active_provider():
    """Return the currently active/default provider."""
    defaults = registry.get_defaults()
    active_id = defaults.get("providerId")

    if not active_id:
        raise HTTPException(status_code=404, detail="No active provider configured")

    provider = await registry.get_provider_from_db(active_id)
    if not provider:
        # Fallback to safe-runner or first available
        return {
            "providerId": active_id,
            "active": True,
            "defaults": defaults,
        }

    result = _safe_provider_response(provider)
    result["active"] = True
    result["defaults"] = defaults
    return result


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
async def update_defaults(
    body: DefaultsUpdate,
    current_user: dict = Depends(require_admin),
):
    """Update execution defaults."""
    data = body.model_dump(exclude_none=True)
    return registry.update_defaults(data)


# ---------------------------------------------------------------------------
# GET /api/v1/llm/usage?range=7d|30d
# ---------------------------------------------------------------------------

@router.get("/usage")
async def get_usage(
    range_label: str = Query(
        "7d",
        alias="range",
        description="Lookback window: '7d' or '30d'",
    ),
):
    """Return daily LLM invocation counts and token usage.

    Reads from ``audit_logs`` where ``action='llm.invoke'`` and groups by
    the date portion of the timestamp. Each row's ``details`` may carry
    ``tokensIn`` and ``tokensOut`` ints; missing values default to 0.

    The endpoint is observational only — it does not introduce a new
    table. Until LLM call sites are wired to log ``llm.invoke`` events,
    the ``daily`` array will be empty and ``totals`` will be zero; the
    ``note`` field explains the wiring state to the UI.
    """
    # Parse and validate the lookback range. ``range`` is exposed in
    # the query string for clarity, but the Python builtin would be
    # shadowed if we named the parameter that — so we use ``range_label``
    # internally and let FastAPI's alias map it back to ``?range=...``.
    if range_label not in ("7d", "30d"):
        raise HTTPException(status_code=422, detail="range must be '7d' or '30d'")
    days = 7 if range_label == "7d" else 30

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    # Seed every day in the window so the chart shows zeros for idle days.
    # Build keys in the local-ish ``YYYY-MM-DD`` form (UTC for consistency
    # with timestamps stored in audit_logs).
    daily_index: list[str] = []
    for offset in range(days - 1, -1, -1):
        d = (now_utc - timedelta(days=offset)).date()
        daily_index.append(d.isoformat())

    bucket_calls: dict[str, int] = defaultdict(int)
    bucket_in: dict[str, int] = defaultdict(int)
    bucket_out: dict[str, int] = defaultdict(int)
    total_calls = 0
    total_in = 0
    total_out = 0
    last_invocation: Optional[str] = None

    try:
        await _db.ensure_db_init()
        async with _db.AsyncSessionLocal() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.action == "llm.invoke")
                .where(AuditLog.timestamp >= cutoff)
                .order_by(AuditLog.timestamp.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            for row in rows:
                if row.timestamp is None:
                    continue
                ts = row.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                day_key = ts.date().isoformat()
                bucket_calls[day_key] += 1
                total_calls += 1

                # Token counts live in ``details``; tolerate any shape.
                details = row.details or {}
                try:
                    in_tokens = int(details.get("tokensIn") or 0)
                except (TypeError, ValueError):
                    in_tokens = 0
                try:
                    out_tokens = int(details.get("tokensOut") or 0)
                except (TypeError, ValueError):
                    out_tokens = 0
                bucket_in[day_key] += in_tokens
                bucket_out[day_key] += out_tokens
                total_in += in_tokens
                total_out += out_tokens

                last_invocation = ts.isoformat()

        daily = [
            {
                "date": day,
                "calls": bucket_calls.get(day, 0),
                "tokensIn": bucket_in.get(day, 0),
                "tokensOut": bucket_out.get(day, 0),
            }
            for day in daily_index
        ]
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Failed to compute LLM usage: {exc}")
        # Surface a clear empty state so the UI can render the "no data"
        # card instead of failing the whole page.
        daily = [
            {"date": day, "calls": 0, "tokensIn": 0, "tokensOut": 0}
            for day in daily_index
        ]
        total_calls = 0
        total_in = 0
        total_out = 0
        last_invocation = None

    if total_calls == 0:
        note = (
            "No LLM invocations recorded yet. Once call sites log "
            "audit_logs entries with action='llm.invoke' and tokens in "
            "details.tokensIn / details.tokensOut, the chart will populate."
        )
    else:
        note = None

    return {
        "range": range_label,
        "days": days,
        "daily": daily,
        "totals": {
            "calls": total_calls,
            "tokensIn": total_in,
            "tokensOut": total_out,
            "tokens": total_in + total_out,
        },
        "lastInvocation": last_invocation,
        "note": note,
    }
