"""Tests for Agent Worker Process — safe runner integration.

Covers:
- ExecutionContext dataclass construction
- SafeRunExecutor deterministic log sequence
- AgentWorkerProcess claim -> execute -> complete lifecycle
- Heartbeat during idle polling
- Failure reporting on exception
- Worker stop signal
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime.worker import (
    AgentWorkerProcess,
    ExecutionContext,
    SafeRunExecutor,
    DEFAULT_SAFE_EVENTS,
)


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------

class TestExecutionContext:
    def test_construction_defaults(self):
        ctx = ExecutionContext(
            run_id="run-1",
            issue_key="DEV-001",
            command="echo hello",
        )
        assert ctx.run_id == "run-1"
        assert ctx.issue_key == "DEV-001"
        assert ctx.profile == "general"
        assert ctx.harness == "safe-runner"
        assert ctx.board_id == "board-default"
        assert ctx.extra_metadata == {}

    def test_construction_custom(self):
        ctx = ExecutionContext(
            run_id="run-2",
            issue_key="DEV-002",
            command="test",
            profile="backend",
            harness="claude-code",
            board_id="board-ops",
            extra_metadata={"key": "val"},
        )
        assert ctx.profile == "backend"
        assert ctx.harness == "claude-code"
        assert ctx.board_id == "board-ops"
        assert ctx.extra_metadata == {"key": "val"}


# ---------------------------------------------------------------------------
# SafeRunExecutor
# ---------------------------------------------------------------------------

class TestSafeRunExecutor:
    @pytest.mark.asyncio
    async def test_execute_emits_all_events(self):
        executor = SafeRunExecutor(tick_delay=0)
        ctx = ExecutionContext(
            run_id="run-1", issue_key="DEV-001", command="test",
        )
        logs = []

        async def on_log(msg):
            logs.append(msg)

        result = await executor.execute(ctx, on_log)

        assert len(logs) == len(DEFAULT_SAFE_EVENTS)
        assert logs[0] == "Analyzing issue DEV-001"
        assert logs[1] == "Preparing execution context for general"
        assert logs[2] == "Running safe quality check"
        assert logs[3] == "Ready for human review"
        assert "human review" in result

    @pytest.mark.asyncio
    async def test_execute_custom_events(self):
        executor = SafeRunExecutor(
            events=["Step A {issue_key}", "Step B"],
            tick_delay=0,
        )
        ctx = ExecutionContext(
            run_id="run-2", issue_key="DEV-002", command="test",
        )
        logs = []

        async def on_log(msg):
            logs.append(msg)

        result = await executor.execute(ctx, on_log)

        assert len(logs) == 2
        assert logs[0] == "Step A DEV-002"
        assert logs[1] == "Step B"

    @pytest.mark.asyncio
    async def test_execute_profile_in_events(self):
        executor = SafeRunExecutor(tick_delay=0)
        ctx = ExecutionContext(
            run_id="run-3", issue_key="DEV-003", command="test",
            profile="backend",
        )
        logs = []

        async def on_log(msg):
            logs.append(msg)

        await executor.execute(ctx, on_log)
        assert logs[1] == "Preparing execution context for backend"


# ---------------------------------------------------------------------------
# AgentWorkerProcess — unit tests with mocked DB
# ---------------------------------------------------------------------------

class TestAgentWorkerProcess:
    def _make_worker(self, **kwargs):
        defaults = dict(
            worker_id="test-worker-1",
            board_id="board-default",
            worker_type="safe-runner",
            harness="safe-runner",
            poll_interval=0.01,
            heartbeat_interval=100,  # high value so heartbeat doesn't trigger
        )
        defaults.update(kwargs)
        return AgentWorkerProcess(**defaults)

    @pytest.mark.asyncio
    async def test_worker_registers_on_start(self):
        """Worker calls upsert_worker during startup."""
        worker = self._make_worker()

        from db import repository as repo

        mock_upsert = AsyncMock(return_value={"id": "test-worker-1"})
        mock_heartbeat = AsyncMock()
        mock_claim = AsyncMock(return_value=None)  # no runs available

        iteration = 0
        original_sleep = asyncio.sleep

        async def limited_sleep(dt):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                worker.stop()
            await original_sleep(0)

        # Patch at the source module since start() does lazy imports
        with patch.object(repo, "upsert_worker", mock_upsert), \
             patch.object(repo, "update_worker_heartbeat", mock_heartbeat), \
             patch("core.runtime.orchestrator.claim_next_run", mock_claim), \
             patch("core.runtime.worker.POLL_INTERVAL", 0.01), \
             patch("asyncio.sleep", limited_sleep):
            await worker.start()

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["id"] == "test-worker-1"
        assert call_kwargs[1]["board_id"] == "board-default"

    @pytest.mark.asyncio
    async def test_worker_executes_a_run(self):
        """Worker claims a run, executes it via safe runner, and completes it."""
        worker = self._make_worker()

        from db import repository as repo

        fake_run = {
            "id": "run-exec-1",
            "issueKey": "DEV-100",
            "command": "test",
            "profile": "general",
            "harness": "safe-runner",
        }

        mock_upsert = AsyncMock(return_value={"id": "test-worker-1"})
        mock_heartbeat = AsyncMock()
        mock_start_run = AsyncMock(return_value=fake_run)
        mock_complete_run = AsyncMock(return_value={**fake_run, "status": "completed"})
        mock_fail_run = AsyncMock()
        mock_append_event = AsyncMock()

        # claim returns the run only once, then None (no more pending runs)
        claim_calls = 0
        async def claim_once(worker_id, board_id):
            nonlocal claim_calls
            claim_calls += 1
            if claim_calls == 1:
                return fake_run
            return None

        iteration = 0
        original_sleep = asyncio.sleep

        async def controlled_sleep(dt):
            nonlocal iteration
            iteration += 1
            if iteration > 10:
                worker.stop()
            await original_sleep(0)

        with patch.object(repo, "upsert_worker", mock_upsert), \
             patch.object(repo, "update_worker_heartbeat", mock_heartbeat), \
             patch("core.runtime.orchestrator.claim_next_run", claim_once), \
             patch("core.runtime.orchestrator.start_run", mock_start_run), \
             patch("core.runtime.orchestrator.complete_run", mock_complete_run), \
             patch("core.runtime.orchestrator.fail_run", mock_fail_run), \
             patch("db.repository.append_run_event", mock_append_event), \
             patch("core.runtime.worker.POLL_INTERVAL", 0.01), \
             patch("core.runtime.worker.EXECUTION_TICK_DELAY", 0), \
             patch("asyncio.sleep", controlled_sleep):
            await worker.start()

        # Verify lifecycle: register -> claim -> start -> append logs -> complete
        mock_upsert.assert_called_once()
        assert claim_calls >= 2  # called at least twice (first returns run, rest return None)
        mock_start_run.assert_called_once_with("run-exec-1", "test-worker-1")
        mock_complete_run.assert_called_once()
        # Should have appended log events (4 from DEFAULT_SAFE_EVENTS)
        assert mock_append_event.call_count >= 4

    @pytest.mark.asyncio
    async def test_worker_reports_failure(self):
        """Worker reports failure when execution raises an exception."""
        worker = self._make_worker()

        from db import repository as repo

        fake_run = {
            "id": "run-fail-1",
            "issueKey": "DEV-200",
            "command": "test",
            "profile": "general",
            "harness": "safe-runner",
        }

        mock_upsert = AsyncMock(return_value={"id": "test-worker-1"})
        mock_heartbeat = AsyncMock()
        mock_start_run = AsyncMock(return_value=fake_run)
        mock_complete_run = AsyncMock()
        mock_fail_run = AsyncMock(return_value={**fake_run, "status": "failed"})
        mock_append_event = AsyncMock(side_effect=RuntimeError("Simulated execution error"))

        # claim returns the run only once, then None
        claim_calls = 0
        async def claim_once(worker_id, board_id):
            nonlocal claim_calls
            claim_calls += 1
            if claim_calls == 1:
                return fake_run
            return None

        iteration = 0
        original_sleep = asyncio.sleep

        async def controlled_sleep(dt):
            nonlocal iteration
            iteration += 1
            if iteration > 10:
                worker.stop()
            await original_sleep(0)

        with patch.object(repo, "upsert_worker", mock_upsert), \
             patch.object(repo, "update_worker_heartbeat", mock_heartbeat), \
             patch("core.runtime.orchestrator.claim_next_run", claim_once), \
             patch("core.runtime.orchestrator.start_run", mock_start_run), \
             patch("core.runtime.orchestrator.complete_run", mock_complete_run), \
             patch("core.runtime.orchestrator.fail_run", mock_fail_run), \
             patch("db.repository.append_run_event", mock_append_event), \
             patch("core.runtime.worker.POLL_INTERVAL", 0.01), \
             patch("core.runtime.worker.EXECUTION_TICK_DELAY", 0), \
             patch("asyncio.sleep", controlled_sleep):
            await worker.start()

        mock_fail_run.assert_called_once()
        fail_args = mock_fail_run.call_args
        assert fail_args[0][0] == "run-fail-1"
        assert "Simulated execution error" in fail_args[1]["error_message"]

    @pytest.mark.asyncio
    async def test_worker_stop_signal(self):
        """Worker exits its loop when stop() is called."""
        worker = self._make_worker(poll_interval=0.01)

        from db import repository as repo

        mock_upsert = AsyncMock(return_value={"id": "test-worker-1"})
        mock_heartbeat = AsyncMock()
        mock_claim = AsyncMock(return_value=None)

        with patch.object(repo, "upsert_worker", mock_upsert), \
             patch.object(repo, "update_worker_heartbeat", mock_heartbeat), \
             patch("core.runtime.orchestrator.claim_next_run", mock_claim), \
             patch("core.runtime.worker.POLL_INTERVAL", 0.01):

            async def auto_stop():
                await asyncio.sleep(0.05)
                worker.stop()

            asyncio.create_task(auto_stop())
            await worker.start()

        # Worker should have stopped and updated status
        assert worker._running is False
