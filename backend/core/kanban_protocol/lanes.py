"""Worker Lane registry — code-defined agent routing contracts."""
from dataclasses import dataclass
from typing import List, Literal

RetryPolicy = Literal["none", "fixed", "exponential"]


@dataclass(frozen=True)
class WorkerLane:
    key: str                                      # e.g. "frontend"
    display_name: str                             # e.g. "Frontend"
    description: str                              # human-readable
    allowed_profiles: List[str]
    default_provider: str                         # e.g. "claude-code"
    default_model: str                            # e.g. "claude-3-5-sonnet"
    allowed_commands: List[str]
    required_completion_fields: List[str]
    timeout_seconds: int
    retry_policy: RetryPolicy
    retry_max: int
    next_lanes: List[str]
    human_approval_required: bool
