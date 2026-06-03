"""Per-lane completion payload schemas.

Each worker lane declares the shape of the payload required to mark a
handoff complete. The validation happens in HandoffService.complete() —
not at the HTTP boundary — so the API surface stays stable while the
contract becomes strict.

The `CompletionPayloadBase` enforces `extra="forbid"` (defense-in-depth
against unknown fields) and `str_strip_whitespace=True` (so `min_length=1`
catches whitespace-only strings). The scope guard (`check_payload`) is
the primary line of defense for the out-of-scope blacklist; both layers
must be present.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompletionPayloadBase(BaseModel):
    """Base for all completion payloads."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TriagePayload(CompletionPayloadBase):
    lane_recommendation: Literal[
        "frontend", "backend", "qa", "architect", "product"
    ]
    summary: str = Field(..., min_length=1, max_length=2000)


class ProductPayload(CompletionPayloadBase):
    acceptance_criteria: list[str] = Field(..., min_length=1)


class ArchitectPayload(CompletionPayloadBase):
    design_notes: str = Field(..., min_length=1, max_length=10000)
    interfaces: list[str] = Field(..., min_length=1)


class FrontendPayload(CompletionPayloadBase):
    diff_summary: str = Field(..., min_length=1, max_length=4000)
    screenshots: list[str] = Field(default_factory=list)


class BackendPayload(CompletionPayloadBase):
    diff_summary: str = Field(..., min_length=1, max_length=4000)
    test_results: str = Field(..., min_length=1, max_length=4000)


class QaPayload(CompletionPayloadBase):
    test_results: str = Field(..., min_length=1, max_length=4000)
    coverage_pct: int = Field(..., ge=0, le=100)


class ReviewPayload(CompletionPayloadBase):
    reviewer: str = Field(..., min_length=1, max_length=128)
    decision: Literal["approve", "reject", "request_changes"]


class DeliveryPayload(CompletionPayloadBase):
    release_notes: str = Field(..., min_length=1, max_length=20000)


LANE_PAYLOADS: dict[str, type[BaseModel]] = {
    "triage": TriagePayload,
    "product": ProductPayload,
    "architect": ArchitectPayload,
    "frontend": FrontendPayload,
    "backend": BackendPayload,
    "qa": QaPayload,
    "review": ReviewPayload,
    "delivery": DeliveryPayload,
}


class PayloadValidationError(ValueError):
    """Raised by HandoffService.complete() when a lane's payload fails
    Pydantic validation.

    Carries structured Pydantic errors so the API layer can produce a
    machine-readable 422 response.
    """

    def __init__(self, lane: str, errors: list[dict]) -> None:
        self.lane = lane
        self.errors = errors
        super().__init__(
            f"Payload validation failed for lane '{lane}': "
            f"{len(errors)} error(s)"
        )
