"""Harness Registry — central dispatch for all execution adapters.

Maps harness types and provider IDs to adapter classes. The worker
calls ``resolve_for_run(run)`` to get the right adapter for a given
run record, eliminating hardcoded routing logic.

Resolution order for ``resolve_for_run``:
1. If ``run.provider`` is set → look up provider-specific adapter.
2. If ``run.harness`` matches a registered harness → use that adapter.
3. Fall back to ``"safe-runner"`` adapter.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type
import logging

from .base import BaseAIAdapter, ExecutionResult

logger = logging.getLogger(__name__)


class HarnessRegistry:
    """Registry for AI harness adapters.

    Two registries:
    - ``_adapter_classes``: harness_type → adapter class (for CLI/safe-runner)
    - ``_provider_classes``: provider_id → adapter class (for LLM API providers)

    Instances are lazily created and cached in ``_adapters``.
    """

    _adapter_classes: Dict[str, Type[BaseAIAdapter]] = {}
    _provider_classes: Dict[str, Type[BaseAIAdapter]] = {}
    _adapters: Dict[str, BaseAIAdapter] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, harness_type: str, adapter_class: Type[BaseAIAdapter]) -> None:
        """Register an adapter class for a harness type (e.g. 'claude-code')."""
        cls._adapter_classes[harness_type] = adapter_class
        logger.info(f"Registered adapter for harness: {harness_type}")

    @classmethod
    def register_provider(
        cls,
        provider_id: str,
        adapter_class: Type[BaseAIAdapter],
    ) -> None:
        """Register an adapter class for a specific LLM provider.

        When a run has ``provider`` set to ``provider_id``, the registry
        will instantiate this adapter class with the provider in config.
        """
        cls._provider_classes[provider_id] = adapter_class
        logger.info(f"Registered adapter for provider: {provider_id}")

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, harness_type: str, config: Optional[Dict] = None) -> Optional[BaseAIAdapter]:
        """Get an adapter instance by harness type."""
        cache_key = harness_type
        if cache_key in cls._adapters:
            return cls._adapters[cache_key]

        if harness_type in cls._adapter_classes:
            adapter = cls._adapter_classes[harness_type](config=config)
            cls._adapters[cache_key] = adapter
            return adapter

        logger.warning(f"No adapter registered for harness: {harness_type}")
        return None

    @classmethod
    def get_for_provider(
        cls,
        provider_id: str,
        config: Optional[Dict] = None,
    ) -> Optional[BaseAIAdapter]:
        """Get an adapter instance for a specific LLM provider."""
        cache_key = f"provider:{provider_id}"
        if cache_key in cls._adapters:
            return cls._adapters[cache_key]

        if provider_id in cls._provider_classes:
            merged = {**(config or {}), "provider_id": provider_id}
            adapter = cls._provider_classes[provider_id](config=merged)
            cls._adapters[cache_key] = adapter
            return adapter

        logger.warning(f"No adapter registered for provider: {provider_id}")
        return None

    @classmethod
    def resolve_for_run(cls, run: Dict) -> Optional[BaseAIAdapter]:
        """Resolve the best adapter for a given run record.

        Creates a **fresh** adapter instance per call (no caching) so each
        run gets its own adapter with the correct config.

        Resolution order:
        1. ``run["provider"]`` → provider-specific adapter
        2. ``run["harness"]`` → harness adapter
        3. Fallback to ``"safe-runner"``
        """
        provider = run.get("provider")
        harness = run.get("harness", "safe-runner")

        # 1. Provider-specific adapter (API model execution)
        if provider and provider in cls._provider_classes:
            config = {"provider_id": provider, "model": run.get("model", "")}
            try:
                return cls._provider_classes[provider](config=config)
            except Exception:
                logger.warning(f"Failed to create adapter for provider '{provider}'")

        # 2. Harness-specific adapter (CLI execution, etc.)
        if harness and harness in cls._adapter_classes:
            config = {
                "claude_path": run.get("metadata", {}).get("claude_path"),
                "working_dir": run.get("metadata", {}).get("workspace_path"),
            }
            try:
                return cls._adapter_classes[harness](config=config)
            except Exception:
                logger.warning(f"Failed to create adapter for harness '{harness}'")

        # 3. Safe runner fallback
        if "safe-runner" in cls._adapter_classes:
            try:
                return cls._adapter_classes["safe-runner"]()
            except Exception:
                logger.warning("Failed to create safe-runner adapter")

        return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @classmethod
    def list_supported(cls) -> List[str]:
        """Return list of registered harness types."""
        return list(cls._adapter_classes.keys())

    @classmethod
    def list_providers(cls) -> List[str]:
        """Return list of registered provider IDs."""
        return list(cls._provider_classes.keys())

    @classmethod
    def is_supported(cls, harness_type: str) -> bool:
        """Check if a harness type is registered."""
        return harness_type in cls._adapter_classes

    @classmethod
    def is_provider_supported(cls, provider_id: str) -> bool:
        """Check if a provider ID is registered."""
        return provider_id in cls._provider_classes

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations and cached instances."""
        cls._adapter_classes.clear()
        cls._provider_classes.clear()
        cls._adapters.clear()
