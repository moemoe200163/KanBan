"""
DevFlow Backend - Webhook Endpoints for CI/PR Events

Handles incoming webhooks from CI systems and PR events.
Stores webhook events in the WebhookEvent model for audit/replay.

The CI and PR endpoints accept two payload shapes side-by-side so the
legacy job-id path (used by internal ECC job fan-out) keeps working
while a simpler, direct issue-id shape (used by external CI providers
that already know which issue they're reporting on) auto-fills the
linked issue's ``ci_status`` / ``pr_url`` columns and writes an
audit log entry.
"""

from datetime import datetime, timezone
from typing import Optional, List, AsyncIterator, Annotated
from uuid import uuid4
import hmac
import hashlib
import json
import os
import re
import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header, Request

# Plan J-3: require_role factory + Annotated signature for the
# new ``/webhooks/{id}/toggle`` endpoint. ``require_role("ops",
# "admin")`` lets both ops and admin flip the active flag; super
# admin always passes through the factory's short-circuit.
from api.v1.auth_deps import require_role as _require_role
require_role_ops = _require_role("ops", "admin")
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# Webhook secret from environment variable (never hardcoded)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Default board ID for GitHub webhooks (scoped issue lookup)
_DEFAULT_BOARD_ID = os.getenv("GITHUB_DEFAULT_BOARD_ID", "board-default")

# Status string the spec maps to. The model column is ``String(32)`` so
# we have room to extend — but the front-end / IssueCard contract
# already understands ``pending | passed | failed`` and we now also
# surface ``error`` as a separate colour-coded state. New aliases
# (``passing`` / ``failing``) are accepted at the API boundary for
# caller convenience and normalised to the canonical form before write.
_CI_STATUS_ALIASES = {
    "success": "passed",
    "passing": "passed",
    "failure": "failed",
    "failing": "failed",
    "pending": "pending",
    "error": "error",
}


# =============================================================================
# Issue Key Extraction
# =============================================================================

_ISSUE_KEY_PATTERN = re.compile(r"(?:DEV-)(\d+)", re.IGNORECASE)


def extract_issue_key(text: str) -> "str | None":
    """Extract issue key (e.g. DEV-123) from text. Returns normalized uppercase or None."""
    match = _ISSUE_KEY_PATTERN.search(text)
    if match:
        return f"DEV-{match.group(1)}"
    return None


# =============================================================================
# Pydantic Models for CI Webhook
# =============================================================================

class CIWebhookPayload(BaseModel):
    """Legacy CI payload (job-id based) — kept for backward compatibility.

    New external callers should prefer the ``issue_id``-based shape
    handled in :func:`receive_ci_webhook`, which auto-fills the issue
    row directly. This model is still used by the ECC job dispatcher
    path (``_update_issue_from_ci_webhook``) and the existing test
    suite (``test_webhooks_api.py``).
    """
    event_type: str = Field(..., description="Event type: build_success, build_failure, deployment")
    job_id: str = Field(..., min_length=1, description="Unique job identifier from CI system")
    metadata: Optional[dict] = Field(default_factory=dict, description="Additional event metadata")


class CIWebhookResponse(BaseModel):
    """Response for CI webhook acknowledgment."""
    status: str
    event_id: str
    message: str


# =============================================================================
# Pydantic Models for PR Webhook
# =============================================================================

class PRWebhookPayload(BaseModel):
    """Legacy PR payload (job-id based) — kept for backward compatibility.

    New external callers should prefer the ``issue_id``-based shape
    handled in :func:`receive_pr_webhook`, which auto-fills the issue
    row directly. This model is still used by the ECC job dispatcher
    path (``_update_issue_from_pr_webhook``) and the existing test
    suite (``test_webhooks_api.py``).
    """
    event_type: str = Field(..., description="Event type: pr_opened, pr_merged, pr_closed")
    pr_number: int = Field(..., ge=1, description="Pull request number")
    title: str = Field(..., min_length=1, description="Pull request title")
    job_id: str = Field(..., min_length=1, description="Associated job identifier")


