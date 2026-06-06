"""GitHub outbound API endpoints."""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.v1.auth_deps import require_auth

from core.github.client import get_github_client
from db.repository import find_issue_by_key, update_issue_pr_url

logger = logging.getLogger(__name__)

router = APIRouter()


class PRCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    body: str = Field("")
    head: str = Field(..., min_length=1)
    base: str = Field("main")
    issue_key: Optional[str] = Field(None)


class LabelSyncRequest(BaseModel):
    labels: List[str] = Field(...)


class CheckRunRequest(BaseModel):
    issue_key: Optional[str] = Field(None)
    name: str = Field("DevFlow CI")
    head_sha: str = Field(..., min_length=1)
    status: str = Field("completed")
    conclusion: Optional[str] = Field(None)
    output: Optional[dict] = Field(None)


@router.post("/github/pr/create", tags=["GitHub"])
async def create_pr(req: PRCreateRequest, current_user: dict = Depends(require_auth)):
    """Create a pull request on GitHub."""
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured (set GITHUB_TOKEN and GITHUB_REPO)")

    result, already_existed = await gh.create_pull_request(
        title=req.title, body=req.body, head=req.head, base=req.base,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    # Link PR to issue if issue_key provided
    if req.issue_key:
        issue = await find_issue_by_key(req.issue_key)
        if issue:
            await update_issue_pr_url(issue["id"], result["html_url"])

    return {
        "ok": True,
        "pr_url": result["html_url"],
        "pr_number": result["number"],
        "already_existed": already_existed,
    }


@router.post("/github/issues/{issue_key}/labels", tags=["GitHub"])
async def sync_labels(issue_key: str, req: LabelSyncRequest, current_user: dict = Depends(require_auth)):
    """Sync labels on the GitHub PR linked to a DevFlow issue."""
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    # Find PR number from issue
    issue = await find_issue_by_key(issue_key)
    if not issue or not issue.get("pr_url"):
        raise HTTPException(status_code=404, detail=f"No PR linked to issue {issue_key}")

    # Extract PR number from pr_url
    pr_number = None
    pr_url = issue["pr_url"]
    parts = pr_url.rstrip("/").split("/")
    if "pull" in parts:
        idx = parts.index("pull")
        if idx + 1 < len(parts):
            try:
                pr_number = int(parts[idx + 1])
            except ValueError:
                logger.warning("Failed to parse PR number from URL segment: %s", parts[idx + 1])
    if not pr_number:
        logger.warning("Could not extract PR number from pr_url: %s", pr_url)
        raise HTTPException(status_code=422, detail="Cannot extract PR number from pr_url")

    ok = await gh.sync_labels(issue_number=pr_number, labels=req.labels)
    if not ok:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    return {"ok": True, "labels": req.labels, "github_pr_number": pr_number}


@router.post("/github/check-run", tags=["GitHub"])
async def create_check_run(req: CheckRunRequest, current_user: dict = Depends(require_auth)):
    """Create a check run on GitHub."""
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    result = await gh.create_check_run(
        name=req.name,
        head_sha=req.head_sha,
        status=req.status,
        conclusion=req.conclusion,
        output=req.output,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="GitHub API request failed")

    return {
        "ok": True,
        "check_run_id": result["id"],
        "html_url": result["html_url"],
    }


@router.get("/github/pr/{pr_number}", tags=["GitHub"])
async def get_pr(pr_number: int, current_user: dict = Depends(require_auth)):
    """Get PR details from GitHub (proxy)."""
    gh = get_github_client()
    if not gh:
        raise HTTPException(status_code=503, detail="GitHub not configured")

    result = await gh.get_pull_request(pr_number)
    if not result:
        raise HTTPException(status_code=404, detail=f"PR #{pr_number} not found")

    return {"ok": True, "pr": result}
