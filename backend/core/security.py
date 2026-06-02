"""
DevFlow Agent Shield - Security Module

Security components for DevFlow Agent Shield integration including:
- Webhook signature verification (HMAC-SHA256)
- Redis-based rate limiting with Lua scripts
- PostgreSQL-based audit logging
- Threat detection for agent operations

All security-sensitive operations are logged for compliance and debugging.
"""

import hmac
import hashlib
import time
import re
import json
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from functools import wraps
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog

logger = logging.getLogger(__name__)


# =============================================================================
# Threat Detection Patterns
# =============================================================================

class ThreatType(Enum):
    """Enumeration of threat types detected by AgentShield."""
    COMMAND_INJECTION = "command_injection"
    PATH_TRAVERSAL = "path_traversal"
    DANGEROUS_OPERATIONS = "dangerous_operations"
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    RATE_VIOLATION = "rate_violation"
    UNAUTHORIZED_ACCESS = "unauthorized_access"


class WebhookValidator:
    """
    Verify webhook signatures using HMAC-SHA256.

    Provides secure signature verification for incoming webhooks
    to ensure payload authenticity and integrity.

    Usage:
        validator = WebhookValidator(secret="your-webhook-secret")
        if validator.verify(payload, signature):
            # Process webhook
    """

    def __init__(self, secret: str):
        """
        Initialize the webhook validator with a secret key.

        Args:
            secret: The shared secret key for HMAC verification.
        """
        self.secret = secret.encode("utf-8")

    def verify(self, payload: bytes, signature: str) -> bool:
        """
        Verify HMAC-SHA256 signature of a webhook payload.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            payload: The raw webhook payload bytes.
            signature: The signature provided by the webhook sender
                      (typically in hex format).

        Returns:
            True if signature is valid, False otherwise.
        """
        if not payload or not signature:
            logger.warning("Webhook verification failed: empty payload or signature")
            return False

        expected = hmac.new(
            self.secret,
            payload,
            hashlib.sha256
        ).hexdigest()

        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(expected, signature)

        if not is_valid:
            logger.warning("Webhook signature verification failed")

        return is_valid

    def sign(self, payload: bytes) -> str:
        """
        Create HMAC-SHA256 signature for a payload.

        Useful for testing or for signing outgoing webhooks.

        Args:
            payload: The payload bytes to sign.

        Returns:
            The hex-encoded signature string.
        """
        return hmac.new(
            self.secret,
            payload,
            hashlib.sha256
        ).hexdigest()

    @classmethod
    def from_environment(cls, secret_env_var: str = "WEBHOOK_SECRET") -> "WebhookValidator":
        """
        Factory method to create validator from environment variable.

        Args:
            secret_env_var: Name of the environment variable containing the secret.

        Returns:
            WebhookValidator instance.

        Raises:
            ValueError: If the environment variable is not set.
        """
        import os
        secret = os.environ.get(secret_env_var)
        if not secret:
            raise ValueError(f"Environment variable {secret_env_var} is not set")
        return cls(secret=secret)


# =============================================================================
# Rate Limiter with Lua Script
# =============================================================================

