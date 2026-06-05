"""Tests for Board Isolation — board_id propagation across repo and API.

Covers:
- _job_model_to_dict includes board_id
- create_issue_event/comment/artifact set board_id on model
- create_job_for_handoff passes board_id to repo
"""

import pytest
from unittest.mock import AsyncMock, patch

from core.kanban_protocol.board_scope import DEFAULT_BOARD_ID


async def _noop():
    pass


# ---------------------------------------------------------------------------
# _job_model_to_dict includes board_id
# ---------------------------------------------------------------------------

class TestJobModelToDict:
    def test_includes_board_id(self):
        from db.repository import _job_model_to_dict

        class FakeJob:
            id = "j1"
            issue_id = "i1"
            issue_key = "DEV-001"
            command = "/loop-start"
            profile = "general"
            harness = "safe-runner"
            status = "queued"
            created_at = "2026-01-01T00:00:00Z"
            updated_at = "2026-01-01T00:00:00Z"
            board_id = "board-default"
            message = "test"
            events = []

        d = _job_model_to_dict(FakeJob())
        assert "board_id" in d
        assert d["board_id"] == "board-default"

    def test_includes_custom_board_id(self):
        from db.repository import _job_model_to_dict

        class FakeJob:
            id = "j1"
            issue_id = "i1"
            issue_key = "DEV-001"
            command = "/loop-start"
            profile = "general"
            harness = "safe-runner"
            status = "queued"
            created_at = "2026-01-01T00:00:00Z"
            updated_at = "2026-01-01T00:00:00Z"
            board_id = "board-alpha"
            message = "test"
            events = []

        d = _job_model_to_dict(FakeJob())
        assert d["board_id"] == "board-alpha"


# ---------------------------------------------------------------------------
# create_issue_event sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueEventBoardId:
    @pytest.mark.asyncio
    async def test_event_board_id_forwarded(self):
        """Verify create_issue_event passes board_id to the IssueEvent model."""
        from db.repository import create_issue_event

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_event(
                issue_id="i1",
                event_type="test",
                summary="test event",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"

    @pytest.mark.asyncio
    async def test_event_defaults_board_id(self):
        from db.repository import create_issue_event

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_event(
                issue_id="i1",
                event_type="test",
                summary="test event",
            )
            assert captured["board_id"] == DEFAULT_BOARD_ID


# ---------------------------------------------------------------------------
# create_issue_comment sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueCommentBoardId:
    @pytest.mark.asyncio
    async def test_comment_board_id_forwarded(self):
        from db.repository import create_issue_comment

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_comment(
                issue_id="i1",
                body="hello",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"


# ---------------------------------------------------------------------------
# create_issue_artifact sets board_id on model
# ---------------------------------------------------------------------------

class TestCreateIssueArtifactBoardId:
    @pytest.mark.asyncio
    async def test_artifact_board_id_forwarded(self):
        from db.repository import create_issue_artifact

        captured = {}

        class FakeSession:
            def add(self, obj):
                captured["board_id"] = obj.board_id
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        fake_sm = lambda: FakeSession()
        with patch("db.repository._get_sessionmaker", return_value=fake_sm), \
             patch("db.repository._ensure_init", return_value=_noop):
            await create_issue_artifact(
                issue_id="i1",
                title="test.txt",
                artifact_type="file",
                board_id="custom-board",
            )
            assert captured["board_id"] == "custom-board"


# ---------------------------------------------------------------------------
# create_job_for_handoff passes board_id
# ---------------------------------------------------------------------------

class TestCreateJobForHandoffBoardId:
    @pytest.mark.asyncio
    async def test_passes_board_id_to_repo(self):
        mock_create = AsyncMock(return_value={"id": "ecc_test", "board_id": "custom-board"})

        with patch("db.repository.create_ecc_job_safe_runner", mock_create), \
             patch("core.kanban_protocol.lanes.get_lane") as mock_get_lane:
            mock_get_lane.return_value = type("Lane", (), {"allowed_commands": ["/loop-start"]})()

            from core.kanban_protocol.orchestrator import create_job_for_handoff
            await create_job_for_handoff(
                handoff_id="h1",
                issue_id="i1",
                issue_key="DEV-001",
                to_lane="review",
                profile="general",
                actor="test",
                board_id="custom-board",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["board_id"] == "custom-board"

    @pytest.mark.asyncio
    async def test_defaults_to_board_default(self):
        mock_create = AsyncMock(return_value={"id": "ecc_test", "board_id": "board-default"})

        with patch("db.repository.create_ecc_job_safe_runner", mock_create), \
             patch("core.kanban_protocol.lanes.get_lane") as mock_get_lane:
            mock_get_lane.return_value = type("Lane", (), {"allowed_commands": ["/loop-start"]})()

            from core.kanban_protocol.orchestrator import create_job_for_handoff
            await create_job_for_handoff(
                handoff_id="h1",
                issue_id="i1",
                issue_key="DEV-001",
                to_lane="review",
                profile="general",
                actor="test",
            )

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["board_id"] == "board-default"
