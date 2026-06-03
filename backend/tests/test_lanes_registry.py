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


from core.kanban_protocol.lanes import WORKER_LANES


EXPECTED_LANES = {
    "triage",
    "product",
    "architect",
    "frontend",
    "backend",
    "qa",
    "review",
    "delivery",
}


def test_worker_lanes_registry_contains_eight_lanes():
    assert set(WORKER_LANES.keys()) == EXPECTED_LANES
    for key, lane in WORKER_LANES.items():
        assert lane.key == key
        assert lane.display_name
        assert lane.allowed_commands
        assert lane.default_provider
        assert lane.default_model
        assert lane.timeout_seconds > 0
        assert lane.retry_max >= 0
        assert isinstance(lane.human_approval_required, bool)


def test_qa_lane_requires_human_approval():
    assert WORKER_LANES["qa"].human_approval_required is True


def test_frontend_lane_allows_only_frontend_profile():
    assert WORKER_LANES["frontend"].allowed_profiles == ["frontend"]


def test_lane_next_lanes_reference_existing_lanes():
    for key, lane in WORKER_LANES.items():
        for nxt in lane.next_lanes:
            assert nxt in WORKER_LANES, f"{key} -> {nxt} not in registry"


def test_required_completion_fields_matches_payload_schema():
    """Regression: required_completion_fields must mirror the schema."""
    from core.kanban_protocol.payloads import LANE_PAYLOADS
    for key, lane in WORKER_LANES.items():
        expected = list(LANE_PAYLOADS[key].model_fields.keys())
        assert lane.required_completion_fields == expected, (
            f"Lane '{key}' list out of sync with {LANE_PAYLOADS[key].__name__}"
        )
