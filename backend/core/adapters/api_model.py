"""API Model Adapter — wraps APIModelExecutor as a BaseAIAdapter.

Enables the HarnessRegistry to dispatch LLM API calls (MiniMax, OpenAI,
Anthropic, Xiaomi MiMo, Ollama) through the same interface as CLI and
safe-runner adapters.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .base import BaseAIAdapter, ExecutionResult

logger = logging.getLogger(__name__)


class APIModelAdapter(BaseAIAdapter):
    """Adapter for real LLM API execution via provider config.

    Config keys:
        provider_id: Provider identifier (e.g. "minimax", "openai").
        model: Model name override (optional, falls back to DB config).
        timeout: HTTP timeout in seconds (default 120).
        system_prompt: Optional system prompt for all calls.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.provider_id: str = self.config.get("provider_id", "")
        self.model: str = self.config.get("model", "")
        self.timeout: float = self.config.get("timeout", 120.0)
        self.system_prompt: Optional[str] = self.config.get("system_prompt")

    @property
    def supported_harnesses(self) -> List[str]:
        return ["api-model"]

    async def dispatch(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionResult:
        """Dispatch an issue to the LLM API."""
        prompt = self._build_prompt(issue, context)
        provider = context.get("provider", self.provider_id)
        model = context.get("model", self.model)

        async def _noop_log(msg: str) -> None:
            pass

        result = await self.execute(
            task_id=issue.get("id", "unknown"),
            prompt=prompt,
            workspace="",
            on_log=_noop_log,
            provider_id=provider,
            model=model,
        )
        return result

    async def execute(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        on_log: Optional[Callable[[str], None]] = None,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute an LLM API call.

        Args:
            task_id: Task identifier for logging.
            prompt: User prompt to send.
            workspace: Unused (API calls don't need a workspace).
            on_log: Optional callback for log lines.
            provider_id: Provider override (falls back to config).
            model: Model override (falls back to config).
        """
        from core.runtime.api_model_executor import APIModelExecutor

        executor = APIModelExecutor(timeout=self.timeout)
        effective_provider = provider_id or self.provider_id
        effective_model = model or self.model

        # Wrap sync/async callback to match APIModelExecutor's coroutine expectation
        async def _on_log(msg: str) -> None:
            if on_log:
                result = on_log(msg)
                if hasattr(result, "__await__"):
                    await result

        api_result = await executor.execute(
            provider_id=effective_provider,
            model=effective_model,
            prompt=prompt,
            on_log=_on_log,
            system_prompt=self.system_prompt,
        )

        return ExecutionResult(
            success=api_result.success,
            output=api_result.output if api_result.success else None,
            error=api_result.error if not api_result.success else None,
            duration_ms=api_result.latency_ms,
        )

    async def test_environment(self) -> bool:
        """Check if the configured provider is available."""
        if not self.provider_id:
            return False
        try:
            from db.repository import get_llm_provider_config
            config = await get_llm_provider_config(self.provider_id)
            return config is not None and config.get("enabled", False)
        except Exception:
            return False

    def _build_prompt(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """Build a prompt from issue data and context."""
        parts = [
            f"# Issue: {issue.get('key', 'UNKNOWN')}",
            f"## Title: {issue.get('title', '')}",
        ]
        if issue.get("description"):
            parts.append(f"## Description:\n{issue['description']}")
        if context.get("command"):
            parts.append(f"## Command: {context['command']}")
        if context.get("profile"):
            parts.append(f"## Profile: {context['profile']}")
        parts.append(
            "\n---\n## Instructions\n"
            "1. Analyze the issue\n"
            "2. Provide a clear, detailed response\n"
            "3. Include examples where appropriate"
        )
        return "\n\n".join(parts)
