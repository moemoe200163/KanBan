"""
Harness Registry
"""
from typing import Dict, Optional, List, Type
import logging

from .base import BaseAIAdapter, ExecutionResult

logger = logging.getLogger(__name__)


class HarnessRegistry:
    """Registry for AI harness adapters."""

    _adapters: Dict[str, BaseAIAdapter] = {}
    _adapter_classes: Dict[str, Type[BaseAIAdapter]] = {}

    @classmethod
    def register(cls, harness_type: str, adapter_class: Type[BaseAIAdapter]) -> None:
        """Register an adapter class for a harness type."""
        cls._adapter_classes[harness_type] = adapter_class
        logger.info(f"Registered adapter class for harness: {harness_type}")

    @classmethod
    def get(cls, harness_type: str, config: Optional[Dict] = None) -> Optional[BaseAIAdapter]:
        """Get an adapter instance for a harness type."""
        if harness_type in cls._adapters:
            return cls._adapters[harness_type]

        if harness_type in cls._adapter_classes:
            adapter = cls._adapter_classes[harness_type](config=config)
            cls._adapters[harness_type] = adapter
            return adapter

        logger.warning(f"No adapter registered for harness: {harness_type}")
        return None

    @classmethod
    def list_supported(cls) -> List[str]:
        """Return list of supported harness types."""
        return list(cls._adapter_classes.keys())

    @classmethod
    def is_supported(cls, harness_type: str) -> bool:
        """Check if a harness type is supported."""
        return harness_type in cls._adapter_classes

    @classmethod
    def clear(cls) -> None:
        """Clear all registered adapters and classes."""
        cls._adapters.clear()
        cls._adapter_classes.clear()