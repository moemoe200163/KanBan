"""Shared GitHub REST API client for outbound API calls."""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GitHubClient:
    """Shared GitHub REST API client."""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    async def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Optional[dict]:
        """Create a PR. Returns PR dict or None on failure."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                pr_resp = await client.post(
                    f"{self.base_url}/pulls",
                    headers=self._headers,
                    json={"title": title, "body": body, "head": head, "base": base},
                )
                if pr_resp.status_code == 201:
                    data = pr_resp.json()
                    return {
                        "number": data["number"],
                        "html_url": data["html_url"],
                        "title": data.get("title", ""),
                    }

                # Handle "PR already exists"
                if pr_resp.status_code == 422:
                    return await self._find_existing_pr(client, head, base)

                logger.warning("PR creation failed: %s", pr_resp.status_code)
                return None
        except Exception as e:
            logger.warning("Failed to create PR: %s", e)
            return None

    async def _find_existing_pr(
        self, client: httpx.AsyncClient, head: str, base: str = "main"
    ) -> Optional[dict]:
        """Find existing PR for a branch."""
        try:
            resp = await client.get(
                f"{self.base_url}/pulls",
                headers=self._headers,
                params={"state": "all", "head": head, "base": base},
            )
            if resp.status_code == 200:
                prs = resp.json()
                if prs:
                    pr = prs[0]
                    return {
                        "number": pr["number"],
                        "html_url": pr["html_url"],
                        "title": pr.get("title", ""),
                    }
        except Exception as e:
            logger.warning("Failed to find existing PR: %s", e)
        return None

    async def sync_labels(self, issue_number: int, labels: list[str]) -> bool:
        """Set labels on a GitHub issue/PR (replaces all)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.put(
                    f"{self.base_url}/issues/{issue_number}/labels",
                    headers=self._headers,
                    json={"labels": labels},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning("Failed to sync labels: %s", e)
            return False

    async def create_check_run(
        self,
        name: str,
        head_sha: str,
        status: str,
        conclusion: Optional[str] = None,
        output: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create a check run."""
        try:
            payload = {"name": name, "head_sha": head_sha, "status": status}
            if conclusion:
                payload["conclusion"] = conclusion
            if output:
                payload["output"] = output
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/check-runs",
                    headers=self._headers,
                    json=payload,
                )
                if resp.status_code == 201:
                    data = resp.json()
                    return {
                        "id": data["id"],
                        "html_url": data.get("html_url", ""),
                        "status": data.get("status", status),
                        "conclusion": data.get("conclusion"),
                    }
                logger.warning("Check run creation failed: %s", resp.status_code)
                return None
        except Exception as e:
            logger.warning("Failed to create check run: %s", e)
            return None

    async def list_pull_requests(self, state: str = "open") -> list:
        """List PRs with state filter."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/pulls",
                    headers=self._headers,
                    params={"state": state},
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("List PRs failed: %s", resp.status_code)
                return []
        except Exception as e:
            logger.warning("Failed to list PRs: %s", e)
            return []

    async def find_existing_pr(self, head: str, base: str = "main") -> Optional[dict]:
        """Find existing PR for a branch (public standalone)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._find_existing_pr(client, head, base)
        except Exception as e:
            logger.warning("Failed to find existing PR: %s", e)
            return None

    async def get_pull_request(self, pr_number: int) -> Optional[dict]:
        """Get PR by number."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/pulls/{pr_number}",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception as e:
            logger.warning("Failed to get PR %d: %s", pr_number, e)
            return None

    async def get_branch(self, branch: str) -> Optional[dict]:
        """Get branch info."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/branches/{branch}",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception as e:
            logger.warning("Failed to get branch %s: %s", branch, e)
            return None


def get_github_client() -> Optional[GitHubClient]:
    """Get a GitHubClient if configured, None otherwise."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return None
    return GitHubClient(token=token, repo=repo)
