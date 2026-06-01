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