"""Tests for GitHub outbound API client and endpoints."""
import pytest
import asyncio
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from core.github.client import GitHubClient, get_github_client


class TestGitHubClient:
    """Unit tests for GitHubClient methods."""

    @pytest.mark.asyncio
    async def test_create_pull_request_success(self):
        """Successful PR creation returns (PR dict, already_existed=False)."""
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
            result, already_existed = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42
        assert result["html_url"] == "https://github.com/owner/repo/pull/42"
        assert already_existed is False

    @pytest.mark.asyncio
    async def test_create_pull_request_already_exists(self):
        """422 response returns (existing PR dict, already_existed=True)."""
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
            result, already_existed = await client.create_pull_request(
                title="test PR", body="body", head="feature/test",
            )
        assert result is not None
        assert result["number"] == 42
        assert already_existed is True

    @pytest.mark.asyncio
    async def test_create_pull_request_network_error(self):
        """Network error returns (None, False)."""
        client = GitHubClient(token="ghp_test", repo="owner/repo")
        with patch("core.github.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post.side_effect = httpx.ConnectError("connection refused")
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http
            result, already_existed = await client.create_pull_request(
                title="test", body="body", head="feature/test",
            )
        assert result is None
        assert already_existed is False

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
        """HTTP 4xx response returns (None, False)."""
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
            result, already_existed = await client.create_pull_request(
                title="test", body="body", head="feature/test",
            )
        assert result is None
        assert already_existed is False

    def test_get_github_client_returns_client_when_configured(self):
        """Returns client when both env vars are set."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test", "GITHUB_REPO": "owner/repo"}, clear=False):
            result = get_github_client()
        assert result is not None
        assert isinstance(result, GitHubClient)


# ============================================================================
# Integration tests for GitHub outbound API endpoints
# ============================================================================

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    from db import database as db_module
    from db.models import Base, User as UserModel
    from datetime import datetime, timezone
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    db_path = "/tmp/test_github_outbound.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"
    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    db_module.engine = new_engine
    db_module.AsyncSessionLocal = new_sessionmaker
    db_module._db_initialized = False
    db_module.DATABASE_URL = new_url

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            from api.v1.endpoints.auth import hash_password
            pwd_hash, _ = hash_password("gh_test_pass_123")
            session.add(UserModel(
                id="user_gh_test",
                username="gh_test_user",
                password_hash=pwd_hash,
                role="admin",
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield TestClient(main.app)
    new_engine.sync_engine.dispose()


def _get_token(client) -> str:
    resp = client.post("/api/v1/auth/token", json={
        "username": "gh_test_user",
        "password": "gh_test_pass_123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestGitHubAPIEndpoints:
    """Integration tests for GitHub outbound API endpoints."""

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_create_pr_success(self, mock_get_client, client):
        """POST /github/pr/create returns PR info."""
        mock_gh = AsyncMock()
        mock_gh.create_pull_request.return_value = (
            {
                "number": 42,
                "html_url": "https://github.com/owner/repo/pull/42",
                "title": "test PR",
            },
            False,
        )
        mock_get_client.return_value = mock_gh

        headers = {"Authorization": f"Bearer {_get_token(client)}"}
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test PR",
            "body": "body",
            "head": "feature/test",
            "base": "main",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["pr_number"] == 42
        assert resp.json()["already_existed"] is False

    def test_create_pr_missing_head(self, client):
        """POST /github/pr/create with missing head returns 422."""
        headers = {"Authorization": f"Bearer {_get_token(client)}"}
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test",
            "body": "body",
        }, headers=headers)
        assert resp.status_code == 422

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_create_pr_unconfigured(self, mock_get_client, client):
        """POST /github/pr/create returns 503 when GITHUB_TOKEN is empty."""
        mock_get_client.return_value = None
        headers = {"Authorization": f"Bearer {_get_token(client)}"}
        resp = client.post("/api/v1/github/pr/create", json={
            "title": "test", "body": "body", "head": "feature/test",
        }, headers=headers)
        assert resp.status_code == 503

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_sync_labels_success(self, mock_get_client, client):
        """POST /github/issues/{key}/labels syncs labels."""
        mock_gh = AsyncMock()
        mock_gh.sync_labels.return_value = True
        mock_get_client.return_value = mock_gh

        with patch("api.v1.endpoints.github_api.find_issue_by_key") as mock_find:
            mock_find.return_value = {
                "id": "DEV-001",
                "pr_url": "https://github.com/owner/repo/pull/42",
            }
            headers = {"Authorization": f"Bearer {_get_token(client)}"}
            resp = client.post("/api/v1/github/issues/DEV-001/labels", json={
                "labels": ["bug", "p1"],
            }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("api.v1.endpoints.github_api.get_github_client")
    def test_check_run_success(self, mock_get_client, client):
        """POST /github/check-run creates check run."""
        mock_gh = AsyncMock()
        mock_gh.create_check_run.return_value = {
            "id": 12345,
            "html_url": "https://github.com/owner/repo/runs/12345",
            "status": "completed",
            "conclusion": "success",
        }
        mock_get_client.return_value = mock_gh

        headers = {"Authorization": f"Bearer {_get_token(client)}"}
        resp = client.post("/api/v1/github/check-run", json={
            "name": "DevFlow CI",
            "head_sha": "abc123",
            "status": "completed",
            "conclusion": "success",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["check_run_id"] == 12345
