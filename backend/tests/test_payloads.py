"""Unit tests for per-lane completion payload schemas.

Contract matrix (run for every lane unless noted):
- Valid payload passes
- Missing required field raises ValidationError with loc and type=missing
- Wrong type raises ValidationError
- Literal mismatch raises ValidationError with type=literal_error
- min_length violation raises ValidationError
- max_length violation raises ValidationError
- Whitespace-only string raises ValidationError (stripped to empty)
- Extra field raises ValidationError with type=extra_forbidden
- ge / le violation raises ValidationError (numeric fields)
- Empty list when min_length=1 raises ValidationError
"""
import pytest
from pydantic import ValidationError

from core.kanban_protocol.payloads import (
    LANE_PAYLOADS,
    CompletionPayloadBase,
    DeliveryPayload,
    FrontendPayload,
    ProductPayload,
    QaPayload,
    ReviewPayload,
    TriagePayload,
    BackendPayload,
    ArchitectPayload,
)


# ---- TriagePayload ---------------------------------------------------------

class TestTriagePayload:
    def test_valid(self):
        m = TriagePayload(
            lane_recommendation="frontend", summary="routes to frontend"
        )
        assert m.lane_recommendation == "frontend"
        assert m.summary == "routes to frontend"

    def test_missing_summary(self):
        with pytest.raises(ValidationError) as exc:
            TriagePayload(lane_recommendation="frontend")
        assert exc.value.errors()[0]["loc"] == ("summary",)
        assert exc.value.errors()[0]["type"] == "missing"

    def test_wrong_lane_recommendation(self):
        with pytest.raises(ValidationError) as exc:
            TriagePayload(lane_recommendation="triage", summary="x")
        assert exc.value.errors()[0]["loc"] == ("lane_recommendation",)
        assert exc.value.errors()[0]["type"] == "literal_error"

    def test_max_length_summary(self):
        with pytest.raises(ValidationError) as exc:
            TriagePayload(lane_recommendation="qa", summary="x" * 2001)
        assert exc.value.errors()[0]["type"] == "string_too_long"

    def test_whitespace_only_summary(self):
        with pytest.raises(ValidationError):
            TriagePayload(lane_recommendation="qa", summary="   ")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TriagePayload(
                lane_recommendation="qa",
                summary="x",
                sneaky_key=1,
            )
        assert exc.value.errors()[0]["type"] == "extra_forbidden"


# ---- ProductPayload --------------------------------------------------------

class TestProductPayload:
    def test_valid(self):
        m = ProductPayload(acceptance_criteria=["User can click submit"])
        assert m.acceptance_criteria == ["User can click submit"]

    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ProductPayload(acceptance_criteria=[])
        assert exc.value.errors()[0]["type"] == "too_short"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ProductPayload(acceptance_criteria=["x"], extra="bad")


# ---- ArchitectPayload ------------------------------------------------------

class TestArchitectPayload:
    def test_valid(self):
        m = ArchitectPayload(
            design_notes="use ESM modules",
            interfaces=["GET /api/v1/lanes"],
        )
        assert m.design_notes == "use ESM modules"
        assert m.interfaces == ["GET /api/v1/lanes"]

    def test_missing_interfaces(self):
        with pytest.raises(ValidationError) as exc:
            ArchitectPayload(design_notes="x")
        assert exc.value.errors()[0]["loc"] == ("interfaces",)
        assert exc.value.errors()[0]["type"] == "missing"

    def test_max_length_design_notes(self):
        with pytest.raises(ValidationError) as exc:
            ArchitectPayload(
                design_notes="x" * 10001, interfaces=["y"]
            )
        assert exc.value.errors()[0]["type"] == "string_too_long"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ArchitectPayload(
                design_notes="x", interfaces=["y"], bogus=1
            )


# ---- FrontendPayload -------------------------------------------------------

class TestFrontendPayload:
    def test_valid(self):
        m = FrontendPayload(
            diff_summary="added sidebar",
            screenshots=["a.png", "b.png"],
        )
        assert m.screenshots == ["a.png", "b.png"]

    def test_default_empty_screenshots(self):
        m = FrontendPayload(diff_summary="x")
        assert m.screenshots == []

    def test_missing_diff_summary(self):
        with pytest.raises(ValidationError) as exc:
            FrontendPayload()
        assert exc.value.errors()[0]["loc"] == ("diff_summary",)
        assert exc.value.errors()[0]["type"] == "missing"

    def test_whitespace_only_diff_summary(self):
        with pytest.raises(ValidationError):
            FrontendPayload(diff_summary="   ")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            FrontendPayload(diff_summary="x", stealth=True)