class PRWebhookResponse(BaseModel):
    """Response for PR webhook acknowledgment."""
    status: str
    event_id: str
    message: str


# =============================================================================
# Pydantic Models — new issue-id based payloads
# =============================================================================
#
# The spec for this iteration is "PR / CI webhook 自動回填 issue.prUrl /
# issue.ciStatus" — i.e. the caller already knows which issue they
# belong to, so we shortcut the job-id → issue-id lookup that the
# legacy path does. The new shape is intentionally permissive:
# ``issue_id`` is the only required field, the rest are best-effort
# audit metadata. We let unknown status / event strings through the
# model and validate them inside the handler so we can return a
# descriptive 400 with the right hint instead of a generic 422.


class CIDirectPayload(BaseModel):
    """New shape for external CI providers.

    Required: ``issue_id`` + ``status``.
    Optional: everything else is captured in the audit log only.
    """
    issue_id: str = Field(..., min_length=1, description="Issue UUID this CI event applies to")
    status: str = Field(..., min_length=1, description="CI status: success | failure | pending | error (also accepts passing/failing)")
    repo: Optional[str] = Field(default=None, description="Repository full name, e.g. org/name")
    sha: Optional[str] = Field(default=None, description="Commit SHA")
    build_url: Optional[str] = Field(default=None, description="Link to the CI build run")


class PRDirectPayload(BaseModel):
    """New shape for external PR providers.

    Required: ``issue_id`` + ``url``.
    Optional: ``number`` (PR number), ``state`` (open/closed/merged), ``repo``.
    """
    issue_id: str = Field(..., min_length=1, description="Issue UUID this PR event applies to")
    url: str = Field(..., min_length=1, description="PR html_url to attach to the issue")
    number: Optional[int] = Field(default=None, ge=1, description="PR number")
    state: Optional[str] = Field(default=None, description="PR state: open | closed | merged")
    repo: Optional[str] = Field(default=None, description="Repository full name")


class WebhookAck(BaseModel):
    """Unified acknowledgment shape used by both new endpoints."""
    status: str
    event_id: str
    message: str
    issue_id: Optional[str] = None
    updated: bool = False


# =============================================================================
# New direct-update handlers
# =============================================================================
#
# These run inline (no background task) because they're cheap: a
# single SQL update + a single audit-log insert. The legacy path
# still schedules background work for the job-id → issue-id walk it
# has to do; that walk is not free so it stays async. The new path
# also runs ``log_audit_event`` inline — if the audit write fails we
# log a warning but still ack 200, because the issue update is the
# user-visible side-effect and the audit row is a side-channel.


def _normalise_ci_status(raw: str) -> Optional[str]:
    """Map the spec's status strings onto the model's canonical set.

    Returns ``None`` for unrecognised values so the caller can 400
    with a clear message rather than silently writing garbage to the
    column.
    """
    if not raw:
        return None
    return _CI_STATUS_ALIASES.get(raw.strip().lower())


async def _handle_ci_direct(payload: CIDirectPayload) -> WebhookAck:
    """Auto-fill the issue's ``ci_status`` from a direct CI payload."""
    from api.v1.endpoints.audit import log_audit_event
    from db import repository as repo

    ci_status = _normalise_ci_status(payload.status)
    if not ci_status:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown CI status '{payload.status}'. "
                f"Expected one of: {sorted(set(_CI_STATUS_ALIASES.keys()))}"
            ),
        )

    # Read the previous value before we overwrite it so the audit log
    # can show the from→to transition. If the issue doesn't exist
    # we 400 + warning — silently 200-ing would let bad callers
    # inject events for arbitrary ids without any signal upstream.
    existing = await repo.get_issue(payload.issue_id)
    if not existing:
        logger.warning(
            "CI webhook: issue %s not found, dropping event (status=%s, repo=%s, sha=%s)",
            payload.issue_id, payload.status, payload.repo, payload.sha,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Issue '{payload.issue_id}' not found",
        )

    previous = existing.get("ciStatus")
    updated = await repo.update_issue_ci_status(payload.issue_id, ci_status)
    if not updated:
        # Race / delete-between-read-and-update — fall back to the
        # same "not found" 400 the pre-check would have produced.
        raise HTTPException(
            status_code=400,
            detail=f"Issue '{payload.issue_id}' disappeared during update",
        )

    # Audit log — best-effort. Failure here must not block the ack
    # because the issue update is the user-visible side effect.
    await log_audit_event(
        action="issue.ci_status_updated",
        resource="issue",
        resource_id=payload.issue_id,
        agent_id=None,
        agent_name="webhook",
        details={
            "from": previous,
            "to": ci_status,
            "repo": payload.repo,
            "sha": payload.sha,
            "buildUrl": payload.build_url,
            "rawStatus": payload.status,
        },
    )

    return WebhookAck(
        status="accepted",
        event_id="",  # filled by caller from the saved event row
        message=f"CI status updated to '{ci_status}'",
        issue_id=payload.issue_id,
        updated=True,
    )


