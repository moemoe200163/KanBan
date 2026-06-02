"""Tests for the shared P0 safe runner.

These tests focus on the deterministic lifecycle and the
dependency-injection surface so the same loop can be wired into
the dispatch endpoint and the adapter layer without regressions.
"""
import asyncio
from typing import Any, Dict, List

import pytest

from core.execution.safe_runner import (
    DEFAULT_SAFE_EVENTS,
    SafeRunnerDeps,
    run_safe_execution,
)


class FakeJob:
    """Minimal stand-in for the pydantic job model used in the API layer."""

    def __init__(self, issue_key: str, profile: str = "general") -> None:
        self.id = "job_test"
        self.issue_key = issue_key
        self.profile = profile
        self.status = "queued"
        self.message: str = ""
        self.events: List[Dict[str, Any]] = []

    def model_dump(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "issue_key": self.issue_key,
            "profile": self.profile,
            "status": self.status,
            "message": self.message,
            "events": list(self.events),
        }


def _make_deps(jobs: Dict[str, Any], job: FakeJob) -> SafeRunnerDeps:
    """Build a SafeRunnerDeps bundle with recording stubs."""

    async def save(j: Any) -> None:
        jobs["__saves__"] = jobs.get("__saves__", 0) + 1

    async def broadcast(jid: str, payload: Dict[str, Any]) -> None:
        jobs.setdefault("__broadcasts__", []).append(payload["status"])

    def transition(j: Any, status: str, message: str) -> Any:
        j.status = status
        j.message = message
        j.events.append({"status": status, "message": message})
        return j

    return SafeRunnerDeps(
        jobs=jobs,
        transition_job=transition,
        save_job_to_db=save,
        broadcast_job_update=broadcast,
        sleep_seconds=0,
    )


@pytest.mark.asyncio
async def test_safe_runner_emits_deterministic_lifecycle() -> None:
    jobs: Dict[str, Any] = {}
    job = FakeJob(issue_key="DEV-001", profile="frontend")
    jobs[job.id] = job

    await run_safe_execution(job.id, _make_deps(jobs, job))

    # Lifecycle: started, four event ticks, then review_required.
    expected = [
        "running",
        "running",
        "running",
        "running",
        "running",
        "review_required",
    ]
    assert [e["status"] for e in job.events] == expected

    # Last event is the review transition.
    assert job.status == "review_required"
    assert "human review" in job.message.lower()

    # Every transition was persisted and broadcast.
    assert jobs["__saves__"] == len(expected)
    assert jobs["__broadcasts__"] == expected


@pytest.mark.asyncio
async def test_safe_runner_uses_default_event_templates() -> None:
    assert len(DEFAULT_SAFE_EVENTS) == 4
    assert "Analyzing issue" in DEFAULT_SAFE_EVENTS[0]


@pytest.mark.asyncio
async def test_safe_runner_is_noop_for_missing_job() -> None:
    deps = _make_deps({}, FakeJob(issue_key="DEV-001"))
    # Should not raise, just log and return.
    await run_safe_execution("does_not_exist", deps)


@pytest.mark.asyncio
async def test_safe_runner_bails_out_when_cancelled_mid_flight() -> None:
    jobs: Dict[str, Any] = {}
    job = FakeJob(issue_key="DEV-002")
    jobs[job.id] = job

    deps = _make_deps(jobs, job)
    # Force cancellation after the first event by flipping status inside transition.
    original = deps.transition_job

    def cancelling_transition(j, status, message):
        original(j, status, message)
        if status == "running" and len(j.events) > 1:
            j.status = "cancelled"
        return j

    deps.transition_job = cancelling_transition
    await run_safe_execution(job.id, deps)

    # Must not reach review_required once cancellation kicks in.
    assert job.status == "cancelled"
    assert not any(e["status"] == "review_required" for e in job.events)


@pytest.mark.asyncio
async def test_safe_runner_accepts_custom_event_templates() -> None:
    jobs: Dict[str, Any] = {}
    job = FakeJob(issue_key="DEV-003")
    jobs[job.id] = job

    deps = _make_deps(jobs, job)
    deps.events = ["step A", "step B"]
    await run_safe_execution(job.id, deps)

    messages = [e["message"] for e in job.events]
    assert "step A" in messages
    assert "step B" in messages
    assert job.status == "review_required"
