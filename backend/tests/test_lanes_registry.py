from core.kanban_protocol.lanes import WorkerLane


def test_worker_lane_is_immutable():
    lane = WorkerLane(
        key="frontend",
        display_name="Frontend",
        description="UI work",
        allowed_profiles=["frontend"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=frontend"],
        required_completion_fields=["diff_summary"],
        timeout_seconds=1800,
        retry_policy="none",
        retry_max=0,
        next_lanes=["qa"],
        human_approval_required=False,
    )
    # frozen=True should raise on attribute assignment
    try:
        lane.key = "backend"
    except Exception as exc:  # FrozenInstanceError
        assert "frozen" in str(exc).lower() or "assign" in str(exc).lower()
    else:
        raise AssertionError("expected frozen dataclass to reject mutation")


def test_worker_lane_holds_all_required_fields():
    lane = WorkerLane(
        key="qa",
        display_name="Quality Assurance",
        description="Verification lane",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/quality-gate --verify"],
        required_completion_fields=["test_results", "coverage_pct"],
        timeout_seconds=3600,
        retry_policy="exponential",
        retry_max=2,
        next_lanes=["review"],
        human_approval_required=True,
    )
    assert lane.key == "qa"
    assert lane.retry_policy == "exponential"
    assert lane.human_approval_required is True
    assert lane.required_completion_fields == ["test_results", "coverage_pct"]
