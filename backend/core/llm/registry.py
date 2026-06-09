"""
LLM Provider Registry

Reads provider definitions and env-based config to build the provider
list.  Never exposes full secrets to the API layer.

Priority for provider display values:
    DB config  >  env var  >  static definition
"""

import asyncio
import os
import logging
from typing import Dict, List, Optional

from .providers import PROVIDERS, PROVIDER_MAP, LLMProviderDef

logger = logging.getLogger(__name__)

# In-memory defaults (persisted via env or future DB)
_defaults: Dict[str, str] = {
    "provider_id": "safe-runner",
    "model_id": "",
    "harness": "safe-runner",
    "max_runtime_seconds": "300",
    "token_budget": "",
    "cost_budget": "",
    "streaming_logs": "true",
}


def _mask_secret(value: str) -> str:
    """Return a masked version of a secret string."""
    if len(value) <= 4:
        return "••••"
    return f"••••{value[-4:]}"


def _check_env(env_var: Optional[str]) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if an env var is set.
    Returns (configured, masked_value, env_var_name).
    """
    if not env_var:
        return False, None, None
    val = os.environ.get(env_var, "")
    if val:
        return True, _mask_secret(val), env_var
    return False, None, env_var


# -----------------------------------------------------------------------
# Sync provider list (env-var based, no DB)
# -----------------------------------------------------------------------

def list_providers(db_configs: Optional[List[dict]] = None) -> List[dict]:
    """Return all providers with their current status.

    When *db_configs* is provided (list of dicts from
    ``list_llm_provider_configs()``), DB values override env-var values
    for fields like ``baseUrl``, ``model``, ``maskedSecret``.
    """
    # Index DB configs by provider_id for fast lookup
    db_by_id: Dict[str, dict] = {}
    if db_configs:
        for cfg in db_configs:
            pid = cfg.get("providerId") or cfg.get("provider_id")
            if pid:
                db_by_id[pid] = cfg

    results = []
    for p in PROVIDERS:
        configured, masked, env_var = _check_env(p.auth_env_var)
        health = "unknown"
        error = None

        if p.adapter == "local-safe-runner":
            configured = True
            health = "healthy"
        elif not configured:
            health = "unknown"
            error = f"Set {env_var} to configure" if env_var else None

        # --- Merge DB config on top of env-var / static defaults --------
        db_cfg = db_by_id.get(p.id)
        if db_cfg:
            # DB has a saved API key prefix/last4 -- use that for display
            db_prefix = db_cfg.get("apiKeyPrefix")
            db_last4 = db_cfg.get("apiKeyLast4")
            if db_prefix or db_last4:
                masked = f"{db_prefix or ''}...{db_last4 or ''}"
                configured = True

            # DB-provided base URL / model override static defaults
            # (These are surfaced in the result dict below.)

        # Determine credential source
        credential_source = "none"
        if db_cfg and (db_cfg.get("apiKeyPrefix") or db_cfg.get("apiKeyLast4")):
            credential_source = "db"
        elif configured and p.auth_env_var:
            credential_source = "env"

        status = "configured" if configured else ("disabled" if not p.enabled else "missing_key")

        result: dict = {
            "id": p.id,
            "name": p.name,
            "adapter": p.adapter,
            "enabled": p.enabled if not db_cfg else db_cfg.get("enabled", p.enabled),
            "configured": configured,
            "status": status,
            "defaultModel": (db_cfg.get("model") if db_cfg else None) or p.default_model,
            "capabilities": p.capabilities,
            "authType": (db_cfg.get("authType") if db_cfg else None) or p.auth_type,
            "authEnvVar": env_var,
            "maskedSecret": masked,
            "healthStatus": health,
            "lastChecked": None,
            "errorSummary": error,
            "credentialSource": credential_source,
        }

        # Surface DB-specific fields when present
        if db_cfg:
            if db_cfg.get("baseUrl"):
                result["baseUrl"] = db_cfg["baseUrl"]
            if db_cfg.get("apiShape"):
                result["apiShape"] = db_cfg["apiShape"]
            if db_cfg.get("endpointPath"):
                result["endpointPath"] = db_cfg["endpointPath"]
            if db_cfg.get("lastTestStatus"):
                result["healthStatus"] = db_cfg["lastTestStatus"]
            if db_cfg.get("lastTestAt"):
                result["lastChecked"] = db_cfg["lastTestAt"]
            if db_cfg.get("lastErrorMessage"):
                result["errorSummary"] = db_cfg["lastErrorMessage"]

        results.append(result)
    return results


def get_provider(provider_id: str, db_configs: Optional[List[dict]] = None) -> Optional[dict]:
    """Return a single provider by ID."""
    p = PROVIDER_MAP.get(provider_id)
    if not p:
        return None
    providers = list_providers(db_configs=db_configs)
    for prov in providers:
        if prov["id"] == provider_id:
            return prov
    return None


# -----------------------------------------------------------------------
# Async DB-aware helpers (used by API layer)
# -----------------------------------------------------------------------

async def list_providers_from_db() -> List[dict]:
    """Read provider configs from DB and return merged provider list.

    Falls back to env-var-only mode when the DB is unavailable.
    """
    try:
        from db.repository import list_llm_provider_configs
        db_configs = await list_llm_provider_configs()
        return list_providers(db_configs=db_configs)
    except Exception as e:
        logger.warning(f"Failed to read DB configs for provider list: {e}")
        return list_providers()


async def get_provider_from_db(provider_id: str) -> Optional[dict]:
    """Read a single provider config from DB and return merged result.

    Falls back to env-var-only mode when the DB is unavailable.
    """
    try:
        from db.repository import list_llm_provider_configs
        db_configs = await list_llm_provider_configs()
        return get_provider(provider_id, db_configs=db_configs)
    except Exception as e:
        logger.warning(f"Failed to read DB config for provider {provider_id}: {e}")
        return get_provider(provider_id)


def get_provider_def(provider_id: str) -> Optional[LLMProviderDef]:
    """Return the raw provider definition."""
    return PROVIDER_MAP.get(provider_id)


def get_defaults() -> dict:
    """Return current execution defaults."""
    return {
        "providerId": _defaults["provider_id"],
        "modelId": _defaults["model_id"],
        "harness": _defaults["harness"],
        "maxRuntimeSeconds": int(_defaults["max_runtime_seconds"]),
        "tokenBudget": int(_defaults["token_budget"]) if _defaults["token_budget"] else None,
        "costBudget": float(_defaults["cost_budget"]) if _defaults["cost_budget"] else None,
        "streamingLogs": _defaults["streaming_logs"] == "true",
    }


def update_defaults(data: dict) -> dict:
    """Update execution defaults."""
    if "providerId" in data:
        _defaults["provider_id"] = str(data["providerId"])
    if "modelId" in data:
        _defaults["model_id"] = str(data["modelId"])
    if "harness" in data:
        _defaults["harness"] = str(data["harness"])
    if "maxRuntimeSeconds" in data:
        _defaults["max_runtime_seconds"] = str(int(data["maxRuntimeSeconds"]))
    if "tokenBudget" in data:
        _defaults["token_budget"] = str(data["tokenBudget"]) if data["tokenBudget"] is not None else ""
    if "costBudget" in data:
        _defaults["cost_budget"] = str(data["costBudget"]) if data["costBudget"] is not None else ""
    if "streamingLogs" in data:
        _defaults["streaming_logs"] = "true" if data["streamingLogs"] else "false"
    logger.info(f"LLM defaults updated: {_defaults}")
    return get_defaults()


def list_models(provider_id: str) -> Optional[List[str]]:
    """Return available models for a provider."""
    p = PROVIDER_MAP.get(provider_id)
    if not p:
        return None
    return p.models


def check_health(provider_id: str) -> dict:
    """
    Check provider health by verifying env var is set.
    Returns health status without making real API calls (P0/P1 stub).
    """
    p = PROVIDER_MAP.get(provider_id)
    if not p:
        return {"status": "unknown", "error": f"Provider '{provider_id}' not found"}

    if p.adapter == "local-safe-runner":
        return {"status": "healthy", "error": None, "lastChecked": None}

    configured, _, env_var = _check_env(p.auth_env_var)

    if not configured:
        return {
            "status": "unhealthy",
            "error": f"Missing {env_var}" if env_var else "Not configured",
            "lastChecked": None,
        }

    # P1 stub: key is present but we don't make real API calls yet
    return {
        "status": "healthy",
        "error": None,
        "lastChecked": None,
    }