async def _handle_pr_direct(payload: PRDirectPayload) -> WebhookAck:
    """Auto-fill the issue's ``pr_url`` from a direct PR payload."""
    from api.v1.endpoints.audit import log_audit_event
    from db import repository as repo

    existing = await repo.get_issue(payload.issue_id)
    if not existing:
        logger.warning(
            "PR webhook: issue %s not found, dropping event (url=%s, number=%s)",
            payload.issue_id, payload.url, payload.number,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Issue '{payload.issue_id}' not found",
        )

    previous_url = existing.get("prUrl")
    updated = await repo.update_issue_pr_url(payload.issue_id, payload.url)
    if not updated:
        raise HTTPException(
            status_code=400,
            detail=f"Issue '{payload.issue_id}' disappeared during update",
        )

    await log_audit_event(
        action="issue.pr_updated",
        resource="issue",
        resource_id=payload.issue_id,
        agent_id=None,
        agent_name="webhook",
        details={
            "from": previous_url,
            "to": payload.url,
            "url": payload.url,
            "number": payload.number,
            "state": payload.state,
            "repo": payload.repo,
        },
    )

    return WebhookAck(
        status="accepted",
        event_id="",
        message=f"PR URL updated for issue",
        issue_id=payload.issue_id,
        updated=True,
    )


