"""Safe Run Adapter — wraps SafeRunExecutor as a BaseAIAdapter.

Enables the HarnessRegistry to dispatch deterministic safe-event
execution through the same interface as CLI and API adapters.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .base import BaseAIAdapter, ExecutionResult

logger = logging.getLogger(__name__)


class SafeRunAdapter(BaseAIAdapter):
    """Adapter for deterministic safe-event execution (P0 default).

    Config keys:
        tick_delay: Delay between events in seconds (default 0.05).
        events: Custom event templates (optional).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.tick_delay: float = self.config.get("tick_delay", 0.05)
        self.events: Optional[List[str]] = self.config.get("events")

    @property
    def supported_harnesses(self) -> List[str]:
        return ["safe-runner"]

    async def dispatch(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionResult:
        """Dispatch an issue through the safe runner."""
        async def _noop_log(msg: str) -> None:
            pass

        task_id = issue.get("id", "unknown")
        prompt = f"Issue: {issue.get('key', 'UNKNOWN')} - {issue.get('title', '')}"
        result = await self.execute(task_id, prompt, "", _noop_log)
        return result

    async def execute(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        """Execute the safe-event sequence.

        Args:
            task_id: Task identifier (used as issue_key in events).
            prompt: Not used (safe runner emits deterministic events).
            workspace: Not used.
            on_log: Optional callback for log lines.
        """
        from core.runtime.worker import SafeRunExecutor, ExecutionContext

        executor = SafeRunExecutor(
            tick_delay=self.tick_delay,
            events=self.events,
        )

        ctx = ExecutionContext(
            run_id=task_id,
            issue_key=task_id,
            command="safe-run",
        )

        async def _on_log(msg: str) -> None:
            if on_log:
                result = on_log(msg)
                if hasattr(result, "__await__"):
                    await result

        output = await executor.execute(ctx, _on_log)
        return ExecutionResult(
            success=True,
            output=output,
            duration_ms=0,
        )

    async def test_environment(self) -> bool:
        """Safe runner always works (no external dependencies)."""
        return True
