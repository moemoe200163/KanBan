"""
DevFlow Budget Controller - Agent Usage Tracking and Limits

This module provides the BudgetController class for tracking agent token
usage and enforcing monthly budget limits.

Environment Variables:
    BUDGET_MAX_HOURS: Maximum AI hours per month (optional, defaults to 5)
    BUDGET_WARNING_THRESHOLD: Warning threshold percentage (optional, defaults to 0.8)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    """
    Current budget status for an agent.

    Attributes:
        total_hours: Maximum allowed hours per month
        used_hours: Hours consumed so far this billing period
        remaining_hours: Hours left before limit is reached
        is_limit_reached: True if budget has been exceeded
        reset_date: When the budget counter will reset
    """
    total_hours: float
    used_hours: float
    remaining_hours: float
    is_limit_reached: bool
    reset_date: datetime


@dataclass
class UsageRecord:
    """
    Record of a single usage event.

    Attributes:
        agent_id: Unique identifier for the agent
        tokens_used: Number of tokens consumed
        duration_ms: Execution duration in milliseconds
        timestamp: When the usage occurred
    """
    agent_id: str
    tokens_used: int
    duration_ms: int
    timestamp: datetime


class BudgetControllerError(Exception):
    """Base exception for BudgetController errors."""
    pass


class BudgetLimitExceededError(BudgetControllerError):
    """Raised when an agent attempts to run after budget limit is reached."""
    pass


class BudgetController:
    """
    Track and control agent usage budget.

    This class enforces monthly budget limits on AI agent usage by:
    1. Tracking token consumption per agent
    2. Converting duration to hours for budget calculation
    3. Enforcing monthly reset cycles
    4. Providing warnings at configurable thresholds

    Limits:
        MAX_HOURS_PER_MONTH: Maximum AI hours per month (default: 5)
        WARNING_THRESHOLD: Percentage when warning is sent (default: 80%)

    The controller uses an in-memory cache for fast access and can optionally
    persist usage records to a database via the provided db_session.
    """

    # Class-level constants for monthly limits
    MAX_HOURS_PER_MONTH: float = 5.0
    WARNING_THRESHOLD: float = 0.8  # 80% threshold

    def __init__(self, db_session=None):
        """
        Initialize the BudgetController.

        Args:
            db_session: Optional SQLAlchemy session for persisting usage records.
                       If not provided, only in-memory tracking is used.
        """
        self.db = db_session

        # In-memory cache: agent_id -> used_hours
        # This provides fast access for budget checks without DB roundtrips
        self._usage_cache: Dict[str, float] = {}

        # Track last reset dates per agent for monthly cycle handling
        self._reset_dates: Dict[str, datetime] = {}

        # Lock for thread-safe cache updates
        self._cache_lock = asyncio.Lock()

        # Load environment variable overrides
        self._max_hours = self._load_max_hours()
        self._warning_threshold = self._load_warning_threshold()

        logger.info(
            f"BudgetController initialized: max_hours={self._max_hours}, "
            f"warning_threshold={self._warning_threshold * 100}%, "
            f"db_session={'configured' if db_session else 'not configured'}"
        )

    def _load_max_hours(self) -> float:
        """Load MAX_HOURS from environment variable with fallback to class default."""
        import os
        env_value = os.getenv("BUDGET_MAX_HOURS")
        if env_value:
            try:
                value = float(env_value)
                if value <= 0:
                    logger.warning(f"BUDGET_MAX_HOURS must be positive, got {value}. Using default.")
                    return self.MAX_HOURS_PER_MONTH
                return value
            except ValueError:
                logger.warning(f"Invalid BUDGET_MAX_HOURS value: {env_value}. Using default.")
        return self.MAX_HOURS_PER_MONTH

    def _load_warning_threshold(self) -> float:
        """Load WARNING_THRESHOLD from environment variable with fallback to class default."""
        import os
        env_value = os.getenv("BUDGET_WARNING_THRESHOLD")
        if env_value:
            try:
                value = float(env_value)
                if not 0 < value <= 1:
                    logger.warning(f"BUDGET_WARNING_THRESHOLD must be 0-1, got {value}. Using default.")
                    return self.WARNING_THRESHOLD
                return value
            except ValueError:
                logger.warning(f"Invalid BUDGET_WARNING_THRESHOLD value: {env_value}. Using default.")
        return self.WARNING_THRESHOLD

    def _hours_to_ms(self, hours: float) -> int:
        """
        Convert hours to milliseconds.

        Args:
            hours: Number of hours to convert

        Returns:
            Equivalent time in milliseconds
        """
        return int(hours * 60 * 60 * 1000)

    def _ms_to_hours(self, ms: int) -> float:
        """
        Convert milliseconds to hours.

        Args:
            ms: Duration in milliseconds

        Returns:
            Equivalent time in hours (rounded to 4 decimal places)
        """
        return round(ms / (60 * 60 * 1000), 4)

    def _get_current_period_start(self) -> datetime:
        """
        Get the start of the current monthly billing period.

        The billing period starts at the beginning of the current month
        at midnight UTC.

        Returns:
            datetime representing the start of the current month
        """
        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    def _get_next_reset_date(self) -> datetime:
        """
        Get the date when the budget will reset.

        Returns:
            datetime representing the start of the next month
        """
        now = datetime.now(timezone.utc)
        # Calculate first day of next month
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        return next_month

    async def _check_and_reset_if_needed(self, agent_id: str) -> bool:
        """
        Check if budget needs to be reset for monthly cycle.

        Args:
            agent_id: Agent identifier

        Returns:
            True if reset occurred, False otherwise
        """
        current_period = self._get_current_period_start()
        reset_date = self._reset_dates.get(agent_id)

        if reset_date is None:
            # First time seeing this agent, set reset date
            self._reset_dates[agent_id] = current_period
            return False

        if reset_date < current_period:
            # New month, reset usage for this agent
            logger.info(
                f"Monthly budget reset for agent {agent_id}: "
                f"previous period ended {reset_date.isoformat()}"
            )
            self._usage_cache[agent_id] = 0.0
            self._reset_dates[agent_id] = current_period
            return True

        return False

    async def _load_usage_from_db(self, agent_id: str) -> float:
        """
        Load total usage for an agent from the database.

        Args:
            agent_id: Agent identifier

        Returns:
            Total hours used in the current billing period
        """
        if not self.db:
            return 0.0

        try:
            from sqlalchemy import select, func
            from ..db.models import AuditLog

            period_start = self._get_current_period_start()

            # Query for all agent usage in the current period
            # We look for 'agent_usage' or 'budget_usage' action types
            stmt = select(
                func.sum(AuditLog.details['duration_ms'].astext.cast(300))
            ).where(
                AuditLog.agent_id == agent_id,
                AuditLog.action.in_(['agent_usage', 'budget_usage']),
                AuditLog.timestamp >= period_start
            )

            result = await self.db.execute(stmt)
            total_ms = result.scalar() or 0

            return self._ms_to_hours(int(total_ms))

        except Exception as e:
            logger.error(f"Failed to load usage from database for {agent_id}: {e}")
            return 0.0

    async def _persist_usage(self, agent_id: str, tokens_used: int, duration_ms: int) -> None:
        """
        Persist a usage record to the database.

        Args:
            agent_id: Agent identifier
            tokens_used: Number of tokens consumed
            duration_ms: Execution duration in milliseconds
        """
        if not self.db:
            return

        try:
            from ..db.models import AuditLog
            import uuid

            record = AuditLog(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                agent_name=f"budget:{agent_id}",
                action="budget_usage",
                resource="budget",
                resource_id=agent_id,
                details={
                    "tokens_used": tokens_used,
                    "duration_ms": duration_ms,
                    "hours_used": self._ms_to_hours(duration_ms),
                },
                timestamp=datetime.now(timezone.utc),
            )

            self.db.add(record)
            await self.db.commit()

            logger.debug(
                f"Persisted usage record for {agent_id}: "
                f"{tokens_used} tokens, {duration_ms}ms"
            )

        except Exception as e:
            logger.error(f"Failed to persist usage for {agent_id}: {e}")
            # Don't raise - persistence failure shouldn't break usage tracking

    async def check_limit(self, agent_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if agent can continue running.

        This method verifies whether the agent has remaining budget for the
        current billing period. It also triggers a reset check for monthly
        cycle handling.

        Args:
            agent_id: Unique identifier for the agent

        Returns:
            Tuple of (can_continue, reason_if_not):
            - If can_continue is True, reason_if_not will be None
            - If can_continue is False, reason_if_not contains the reason
        """
        await self._check_and_reset_if_needed(agent_id)

        current_usage = self._usage_cache.get(agent_id, 0.0)

        # Check if limit is already reached
        if current_usage >= self._max_hours:
            reason = (
                f"Budget limit reached for agent {agent_id}: "
                f"{current_usage:.2f}/{self._max_hours:.2f} hours used. "
                f"Resets on {self._get_next_reset_date().isoformat()}"
            )
            logger.warning(reason)
            return False, reason

        # Check warning threshold
        usage_ratio = current_usage / self._max_hours
        if usage_ratio >= self._warning_threshold:
            logger.warning(
                f"Budget warning for agent {agent_id}: "
                f"{usage_ratio * 100:.1f}% of monthly budget used "
                f"({current_usage:.2f}/{self._max_hours:.2f} hours)"
            )

        return True, None

    async def record_usage(
        self,
        agent_id: str,
        tokens_used: int,
        duration_ms: int
    ) -> None:
        """
        Record agent usage.

        This method updates the internal cache with the usage and optionally
        persists it to the database. It also handles monthly reset logic.

        Args:
            agent_id: Unique identifier for the agent
            tokens_used: Number of tokens consumed in this execution
            duration_ms: Duration of the execution in milliseconds
        """
        # Check for monthly reset before updating
        await self._check_and_reset_if_needed(agent_id)

        # Convert duration to hours for budget tracking
        hours_used = self._ms_to_hours(duration_ms)

        async with self._cache_lock:
            # Update in-memory cache
            current_usage = self._usage_cache.get(agent_id, 0.0)
            self._usage_cache[agent_id] = current_usage + hours_used

        # Persist to database asynchronously
        await self._persist_usage(agent_id, tokens_used, duration_ms)

        logger.info(
            f"Recorded usage for agent {agent_id}: "
            f"{tokens_used} tokens, {duration_ms}ms ({hours_used:.4f} hours). "
            f"Total this period: {self._usage_cache.get(agent_id, 0.0):.4f} hours"
        )

    async def get_status(self, agent_id: str) -> BudgetStatus:
        """
        Get current budget status for an agent.

        This method returns the current usage statistics and whether the
        budget limit has been reached.

        Args:
            agent_id: Unique identifier for the agent

        Returns:
            BudgetStatus object with current budget information
        """
        # Check for monthly reset
        await self._check_and_reset_if_needed(agent_id)

        used_hours = self._usage_cache.get(agent_id, 0.0)
        remaining_hours = max(0.0, self._max_hours - used_hours)
        is_limit_reached = used_hours >= self._max_hours

        return BudgetStatus(
            total_hours=self._max_hours,
            used_hours=round(used_hours, 4),
            remaining_hours=round(remaining_hours, 4),
            is_limit_reached=is_limit_reached,
            reset_date=self._get_next_reset_date(),
        )

    async def terminate_if_needed(self, agent_id: str) -> bool:
        """
        Terminate agent if budget is exceeded.

        This method checks the current budget status and returns whether
        the agent should be terminated. The actual termination is handled
        by the caller.

        Args:
            agent_id: Unique identifier for the agent

        Returns:
            True if the agent should be terminated (budget exceeded),
            False if the agent can continue
        """
        can_continue, reason = await self.check_limit(agent_id)

        if not can_continue:
            logger.warning(
                f"Agent {agent_id} should be terminated: {reason}"
            )
            return True

        return False

    async def get_all_agents_status(self) -> Dict[str, BudgetStatus]:
        """
        Get budget status for all agents with recorded usage.

        Returns:
            Dictionary mapping agent_id to their BudgetStatus
        """
        status_dict = {}
        for agent_id in self._usage_cache.keys():
            status_dict[agent_id] = await self.get_status(agent_id)
        return status_dict

    async def reset_agent_budget(self, agent_id: str) -> None:
        """
        Manually reset budget for an agent.

        This is useful for administrative purposes when a user's
        budget needs to be reset mid-cycle.

        Args:
            agent_id: Agent identifier to reset
        """
        async with self._cache_lock:
            self._usage_cache[agent_id] = 0.0
            self._reset_dates[agent_id] = self._get_current_period_start()

        logger.info(f"Manual budget reset for agent {agent_id}")

    def get_max_hours(self) -> float:
        """Get the configured maximum hours per month."""
        return self._max_hours

    def get_warning_threshold(self) -> float:
        """Get the configured warning threshold (as a ratio, not percentage)."""
        return self._warning_threshold