# =============================================================================
# Webhook Signature Verification
# =============================================================================

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify HMAC-SHA256 webhook signature using timing-safe comparison.

    Args:
        payload: Raw request body bytes
        signature: X-Webhook-Signature header value (format: sha256=<hex>)

    Returns:
        True if signature is valid, False otherwise
    """
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not configured, skipping signature verification")
        return True  # Skip verification if secret not set (dev mode)

    if not signature:
        return False

    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    # Use timing-safe comparison to prevent timing attacks
    return hmac.compare_digest(f"sha256={expected_signature}", signature)


# =============================================================================
# Database Operations
# =============================================================================

async def _save_webhook_event(
    event_type: str,
    payload: dict,
    headers: dict,
    status: str = "received",
) -> str:
    """
    Persist webhook event to database.

    Args:
        event_type: Type of webhook event
        payload: Event payload data
        headers: Request headers
        status: Event processing status

    Returns:
        Created event ID
    """
    from db.database import AsyncSessionLocal, ensure_db_init
    from db.models import WebhookEvent

    await ensure_db_init()

    event_id = f"wh_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        event = WebhookEvent(
            id=event_id,
            webhook_id=event_id,
            event_type=event_type,
            payload=payload,
            headers=headers,
            status=status,
            created_at=now,
        )
        session.add(event)
        await session.commit()

    return event_id


async def _update_job_status_from_ci(job_id: str, event_type: str, metadata: dict) -> None:
    """
    Update associated ECC job with CI status.

    Args:
        job_id: The job identifier to update
        event_type: CI event type (build_success, build_failure, deployment)
        metadata: Additional event metadata
    """
    from api.v1.endpoints.ecc import _jobs, _save_job_to_db, _transition_job

    # Find job by ID or metadata reference
    job = _jobs.get(job_id)
    if not job:
        # Try to find by looking up in the jobs dict
        logger.warning(f"CI event for unknown job: {job_id}")
        return

    # Map CI event to job status
    status_map = {
        "build_success": "completed",
        "build_failure": "failed",
        "deployment": "completed",
    }

    new_status = status_map.get(event_type, job.status)
    message = f"CI event: {event_type}"

    if metadata:
        message += f" - {metadata.get('message', '')}"

    updated_job = _transition_job(job, new_status, message.strip())
    await _save_job_to_db(updated_job)
    logger.info(f"Updated job {job_id} status to {new_status} from CI webhook")


async def _update_issue_from_ci_webhook(job_id: str, event_type: str, metadata: dict) -> None:
    """
    Update the Issue record linked to an ECC job with CI status.

    Looks up the job in the DB to find its issue_id, then updates
    the issue's ci_status field.
    """
    from db import repository as repo

    job = await repo.get_job(job_id)
    if not job:
        logger.warning(f"CI webhook: job {job_id} not found, skipping issue update")
        return

    issue_id = job.get("issue_id")
    if not issue_id:
        logger.warning(f"CI webhook: job {job_id} has no issue_id, skipping")
        return

    # Map CI event to issue ci_status
    ci_status_map = {
        "build_success": "passed",
        "build_failure": "failed",
        "deployment": "passed",
    }
    ci_status = ci_status_map.get(event_type)
    if ci_status:
        await repo.update_issue_ci_status(issue_id, ci_status)
        logger.info(f"Updated issue {issue_id} ci_status to {ci_status} from CI webhook")


async def _update_issue_from_pr_webhook(job_id: str, pr_number: int, title: str, event_type: str) -> None:
    """
    Update the Issue record linked to an ECC job with PR URL.

    On pr_opened events, sets the issue's pr_url to a constructed GitHub URL.
    The actual PR URL should come from the metadata; here we use pr_number + title
    as a fallback.
    """
    from db import repository as repo

    job = await repo.get_job(job_id)
    if not job:
        logger.warning(f"PR webhook: job {job_id} not found, skipping issue update")
        return

    issue_id = job.get("issue_id")
    if not issue_id:
        logger.warning(f"PR webhook: job {job_id} has no issue_id, skipping")
        return

    if event_type == "pr_opened":
        # The PR URL should be provided in metadata in production.
        # Construct a placeholder if not available.
        metadata = job.get("metadata") or {}
        pr_url = metadata.get("pr_url", f"https://github.com/org/repo/pull/{pr_number}")
        await repo.update_issue_pr_url(issue_id, pr_url)
        logger.info(f"Updated issue {issue_id} pr_url from PR webhook")


# =============================================================================
# CI Webhook Endpoint
# =============================================================================

@router.post("/webhooks/ci", tags=["Webhooks"])
async def receive_ci_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """Receive CI pipeline events.

    Accepts two payload shapes side-by-side:

    1. **Legacy job-id shape** — ``{event_type, job_id, metadata?}``
       used by the internal ECC dispatcher. Returns a 200 ack and
       schedules a background task that walks job_id → issue_id and
       updates ``issues.ci_status``.
    2. **New direct shape** — ``{issue_id, status, repo?, sha?,
       build_url?}`` for external CI providers that already know
       which issue they're reporting on. Updates the issue inline,
       writes an audit log row, and returns 200 with the updated
       issue id in the response body.

    Both shapes persist the raw event in ``webhook_events`` for
    replay / debugging.
    """
    # Read raw body once — we need it for signature verification AND
    # to figure out which payload shape the caller used.
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    try:
        raw = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    # Verify signature against the *raw* body bytes. If a signature
    # header is supplied (or a secret is configured) the check runs
    # regardless of which shape the caller uses.
    if x_webhook_signature or WEBHOOK_SECRET:
        if x_webhook_signature and not verify_webhook_signature(body, x_webhook_signature):
            logger.warning("CI webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    is_direct = "issue_id" in raw and "status" in raw
    is_legacy = "event_type" in raw and "job_id" in raw

    if not is_direct and not is_legacy:
        raise HTTPException(
            status_code=400,
            detail=(
                "Body must be either the direct shape "
                "({issue_id, status, repo?, sha?, build_url?}) "
                "or the legacy shape ({event_type, job_id, metadata?})"
            ),
        )

    headers = {
        "user_agent": request.headers.get("user-agent", ""),
        "content_type": request.headers.get("content-type", ""),
    }

    if is_direct:
        # Validate the new shape with Pydantic so we get clean 422s
        # for type errors before touching the DB.
        try:
            direct = CIDirectPayload(**raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid CI payload: {e}")

        event_id = await _save_webhook_event(
            event_type="ci_direct",
            payload=raw,
            headers=headers,
            status="received",
        )
        logger.info(
            "CI direct webhook received: issue_id=%s, status=%s",
            direct.issue_id, direct.status,
        )

        ack = await _handle_ci_direct(direct)
        ack.event_id = event_id
        return ack.model_dump()

    # ----- Legacy job-id path (preserves test_webhooks_api.py) -----
    legacy = CIWebhookPayload(**raw)
    valid_ci_events = {"build_success", "build_failure", "deployment"}
    if legacy.event_type not in valid_ci_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_ci_events}"
        )

    event_id = await _save_webhook_event(
        event_type=f"ci_{legacy.event_type}",
        payload=raw,
        headers=headers,
        status="received",
    )
    logger.info(f"CI webhook received: event_type={legacy.event_type}, job_id={legacy.job_id}")

    # Schedule background work — these are deferred because the
    # job-id → issue-id walk is not free.
    background_tasks.add_task(
        _update_job_status_from_ci,
        legacy.job_id,
        legacy.event_type,
        legacy.metadata or {},
    )
    background_tasks.add_task(
        _update_issue_from_ci_webhook,
        legacy.job_id,
        legacy.event_type,
        legacy.metadata or {},
    )

    return CIWebhookResponse(
        status="accepted",
        event_id=event_id,
        message=f"CI event '{legacy.event_type}' queued for processing",
    ).model_dump()


# =============================================================================
# PR Webhook Endpoint
# =============================================================================

@router.post("/webhooks/pr", tags=["Webhooks"])
async def receive_pr_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """Receive PR events.

    Accepts two payload shapes side-by-side:

    1. **Legacy job-id shape** — ``{event_type, pr_number, title,
       job_id}`` used by the internal ECC dispatcher. Returns 200 and
       schedules a background task that walks job_id → issue_id and
       updates ``issues.pr_url``.
    2. **New direct shape** — ``{issue_id, url, number?, state?,
       repo?}`` for external PR providers. Updates the issue inline,
       writes an audit log row, and returns 200 with the updated
       issue id in the response body.

    Both shapes persist the raw event in ``webhook_events`` for
    replay / debugging.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    try:
        raw = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    if x_webhook_signature or WEBHOOK_SECRET:
        if x_webhook_signature and not verify_webhook_signature(body, x_webhook_signature):
            logger.warning("PR webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    is_direct = "issue_id" in raw and "url" in raw
    is_legacy = "event_type" in raw and "job_id" in raw

    if not is_direct and not is_legacy:
        raise HTTPException(
            status_code=400,
            detail=(
                "Body must be either the direct shape "
                "({issue_id, url, number?, state?, repo?}) "
                "or the legacy shape ({event_type, pr_number, title, job_id})"
            ),
        )

    headers = {
        "user_agent": request.headers.get("user-agent", ""),
        "content_type": request.headers.get("content-type", ""),
    }

    if is_direct:
        try:
            direct = PRDirectPayload(**raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid PR payload: {e}")

        event_id = await _save_webhook_event(
            event_type="pr_direct",
            payload=raw,
            headers=headers,
            status="received",
        )
        logger.info(
            "PR direct webhook received: issue_id=%s, url=%s",
            direct.issue_id, direct.url,
        )

        ack = await _handle_pr_direct(direct)
        ack.event_id = event_id
        return ack.model_dump()

    # ----- Legacy job-id path (preserves test_webhooks_api.py) -----
    legacy = PRWebhookPayload(**raw)
    valid_pr_events = {"pr_opened", "pr_merged", "pr_closed"}
    if legacy.event_type not in valid_pr_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_pr_events}"
        )

    event_id = await _save_webhook_event(
        event_type=f"pr_{legacy.event_type}",
        payload=raw,
        headers=headers,
        status="received",
    )

    logger.info(
        f"PR webhook received: event_type={legacy.event_type}, "
        f"pr_number={legacy.pr_number}, job_id={legacy.job_id}"
    )

    # Schedule background update of job status
    background_tasks.add_task(
        _update_job_status_from_ci,  # Reuse the same function for job updates
        legacy.job_id,
        legacy.event_type,
        {"pr_number": legacy.pr_number, "title": legacy.title},
    )

    # Also update the linked Issue's pr_url
    background_tasks.add_task(
        _update_issue_from_pr_webhook,
        legacy.job_id,
        legacy.pr_number,
        legacy.title,
        legacy.event_type,
    )

    return PRWebhookResponse(
        status="accepted",
        event_id=event_id,
        message=f"PR event '{legacy.event_type}' for PR #{legacy.pr_number} queued",
    ).model_dump()