# ---- BackendPayload --------------------------------------------------------

class TestBackendPayload:
    def test_valid(self):
        m = BackendPayload(
            diff_summary="added endpoint", test_results="42 passed"
        )
        assert m.test_results == "42 passed"

    def test_missing_test_results(self):
        with pytest.raises(ValidationError) as exc:
            BackendPayload(diff_summary="x")
        assert exc.value.errors()[0]["loc"] == ("test_results",)
        assert exc.value.errors()[0]["type"] == "missing"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            BackendPayload(
                diff_summary="x", test_results="ok", oops="bad"
            )


# ---- QaPayload -------------------------------------------------------------

class TestQaPayload:
    def test_valid(self):
        m = QaPayload(test_results="ok", coverage_pct=95)
        assert m.coverage_pct == 95

    def test_coverage_above_max(self):
        with pytest.raises(ValidationError) as exc:
            QaPayload(test_results="ok", coverage_pct=150)
        assert exc.value.errors()[0]["loc"] == ("coverage_pct",)
        assert exc.value.errors()[0]["type"] == "less_than_equal"

    def test_coverage_below_min(self):
        with pytest.raises(ValidationError) as exc:
            QaPayload(test_results="ok", coverage_pct=-1)
        assert exc.value.errors()[0]["type"] == "greater_than_equal"

    def test_coverage_wrong_type(self):
        with pytest.raises(ValidationError) as exc:
            QaPayload(test_results="ok", coverage_pct="not_an_int")
        # Pydantic 2 coerces parseable strings ("99") to int, so we use a
        # non-parseable value to trigger int_parsing.
        assert exc.value.errors()[0]["loc"] == ("coverage_pct",)
        assert "int" in exc.value.errors()[0]["type"]

    def test_missing_coverage_pct(self):
        with pytest.raises(ValidationError) as exc:
            QaPayload(test_results="ok")
        assert exc.value.errors()[0]["loc"] == ("coverage_pct",)

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            QaPayload(
                test_results="ok", coverage_pct=50, surprise="bad"
            )


# ---- ReviewPayload ---------------------------------------------------------

class TestReviewPayload:
    def test_valid_approve(self):
        m = ReviewPayload(reviewer="alice", decision="approve")
        assert m.decision == "approve"

    def test_valid_request_changes(self):
        m = ReviewPayload(reviewer="bob", decision="request_changes")
        assert m.decision == "request_changes"

    def test_invalid_decision(self):
        with pytest.raises(ValidationError) as exc:
            ReviewPayload(reviewer="x", decision="yes")
        assert exc.value.errors()[0]["loc"] == ("decision",)
        assert exc.value.errors()[0]["type"] == "literal_error"

    def test_whitespace_only_reviewer(self):
        with pytest.raises(ValidationError):
            ReviewPayload(reviewer="  ", decision="approve")

    def test_max_length_reviewer(self):
        with pytest.raises(ValidationError) as exc:
            ReviewPayload(reviewer="x" * 129, decision="approve")
        assert exc.value.errors()[0]["type"] == "string_too_long"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ReviewPayload(
                reviewer="x", decision="approve", stealth="bad"
            )


# ---- DeliveryPayload -------------------------------------------------------

class TestDeliveryPayload:
    def test_valid(self):
        m = DeliveryPayload(release_notes="shipped v1.0")
        assert m.release_notes == "shipped v1.0"

    def test_missing_release_notes(self):
        with pytest.raises(ValidationError) as exc:
            DeliveryPayload()
        assert exc.value.errors()[0]["loc"] == ("release_notes",)

    def test_max_length_release_notes(self):
        with pytest.raises(ValidationError) as exc:
            DeliveryPayload(release_notes="x" * 20001)
        assert exc.value.errors()[0]["type"] == "string_too_long"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            DeliveryPayload(release_notes="x", oops=1)


# ---- Registry integrity ----------------------------------------------------

class TestLanePayloadsRegistry:
    def test_all_eight_lanes_registered(self):
        assert set(LANE_PAYLOADS.keys()) == {
            "triage", "product", "architect", "frontend",
            "backend", "qa", "review", "delivery",
        }

    def test_all_schemas_inherit_base(self):
        for cls in LANE_PAYLOADS.values():
            assert issubclass(cls, CompletionPayloadBase)

    def test_all_schemas_forbid_extras(self):
        for cls in LANE_PAYLOADS.values():
            assert cls.model_config.get("extra") == "forbid"
