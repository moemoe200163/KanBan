"""
Issue suggestions — LLM-assisted AC generation.

Endpoints:

- ``POST /api/v1/issues/{issue_id}/suggest-ac`` — generate 3-5
  acceptance criteria for an issue using the active LLM provider.
  Falls back to a deterministic heuristic if no provider is
  configured (so the "Suggest AC" button still does something
  useful on a fresh install).

Design notes
------------
We deliberately keep the prompt tiny and ask for JSON output
because the rest of the Mavis flow is JSON-native. The
heuristic fallback generates the same shape (3 templated AC)
so the front-end never has to special-case the "no LLM"
path. We cache by ``(title|description) hash`` so hitting
"Re-suggest" repeatedly on the same issue doesn't re-burn
provider tokens.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth
from core.llm.health_check import chat_complete, ChatError
from db import repository as repo
from db.models import LLMProviderConfig as LLMProviderConfigModel
from db.database import AsyncSessionLocal, ensure_db_init
from sqlalchemy import select


router = APIRouter()


# ---------------------------------------------------------------------------
# In-process cache. The cache is bounded by the number of unique
# (title|description) tuples the leader has ever asked about in
# this process, which in practice is small. A miss is cheap (one
# LLM call); a hit is free.
# ---------------------------------------------------------------------------
_SUGGESTION_CACHE: dict[str, List[Dict[str, Any]]] = {}
_CACHE_MAX = 256

_PROMPT_VERSION = 1


def _cache_key(title: str, description: str) -> str:
    h = hashlib.sha256()
    h.update(f"{_PROMPT_VERSION}|".encode())
    h.update(title.encode())
    h.update("|".encode())
    h.update((description or "").encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SuggestAcRequest(BaseModel):
    # Optional override: if the caller wants to bypass the cache
    # (e.g. the operator hit "Re-suggest" deliberately).
    refresh: bool = Field(default=False)


class SuggestAcResponse(BaseModel):
    source: str  # "llm" | "heuristic" | "cache"
    provider: Optional[str] = None
    model: Optional[str] = None
    criteria: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Heuristic fallback — produces the same JSON shape as the LLM path so
# the front-end doesn't have to branch on ``source``. Three criteria is
# the minimum; we add up to 5 if the title/description carry enough
# signal to seed them.
# ---------------------------------------------------------------------------

_TEST_KEYWORDS = ("test", "tests", "unit test", "integration", "spec", "tdd")
_ERROR_KEYWORDS = ("error", "exception", "fail", "failure", "crash", "bug", "fix")
_DOC_KEYWORDS = ("document", "docs", "readme", "comment", "explain")


def _heuristic_acceptance_criteria(title: str, description: str) -> List[Dict[str, Any]]:
    """Generate 3-5 AC entries without an LLM.

    We seed the criteria from the issue's title and description. The
    structure is always: (1) functional correctness, (2) error /
    failure handling, (3) tests added, (4) documentation updated.
    The fifth slot is a "boundary / edge case" check that fires when
    the title hints at scope (e.g. words like "all", "every", "support").
    """
    text = f"{title}\n{description or ''}".lower()
    criteria: List[Dict[str, Any]] = []

    # 1. Functional — always included, named after the title.
    criteria.append({
        "text": f"Implementation matches the behavior described in: {title}",
    })

    # 2. Error handling.
    if any(k in text for k in _ERROR_KEYWORDS):
        criteria.append({
            "text": "Handles the failure mode described, with a clear error message",
        })
    else:
        criteria.append({
            "text": "Rejects invalid inputs with a clear, user-visible error",
        })

    # 3. Tests.
    if any(k in text for k in _TEST_KEYWORDS):
        criteria.append({
            "text": "Unit / integration tests cover the new behavior (green CI)",
        })
    else:
        criteria.append({
            "text": "At least one new test covers the happy path",
        })

    # 4. Documentation.
    if any(k in text for k in _DOC_KEYWORDS):
        criteria.append({
            "text": "README / inline docs updated to reflect the new behavior",
        })

    # 5. Boundary / edge case.
    if any(k in text for k in ("all ", "every", "support", "across", "edge case")):
        criteria.append({
            "text": "Edge cases enumerated in the description are handled",
        })

    # Truncate to 5 if we somehow got more, and ensure ids.
    out = []
    for i, c in enumerate(criteria[:5], start=1):
        out.append({"id": f"ac_{i}", "text": c["text"], "done": False})
    return out


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a senior engineer reviewing a Kanban issue. Your job is "
    "to produce a JSON array of 3 to 5 short, testable acceptance "
    "criteria. Each criterion must be:\n"
    "  - a single sentence (≤ 100 chars),\n"
    "  - stated in the active voice,\n"
    "  - verifiable by inspection or a test,\n"
    "  - free of implementation details.\n"
    "Reply with ONLY a JSON array — no prose, no code fence, no "
    "explanation. Each element: {\"text\": \"...\"}.\n"
    "Do not include an ``id`` or ``done`` field — the caller adds those."
)


def _user_prompt(title: str, description: str) -> str:
    return (
        f"Issue title: {title}\n\n"
        f"Issue description:\n{description or '(no description provided)'}\n\n"
        "Acceptance criteria:"
    )


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

async def _resolve_active_provider() -> Optional[Dict[str, Any]]:
    """Look up the active LLM provider's runtime config.

    Returns ``None`` if no provider is selected or the selected
    provider isn't configured. The caller falls back to the
    heuristic path in that case.
    """
    from api.v1.endpoints.llm import get_active_provider
    from db.repository import get_llm_provider_config_with_key
    info = await get_active_provider()
    if not info:
        return None
    # ``get_active_provider`` returns the merged provider descriptor
    # from /api/v1/llm/active, which uses ``providerId`` (and also
    # exposes ``id`` as an alias). The earlier ``provider`` key was
    # a typo from when this file was first written; the new
    # endpoint never returned it, so the resolve silently fell
    # back to the heuristic path even when an LLM was selected.
    provider_id = info.get("providerId") or info.get("id")
    if not provider_id:
        return None
    full = await get_llm_provider_config_with_key(provider_id)
    if not full:
        return None
    base_url = full.get("baseUrl") or ""
    endpoint_path = full.get("endpointPath") or ""
    model = full.get("model") or ""
    if not (base_url and model):
        return None
    return {
        "provider": provider_id,
        "api_shape": full.get("apiShape") or "openai-chat",
        "base_url": base_url,
        "endpoint_path": endpoint_path,
        "model": model,
        # ``get_llm_provider_config_with_key`` exposes the stored
        # secret under ``api_key_encrypted`` (not ``apiKey`` —
        # that's the prefix/last4 form used by the public endpoint).
        # Pulling from the wrong key here silently sent the LLM
        # call with an empty bearer, which the provider rejected
        # as a 401 and the endpoint reported as a generic
        # ChatError → fell back to the heuristic path.
        "api_key": full.get("api_key_encrypted") or "",
    }


def _parse_criteria_json(text: str) -> Optional[List[Dict[str, Any]]]:
    """Robustly parse the LLM's JSON array response.

    The LLM sometimes wraps the JSON in a code fence or prefixes it
    with a sentence. We strip the fence and try to find the first
    array. We only accept the first one — anything after is
    treated as an explanation and discarded.
    """
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    # Try the whole string first
    for candidate in (text, _extract_first_json_array(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return _normalize_criteria(data)
    return None


def _extract_first_json_array(text: str) -> Optional[str]:
    """Find the first balanced ``[... ]`` substring in ``text``."""
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _normalize_criteria(raw: List[Any]) -> List[Dict[str, Any]]:
    """Coerce LLM output into the canonical ``{id, text, done}`` shape."""
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(raw[:5], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or len(text) > 200:
            continue
        out.append({"id": f"ac_{i}", "text": text, "done": False})
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/issues/{issue_id}/suggest-ac")
async def suggest_acceptance_criteria(
    issue_id: str = Path(...),
    body: SuggestAcRequest = Body(default_factory=SuggestAcRequest),
    current_user: dict = Depends(require_auth),
):
    """Generate acceptance criteria for ``issue_id``.

    The endpoint never mutates the issue — it returns the suggested
    list and the front-end commits them via the existing
    ``PATCH /issues/{id}/acceptance-criteria`` endpoint. That
    keeps this path read-only and idempotent: the operator can
    hit it many times before committing the result.
    """
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")

    title = issue.get("title", "")
    description = issue.get("description", "")

    # Cache check
    key = _cache_key(title, description)
    if not body.refresh and key in _SUGGESTION_CACHE:
        return SuggestAcResponse(
            source="cache",
            provider=None,
            model=None,
            criteria=_SUGGESTION_CACHE[key],
        )

    # LLM path
    provider = await _resolve_active_provider()
    if provider is not None:
        try:
            import logging
            logging.getLogger(__name__).info(
                "[suggest-ac] calling LLM (provider=%s model=%s shape=%s)",
                provider["provider"], provider["model"], provider["api_shape"],
            )
            text = await chat_complete(
                api_shape=provider["api_shape"],
                base_url=provider["base_url"],
                endpoint_path=provider["endpoint_path"],
                model=provider["model"],
                api_key=provider["api_key"],
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _user_prompt(title, description)},
                ],
            )
            parsed = _parse_criteria_json(text)
            if parsed:
                if len(_SUGGESTION_CACHE) >= _CACHE_MAX:
                    _SUGGESTION_CACHE.pop(next(iter(_SUGGESTION_CACHE)))
                _SUGGESTION_CACHE[key] = parsed
                return SuggestAcResponse(
                    source="llm",
                    provider=provider["provider"],
                    model=provider["model"],
                    criteria=parsed,
                )
            # LLM returned something we can't parse — fall through to
            # heuristic so the operator still gets a usable list.
        except ChatError as exc:
            # Provider call failed (network, auth, parse, etc.) —
            # don't block the operator on this. Fall back.
            import logging
            logging.getLogger(__name__).warning(
                "[suggest-ac] LLM call failed (provider=%s model=%s): %s",
                provider.get("provider"), provider.get("model"), exc,
            )
            pass

    # Heuristic fallback
    criteria = _heuristic_acceptance_criteria(title, description)
    if len(_SUGGESTION_CACHE) >= _CACHE_MAX:
        _SUGGESTION_CACHE.pop(next(iter(_SUGGESTION_CACHE)))
    _SUGGESTION_CACHE[key] = criteria
    return SuggestAcResponse(
        source="heuristic",
        provider=None,
        model=None,
        criteria=criteria,
    )