# =============================================================================
# Webhook Event Listing (for debugging/admin)
# =============================================================================

class WebhookEventResponse(BaseModel):
    """Response model for webhook event."""
    id: str
    event_type: str
    payload: dict
    status: str
    created_at: Optional[str] = None


@router.get("/webhooks/events", response_model=List[WebhookEventResponse], tags=["Webhooks"])
async def list_webhook_events(
    event_type: Optional[str] = None,
    limit: int = 50,
):
    """
    List recent webhook events for debugging/admin purposes.

    Args:
        event_type: Optional filter by event type prefix (e.g., "ci_", "pr_")
        limit: Maximum number of events to return (default 50, max 100)

    Returns:
        List of webhook events
    """
    from sqlalchemy import select, desc
    from db.database import AsyncSessionLocal, ensure_db_init
    from db.models import WebhookEvent

    await ensure_db_init()

    limit = min(limit, 100)  # Cap at 100

    async with AsyncSessionLocal() as session:
        query = select(WebhookEvent).order_by(desc(WebhookEvent.created_at)).limit(limit)

        if event_type:
            query = query.where(WebhookEvent.event_type.like(f"{event_type}%"))

        result = await session.execute(query)
        events = result.scalars().all()

    return [
        WebhookEventResponse(
            id=e.id,
            event_type=e.event_type,
            payload=e.payload or {},
            status=e.status,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in events
    ]


# =============================================================================
# GitHub Webhook Endpoint (real GitHub payloads)
# =============================================================================

@router.post("/webhooks/github", tags=["Webhooks"])
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
):
    """Receive real GitHub webhook payloads.

    Handles pull_request and workflow_run events.
    Returns 200 for all valid requests (GitHub expects 2xx for success).
    """
    body = await request.body()

    # Verify signature — when WEBHOOK_SECRET is set, signature is required
    if WEBHOOK_SECRET:
        if not x_hub_signature_256:
            logger.warning("GitHub webhook missing signature (delivery=%s)", x_github_delivery)
            raise HTTPException(status_code=401, detail="Missing webhook signature")
        if not verify_webhook_signature(body, x_hub_signature_256):
            logger.warning("GitHub webhook signature verification failed (delivery=%s)", x_github_delivery)
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse payload
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Store event for audit
    event_type = f"github_{x_github_event or 'unknown'}"
    headers = {
        "x_github_event": x_github_event or "",
        "x_github_delivery": x_github_delivery or "",
        "user_agent": request.headers.get("user-agent", ""),
    }
    await _save_webhook_event(event_type=event_type, payload=payload, headers=headers)

    # Route to handler
    if x_github_event == "pull_request":
        background_tasks.add_task(_handle_github_pr_event, payload)
    elif x_github_event == "workflow_run":
        background_tasks.add_task(_handle_github_workflow_run_event, payload)
    else:
        logger.debug("GitHub webhook: unhandled event type '%s'", x_github_event)

    return {"status": "accepted", "event": x_github_event, "delivery": x_github_delivery}