class RateLimiter:
    """
    Redis-based rate limiter using sliding window algorithm.

    Implements a sliding window rate limiting strategy with atomic
    operations via Lua scripts to ensure accurate limiting across
    distributed systems.

    Configuration:
        - max_requests: Maximum requests allowed per window (default: 100)
        - window: Time window in seconds (default: 60)

    Usage:
        limiter = RateLimiter(redis_client, max_requests=100, window=60)
        if await limiter.is_allowed("client-123"):
            # Process request
        else:
            # Rate limit exceeded
    """

    # Lua script for atomic sliding window rate limiting
    # Returns 1 if allowed, 0 if rate limited
    LUA_SCRIPT = """
    local key = KEYS[1]
    local max_requests = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])

    -- Remove expired entries outside the window
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)

    -- Count current requests in window
    local current = redis.call('ZCARD', key)

    if current < max_requests then
        -- Add new request with current timestamp as score
        redis.call('ZADD', key, now, now .. ':' .. math.random())
        -- Set expiry on the key
        redis.call('EXPIRE', key, window)
        return 1
    else
        return 0
    end
    """

    def __init__(
        self,
        redis_client,
        max_requests: int = 100,
        window: int = 60
    ):
        """
        Initialize the rate limiter.

        Args:
            redis_client: Redis client instance (aioredis or redis-py).
            max_requests: Maximum requests allowed per window.
            window: Time window in seconds.
        """
        self.redis = redis_client
        self.max_requests = max_requests
        self.window = window

        # Register Lua script for atomic operations
        # Redis-py uses Script object, aioredis uses register_script
        if hasattr(redis_client, "register_script"):
            self._lua_script = redis_client.register_script(self.LUA_SCRIPT)
        else:
            self._lua_script = self.LUA_SCRIPT

    async def is_allowed(self, key: str) -> bool:
        """
        Check if a request is allowed under the rate limit.

        Uses sliding window algorithm with Redis sorted sets
        for accurate distributed rate limiting.

        Args:
            key: Unique identifier for the rate limit bucket
                 (e.g., user_id, IP address, API key).

        Returns:
            True if request is allowed, False if rate limited.
        """
        try:
            now_ms = int(time.time() * 1000)

            # Execute Lua script atomically
            if hasattr(self._lua_script, "__call__"):
                # aioredis style
                result = await self._lua_script(
                    keys=[key],
                    args=[self.max_requests, self.window, now_ms]
                )
            else:
                # redis-py EVAL style
                result = await self.redis.eval(
                    self.LUA_SCRIPT,
                    1,  # number of keys
                    key,
                    self.max_requests,
                    self.window,
                    now_ms
                )

            is_allowed = result == 1

            if not is_allowed:
                logger.warning(
                    f"Rate limit exceeded for key: {key} "
                    f"(max: {self.max_requests}, window: {self.window}s)"
                )

            return is_allowed

        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            # Fail open - allow request if Redis is unavailable
            # This prevents Redis failures from blocking the entire system
            return True

    async def get_remaining(self, key: str) -> int:
        """
        Get remaining requests for a given key in current window.

        Args:
            key: Unique identifier for the rate limit bucket.

        Returns:
            Number of remaining requests, or -1 if unable to determine.
        """
        try:
            now_ms = int(time.time() * 1000)

            # Remove expired entries
            await self.redis.zremrangebyscore(key, 0, now_ms - self.window * 1000)

            # Count current entries
            current = await self.redis.zcard(key)

            remaining = max(0, self.max_requests - current)
            return remaining

        except Exception as e:
            logger.error(f"Error getting remaining requests: {e}")
            return -1

    async def reset(self, key: str) -> bool:
        """
        Reset rate limit counter for a given key.

        Useful for administrative purposes or testing.

        Args:
            key: Unique identifier for the rate limit bucket.

        Returns:
            True if reset successful, False otherwise.
        """
        try:
            await self.redis.delete(key)
            logger.info(f"Rate limit reset for key: {key}")
            return True
        except Exception as e:
            logger.error(f"Error resetting rate limit: {e}")
            return False


