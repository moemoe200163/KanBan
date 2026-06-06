"""Tests for GitHub outbound API client and endpoints."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from core.github.client import GitHubClient, get_github_client


class TestGitHubClient:
    """Unit tests for GitHubClient methods."""

    @pytest.mark.asyncio
    async def test_create_pull_request_success(self):
        """Successful PR creation returns PR dict."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "title": "test PR",
        }
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42
        assert result["html_url"] == "https://github.com/owner/repo/pull/42"

    @pytest.mark.asyncio
    async def test_create_pull_request_already_exists(self):
        """422 response returns existing PR info if available."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        # First call: 422 with message about existing PR
        mock_422 = MagicMock()
        mock_422.status_code = 422
        mock_422.json.return_value = {
            "message": "Validation Failed",
            "errors": [{"message": "A pull request already exists for"}],
        }
        # Second call: find existing PR
        mock_list = MagicMock()
        mock_list.status_code = 200
        mock_list.json.return_value = [{
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "head": {"ref": "feature/test"},
        }]
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_422
            mock_http.get.return_value = mock_list
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_create_pull_request_network_error(self):
        """Network error returns None."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.side_effect = httpx.ConnectError("connection refused")
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test", body="body", head="feature/test",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_labels_success(self):
        """Label sync sends PUT with correct labels."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "bug"}, {"name": "p1"}]
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.put.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.sync_labels(issue_number=42, labels=["bug", "p1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_create_check_run_success(self):
        """Check run creation returns check run dict."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 12345,
            "html_url": "https://github.com/owner/repo/runs/12345",
            "status": "completed",
            "conclusion": "success",
        }
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_response
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_check_run(
                name="DevFlow CI", head_sha="abc123",
                status="completed", conclusion="success",
            )
        assert result is not None
        assert result["id"] == 12345

    @pytest.mark.asyncio
    async def test_get_github_client_returns_none_when_unconfigured(self):
        """Returns None when GITHUB_TOKEN is empty."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "", "GITHUB_REPO": ""}, clear=False):
            result = get_github_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_create_pull_request_returns_none_on_4xx(self):
        """HTTP 4xx response returns None."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        mock_branch = MagicMock()
        mock_branch.status_code = 200
        mock_403 = MagicMock()
        mock_403.status_code = 403
        mock_403.json.return_value = {"message": "Forbidden"}
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_branch
            mock_http.post.return_value = mock_403
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result = await client.create_pull_request(
                title="test", body="body", head="feature/test",
            )
        assert result is None

    def test_get_github_client_returns_client_when_configured(self):
        """Returns client when both env vars are set."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test", "GITHUB_REPO": "owner/repo"}, clear=False):
            result = get_github_client()
        assert result is not None
        assert isinstance(result, GitHubClient)
