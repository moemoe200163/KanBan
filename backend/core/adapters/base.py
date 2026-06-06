from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Result of an AI execution attempt."""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    pr_url: Optional[str] = None
    duration_ms: int = 0

    # Session resume fields (set by adapter when resume is supported)
    conversation_history: Optional[list] = None
    checkpoint_data: Optional[dict] = None
    provider_resume_ref: Optional[str] = None


class BaseAIAdapter(ABC):
    """
    Abstract base class for AI harness adapters.
    """

    @property
    @abstractmethod
    def supported_harnesses(self) -> List[str]:
        """Return list of supported harness types."""
        pass

    @abstractmethod
    async def dispatch(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ExecutionResult:
        pass

    @abstractmethod
    async def execute(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        pass

    @abstractmethod
    async def test_environment(self) -> bool:
        pass

    def supports_resume(self) -> bool:
        """Return True if this adapter can resume sessions. Default: False."""
        return False

    async def execute_with_session(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        session: dict,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        """Execute with resume context. Default: ignore session, call execute()."""
        return await self.execute(task_id, prompt, workspace, on_log)