def rate_limit(limiter: RateLimiter, key_func: callable):
    """
    Decorator for adding rate limiting to async functions.

    Args:
        limiter: RateLimiter instance to use.
        key_func: Function that extracts the rate limit key from
                  the decorated function's arguments.

    Usage:
        rate_limiter = RateLimiter(redis_client)

        @rate_limit(rate_limiter, lambda ctx: ctx["user_id"])
        async def api_endpoint(ctx):
            # Your endpoint logic
            pass
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = key_func(*args, **kwargs)

            if not await limiter.is_allowed(key):
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Please try again later."
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


# =============================================================================
# Audit Logger
# =============================================================================

class AuditLogger:
    """
    Security audit logging to PostgreSQL.

    Provides comprehensive audit trail for all security-relevant
    operations including agent actions, authentication events,
    and sensitive data access.

    Usage:
        logger = AuditLogger(db_session)
        await logger.log(
            agent_id="agent-123",
            action="execute_command",
            resource="shell",
            details={"command": "ls"},
            success=True
        )
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize the audit logger with a database session.

        Args:
            db_session: SQLAlchemy async session for database access.
        """
        self.db = db_session

    async def log(
        self,
        agent_id: str,
        action: str,
        resource: str,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Optional[str]:
        """
        Log a security audit event.

        Args:
            agent_id: Identifier of the agent performing the action.
            action: The action being performed (e.g., "execute_command",
                   "access_file", "authenticate").
            resource: The resource being acted upon (e.g., "shell",
                     "filesystem", "api").
            details: Additional context about the action (e.g., command
                    being executed, file being accessed).
            success: Whether the action succeeded.
            resource_id: Optional specific resource identifier.
            ip_address: Client IP address for the request.
            user_agent: Client user agent string.

        Returns:
            The ID of the created audit log entry, or None if creation failed.
        """
        import uuid

        try:
            audit_entry = AuditLog(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
                timestamp=datetime.now(timezone.utc),
                # Map success to changes for tracking
                changes={"success": success}
            )

            self.db.add(audit_entry)
            await self.db.commit()

            logger.debug(
                f"Audit log created: agent={agent_id}, action={action}, "
                f"resource={resource}, success={success}"
            )

            return audit_entry.id

        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
            # Rollback to avoid leaving transaction in bad state
            await self.db.rollback()
            return None

    async def log_security_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        agent_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Log a security event with severity level.

        Convenience method specifically for security-relevant events.

        Args:
            event_type: Type of security event (e.g., "intrusion_attempt",
                       "data_breach", "policy_violation").
            severity: Severity level ("low", "medium", "high", "critical").
            message: Human-readable description of the event.
            agent_id: Identifier of related agent if applicable.
            details: Additional event details.

        Returns:
            The ID of the created audit log entry, or None if creation failed.
        """
        return await self.log(
            agent_id=agent_id or "system",
            action=f"security_{event_type}",
            resource="security",
            details={
                "severity": severity,
                "message": message,
                "event_type": event_type,
                **(details or {})
            },
            success=True  # Security events are always "successful" logs
        )

    async def query_logs(
        self,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> list[AuditLog]:
        """
        Query audit logs with filters.

        Args:
            agent_id: Filter by agent ID.
            action: Filter by action type.
            resource: Filter by resource type.
            start_time: Filter by start timestamp (inclusive).
            end_time: Filter by end timestamp (inclusive).
            limit: Maximum number of results to return.

        Returns:
            List of matching AuditLog entries.
        """
        try:
            stmt = select(AuditLog)

            if agent_id:
                stmt = stmt.where(AuditLog.agent_id == agent_id)
            if action:
                stmt = stmt.where(AuditLog.action == action)
            if resource:
                stmt = stmt.where(AuditLog.resource == resource)
            if start_time:
                stmt = stmt.where(AuditLog.timestamp >= start_time)
            if end_time:
                stmt = stmt.where(AuditLog.timestamp <= end_time)

            stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit)

            result = await self.db.execute(stmt)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to query audit logs: {e}")
            return []


# =============================================================================
# Agent Shield - Threat Detection
# =============================================================================

