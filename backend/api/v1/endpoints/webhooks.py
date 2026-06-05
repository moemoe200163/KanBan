"""
DevFlow Backend - Webhook Endpoints for CI/PR Events

Handles incoming webhooks from CI systems and PR events.
Stores webhook events in the WebhookEvent model for audit/replay.
"""

from datetime import datetime, timezone
from typing import Optional, List, AsyncIterator
from uuid import uuid4
import hmac
import hashlib
import json
import os
import re
import logging

from fastapi import APIRouter, HTTPException, BackgroundTasks, Header, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# Webhook secret from environment variable (never hardcoded)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


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
    """Payload for CI pipeline webhook events."""
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
    """Payload for PR webhook events."""
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

@router.post("/webhooks/ci", response_model=CIWebhookResponse, tags=["Webhooks"])
async def receive_ci_webhook(
    request: Request,
    payload: CIWebhookPayload,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """
    Receive CI pipeline events.

    Handles:
    - build_success: CI build completed successfully
    - build_failure: CI build failed
    - deployment: Code was deployed

    Updates the associated ECC job with CI status.

    Args:
        request: FastAPI request object (for raw body access)
        payload: CI webhook payload
        background_tasks: FastAPI background tasks
        x_webhook_signature: Optional webhook signature header

    Returns:
        Acknowledgment with event_id for tracking
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify webhook signature
    if x_webhook_signature and not verify_webhook_signature(body, x_webhook_signature):
        logger.warning(f"CI webhook signature verification failed for job: {payload.job_id}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Validate event type
    valid_ci_events = {"build_success", "build_failure", "deployment"}
    if payload.event_type not in valid_ci_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_ci_events}"
        )

    # Extract headers for storage
    headers = {
        "user_agent": request.headers.get("user-agent", ""),
        "content_type": request.headers.get("content-type", ""),
    }

    # Store webhook event
    event_id = await _save_webhook_event(
        event_type=f"ci_{payload.event_type}",
        payload=payload.model_dump(),
        headers=headers,
        status="received",
    )

    logger.info(f"CI webhook received: event_type={payload.event_type}, job_id={payload.job_id}")

    # Schedule background update of job status
    background_tasks.add_task(
        _update_job_status_from_ci,
        payload.job_id,
        payload.event_type,
        payload.metadata or {},
    )

    # Also update the linked Issue's ci_status
    background_tasks.add_task(
        _update_issue_from_ci_webhook,
        payload.job_id,
        payload.event_type,
        payload.metadata or {},
    )

    return CIWebhookResponse(
        status="accepted",
        event_id=event_id,
        message=f"CI event '{payload.event_type}' queued for processing",
    )


# =============================================================================
# PR Webhook Endpoint
# =============================================================================

@router.post("/webhooks/pr", response_model=PRWebhookResponse, tags=["Webhooks"])
async def receive_pr_webhook(
    request: Request,
    payload: PRWebhookPayload,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """
    Receive PR events.

    Handles:
    - pr_opened: Pull request was opened
    - pr_merged: Pull request was merged
    - pr_closed: Pull request was closed (without merge)

    Updates the associated ECC job with PR status.

    Args:
        request: FastAPI request object (for raw body access)
        payload: PR webhook payload
        background_tasks: FastAPI background tasks
        x_webhook_signature: Optional webhook signature header

    Returns:
        Acknowledgment with event_id for tracking
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify webhook signature
    if x_webhook_signature and not verify_webhook_signature(body, x_webhook_signature):
        logger.warning(f"PR webhook signature verification failed for job: {payload.job_id}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Validate event type
    valid_pr_events = {"pr_opened", "pr_merged", "pr_closed"}
    if payload.event_type not in valid_pr_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_pr_events}"
        )

    # Extract headers for storage
    headers = {
        "user_agent": request.headers.get("user-agent", ""),
        "content_type": request.headers.get("content-type", ""),
    }

    # Store webhook event
    event_id = await _save_webhook_event(
        event_type=f"pr_{payload.event_type}",
        payload=payload.model_dump(),
        headers=headers,
        status="received",
    )

    logger.info(
        f"PR webhook received: event_type={payload.event_type}, "
        f"pr_number={payload.pr_number}, job_id={payload.job_id}"
    )

    # Schedule background update of job status
    background_tasks.add_task(
        _update_job_status_from_ci,  # Reuse the same function for job updates
        payload.job_id,
        payload.event_type,
        {"pr_number": payload.pr_number, "title": payload.title},
    )

    # Also update the linked Issue's pr_url
    background_tasks.add_task(
        _update_issue_from_pr_webhook,
        payload.job_id,
        payload.pr_number,
        payload.title,
        payload.event_type,
    )

    return PRWebhookResponse(
        status="accepted",
        event_id=event_id,
        message=f"PR event '{payload.event_type}' for PR #{payload.pr_number} queued",
    )


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

    # Verify signature
    if x_hub_signature_256 and not verify_webhook_signature(body, x_hub_signature_256):
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

    issue = await repo.find_issue_by_key(issue_key)
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

    issue = await repo.find_issue_by_key(issue_key)
    if not issue:
        return

    await repo.update_issue_ci_status(issue["id"], ci_status)
    logger.info("Issue %s: ci_status=%s (workflow_run %s)", issue_key, ci_status, conclusion)