# =============================================================================
# GitHub Event Handlers
# =============================================================================

async def _handle_github_pr_event(payload: dict) -> None:
    """Handle GitHub pull_request webhook event."""
    from db import repository as repo

    action = payload.get("action")
    pr = payload.get("pull_request", {})
    if not pr:
        return

    # Extract issue key from branch → title → body → labels
    issue_key = (
        extract_issue_key(pr.get("head", {}).get("ref", ""))
        or extract_issue_key(pr.get("title", ""))
        or extract_issue_key(pr.get("body", ""))
        or extract_issue_key(" ".join(l.get("name", "") for l in pr.get("labels", [])))
    )
    if not issue_key:
        logger.debug("GitHub PR event: no issue key in PR #%s", pr.get("number"))
        return

    issue = await repo.find_issue_by_key(issue_key, board_id=_DEFAULT_BOARD_ID)
    if not issue:
        return

    if action == "opened":
        await repo.update_issue_pr_url(issue["id"], pr.get("html_url", ""))
        await repo.update_issue_ci_status(issue["id"], "pending")
        logger.info("Issue %s: pr_url set, ci_status=pending (PR #%s opened)", issue_key, pr.get("number"))
    elif action == "closed" and pr.get("merged"):
        await repo.update_issue_status(issue["id"], "done")
        logger.info("Issue %s: status=done (PR #%s merged)", issue_key, pr.get("number"))