class AgentShield:
    """
    Threat detection for agent operations.

    Provides security monitoring and threat detection for agent
    actions including command execution, file operations, and
    data access. All detected threats are logged to the audit trail.

    Detection capabilities:
        - Command injection patterns
        - Path traversal attacks
        - Dangerous system operations
        - Sensitive data access attempts

    Usage:
        shield = AgentShield(audit_logger)
        is_safe, reason = await shield.check_command("ls -la /home")
        if not is_safe:
            raise PermissionError(f"Command blocked: {reason}")
    """

    # Patterns for detecting command injection attempts
    COMMAND_INJECTION_PATTERNS = [
        # Semicolon chain commands
        re.compile(r';\s*\w+'),
        # Pipe chain commands
        re.compile(r'\|\s*\w+'),
        # Command substitution
        re.compile(r'\$\([^)]+\)'),
        re.compile(r'`[^`]+`'),
        # Environment variable injection
        re.compile(r'\$\w+'),
        # quotes escaping
        re.compile(r'["\'][^"\']*[;&][^"\']*["\']'),
    ]

    # Patterns for detecting path traversal
    PATH_TRAVERSAL_PATTERNS = [
        re.compile(r'\.\./'),
        re.compile(r'\.\.\\'),
        re.compile(r'/etc/passwd'),
        re.compile(r'/etc/shadow'),
        re.compile(r'C:\\Windows'),
        re.compile(r'C:\\boot'),
    ]

    # Dangerous commands that should be explicitly allowed
    DANGEROUS_COMMANDS = {
        'rm': 'Removes files/directories',
        'dd': 'Direct disk operations',
        'mkfs': 'Filesystem creation',
        'fdisk': 'Disk partitioning',
        'parted': 'Disk partitioning',
        ':(){:|:&};:': 'Fork bomb',
        'shutdown': 'System shutdown',
        'reboot': 'System reboot',
        'halt': 'System halt',
        'poweroff': 'System power off',
        'chmod': 'Permission changes',
        'chown': 'Ownership changes',
    }

    # Sensitive paths that should not be accessed
    SENSITIVE_PATHS = [
        '/etc/shadow',
        '/etc/sudoers',
        '/root/.ssh',
        '/home/*/.ssh',
        '/.ssh',
        '/var/log/secure',
        '/var/log/auth.log',
    ]

    def __init__(self, audit_logger: AuditLogger):
        """
        Initialize the AgentShield with an audit logger.

        Args:
            audit_logger: AuditLogger instance for recording security events.
        """
        self.audit_logger = audit_logger

    async def check_command(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a command is safe to execute.

        Performs multi-stage threat detection:
        1. Check for command injection patterns
        2. Check for path traversal attempts
        3. Check for dangerous operations
        4. Check for sensitive data access

        Args:
            command: The command string to check.

        Returns:
            Tuple of (is_safe, reason_if_unsafe).
            - is_safe: True if command passes all checks.
            - reason_if_unsafe: Description of why command was blocked,
                               or None if is_safe is True.
        """
        if not command or not command.strip():
            return False, "Empty command"

        # Stage 1: Check for command injection
        for pattern in self.COMMAND_INJECTION_PATTERNS:
            if pattern.search(command):
                await self._log_threat(
                    ThreatType.COMMAND_INJECTION,
                    command,
                    f"Command injection pattern detected: {pattern.pattern}"
                )
                return False, f"Command injection pattern detected"

        # Stage 2: Check for path traversal
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if pattern.search(command):
                await self._log_threat(
                    ThreatType.PATH_TRAVERSAL,
                    command,
                    f"Path traversal pattern detected: {pattern.pattern}"
                )
                return False, f"Path traversal attempt detected"

        # Stage 3: Check for dangerous commands
        command_parts = command.strip().split()
        if command_parts:
            base_cmd = command_parts[0]
            if base_cmd in self.DANGEROUS_COMMANDS:
                await self._log_threat(
                    ThreatType.DANGEROUS_OPERATIONS,
                    command,
                    f"Dangerous command detected: {base_cmd}"
                )
                return False, f"Dangerous command blocked: {base_cmd}"

        # Stage 4: Check for sensitive path access
        for sensitive_path in self.SENSITIVE_PATHS:
            if sensitive_path.replace('*', '') in command:
                await self._log_threat(
                    ThreatType.SENSITIVE_DATA_ACCESS,
                    command,
                    f"Sensitive path access attempted: {sensitive_path}"
                )
                return False, f"Sensitive path access blocked: {sensitive_path}"

        return True, None

    async def check_file_access(
        self,
        file_path: str,
        operation: str = "read"
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if file access should be allowed.

        Args:
            file_path: The file path being accessed.
            operation: The operation type ("read", "write", "delete").

        Returns:
            Tuple of (is_safe, reason_if_unsafe).
        """
        if not file_path:
            return False, "Empty file path"

        # Check for path traversal
        if "../" in file_path or "..\\" in file_path:
            await self._log_threat(
                ThreatType.PATH_TRAVERSAL,
                file_path,
                "Path traversal in file access"
            )
            return False, "Path traversal detected"

        # Check for sensitive paths
        for sensitive_path in self.SENSITIVE_PATHS:
            if sensitive_path.replace('*', '') in file_path:
                await self._log_threat(
                    ThreatType.SENSITIVE_DATA_ACCESS,
                    file_path,
                    f"Sensitive file access attempted"
                )
                return False, f"Access to sensitive file blocked"

        return True, None

    async def check_data_access(
        self,
        data_type: str,
        resource_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if access to data resources should be allowed.

        Args:
            data_type: Type of data being accessed (e.g., "credentials",
                      "audit_logs", "user_data").
            resource_id: Optional specific resource identifier.

        Returns:
            Tuple of (is_safe, reason_if_unsafe).
        """
        sensitive_data_types = {
            'credentials',
            'secrets',
            'api_keys',
            'tokens',
            'passwords',
            'audit_logs',
            'security_config'
        }

        if data_type.lower() in sensitive_data_types:
            await self.audit_logger.log_security_event(
                event_type="sensitive_data_access",
                severity="medium",
                message=f"Sensitive data access: {data_type}",
                agent_id="agent",
                details={"data_type": data_type, "resource_id": resource_id}
            )

        return True, None

    async def _log_threat(
        self,
        threat_type: ThreatType,
        payload: str,
        description: str
    ) -> None:
        """
        Log a detected threat to the audit trail.

        Args:
            threat_type: The type of threat detected.
            payload: The content that triggered the threat detection.
            description: Human-readable description of the threat.
        """
        severity_map = {
            ThreatType.COMMAND_INJECTION: "high",
            ThreatType.PATH_TRAVERSAL: "high",
            ThreatType.DANGEROUS_OPERATIONS: "medium",
            ThreatType.SENSITIVE_DATA_ACCESS: "medium",
            ThreatType.RATE_VIOLATION: "low",
            ThreatType.UNAUTHORIZED_ACCESS: "critical",
        }

        await self.audit_logger.log_security_event(
            event_type=threat_type.value,
            severity=severity_map.get(threat_type, "medium"),
            message=description,
            details={
                "threat_type": threat_type.value,
                "payload": payload,
                "description": description
            }
        )

        logger.warning(
            f"Threat detected: {threat_type.value} - {description}"
        )

    def add_custom_pattern(
        self,
        pattern: str,
        threat_type: ThreatType,
        description: str
    ) -> None:
        """
        Add a custom detection pattern at runtime.

        Args:
            pattern: Regular expression pattern to match.
            threat_type: The type of threat this pattern represents.
            description: Description for logging when pattern matches.
        """
        compiled = re.compile(pattern)

        if threat_type == ThreatType.COMMAND_INJECTION:
            self.COMMAND_INJECTION_PATTERNS.append(compiled)
        elif threat_type == ThreatType.PATH_TRAVERSAL:
            self.PATH_TRAVERSAL_PATTERNS.append(compiled)

        logger.info(f"Added custom pattern for {threat_type.value}: {pattern}")
