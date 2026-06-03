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
    timeout_seconds: int
    retry_policy: RetryPolicy
    retry_max: int
    next_lanes: List[str]
    human_approval_required: bool


@property
def required_completion_fields(self) -> List[str]:
    """Derived from LANE_PAYLOADS schema — single source of truth."""
    from core.kanban_protocol.payloads import LANE_PAYLOADS
    return list(LANE_PAYLOADS[self.key].model_fields.keys())


WorkerLane.required_completion_fields = required_completion_fields


WORKER_LANES: dict[str, WorkerLane] = {
    "triage": WorkerLane(
        key="triage",
        display_name="Triage",
        description="Classify incoming work and route to the right worker lane.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=general"],
        timeout_seconds=900,
        retry_policy="none",
        retry_max=0,
        next_lanes=["product", "architect", "frontend", "backend"],
        human_approval_required=False,
    ),
    "product": WorkerLane(
        key="product",
        display_name="Product",
        description="Refine problem statement, acceptance criteria, and user impact.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=general"],
        timeout_seconds=1800,
        retry_policy="none",
        retry_max=0,
        next_lanes=["architect", "frontend", "backend"],
        human_approval_required=True,
    ),
    "architect": WorkerLane(
        key="architect",
        display_name="Architect",
        description="Design interfaces, contracts, and migration plan.",
        allowed_profiles=["backend", "general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=backend"],
        timeout_seconds=1800,
        retry_policy="none",
        retry_max=0,
        next_lanes=["frontend", "backend"],
        human_approval_required=True,
    ),
    "frontend": WorkerLane(
        key="frontend",
        display_name="Frontend",
        description="Implement UI changes against the agreed design.",
        allowed_profiles=["frontend"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=frontend"],
        timeout_seconds=1800,
        retry_policy="fixed",
        retry_max=1,
        next_lanes=["qa"],
        human_approval_required=False,
    ),
    "backend": WorkerLane(
        key="backend",
        display_name="Backend",
        description="Implement server, API, and data layer changes.",
        allowed_profiles=["backend"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=backend"],
        timeout_seconds=1800,
        retry_policy="fixed",
        retry_max=1,
        next_lanes=["qa"],
        human_approval_required=False,
    ),
    "qa": WorkerLane(
        key="qa",
        display_name="Quality Assurance",
        description="Run the verification gate and report results.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/quality-gate --verify"],
        timeout_seconds=3600,
        retry_policy="exponential",
        retry_max=2,
        next_lanes=["review", "frontend", "backend"],
        human_approval_required=True,
    ),
    "review": WorkerLane(
        key="review",
        display_name="Review",
        description="Human review stage. Holds the handoff until a human approves.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/harness-pause"],
        timeout_seconds=86400,
        retry_policy="none",
        retry_max=0,
        next_lanes=["delivery", "frontend", "backend"],
        human_approval_required=True,
    ),
    "delivery": WorkerLane(
        key="delivery",
        display_name="Delivery",
        description="Mark release readiness and record the final handoff.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/release-ready --merge"],
        timeout_seconds=1800,
        retry_policy="none",
        retry_max=0,
        next_lanes=[],
        human_approval_required=True,
    ),
}


def get_lane(key: str) -> WorkerLane:
    """Return the lane for `key` or raise KeyError with a helpful message."""
    if key not in WORKER_LANES:
        raise KeyError(
            f"Unknown worker lane '{key}'. "
            f"Known lanes: {sorted(WORKER_LANES.keys())}"
        )
    return WORKER_LANES[key]