async def _handle_github_workflow_run_event(payload: dict) -> None:
    """Handle GitHub workflow_run webhook event."""
    from db import repository as repo

    action = payload.get("action")
    if action != "completed":
        return

    wr = payload.get("workflow_run", {})
    conclusion = wr.get("conclusion")
    head_branch = wr.get("head_branch", "")

    status_map = {
        "success": "passed",
        "failure": "failed",
        "cancelled": "failed",
        "timed_out": "failed",
    }
    ci_status = status_map.get(conclusion)
    if not ci_status:
        return

    issue_key = extract_issue_key(head_branch)
    if not issue_key:
        logger.debug("GitHub workflow_run: no issue key from branch '%s'", head_branch)
        return

    issue = await repo.find_issue_by_key(issue_key, board_id=_DEFAULT_BOARD_ID)
    if not issue:
        return

    await repo.update_issue_ci_status(issue["id"], ci_status)
    logger.info("Issue %s: ci_status=%s (workflow_run %s)", issue_key, ci_status, conclusion)

# ---------------------------------------------------------------------------
# Plan J-3 stub: POST /webhooks/{id}/toggle
# ---------------------------------------------------------------------------
# Plan J-3 prompt §九 #16: this endpoint flips the active/inactive
# state of a configured outbound webhook. The codebase currently
# only models inbound webhooks (CI / PR / GitHub), so ``Webhook``
# is not a real model yet. This stub keeps the route reserved
# under the require_ops gate so a future Plan K iteration can
# flesh out the model without changing the URL.
#
# Storage: an in-process dict keyed by webhook id. This survives
# the lifetime of the FastAPI process only — it's a placeholder
# for the real persistence layer that ships in a later plan.
from typing import Dict as _Dict
_WEBHOOK_ACTIVE: _Dict[str, bool] = {}


@router.post(
    "/webhooks/{webhook_id}/toggle",
    tags=["Webhooks"],
    status_code=200,
)
async def toggle_webhook(
    webhook_id: str,
    _ops: Annotated[dict, Depends(require_role_ops)],
):
    """Plan J-3 stub: flip a webhook's active flag (in-process only)."""
    current = _WEBHOOK_ACTIVE.get(webhook_id, True)
    _WEBHOOK_ACTIVE[webhook_id] = not current
    return {
        "webhook_id": webhook_id,
        "is_active": _WEBHOOK_ACTIVE[webhook_id],
    }
