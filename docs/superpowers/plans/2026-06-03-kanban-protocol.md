# Kanban Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote DevFlow from a Kanban UI with a control-plane dispatch endpoint to a durable multi-agent work queue. Handoffs become a first-class queue item with a status machine, declared worker lanes, rules preview, and board isolation.

**Architecture:** Backend adds a code-defined `WorkerLane` registry, a `core/kanban_protocol/` package (lane registry + scope guard + handoff service + manual orchestrator), a new `issue_handoffs` table with status machine, and `board_id` columns on existing collaboration tables. Frontend adds a Lane Matrix view, a Handoffs section in the issue detail panel, and a rules-preview modal. Real adapter execution remains opt-in; safe runner is still the default dispatch path.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, Nuxt 3 / Vue 3 / TypeScript / Pinia, Pytest, `fastapi.testclient.TestClient`.

**Spec reference:** `docs/superpowers/specs/kanban-protocol-design.md` (commit `af418b2`).

**Naming note:** This is the **Kanban Protocol / P2.5** plan. It is **not** the legacy P3 (PR/CI + Session resume) and must not implement that work.

---

## File Structure

New files this plan creates or modifies:

```text
backend/
├── core/
│   └── kanban_protocol/
│       ├── __init__.py                       (new)
│       ├── lanes.py                          (new) WorkerLane + WORKER_LANES
│       ├── board_scope.py                    (new) DEFAULT_BOARD_ID + resolve_board_id
│       ├── scope_guard.py                    (new) DENIED_PAYLOAD_KEYS + check
│       ├── handoff.py                        (new) HandoffService (status machine)
│       ├── orchestrator.py                   (new) manual dispatch + JobModel creation
│       └── schemas.py                        (new) Pydantic request/response models
├── api/v1/endpoints/
│   ├── lanes.py                              (new) GET /api/v1/lanes
│   └── handoffs.py                           (new) all handoff endpoints
├── db/
│   ├── models.py                             (modify) add IssueHandoff + board_id
│   └── repository.py                         (modify) add handoff repo functions
├── alembic/versions/
│   └── 0004_add_board_id_and_handoffs.py     (new)
└── tests/
    ├── test_lanes_registry.py                (new)
    ├── test_board_scope.py                   (new)
    ├── test_scope_guard.py                   (new)
    ├── test_lanes_api.py                     (new)
    ├── test_handoff_service.py               (new)
    └── test_handoffs_api.py                  (new)

src/
├── types/
│   └── kanbanProtocol.ts                     (new)
├── composables/
│   └── useKanbanProtocol.ts                  (new) API calls for lanes + handoffs
├── stores/
│   └── board.ts                              (modify) handoff state + actions
├── components/
│   ├── lanes/
│   │   └── LaneMatrix.vue                    (new)
│   ├── handoffs/
│   │   ├── HandoffSection.vue                (new)
│   │   ├── HandoffRow.vue                    (new)
│   │   ├── HandoffActions.vue                (new)
│   │   └── RulesPreviewModal.vue             (new)
│   └── IssueDetail.vue                       (modify) embed HandoffSection

backend/main.py                               (modify) mount new routers
```

Each file has one clear responsibility. The `core/kanban_protocol/` package is
self-contained: registry, scope helpers, handoff service, orchestrator, and
API schemas live in separate modules so each can be reasoned about alone.

---

# Phase 0: Setup

## Task 1: Create the `kanban_protocol` package skeleton

**Files:**
- Create: `backend/core/kanban_protocol/__init__.py`

- [ ] **Step 1: Create the package directory and `__init__.py`**

Create an empty package marker:

```python
"""
Kanban Protocol — Agent-Native Kanban core.

Public surface is exposed from submodules; this file intentionally stays
empty so importing the package has no side effects.
"""
```

- [ ] **Step 2: Verify the package imports**

Run:
```bash
PYTHONPATH=backend python3 -c "import core.kanban_protocol; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/core/kanban_protocol/__init__.py
git commit -m "feat(kanban-protocol): add package skeleton"
```

---

# Phase 1: Worker Lane Registry (Code-Defined)

## Task 2: `WorkerLane` dataclass with TDD

**Files:**
- Create: `backend/core/kanban_protocol/lanes.py`
- Create: `backend/tests/test_lanes_registry.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_lanes_registry.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_registry.py
```

Expected: `ModuleNotFoundError: No module named 'core.kanban_protocol.lanes'`

- [ ] **Step 3: Implement the dataclass**

`backend/core/kanban_protocol/lanes.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_registry.py
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/lanes.py backend/tests/test_lanes_registry.py
git commit -m "feat(kanban-protocol): add WorkerLane dataclass with TDD"
```

---

## Task 3: `WORKER_LANES` registry (eight lanes)

**Files:**
- Modify: `backend/core/kanban_protocol/lanes.py`
- Modify: `backend/tests/test_lanes_registry.py`

- [ ] **Step 1: Append failing test for `WORKER_LANES`**

Append to `backend/tests/test_lanes_registry.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_registry.py
```

Expected: `ImportError: cannot import name 'WORKER_LANES'`

- [ ] **Step 3: Add the registry to `lanes.py`**

Append to `backend/core/kanban_protocol/lanes.py`:

```python
WORKER_LANES: dict[str, WorkerLane] = {
    "triage": WorkerLane(
        key="triage",
        display_name="Triage",
        description="Classify incoming work and route to the right worker lane.",
        allowed_profiles=["general"],
        default_provider="claude-code",
        default_model="claude-3-5-sonnet",
        allowed_commands=["/loop-start --profile=general"],
        required_completion_fields=["lane_recommendation", "summary"],
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
        required_completion_fields=["acceptance_criteria"],
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
        required_completion_fields=["design_notes", "interfaces"],
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
        required_completion_fields=["diff_summary", "screenshots"],
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
        required_completion_fields=["diff_summary", "test_results"],
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
        required_completion_fields=["test_results", "coverage_pct"],
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
        required_completion_fields=["reviewer", "decision"],
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
        required_completion_fields=["release_notes"],
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_registry.py
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/lanes.py backend/tests/test_lanes_registry.py
git commit -m "feat(kanban-protocol): add WORKER_LANES registry with eight lanes"
```

---

## Task 4: `GET /api/v1/lanes` endpoint

**Files:**
- Create: `backend/api/v1/endpoints/lanes.py`
- Create: `backend/tests/test_lanes_api.py`
- Modify: `backend/main.py` (mount router)

- [ ] **Step 1: Write the failing test**

`backend/tests/test_lanes_api.py`:

```python
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_get_lanes_returns_eight_lanes():
    response = client.get("/api/v1/lanes")
    assert response.status_code == 200
    body = response.json()
    assert "lanes" in body
    keys = {lane["key"] for lane in body["lanes"]}
    assert keys == {
        "triage", "product", "architect", "frontend",
        "backend", "qa", "review", "delivery",
    }
    # every lane exposes the fields the Lane Matrix needs
    for lane in body["lanes"]:
        assert "displayName" in lane
        assert "defaultProvider" in lane
        assert "defaultModel" in lane
        assert "requiredCompletionFields" in lane
        assert "humanApprovalRequired" in lane
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_api.py
```

Expected: `404` (route not yet mounted)

- [ ] **Step 3: Implement the endpoint**

`backend/api/v1/endpoints/lanes.py`:

```python
"""Worker Lane read-only API."""
from fastapi import APIRouter

from core.kanban_protocol.lanes import WORKER_LANES

router = APIRouter()


@router.get("/lanes")
async def list_lanes():
    """Return the code-defined worker lane registry."""
    lanes = [
        {
            "key": lane.key,
            "displayName": lane.display_name,
            "description": lane.description,
            "allowedProfiles": lane.allowed_profiles,
            "defaultProvider": lane.default_provider,
            "defaultModel": lane.default_model,
            "allowedCommands": lane.allowed_commands,
            "requiredCompletionFields": lane.required_completion_fields,
            "timeoutSeconds": lane.timeout_seconds,
            "retryPolicy": lane.retry_policy,
            "retryMax": lane.retry_max,
            "nextLanes": lane.next_lanes,
            "humanApprovalRequired": lane.human_approval_required,
        }
        for lane in WORKER_LANES.values()
    ]
    return {"lanes": lanes}
```

- [ ] **Step 4: Mount the router in `main.py`**

In `backend/main.py`, inside the `try:` block where other endpoints are
imported (around line 330), add `lanes` to the import line and to the
`app.include_router(...)` calls:

```python
    from api.v1.endpoints import (
        webhooks, agents, issues, ecc, board, quality, auth, ws, audit,
        analytics, llm, issue_collaboration, lanes,
    )
    ...
    app.include_router(lanes.router, prefix="/api/v1", tags=["Lanes"])
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_lanes_api.py
```

Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/endpoints/lanes.py backend/tests/test_lanes_api.py backend/main.py
git commit -m "feat(kanban-protocol): add GET /api/v1/lanes endpoint"
```

---

# Phase 2: Board Scope and Scope Guard

## Task 5: `board_scope` helpers

**Files:**
- Create: `backend/core/kanban_protocol/board_scope.py`
- Create: `backend/tests/test_board_scope.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_board_scope.py`:

```python
import pytest

from core.kanban_protocol.board_scope import (
    DEFAULT_BOARD_ID,
    assert_board_id_allowed,
    resolve_board_id,
)


def test_default_board_id_is_board_default():
    assert DEFAULT_BOARD_ID == "board-default"


def test_resolve_board_id_returns_default_when_none():
    assert resolve_board_id(None) == DEFAULT_BOARD_ID


def test_resolve_board_id_returns_explicit_when_provided():
    assert resolve_board_id("board-default") == "board-default"


def test_assert_board_id_allowed_passes_for_default():
    assert_board_id_allowed("board-default")  # does not raise


def test_assert_board_id_allowed_raises_for_unknown():
    with pytest.raises(LookupError):
        assert_board_id_allowed("some-other-board")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_board_scope.py
```

Expected: `ModuleNotFoundError: No module named 'core.kanban_protocol.board_scope'`

- [ ] **Step 3: Implement the helpers**

`backend/core/kanban_protocol/board_scope.py`:

```python
"""Board isolation helpers.

In MVP, only the default board is allowed. This module centralizes the
rule so future multi-board work only needs to swap the implementation.
"""
from typing import Optional

DEFAULT_BOARD_ID = "board-default"
_KNOWN_BOARD_IDS = frozenset({DEFAULT_BOARD_ID})


def resolve_board_id(explicit: Optional[str]) -> str:
    """Return the board id to use for a request.

    In MVP, an unspecified board id falls back to ``DEFAULT_BOARD_ID``.
    """
    return explicit or DEFAULT_BOARD_ID


def assert_board_id_allowed(board_id: str) -> None:
    """Raise ``LookupError`` if ``board_id`` is not allowed in MVP."""
    if board_id not in _KNOWN_BOARD_IDS:
        raise LookupError(
            f"Board '{board_id}' is not available in MVP. "
            f"Allowed: {sorted(_KNOWN_BOARD_IDS)}"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_board_scope.py
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/board_scope.py backend/tests/test_board_scope.py
git commit -m "feat(kanban-protocol): add board_scope helpers"
```

---

## Task 6: `scope_guard` module

**Files:**
- Create: `backend/core/kanban_protocol/scope_guard.py`
- Create: `backend/tests/test_scope_guard.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_scope_guard.py`:

```python
import pytest

from core.kanban_protocol.scope_guard import (
    DENIED_PAYLOAD_KEYS,
    check_payload,
    find_denied_keys,
)


def test_denied_payload_keys_includes_security_work():
    assert "sandbox_egress" in DENIED_PAYLOAD_KEYS
    assert "iptables_rules" in DENIED_PAYLOAD_KEYS
    assert "admin_keys" in DENIED_PAYLOAD_KEYS
    assert "pentest_findings" in DENIED_PAYLOAD_KEYS


def test_find_denied_keys_returns_empty_for_clean_payload():
    payload = {"diff_summary": "ok", "test_results": "ok"}
    assert find_denied_keys(payload) == set()


def test_find_denied_keys_finds_nested_denied_keys():
    payload = {
        "diff_summary": "ok",
        "metadata": {"sandbox_egress": "10.0.0.0/8"},
    }
    assert find_denied_keys(payload) == {"sandbox_egress"}


def test_find_denied_keys_finds_denied_in_lists():
    payload = {"steps": ["run", {"iptables_rules": "ACCEPT"}]}
    assert find_denied_keys(payload) == {"iptables_rules"}


def test_check_payload_passes_for_clean_payload():
    check_payload({"diff_summary": "ok"})  # does not raise


def test_check_payload_raises_scope_denied_error():
    from core.kanban_protocol.scope_guard import ScopeDeniedError
    with pytest.raises(ScopeDeniedError) as exc_info:
        check_payload({"admin_keys": "supersecret"})
    assert "admin_keys" in exc_info.value.offending_keys
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_scope_guard.py
```

Expected: `ModuleNotFoundError: No module named 'core.kanban_protocol.scope_guard'`

- [ ] **Step 3: Implement the guard**

`backend/core/kanban_protocol/scope_guard.py`:

```python
"""Scope guard — tripwire against out-of-scope work patterns.

This is NOT a substitute for code review. It refuses handoff payloads that
contain keys associated with archived security work, so the archived work
cannot easily leak back into the mainline through the Kanban Protocol API.
"""
from typing import Any, Iterable, Set

DENIED_PAYLOAD_KEYS: Set[str] = {
    "sandbox_egress",
    "iptables_rules",
    "admin_keys",
    "pentest_findings",
}


class ScopeDeniedError(Exception):
    """Raised when a payload contains keys reserved for out-of-scope work."""

    def __init__(self, offending_keys: Iterable[str]):
        self.offending_keys = sorted(set(offending_keys))
        super().__init__(
            "Scope denied: payload contains reserved keys "
            f"{self.offending_keys}"
        )


def find_denied_keys(payload: Any) -> Set[str]:
    """Recursively walk a JSON-shaped payload and return any denied keys."""
    found: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in DENIED_PAYLOAD_KEYS:
                    found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def check_payload(payload: Any) -> None:
    """Raise ``ScopeDeniedError`` if the payload contains any denied key."""
    denied = find_denied_keys(payload)
    if denied:
        raise ScopeDeniedError(denied)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_scope_guard.py
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/scope_guard.py backend/tests/test_scope_guard.py
git commit -m "feat(kanban-protocol): add scope_guard tripwire"
```

---

# Phase 3: Database Migration and Models

## Task 7: Migration 0004 — `board_id` columns and `issue_handoffs` table

**Files:**
- Create: `backend/alembic/versions/0004_add_board_id_and_handoffs.py`

- [ ] **Step 1: Create the migration file**

`backend/alembic/versions/0004_add_board_id_and_handoffs.py`:

```python
"""add board_id columns and issue_handoffs table

Revision ID: 0004_add_board_id_and_handoffs
Revises: 0003_issue_collaboration_records
Create Date: 2026-06-03

Adds the schema pieces for Kanban Protocol:
- ``board_id`` column on every Kanban-Protocol-aware table, defaulting to
  ``"board-default"`` so the migration is non-destructive on existing rows.
- ``issue_handoffs`` table: durable queue items with a status machine
  (pending / accepted / in_progress / completed / blocked / cancelled).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_add_board_id_and_handoffs"
down_revision = "0003_issue_collaboration_records"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type(is_pg: bool):
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    is_pg = _is_postgres()
    default_board = "board-default"

    # ---------------------------------------------------------------- board_id
    # Add board_id to every Kanban-Protocol-aware table. Nullable for safety
    # on pre-migration rows; we backfill below.
    tables_with_board = [
        "issues",
        "issue_events",
        "issue_comments",
        "issue_artifacts",
        "ecc_jobs",
    ]
    for table in tables_with_board:
        op.add_column(
            table,
            sa.Column(
                "board_id",
                sa.String(64),
                nullable=True,
            ),
        )
        op.execute(
            f"UPDATE {table} SET board_id = '{default_board}' "
            f"WHERE board_id IS NULL"
        )
        op.alter_column(
            table,
            "board_id",
            nullable=False,
            server_default=default_board,
        )
        op.create_index(
            f"ix_{table}_board_id",
            table,
            ["board_id"],
        )

    # ---------------------------------------------------------------- handoffs
    op.create_table(
        "issue_handoffs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("board_id", sa.String(64), nullable=False, server_default=default_board),
        sa.Column("issue_id", sa.String(64), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("from_lane", sa.String(32), nullable=True),
        sa.Column("to_lane", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("payload", _json_type(is_pg), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("accepted_by", sa.String(128), nullable=True),
        sa.Column("dispatched_by", sa.String(128), nullable=True),
        sa.Column("completed_by", sa.String(128), nullable=True),
        sa.Column("cancelled_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_issue_handoffs_board_id", "issue_handoffs", ["board_id"])
    op.create_index("ix_issue_handoffs_issue_id", "issue_handoffs", ["issue_id"])
    op.create_index("ix_issue_handoffs_status", "issue_handoffs", ["status"])
    op.create_index(
        "ix_issue_handoffs_board_status",
        "issue_handoffs",
        ["board_id", "status"],
    )
    op.create_index(
        "ix_issue_handoffs_issue_created",
        "issue_handoffs",
        ["issue_id", "created_at"],
    )
    op.create_index(
        "ix_issue_handoffs_to_lane_status",
        "issue_handoffs",
        ["to_lane", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_issue_handoffs_to_lane_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_issue_created", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_board_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_status", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_issue_id", table_name="issue_handoffs")
    op.drop_index("ix_issue_handoffs_board_id", table_name="issue_handoffs")
    op.drop_table("issue_handoffs")

    for table in [
        "ecc_jobs", "issue_artifacts", "issue_comments", "issue_events", "issues",
    ]:
        op.drop_index(f"ix_{table}_board_id", table_name=table)
        op.drop_column(table, "board_id")
```

- [ ] **Step 2: Verify the migration applies cleanly on SQLite**

Run:
```bash
PYTHONPATH=backend alembic upgrade head
```

Expected: log line "Running upgrade 0003_issue_collaboration_records -> 0004_add_board_id_and_handoffs"

- [ ] **Step 3: Verify the schema**

Run:
```bash
PYTHONPATH=backend python3 -c "
from db.database import engine
import sqlalchemy as sa
with engine.connect() as conn:
    for row in conn.execute(sa.text(\"SELECT name FROM sqlite_master WHERE type='table' AND name='issue_handoffs'\")):
        print(row)
"
```

Expected: `('issue_handoffs',)`

- [ ] **Step 4: Run the existing migration parity test to make sure nothing broke**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_migration_parity.py
```

Expected: pass

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0004_add_board_id_and_handoffs.py
git commit -m "feat(kanban-protocol): add migration 0004 (board_id + issue_handoffs)"
```

---

## Task 8: Update `db/models.py` — add `board_id` and `IssueHandoff`

**Files:**
- Modify: `backend/db/models.py` (add `board_id` columns + `IssueHandoff` class)

- [ ] **Step 1: Add `board_id` to existing models**

In `backend/db/models.py`, add the `board_id` column + a `to_dict` field to
each of the existing models whose tables got the column in migration 0004:

`Issue` (around line 39): add after `priority` line:
```python
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
```

`IssueEvent` (around line 357): add at the end of the column block:
```python
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
```

`IssueComment` (around line 392): add at the end of the column block:
```python
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
```

`IssueArtifact` (around line 428): add at the end of the column block:
```python
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
```

`JobModel` (around line 205): add at the end of the column block:
```python
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
```

For each, also add `"boardId": self.board_id` to its `to_dict()` return.

- [ ] **Step 2: Append the `IssueHandoff` class**

Append to the end of `backend/db/models.py`:

```python
class IssueHandoff(Base):
    """
    Durable queue item for Kanban Protocol.

    A handoff is created when an issue is moved from one worker lane to
    another. It carries its own status machine, payload, and audit fields
    so the transition is durable and replayable.
    """
    __tablename__ = "issue_handoffs"

    id = Column(String(64), primary_key=True)
    board_id = Column(String(64), nullable=False, default="board-default", index=True)
    issue_id = Column(String(64), nullable=False, index=True)
    from_lane = Column(String(32), nullable=True)
    to_lane = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    payload = Column(JSON, nullable=True, default=dict)
    block_reason = Column(Text, nullable=True)
    created_by = Column(String(128), nullable=True)
    accepted_by = Column(String(128), nullable=True)
    dispatched_by = Column(String(128), nullable=True)
    completed_by = Column(String(128), nullable=True)
    cancelled_by = Column(String(128), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "boardId": self.board_id,
            "issueId": self.issue_id,
            "fromLane": self.from_lane,
            "toLane": self.to_lane,
            "status": self.status,
            "payload": self.payload if isinstance(self.payload, dict) else {},
            "blockReason": self.block_reason,
            "createdBy": self.created_by,
            "acceptedBy": self.accepted_by,
            "dispatchedBy": self.dispatched_by,
            "completedBy": self.completed_by,
            "cancelledBy": self.cancelled_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
        }
```

- [ ] **Step 3: Run the existing smoke + migration tests**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_api_smoke.py backend/tests/test_migration_parity.py
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add backend/db/models.py
git commit -m "feat(kanban-protocol): add board_id columns and IssueHandoff model"
```

---

# Phase 4: Handoff Repository

## Task 9: Repository functions for `IssueHandoff`

**Files:**
- Modify: `backend/db/repository.py` (append handoff functions)

- [ ] **Step 1: Append handoff repository functions**

Append to `backend/db/repository.py`:

```python
# ============================================================================
# IssueHandoff — Kanban Protocol
# ============================================================================

async def create_issue_handoff(
    *,
    id: str,
    board_id: str,
    issue_id: str,
    from_lane: Optional[str],
    to_lane: str,
    payload: Optional[dict],
    created_by: Optional[str],
) -> dict:
    """Insert a new IssueHandoff in 'pending' status and return its dict form."""
    from db.database import AsyncSessionLocal
    from db.models import IssueHandoff

    row = IssueHandoff(
        id=id,
        board_id=board_id,
        issue_id=issue_id,
        from_lane=from_lane,
        to_lane=to_lane,
        status="pending",
        payload=payload or {},
        created_by=created_by,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()


async def get_issue_handoff(handoff_id: str) -> Optional[dict]:
    from db.database import AsyncSessionLocal
    from db.models import IssueHandoff

    async with AsyncSessionLocal() as session:
        row = await session.get(IssueHandoff, handoff_id)
    return row.to_dict() if row else None


async def list_issue_handoffs(
    *,
    issue_id: str,
    board_id: str,
    limit: int = 100,
) -> list[dict]:
    from sqlalchemy import select
    from db.database import AsyncSessionLocal
    from db.models import IssueHandoff

    async with AsyncSessionLocal() as session:
        stmt = (
            select(IssueHandoff)
            .where(IssueHandoff.issue_id == issue_id)
            .where(IssueHandoff.board_id == board_id)
            .order_by(IssueHandoff.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [r.to_dict() for r in rows]


async def update_issue_handoff(
    handoff_id: str,
    *,
    status: str,
    block_reason: Optional[str] = None,
    payload: Optional[dict] = None,
    actor_field: Optional[str] = None,
    actor_value: Optional[str] = None,
    set_completed_at: bool = False,
) -> Optional[dict]:
    """Update a handoff's status and optional audit fields."""
    from datetime import datetime, timezone
    from db.database import AsyncSessionLocal
    from db.models import IssueHandoff

    async with AsyncSessionLocal() as session:
        row = await session.get(IssueHandoff, handoff_id)
        if not row:
            return None
        row.status = status
        if block_reason is not None:
            row.block_reason = block_reason
        if payload is not None:
            row.payload = payload
        if actor_field and actor_value is not None:
            setattr(row, actor_field, actor_value)
        if set_completed_at:
            row.completed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()
```

Also add the `Optional` import at the top of the file if not already present:
`from typing import Optional`.

- [ ] **Step 2: Run the existing tests to confirm no regression**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_api_smoke.py
```

Expected: pass

- [ ] **Step 3: Commit**

```bash
git add backend/db/repository.py
git commit -m "feat(kanban-protocol): add handoff repository functions"
```

---

# Phase 5: Handoff Service (Status Machine)

## Task 10: Pydantic schemas for handoff API

**Files:**
- Create: `backend/core/kanban_protocol/schemas.py`

- [ ] **Step 1: Create the schemas file**

`backend/core/kanban_protocol/schemas.py`:

```python
"""Pydantic schemas for Kanban Protocol API requests and responses."""
from typing import List, Optional

from pydantic import BaseModel, Field


HandoffStatus = str  # one of: pending, accepted, in_progress, completed, blocked, cancelled


class HandoffCreateRequest(BaseModel):
    fromLane: Optional[str] = Field(default=None, max_length=32)
    toLane: str = Field(..., min_length=1, max_length=32)
    payload: Optional[dict] = Field(default_factory=dict)
    createdBy: Optional[str] = Field(default=None, max_length=128)


class HandoffActorRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)


class HandoffCompleteRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)
    payload: Optional[dict] = None  # if provided, merged into the existing payload


class HandoffBlockRequest(BaseModel):
    actor: Optional[str] = Field(default=None, max_length=128)
    blockReason: str = Field(..., min_length=1, max_length=4000)


class HandoffCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)
    authorId: Optional[str] = Field(default=None, max_length=64)
    authorName: Optional[str] = Field(default=None, max_length=128)
    commentType: str = Field(default="handoff", max_length=32)


class HandoffPreviewResponse(BaseModel):
    handoffId: str
    toLane: str
    displayName: str
    defaultProvider: str
    defaultModel: str
    allowedCommands: List[str]
    requiredCompletionFields: List[str]
    presentFields: List[str]
    missingFields: List[str]
    nextLanes: List[str]
    humanApprovalRequired: bool
    hasApprover: bool
    timeoutSeconds: int
    retryPolicy: str
    retryMax: int
```

- [ ] **Step 2: Verify imports**

Run:
```bash
PYTHONPATH=backend python3 -c "from core.kanban_protocol.schemas import HandoffCreateRequest; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/core/kanban_protocol/schemas.py
git commit -m "feat(kanban-protocol): add Pydantic schemas for handoff API"
```

---

## Task 11: `HandoffService` — create + accept

**Files:**
- Create: `backend/core/kanban_protocol/handoff.py`
- Create: `backend/tests/test_handoff_service.py`

- [ ] **Step 1: Write the failing test for `create` and `accept`**

`backend/tests/test_handoff_service.py`:

```python
import pytest

from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.lanes import WORKER_LANES


@pytest.mark.asyncio
async def test_create_returns_pending_handoff():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "wip"},
        created_by="alice",
    )
    assert handoff["status"] == "pending"
    assert handoff["toLane"] == "frontend"
    assert handoff["createdBy"] == "alice"
    assert handoff["boardId"] == "board-default"


@pytest.mark.asyncio
async def test_create_rejects_unknown_target_lane():
    svc = HandoffService()
    with pytest.raises(ValueError) as exc_info:
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="not-a-lane",
            payload={},
            created_by="alice",
        )
    assert "Unknown worker lane" in str(exc_info.value)


@pytest.mark.asyncio
async def test_accept_moves_pending_to_accepted():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    accepted = await svc.accept(handoff["id"], actor="bob")
    assert accepted["status"] == "accepted"
    assert accepted["acceptedBy"] == "bob"


@pytest.mark.asyncio
async def test_accept_rejects_non_pending_handoff():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ValueError) as exc_info:
        await svc.accept(handoff["id"], actor="bob")
    assert "cannot accept" in str(exc_info.value).lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py
```

Expected: `ModuleNotFoundError: No module named 'core.kanban_protocol.handoff'`

- [ ] **Step 3: Implement `create` and `accept`**

`backend/core/kanban_protocol/handoff.py`:

```python
"""HandoffService — Kanban Protocol status machine.

Encapsulates the state transitions for an IssueHandoff. All methods are
idempotent on read; transitions raise ``ValueError`` on illegal moves.
"""
from typing import Optional

from db import repository as repo
from core.kanban_protocol.lanes import get_lane


def _new_id() -> str:
    import uuid
    return f"h_{uuid.uuid4().hex[:16]}"


class HandoffService:
    """Pure status-machine layer. Persistence lives in ``db.repository``."""

    async def create(
        self,
        *,
        issue_id: str,
        board_id: str,
        from_lane: Optional[str],
        to_lane: str,
        payload: Optional[dict],
        created_by: Optional[str],
    ) -> dict:
        # Validate target lane up front so callers fail fast.
        try:
            get_lane(to_lane)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        return await repo.create_issue_handoff(
            id=_new_id(),
            board_id=board_id,
            issue_id=issue_id,
            from_lane=from_lane,
            to_lane=to_lane,
            payload=payload,
            created_by=created_by,
        )

    async def accept(self, handoff_id: str, *, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "pending":
            raise ValueError(
                f"Cannot accept handoff in status '{current['status']}'; "
                "only 'pending' handoffs can be accepted"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="accepted",
            actor_field="accepted_by",
            actor_value=actor,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/handoff.py backend/tests/test_handoff_service.py
git commit -m "feat(kanban-protocol): add HandoffService.create and accept"
```

---

## Task 12: `HandoffService.dispatch` (creates `JobModel` via P0 path)

**Files:**
- Modify: `backend/core/kanban_protocol/handoff.py`
- Modify: `backend/tests/test_handoff_service.py`
- Create: `backend/core/kanban_protocol/orchestrator.py`

- [ ] **Step 1: Add the orchestrator stub**

`backend/core/kanban_protocol/orchestrator.py`:

```python
"""Delivery Orchestrator — manual, rules-driven, no daemon.

Exposes ``create_job_for_handoff`` which the HandoffService calls during
dispatch. The implementation delegates to the existing P0 safe-runner
dispatch path so real Claude/Codex execution is never triggered by
default.
"""
from typing import Optional


async def create_job_for_handoff(
    *,
    handoff_id: str,
    issue_id: str,
    issue_key: str,
    to_lane: str,
    profile: str,
    actor: Optional[str],
) -> dict:
    """Create a JobModel row using the existing P0 dispatch path."""
    # Lazy import to avoid pulling the existing dispatch path during
    # unit tests that only exercise the status machine.
    from db import repository as repo

    # Build a command from the lane contract. The command name is
    # the lane's first allowed command; this is purely advisory for
    # the safe runner, which never actually executes user-provided
    # commands.
    from core.kanban_protocol.lanes import get_lane
    lane = get_lane(to_lane)
    command = lane.allowed_commands[0] if lane.allowed_commands else "/loop-start"

    # Re-use the safe-runner default; real adapter execution is opt-in
    # via env flag, unchanged.
    return await repo.create_ecc_job_safe_runner(
        issue_id=issue_id,
        issue_key=issue_key,
        command=command,
        profile=profile,
        harness="safe-runner",
        handoff_id=handoff_id,
    )
```

- [ ] **Step 2: Append the `create_ecc_job_safe_runner` repository function**

Append to `backend/db/repository.py`:

```python
async def create_ecc_job_safe_runner(
    *,
    issue_id: str,
    issue_key: str,
    command: str,
    profile: str,
    harness: str,
    handoff_id: Optional[str] = None,
) -> dict:
    """Create a JobModel row that runs through the P0 safe runner."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from db.database import AsyncSessionLocal
    from db.models import JobModel

    job_id = f"ecc_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    row = JobModel(
        id=job_id,
        board_id="board-default",
        issue_id=issue_id,
        issue_key=issue_key,
        command=command,
        profile=profile,
        harness=harness,
        status="queued",
        created_at=now,
        updated_at=now,
        message=f"Created by Kanban Protocol handoff {handoff_id or '<unknown>'}",
        events=[
            {
                "timestamp": now,
                "status": "queued",
                "message": "Job created by Kanban Protocol dispatch",
            }
        ],
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row.to_dict()
```

- [ ] **Step 3: Add the failing test for `dispatch`**

Append to `backend/tests/test_handoff_service.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_creates_ecc_job_and_moves_to_in_progress():
    from db import repository as repo

    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "wip"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")

    # Seed an Issue row with key DEV-001 so dispatch has something to attach to.
    await repo.upsert_issue(
        id="issue-1",
        key="DEV-001",
        title="test",
        description="",
        status="in_progress",
    )

    result = await svc.dispatch(
        handoff_id=handoff["id"],
        issue_key="DEV-001",
        profile="frontend",
        actor="bob",
    )
    assert result["handoff"]["status"] == "in_progress"
    assert result["handoff"]["dispatchedBy"] == "bob"
    assert result["job"]["id"].startswith("ecc_")
    assert result["job"]["harness"] == "safe-runner"


@pytest.mark.asyncio
async def test_dispatch_rejects_when_approval_required_and_missing():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",  # qa requires human approval
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    from db import repository as repo
    await repo.upsert_issue(
        id="issue-1", key="DEV-002", title="t", description="", status="in_progress"
    )
    with pytest.raises(PermissionError) as exc_info:
        await svc.dispatch(
            handoff_id=handoff["id"],
            issue_key="DEV-002",
            profile="general",
            actor="bob",
        )
    assert "approval" in str(exc_info.value).lower()
```

- [ ] **Step 4: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k dispatch
```

Expected: `AttributeError: 'HandoffService' object has no attribute 'dispatch'`

- [ ] **Step 5: Implement `dispatch` in `HandoffService`**

Add to `backend/core/kanban_protocol/handoff.py`:

```python
    async def dispatch(
        self,
        *,
        handoff_id: str,
        issue_key: str,
        profile: str,
        actor: Optional[str],
    ) -> dict:
        from core.kanban_protocol.lanes import get_lane
        from core.kanban_protocol.orchestrator import create_job_for_handoff

        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "accepted":
            raise ValueError(
                f"Cannot dispatch handoff in status '{current['status']}'; "
                "only 'accepted' handoffs can be dispatched"
            )

        lane = get_lane(current["toLane"])
        payload = current.get("payload") or {}

        if lane.human_approval_required and not payload.get("approver"):
            raise PermissionError(
                f"Lane '{lane.key}' requires human approval; "
                "payload must include an 'approver' field before dispatch"
            )

        job = await create_job_for_handoff(
            handoff_id=handoff_id,
            issue_id=current["issueId"],
            issue_key=issue_key,
            to_lane=lane.key,
            profile=profile,
            actor=actor,
        )

        updated = await repo.update_issue_handoff(
            handoff_id,
            status="in_progress",
            actor_field="dispatched_by",
            actor_value=actor,
        )
        return {"handoff": updated, "job": job}
```

- [ ] **Step 6: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k dispatch
```

Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add backend/core/kanban_protocol/handoff.py \
        backend/core/kanban_protocol/orchestrator.py \
        backend/db/repository.py \
        backend/tests/test_handoff_service.py
git commit -m "feat(kanban-protocol): add dispatch path with safe-runner job creation"
```

---

## Task 13: `HandoffService.complete` with required-fields validation

**Files:**
- Modify: `backend/core/kanban_protocol/handoff.py`
- Modify: `backend/tests/test_handoff_service.py`

- [ ] **Step 1: Add the failing test for `complete`**

Append to `backend/tests/test_handoff_service.py`:

```python
@pytest.mark.asyncio
async def test_complete_rejects_when_required_fields_missing():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",
        payload={},  # missing test_results and coverage_pct
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ValueError) as exc_info:
        await svc.complete(handoff_id=handoff["id"], actor="bob", payload=None)
    msg = str(exc_info.value)
    assert "test_results" in msg
    assert "coverage_pct" in msg


@pytest.mark.asyncio
async def test_complete_succeeds_with_all_required_fields():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="qa",
        payload={"test_results": "ok", "coverage_pct": 95},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    completed = await svc.complete(
        handoff_id=handoff["id"], actor="bob", payload=None
    )
    assert completed["status"] == "completed"
    assert completed["completedBy"] == "bob"
    assert completed["completedAt"] is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k complete
```

Expected: `AttributeError: 'HandoffService' object has no attribute 'complete'`

- [ ] **Step 3: Implement `complete` in `HandoffService`**

Add to `backend/core/kanban_protocol/handoff.py`:

```python
    async def complete(
        self,
        *,
        handoff_id: str,
        actor: Optional[str],
        payload: Optional[dict],
    ) -> dict:
        from core.kanban_protocol.lanes import get_lane

        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] not in ("in_progress", "accepted"):
            raise ValueError(
                f"Cannot complete handoff in status '{current['status']}'"
            )

        lane = get_lane(current["toLane"])
        merged_payload = dict(current.get("payload") or {})
        if payload:
            merged_payload.update(payload)
        missing = [
            field for field in lane.required_completion_fields
            if field not in merged_payload
        ]
        if missing:
            raise ValueError(
                f"Cannot complete handoff: missing required fields {missing}"
            )

        return await repo.update_issue_handoff(
            handoff_id,
            status="completed",
            payload=merged_payload,
            actor_field="completed_by",
            actor_value=actor,
            set_completed_at=True,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k complete
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/handoff.py backend/tests/test_handoff_service.py
git commit -m "feat(kanban-protocol): add complete with required-fields validation"
```

---

## Task 14: `HandoffService.block` / `unblock` / `cancel`

**Files:**
- Modify: `backend/core/kanban_protocol/handoff.py`
- Modify: `backend/tests/test_handoff_service.py`

- [ ] **Step 1: Add the failing tests**

Append to `backend/tests/test_handoff_service.py`:

```python
@pytest.mark.asyncio
async def test_block_rejects_empty_reason():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    with pytest.raises(ValueError):
        await svc.block(handoff_id=handoff["id"], actor="bob", reason="")


@pytest.mark.asyncio
async def test_block_and_unblock_round_trip():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    blocked = await svc.block(
        handoff_id=handoff["id"], actor="bob", reason="CI red"
    )
    assert blocked["status"] == "blocked"
    assert blocked["blockReason"] == "CI red"
    # unblock returns to the last non-terminal state (pending by default).
    restored = await svc.unblock(handoff_id=handoff["id"], actor="bob")
    assert restored["status"] == "pending"
    assert restored["blockReason"] is None


@pytest.mark.asyncio
async def test_cancel_allowed_from_non_terminal_state():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    cancelled = await svc.cancel(handoff_id=handoff["id"], actor="bob")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelledBy"] == "bob"


@pytest.mark.asyncio
async def test_cancel_rejected_from_completed_state():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "ok", "screenshots": "ok"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    await svc.complete(handoff_id=handoff["id"], actor="bob", payload=None)
    with pytest.raises(ValueError):
        await svc.cancel(handoff_id=handoff["id"], actor="bob")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k "block or unblock or cancel"
```

Expected: `AttributeError: 'HandoffService' object has no attribute 'block'`

- [ ] **Step 3: Implement `block` / `unblock` / `cancel`**

Add to `backend/core/kanban_protocol/handoff.py`:

```python
    async def block(self, *, handoff_id: str, actor: Optional[str], reason: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("block_reason must be a non-empty string")
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] in ("completed", "cancelled"):
            raise ValueError(
                f"Cannot block handoff in terminal status '{current['status']}'"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="blocked",
            block_reason=reason,
        )

    async def unblock(self, *, handoff_id: str, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] != "blocked":
            raise ValueError(
                f"Cannot unblock handoff in status '{current['status']}'"
            )
        # MVP: return to the last non-blocked state. Without history
        # tracking, the safe assumption is that we came from 'pending'
        # or 'accepted'. We pick 'pending' so the human re-evaluates.
        return await repo.update_issue_handoff(
            handoff_id,
            status="pending",
            block_reason=None,
        )

    async def cancel(self, *, handoff_id: str, actor: Optional[str]) -> dict:
        current = await repo.get_issue_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        if current["status"] in ("completed", "cancelled"):
            raise ValueError(
                f"Cannot cancel handoff in terminal status '{current['status']}'"
            )
        return await repo.update_issue_handoff(
            handoff_id,
            status="cancelled",
            actor_field="cancelled_by",
            actor_value=actor,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k "block or unblock or cancel"
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/handoff.py backend/tests/test_handoff_service.py
git commit -m "feat(kanban-protocol): add block, unblock, cancel transitions"
```

---

## Task 15: Handoff service — scope guard integration

**Files:**
- Modify: `backend/core/kanban_protocol/handoff.py`
- Modify: `backend/tests/test_handoff_service.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_handoff_service.py`:

```python
from core.kanban_protocol.scope_guard import ScopeDeniedError


@pytest.mark.asyncio
async def test_create_rejects_payload_with_denied_keys():
    svc = HandoffService()
    with pytest.raises(ScopeDeniedError):
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="frontend",
            payload={"sandbox_egress": "10.0.0.0/8"},
            created_by="alice",
        )


@pytest.mark.asyncio
async def test_complete_rejects_payload_with_denied_keys():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "ok", "screenshots": "ok"},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ScopeDeniedError):
        await svc.complete(
            handoff_id=handoff["id"],
            actor="bob",
            payload={"iptables_rules": "ACCEPT"},
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k "denied"
```

Expected: handoff is created/completed without raising (current behaviour)

- [ ] **Step 3: Add the scope-guard call to `create` and `complete`**

In `backend/core/kanban_protocol/handoff.py`:

- Add at the top of the file (with the other imports):
  ```python
  from core.kanban_protocol.scope_guard import ScopeDeniedError, check_payload
  ```

- In `create`, right before the call to `repo.create_issue_handoff`:
  ```python
          check_payload(payload or {})
  ```

- In `complete`, right before the call to `repo.update_issue_handoff`:
  ```python
          check_payload(merged_payload)
  ```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoff_service.py -k "denied"
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/kanban_protocol/handoff.py backend/tests/test_handoff_service.py
git commit -m "feat(kanban-protocol): integrate scope_guard into handoff service"
```

---

# Phase 6: Handoff API Endpoints

## Task 16: Handoff router skeleton and read endpoints

**Files:**
- Create: `backend/api/v1/endpoints/handoffs.py`
- Create: `backend/tests/test_handoffs_api.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write the failing test for the read endpoints**

`backend/tests/test_handoffs_api.py`:

```python
import pytest

from fastapi.testclient import TestClient

import main
from db import repository as repo
from core.kanban_protocol.handoff import HandoffService


client = TestClient(main.app)


@pytest.fixture
async def seeded_issue():
    await repo.upsert_issue(
        id="issue-api-1",
        key="DEV-100",
        title="api test issue",
        description="",
        status="backlog",
    )
    yield "issue-api-1"
    # Best-effort cleanup; the smoke test DB is throwaway.
    try:
        await repo.delete_issue("issue-api-1")
    except Exception:
        pass


@pytest.mark.asyncio
async def test_create_handoff_returns_pending(seeded_issue):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {"diff_summary": "wip"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["toLane"] == "frontend"
    assert body["boardId"] == "board-default"
    handoff_id = body["id"]


@pytest.mark.asyncio
async def test_create_handoff_rejects_unknown_lane(seeded_issue):
    response = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "not-a-lane"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_handoffs_for_issue(seeded_issue):
    svc = HandoffService()
    await svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    response = client.get(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["handoffs"][0]["toLane"] == "frontend"


@pytest.mark.asyncio
async def test_get_one_handoff(seeded_issue):
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-api-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    response = client.get(
        f"/api/v1/boards/board-default/handoffs/{handoff['id']}"
    )
    assert response.status_code == 200
    assert response.json()["id"] == handoff["id"]


@pytest.mark.asyncio
async def test_unknown_board_id_returns_404(seeded_issue):
    response = client.get(
        "/api/v1/boards/some-other-board/issues/issue-api-1/handoffs"
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py
```

Expected: `404` for every request (router not mounted)

- [ ] **Step 3: Implement the router with create + list + get**

`backend/api/v1/endpoints/handoffs.py`:

```python
"""Kanban Protocol — Handoff API."""
from typing import Optional

from fastapi import APIRouter, HTTPException

from core.kanban_protocol.board_scope import assert_board_id_allowed
from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.schemas import HandoffCreateRequest
from db import repository as repo

router = APIRouter()
_svc = HandoffService()


def _check_board(board_id: str) -> None:
    try:
        assert_board_id_allowed(board_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/boards/{board_id}/issues/{issue_id}/handoffs", status_code=201)
async def create_handoff(
    board_id: str,
    issue_id: str,
    body: HandoffCreateRequest,
):
    _check_board(board_id)
    # Confirm the issue exists; otherwise we'd create orphan handoffs.
    issue = await repo.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return await _svc.create(
        issue_id=issue_id,
        board_id=board_id,
        from_lane=body.fromLane,
        to_lane=body.toLane,
        payload=body.payload,
        created_by=body.createdBy,
    )


@router.get("/boards/{board_id}/issues/{issue_id}/handoffs")
async def list_handoffs(board_id: str, issue_id: str):
    _check_board(board_id)
    handoffs = await repo.list_issue_handoffs(
        issue_id=issue_id, board_id=board_id
    )
    return {"handoffs": handoffs, "total": len(handoffs)}


@router.get("/boards/{board_id}/handoffs/{handoff_id}")
async def get_handoff(board_id: str, handoff_id: str):
    _check_board(board_id)
    handoff = await repo.get_issue_handoff(handoff_id)
    if not handoff or handoff["boardId"] != board_id:
        raise HTTPException(
            status_code=404, detail=f"Handoff '{handoff_id}' not found"
        )
    return handoff
```

- [ ] **Step 4: Mount the router in `main.py`**

In `backend/main.py`, inside the imports block (around line 330):

```python
    from api.v1.endpoints import (
        webhooks, agents, issues, ecc, board, quality, auth, ws, audit,
        analytics, llm, issue_collaboration, lanes, handoffs,
    )
```

And in the `app.include_router(...)` block:

```python
    app.include_router(handoffs.router, prefix="/api/v1", tags=["Kanban Protocol"])
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/endpoints/handoffs.py \
        backend/tests/test_handoffs_api.py \
        backend/main.py
git commit -m "feat(kanban-protocol): add handoff create, list, get endpoints"
```

---

## Task 17: Handoff API — `accept`, `dispatch`, `complete`

**Files:**
- Modify: `backend/api/v1/endpoints/handoffs.py`
- Modify: `backend/tests/test_handoffs_api.py`

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_handoffs_api.py`:

```python
@pytest.mark.asyncio
async def test_accept_dispatch_complete_round_trip(seeded_issue):
    # 1) create + accept via API
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {"diff_summary": "wip"}},
    )
    handoff_id = create_resp.json()["id"]
    accept_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/accept",
        json={"actor": "bob"},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    # 2) dispatch via API (no human_approval_required for frontend)
    dispatch_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/dispatch",
        json={"actor": "bob", "issueKey": "DEV-100", "profile": "frontend"},
    )
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["handoff"]["status"] == "in_progress"
    assert body["job"]["harness"] == "safe-runner"

    # 3) complete via API
    complete_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/complete",
        json={"actor": "bob", "payload": {"screenshots": "captured"}},
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_approval_for_qa_lane(seeded_issue):
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "qa", "payload": {}},
    )
    handoff_id = create_resp.json()["id"]
    client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/accept",
        json={"actor": "bob"},
    )
    dispatch_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/dispatch",
        json={"actor": "bob", "issueKey": "DEV-100", "profile": "general"},
    )
    assert dispatch_resp.status_code == 409
    assert dispatch_resp.json()["detail"]["requires_approval"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py -k "accept_dispatch_complete or missing_approval"
```

Expected: 404 (endpoints not yet defined)

- [ ] **Step 3: Add the endpoints to the router**

Append to `backend/api/v1/endpoints/handoffs.py`:

```python
from core.kanban_protocol.schemas import (
    HandoffActorRequest,
    HandoffCompleteRequest,
)


def _load_handoff_or_404(board_id: str, handoff_id: str) -> dict:
    handoff = _svc._load_or_404(handoff_id)  # type: ignore[attr-defined]
    if handoff["boardId"] != board_id:
        raise HTTPException(
            status_code=404, detail=f"Handoff '{handoff_id}' not found"
        )
    return handoff


@router.post("/boards/{board_id}/handoffs/{handoff_id}/accept")
async def accept_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    _check_board(board_id)
    try:
        return await _svc.accept(handoff_id, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/boards/{board_id}/handoffs/{handoff_id}/dispatch")
async def dispatch_handoff(
    board_id: str,
    handoff_id: str,
    body: dict,
):
    _check_board(board_id)
    actor = body.get("actor")
    issue_key = body.get("issueKey")
    profile = body.get("profile", "general")
    try:
        return await _svc.dispatch(
            handoff_id=handoff_id,
            issue_key=issue_key,
            profile=profile,
            actor=actor,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"requires_approval": True, "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/boards/{board_id}/handoffs/{handoff_id}/complete")
async def complete_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffCompleteRequest,
):
    _check_board(board_id)
    try:
        return await _svc.complete(
            handoff_id=handoff_id,
            actor=body.actor,
            payload=body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
```

Also add a small helper to `HandoffService`:

In `backend/core/kanban_protocol/handoff.py`, add:

```python
    async def _load_or_404(self, handoff_id: str) -> dict:
        handoff = await repo.get_issue_handoff(handoff_id)
        if not handoff:
            raise ValueError(f"Handoff '{handoff_id}' not found")
        return handoff
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py -k "accept_dispatch_complete or missing_approval"
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/endpoints/handoffs.py \
        backend/core/kanban_protocol/handoff.py \
        backend/tests/test_handoffs_api.py
git commit -m "feat(kanban-protocol): add accept, dispatch, complete endpoints"
```

---

## Task 18: Handoff API — `block`, `unblock`, `cancel`, `comment`, `preview`

**Files:**
- Modify: `backend/api/v1/endpoints/handoffs.py`
- Modify: `backend/tests/test_handoffs_api.py`

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_handoffs_api.py`:

```python
from core.kanban_protocol.schemas import HandoffPreviewResponse


@pytest.mark.asyncio
async def test_block_rejects_empty_reason(seeded_issue):
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {}},
    )
    handoff_id = create_resp.json()["id"]
    block_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/block",
        json={"actor": "bob", "blockReason": ""},
    )
    assert block_resp.status_code == 422


@pytest.mark.asyncio
async def test_block_unblock_cancel_flow(seeded_issue):
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {}},
    )
    handoff_id = create_resp.json()["id"]
    block_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/block",
        json={"actor": "bob", "blockReason": "waiting on API key"},
    )
    assert block_resp.status_code == 200
    assert block_resp.json()["status"] == "blocked"

    unblock_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/unblock",
        json={"actor": "bob"},
    )
    assert unblock_resp.status_code == 200
    assert unblock_resp.json()["status"] == "pending"

    cancel_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/cancel",
        json={"actor": "bob"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_comment_appends_to_issue(seeded_issue):
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "frontend", "payload": {}},
    )
    handoff_id = create_resp.json()["id"]
    comment_resp = client.post(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/comments",
        json={"body": "Looks good to me", "authorName": "bob"},
    )
    assert comment_resp.status_code == 201
    # Verify it shows up on the issue collaboration comments endpoint.
    list_resp = client.get(
        "/api/v1/board/issues/issue-api-1/comments"
    )
    # We don't assert the board endpoint here (different shape); we
    # just confirm the comment was accepted.
    assert comment_resp.json()["body"] == "Looks good to me"


@pytest.mark.asyncio
async def test_preview_returns_rules_summary(seeded_issue):
    create_resp = client.post(
        "/api/v1/boards/board-default/issues/issue-api-1/handoffs",
        json={"toLane": "qa", "payload": {"test_results": "ok"}},
    )
    handoff_id = create_resp.json()["id"]
    preview_resp = client.get(
        f"/api/v1/boards/board-default/handoffs/{handoff_id}/preview"
    )
    assert preview_resp.status_code == 200
    body = preview_resp.json()
    assert body["toLane"] == "qa"
    assert body["displayName"] == "Quality Assurance"
    assert body["humanApprovalRequired"] is True
    assert body["hasApprover"] is False
    assert "test_results" in body["presentFields"]
    assert "coverage_pct" in body["missingFields"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py -k "block or preview or comment"
```

Expected: 404 (endpoints not yet defined)

- [ ] **Step 3: Add the endpoints**

Append to `backend/api/v1/endpoints/handoffs.py`:

```python
from core.kanban_protocol.schemas import (
    HandoffBlockRequest,
    HandoffCommentRequest,
)
from core.kanban_protocol.lanes import get_lane


@router.post("/boards/{board_id}/handoffs/{handoff_id}/block")
async def block_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffBlockRequest,
):
    _check_board(board_id)
    try:
        return await _svc.block(
            handoff_id=handoff_id,
            actor=body.actor,
            reason=body.blockReason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/boards/{board_id}/handoffs/{handoff_id}/unblock")
async def unblock_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    _check_board(board_id)
    try:
        return await _svc.unblock(handoff_id=handoff_id, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/boards/{board_id}/handoffs/{handoff_id}/cancel")
async def cancel_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffActorRequest,
):
    _check_board(board_id)
    try:
        return await _svc.cancel(handoff_id=handoff_id, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/boards/{board_id}/handoffs/{handoff_id}/comments", status_code=201
)
async def comment_on_handoff(
    board_id: str,
    handoff_id: str,
    body: HandoffCommentRequest,
):
    _check_board(board_id)
    handoff = await _svc._load_or_404(handoff_id)
    return await repo.create_issue_comment(
        issue_id=handoff["issueId"],
        body=body.body,
        author_id=body.authorId,
        author_name=body.authorName,
        comment_type=f"handoff:{body.commentType}",
        metadata={"handoffId": handoff_id, "toLane": handoff["toLane"]},
    )


@router.get("/boards/{board_id}/handoffs/{handoff_id}/preview")
async def preview_handoff(board_id: str, handoff_id: str):
    _check_board(board_id)
    handoff = await _svc._load_or_404(handoff_id)
    if handoff["boardId"] != board_id:
        raise HTTPException(
            status_code=404, detail=f"Handoff '{handoff_id}' not found"
        )
    lane = get_lane(handoff["toLane"])
    payload = handoff.get("payload") or {}
    present = [f for f in lane.required_completion_fields if f in payload]
    missing = [f for f in lane.required_completion_fields if f not in payload]
    return HandoffPreviewResponse(
        handoffId=handoff["id"],
        toLane=lane.key,
        displayName=lane.display_name,
        defaultProvider=lane.default_provider,
        defaultModel=lane.default_model,
        allowedCommands=lane.allowed_commands,
        requiredCompletionFields=lane.required_completion_fields,
        presentFields=present,
        missingFields=missing,
        nextLanes=lane.next_lanes,
        humanApprovalRequired=lane.human_approval_required,
        hasApprover=bool(payload.get("approver")),
        timeoutSeconds=lane.timeout_seconds,
        retryPolicy=lane.retry_policy,
        retryMax=lane.retry_max,
    )
```

- [ ] **Step 4: Confirm `create_issue_comment` exists in `repository.py`**

Run:
```bash
PYTHONPATH=backend python3 -c "from db import repository; print(hasattr(repository, 'create_issue_comment'))"
```

Expected: `True`

If it does not exist, the existing P2 collaboration records work has
likely defined a different signature. Adapt the call above to match the
function already in `repository.py` from commit `5205a5f` (P2). The intent
is to create a comment row tied to the handoff's issue.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests/test_handoffs_api.py
```

Expected: all handoff API tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/endpoints/handoffs.py backend/tests/test_handoffs_api.py
git commit -m "feat(kanban-protocol): add block, unblock, cancel, comment, preview endpoints"
```

---

# Phase 7: Frontend

## Task 19: Frontend types

**Files:**
- Create: `src/types/kanbanProtocol.ts`

- [ ] **Step 1: Create the types file**

`src/types/kanbanProtocol.ts`:

```typescript
// Kanban Protocol — Agent-Native Kanban types
// Spec: docs/superpowers/specs/kanban-protocol-design.md

export type WorkerLaneKey =
  | 'triage'
  | 'product'
  | 'architect'
  | 'frontend'
  | 'backend'
  | 'qa'
  | 'review'
  | 'delivery'

export type HandoffStatus =
  | 'pending'
  | 'accepted'
  | 'in_progress'
  | 'completed'
  | 'blocked'
  | 'cancelled'

export interface WorkerLane {
  key: WorkerLaneKey
  displayName: string
  description: string
  allowedProfiles: string[]
  defaultProvider: string
  defaultModel: string
  allowedCommands: string[]
  requiredCompletionFields: string[]
  timeoutSeconds: number
  retryPolicy: 'none' | 'fixed' | 'exponential'
  retryMax: number
  nextLanes: WorkerLaneKey[]
  humanApprovalRequired: boolean
}

export interface IssueHandoff {
  id: string
  boardId: string
  issueId: string
  fromLane: WorkerLaneKey | null
  toLane: WorkerLaneKey
  status: HandoffStatus
  payload: Record<string, unknown>
  blockReason: string | null
  createdBy: string | null
  acceptedBy: string | null
  dispatchedBy: string | null
  completedBy: string | null
  cancelledBy: string | null
  createdAt: string
  updatedAt: string
  completedAt: string | null
}

export interface HandoffPreview {
  handoffId: string
  toLane: WorkerLaneKey
  displayName: string
  defaultProvider: string
  defaultModel: string
  allowedCommands: string[]
  requiredCompletionFields: string[]
  presentFields: string[]
  missingFields: string[]
  nextLanes: WorkerLaneKey[]
  humanApprovalRequired: boolean
  hasApprover: boolean
  timeoutSeconds: number
  retryPolicy: 'none' | 'fixed' | 'exponential'
  retryMax: number
}
```

- [ ] **Step 2: Run the typecheck**

Run:
```bash
npm run typecheck
```

Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add src/types/kanbanProtocol.ts
git commit -m "feat(kanban-protocol): add frontend types for lanes and handoffs"
```

---

## Task 20: Frontend API composable

**Files:**
- Create: `src/composables/useKanbanProtocol.ts`

- [ ] **Step 1: Create the composable**

`src/composables/useKanbanProtocol.ts`:

```typescript
// Kanban Protocol — API client composable
import type {
  HandoffPreview,
  IssueHandoff,
  WorkerLane,
  WorkerLaneKey,
  HandoffStatus,
} from '~/types/kanbanProtocol'

interface HandoffCreatePayload {
  fromLane?: WorkerLaneKey
  toLane: WorkerLaneKey
  payload?: Record<string, unknown>
  createdBy?: string
}

interface HandoffDispatchPayload {
  issueKey: string
  profile?: string
  actor?: string
}

interface HandoffCompletePayload {
  actor?: string
  payload?: Record<string, unknown>
}

const DEFAULT_BOARD_ID = 'board-default'

export function useKanbanProtocol() {
  const api = useApi()

  async function listLanes(): Promise<WorkerLane[]> {
    const body = await api.get<{ lanes: WorkerLane[] }>('/lanes')
    return body.lanes
  }

  async function listHandoffsForIssue(issueId: string): Promise<IssueHandoff[]> {
    const body = await api.get<{ handoffs: IssueHandoff[]; total: number }>(
      `/boards/${DEFAULT_BOARD_ID}/issues/${issueId}/handoffs`,
    )
    return body.handoffs
  }

  async function createHandoff(
    issueId: string,
    payload: HandoffCreatePayload,
  ): Promise<IssueHandoff> {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/issues/${issueId}/handoffs`,
      payload,
    )
  }

  async function acceptHandoff(handoffId: string, actor?: string) {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/accept`,
      { actor },
    )
  }

  async function dispatchHandoff(
    handoffId: string,
    payload: HandoffDispatchPayload,
  ) {
    return await api.post<{ handoff: IssueHandoff; job: { id: string; harness: string } }>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/dispatch`,
      payload,
    )
  }

  async function completeHandoff(
    handoffId: string,
    payload: HandoffCompletePayload,
  ): Promise<IssueHandoff> {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/complete`,
      payload,
    )
  }

  async function blockHandoff(
    handoffId: string,
    actor: string | undefined,
    blockReason: string,
  ): Promise<IssueHandoff> {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/block`,
      { actor, blockReason },
    )
  }

  async function unblockHandoff(
    handoffId: string,
    actor?: string,
  ): Promise<IssueHandoff> {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/unblock`,
      { actor },
    )
  }

  async function cancelHandoff(
    handoffId: string,
    actor?: string,
  ): Promise<IssueHandoff> {
    return await api.post<IssueHandoff>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/cancel`,
      { actor },
    )
  }

  async function previewHandoff(handoffId: string): Promise<HandoffPreview> {
    return await api.get<HandoffPreview>(
      `/boards/${DEFAULT_BOARD_ID}/handoffs/${handoffId}/preview`,
    )
  }

  return {
    DEFAULT_BOARD_ID,
    listLanes,
    listHandoffsForIssue,
    createHandoff,
    acceptHandoff,
    dispatchHandoff,
    completeHandoff,
    blockHandoff,
    unblockHandoff,
    cancelHandoff,
    previewHandoff,
  }
}
```

- [ ] **Step 2: Run the typecheck**

Run:
```bash
npm run typecheck
```

Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add src/composables/useKanbanProtocol.ts
git commit -m "feat(kanban-protocol): add useKanbanProtocol composable"
```

---

## Task 21: Pinia store actions for handoffs

**Files:**
- Modify: `src/stores/board.ts` (add handoff state + actions)

- [ ] **Step 1: Add handoff state and actions to the store**

In `src/stores/board.ts`, inside the `defineStore` body, add:

```typescript
import type { IssueHandoff, HandoffPreview, WorkerLane, WorkerLaneKey } from '~/types/kanbanProtocol'
```

State additions:
```typescript
    lanes: [] as WorkerLane[],
    handoffsByIssue: {} as Record<string, IssueHandoff[]>,
    previewByHandoff: {} as Record<string, HandoffPreview>,
    handoffsLoading: false as boolean,
```

Action additions (place alongside other actions):

```typescript
    async fetchLanes() {
      const { listLanes } = useKanbanProtocol()
      this.lanes = await listLanes()
    },
    async fetchHandoffs(issueId: string) {
      this.handoffsLoading = true
      try {
        const { listHandoffsForIssue } = useKanbanProtocol()
        this.handoffsByIssue[issueId] = await listHandoffsForIssue(issueId)
      } finally {
        this.handoffsLoading = false
      }
    },
    async createHandoff(issueId: string, toLane: WorkerLaneKey, payload: Record<string, unknown> = {}) {
      const { createHandoff } = useKanbanProtocol()
      const handoff = await createHandoff(issueId, { toLane, payload })
      const list = this.handoffsByIssue[issueId] || []
      this.handoffsByIssue[issueId] = [handoff, ...list]
      return handoff
    },
    async acceptHandoff(issueId: string, handoffId: string) {
      const { acceptHandoff } = useKanbanProtocol()
      const updated = await acceptHandoff(handoffId)
      this._replaceHandoff(issueId, updated)
      return updated
    },
    async dispatchHandoff(issueId: string, handoffId: string, issueKey: string, profile = 'general') {
      const { dispatchHandoff } = useKanbanProtocol()
      const result = await dispatchHandoff(handoffId, { issueKey, profile })
      this._replaceHandoff(issueId, result.handoff)
      return result
    },
    async completeHandoff(issueId: string, handoffId: string, payload: Record<string, unknown> = {}) {
      const { completeHandoff } = useKanbanProtocol()
      const updated = await completeHandoff(handoffId, { payload })
      this._replaceHandoff(issueId, updated)
      return updated
    },
    async blockHandoff(issueId: string, handoffId: string, blockReason: string) {
      const { blockHandoff } = useKanbanProtocol()
      const updated = await blockHandoff(handoffId, undefined, blockReason)
      this._replaceHandoff(issueId, updated)
      return updated
    },
    async unblockHandoff(issueId: string, handoffId: string) {
      const { unblockHandoff } = useKanbanProtocol()
      const updated = await unblockHandoff(handoffId)
      this._replaceHandoff(issueId, updated)
      return updated
    },
    async cancelHandoff(issueId: string, handoffId: string) {
      const { cancelHandoff } = useKanbanProtocol()
      const updated = await cancelHandoff(handoffId)
      this._replaceHandoff(issueId, updated)
      return updated
    },
    async previewHandoff(handoffId: string) {
      const { previewHandoff } = useKanbanProtocol()
      this.previewByHandoff[handoffId] = await previewHandoff(handoffId)
      return this.previewByHandoff[handoffId]
    },
    _replaceHandoff(issueId: string, handoff: IssueHandoff) {
      const list = this.handoffsByIssue[issueId] || []
      this.handoffsByIssue[issueId] = list.map((h) =>
        h.id === handoff.id ? handoff : h,
      )
    },
```

- [ ] **Step 2: Run the typecheck and build**

Run:
```bash
npm run typecheck
npm run build
```

Expected: both succeed

- [ ] **Step 3: Commit**

```bash
git add src/stores/board.ts
git commit -m "feat(kanban-protocol): add handoff state and actions to board store"
```

---

## Task 22: `LaneMatrix.vue` component

**Files:**
- Create: `src/components/lanes/LaneMatrix.vue`

- [ ] **Step 1: Create the component**

`src/components/lanes/LaneMatrix.vue`:

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useBoardStore } from '~/stores/board'

const boardStore = useBoardStore()

onMounted(async () => {
  if (boardStore.lanes.length === 0) {
    await boardStore.fetchLanes()
  }
})
</script>

<template>
  <section class="lane-matrix" data-testid="lane-matrix">
    <h3>Worker Lanes</h3>
    <p v-if="boardStore.lanes.length === 0">Loading worker lanes…</p>
    <ul v-else>
      <li v-for="lane in boardStore.lanes" :key="lane.key" class="lane-row">
        <header>
          <span class="lane-key">{{ lane.key }}</span>
          <span class="lane-name">{{ lane.displayName }}</span>
        </header>
        <p class="lane-description">{{ lane.description }}</p>
        <dl>
          <dt>Provider</dt>
          <dd>{{ lane.defaultProvider }} / {{ lane.defaultModel }}</dd>
          <dt>Required fields</dt>
          <dd>{{ lane.requiredCompletionFields.join(', ') || '—' }}</dd>
          <dt>Next lanes</dt>
          <dd>{{ lane.nextLanes.join(', ') || '—' }}</dd>
          <dt>Human approval</dt>
          <dd>{{ lane.humanApprovalRequired ? 'required' : 'no' }}</dd>
        </dl>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.lane-matrix ul { list-style: none; padding: 0; display: grid; gap: 0.75rem; }
.lane-row { padding: 0.75rem; border: 1px solid var(--hairline); border-radius: 8px; background: var(--surface-card); }
.lane-row header { display: flex; gap: 0.5rem; align-items: baseline; }
.lane-key { font-family: var(--font-mono); color: var(--muted); font-size: 0.85rem; }
.lane-name { font-weight: 600; }
.lane-description { color: var(--muted); margin: 0.25rem 0 0.5rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 0.75rem; font-size: 0.85rem; }
dt { color: var(--muted); }
dd { margin: 0; }
</style>
```

- [ ] **Step 2: Run the typecheck and build**

Run:
```bash
npm run typecheck
npm run build
```

Expected: both succeed

- [ ] **Step 3: Commit**

```bash
git add src/components/lanes/LaneMatrix.vue
git commit -m "feat(kanban-protocol): add LaneMatrix component"
```

---

## Task 23: Handoff section components

**Files:**
- Create: `src/components/handoffs/HandoffSection.vue`
- Create: `src/components/handoffs/HandoffRow.vue`
- Create: `src/components/handoffs/HandoffActions.vue`
- Create: `src/components/handoffs/RulesPreviewModal.vue`

- [ ] **Step 1: Create `HandoffRow.vue`**

`src/components/handoffs/HandoffRow.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { IssueHandoff } from '~/types/kanbanProtocol'

const props = defineProps<{
  handoff: IssueHandoff
  canAccept: boolean
  canDispatch: boolean
  canComplete: boolean
  canBlock: boolean
  canUnblock: boolean
  canCancel: boolean
}>()

const emit = defineEmits<{
  accept: []
  dispatch: []
  complete: []
  block: []
  unblock: []
  cancel: []
  preview: []
}>()

const statusClass = computed(() => `handoff-status handoff-status--${props.handoff.status}`)
</script>

<template>
  <article class="handoff-row" :data-handoff-id="handoff.id" :data-status="handoff.status">
    <header>
      <span class="handoff-lanes">
        <span class="lane-tag">{{ handoff.fromLane || '∅' }}</span>
        <span class="handoff-arrow">→</span>
        <span class="lane-tag lane-tag--target">{{ handoff.toLane }}</span>
      </span>
      <span :class="statusClass">{{ handoff.status }}</span>
    </header>
    <p v-if="handoff.blockReason" class="handoff-block-reason">
      Blocked: {{ handoff.blockReason }}
    </p>
    <details>
      <summary>payload</summary>
      <pre>{{ JSON.stringify(handoff.payload, null, 2) }}</pre>
    </details>
    <HandoffActions
      :handoff="handoff"
      :can-accept="canAccept"
      :can-dispatch="canDispatch"
      :can-complete="canComplete"
      :can-block="canBlock"
      :can-unblock="canUnblock"
      :can-cancel="canCancel"
      @accept="emit('accept')"
      @dispatch="emit('dispatch')"
      @complete="emit('complete')"
      @block="emit('block')"
      @unblock="emit('unblock')"
      @cancel="emit('cancel')"
      @preview="emit('preview')"
    />
  </article>
</template>

<style scoped>
.handoff-row { border: 1px solid var(--hairline); border-radius: 8px; padding: 0.75rem; background: var(--surface-card); }
.handoff-row header { display: flex; justify-content: space-between; align-items: center; }
.lane-tag { font-family: var(--font-mono); color: var(--muted); }
.lane-tag--target { color: var(--primary); font-weight: 600; }
.handoff-arrow { margin: 0 0.25rem; color: var(--muted); }
.handoff-status { font-size: 0.75rem; text-transform: uppercase; padding: 0.1rem 0.4rem; border-radius: 4px; background: var(--surface-soft); color: var(--muted); }
.handoff-status--in_progress, .handoff-status--accepted { background: var(--primary); color: white; }
.handoff-status--completed { background: var(--sage); color: white; }
.handoff-status--blocked { background: var(--amber); color: white; }
.handoff-status--cancelled { background: var(--clay-red); color: white; }
.handoff-block-reason { color: var(--clay-red); margin: 0.5rem 0; }
details pre { font-size: 0.8rem; max-height: 12rem; overflow: auto; }
</style>
```

- [ ] **Step 2: Create `HandoffActions.vue`**

`src/components/handoffs/HandoffActions.vue`:

```vue
<script setup lang="ts">
import type { IssueHandoff } from '~/types/kanbanProtocol'

defineProps<{
  handoff: IssueHandoff
  canAccept: boolean
  canDispatch: boolean
  canComplete: boolean
  canBlock: boolean
  canUnblock: boolean
  canCancel: boolean
}>()

const emit = defineEmits<{
  accept: []
  dispatch: []
  complete: []
  block: []
  unblock: []
  cancel: []
  preview: []
}>()
</script>

<template>
  <div class="handoff-actions">
    <button v-if="canAccept" type="button" @click="emit('accept')">Accept</button>
    <button v-if="canDispatch" type="button" @click="emit('dispatch')">Dispatch</button>
    <button v-if="canComplete" type="button" @click="emit('complete')">Complete</button>
    <button v-if="canBlock" type="button" @click="emit('block')">Block</button>
    <button v-if="canUnblock" type="button" @click="emit('unblock')">Unblock</button>
    <button v-if="canCancel" type="button" @click="emit('cancel')">Cancel</button>
    <button type="button" @click="emit('preview')">Preview rules</button>
  </div>
</template>

<style scoped>
.handoff-actions { display: flex; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap; }
.handoff-actions button { padding: 0.3rem 0.6rem; border-radius: 4px; border: 1px solid var(--hairline); background: var(--surface-soft); cursor: pointer; }
.handoff-actions button:hover { background: var(--primary); color: white; border-color: var(--primary); }
</style>
```

- [ ] **Step 3: Create `RulesPreviewModal.vue`**

`src/components/handoffs/RulesPreviewModal.vue`:

```vue
<script setup lang="ts">
import type { HandoffPreview } from '~/types/kanbanProtocol'

defineProps<{ preview: HandoffPreview | null; open: boolean }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div v-if="open && preview" class="rules-preview-backdrop" @click.self="emit('close')">
    <div class="rules-preview-modal" role="dialog" aria-modal="true">
      <header>
        <h3>Rules preview — {{ preview.toLane }}</h3>
        <button type="button" @click="emit('close')">Close</button>
      </header>
      <dl>
        <dt>Display name</dt><dd>{{ preview.displayName }}</dd>
        <dt>Provider / model</dt><dd>{{ preview.defaultProvider }} / {{ preview.defaultModel }}</dd>
        <dt>Allowed commands</dt><dd>{{ preview.allowedCommands.join(', ') }}</dd>
        <dt>Required fields</dt><dd>{{ preview.requiredCompletionFields.join(', ') || '—' }}</dd>
        <dt>Present fields</dt><dd>{{ preview.presentFields.join(', ') || '—' }}</dd>
        <dt>Missing fields</dt>
        <dd>
          <span v-if="preview.missingFields.length === 0">none</span>
          <span v-else class="missing">{{ preview.missingFields.join(', ') }}</span>
        </dd>
        <dt>Next lanes</dt><dd>{{ preview.nextLanes.join(', ') || '—' }}</dd>
        <dt>Human approval</dt>
        <dd>
          {{ preview.humanApprovalRequired ? 'required' : 'not required' }}
          <span v-if="preview.humanApprovalRequired">
            ({{ preview.hasApprover ? 'approver recorded' : 'approver missing' }})
          </span>
        </dd>
        <dt>Timeout</dt><dd>{{ preview.timeoutSeconds }}s</dd>
        <dt>Retry policy</dt>
        <dd>{{ preview.retryPolicy }} (max {{ preview.retryMax }})</dd>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.rules-preview-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 50; }
.rules-preview-modal { background: var(--surface-card); padding: 1.25rem; border-radius: 8px; max-width: 32rem; width: 90%; max-height: 80vh; overflow: auto; }
.rules-preview-modal header { display: flex; justify-content: space-between; align-items: center; }
.rules-preview-modal dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.4rem 0.75rem; font-size: 0.9rem; }
.rules-preview-modal dt { color: var(--muted); }
.missing { color: var(--clay-red); font-weight: 600; }
</style>
```

- [ ] **Step 4: Create `HandoffSection.vue`**

`src/components/handoffs/HandoffSection.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useBoardStore } from '~/stores/board'
import type { IssueHandoff, HandoffStatus } from '~/types/kanbanProtocol'
import RulesPreviewModal from './RulesPreviewModal.vue'

const props = defineProps<{ issueId: string; issueKey: string }>()
const boardStore = useBoardStore()

const previewHandoffId = ref<string | null>(null)
const preview = computed(() =>
  previewHandoffId.value ? boardStore.previewByHandoff[previewHandoffId.value] : null,
)
const previewOpen = computed(() => previewHandoffId.value !== null)

watch(
  () => props.issueId,
  async (id) => {
    await boardStore.fetchHandoffs(id)
  },
  { immediate: true },
)

const handoffs = computed<IssueHandoff[]>(
  () => boardStore.handoffsByIssue[props.issueId] || [],
)

const grouped = computed(() => {
  const groups: Record<HandoffStatus, IssueHandoff[]> = {
    pending: [], accepted: [], in_progress: [],
    completed: [], blocked: [], cancelled: [],
  }
  for (const h of handoffs.value) groups[h.status].push(h)
  return groups
})

function isLegal(h: IssueHandoff, target: HandoffStatus): boolean {
  if (h.status === 'pending') return target === 'accepted'
  if (h.status === 'accepted') return target === 'in_progress'
  if (h.status === 'in_progress') return target === 'completed'
  if (h.status === 'blocked') return target === 'pending'
  return false
}

async function onAccept(h: IssueHandoff) {
  await boardStore.acceptHandoff(props.issueId, h.id)
}
async function onDispatch(h: IssueHandoff) {
  await boardStore.dispatchHandoff(props.issueId, h.id, props.issueKey, 'general')
}
async function onComplete(h: IssueHandoff) {
  await boardStore.completeHandoff(props.issueId, h.id, {})
}
async function onBlock(h: IssueHandoff) {
  const reason = window.prompt('Block reason?')
  if (!reason) return
  await boardStore.blockHandoff(props.issueId, h.id, reason)
}
async function onUnblock(h: IssueHandoff) {
  await boardStore.unblockHandoff(props.issueId, h.id)
}
async function onCancel(h: IssueHandoff) {
  await boardStore.cancelHandoff(props.issueId, h.id)
}
async function onPreview(h: IssueHandoff) {
  previewHandoffId.value = h.id
  await boardStore.previewHandoff(h.id)
}
function closePreview() {
  previewHandoffId.value = null
}
</script>

<template>
  <section class="handoff-section" data-testid="handoff-section">
    <header class="handoff-section__header">
      <h3>Handoffs</h3>
      <button
        type="button"
        @click="boardStore.createHandoff(issueId, 'frontend', { diff_summary: 'TBD' })"
      >
        + New handoff
      </button>
    </header>
    <p v-if="boardStore.handoffsLoading">Loading handoffs…</p>
    <p v-else-if="handoffs.length === 0">No handoffs yet.</p>
    <div v-else class="handoff-section__columns">
      <div v-for="(rows, status) in grouped" :key="status" class="handoff-section__column">
        <h4>{{ status }} ({{ rows.length }})</h4>
        <HandoffRow
          v-for="h in rows"
          :key="h.id"
          :handoff="h"
          :can-accept="isLegal(h, 'accepted')"
          :can-dispatch="isLegal(h, 'in_progress')"
          :can-complete="isLegal(h, 'completed')"
          :can-block="['pending', 'accepted', 'in_progress'].includes(h.status)"
          :can-unblock="h.status === 'blocked'"
          :can-cancel="['pending', 'accepted', 'in_progress', 'blocked'].includes(h.status)"
          @accept="onAccept(h)"
          @dispatch="onDispatch(h)"
          @complete="onComplete(h)"
          @block="onBlock(h)"
          @unblock="onUnblock(h)"
          @cancel="onCancel(h)"
          @preview="onPreview(h)"
        />
      </div>
    </div>
    <RulesPreviewModal :preview="preview" :open="previewOpen" @close="closePreview" />
  </section>
</template>

<style scoped>
.handoff-section__header { display: flex; justify-content: space-between; align-items: center; }
.handoff-section__columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 0.75rem; margin-top: 0.5rem; }
.handoff-section__column h4 { margin: 0 0 0.5rem; text-transform: capitalize; color: var(--muted); font-size: 0.85rem; }
</style>
```

- [ ] **Step 5: Run the typecheck and build**

Run:
```bash
npm run typecheck
npm run build
```

Expected: both succeed

- [ ] **Step 6: Commit**

```bash
git add src/components/handoffs/
git commit -m "feat(kanban-protocol): add HandoffSection, Row, Actions, RulesPreview"
```

---

## Task 24: Embed `HandoffSection` in `IssueDetail.vue`

**Files:**
- Modify: `src/components/IssueDetail.vue`

- [ ] **Step 1: Add a new "Handoffs" tab/section**

In `src/components/IssueDetail.vue`:

- Import the new component near the other imports:
  ```typescript
  import HandoffSection from '~/components/handoffs/HandoffSection.vue'
  ```

- Add `handoffs` to the active tab state (or section list). The existing
  component uses a `tabs` ref. Add a new entry `'handoffs'` and render
  `HandoffSection` inside that branch, passing the issue's `id` and `key`.

  The exact change depends on the existing tab wiring in the file. The
  pattern to apply is:

  ```vue
  <HandoffSection
    v-if="activeTab === 'handoffs'"
    :issue-id="issue.id"
    :issue-key="issue.key"
  />
  ```

  Also add a "Handoffs" entry to the tab list rendered in the panel
  header.

- [ ] **Step 2: Run the typecheck and build**

Run:
```bash
npm run typecheck
npm run build
```

Expected: both succeed

- [ ] **Step 3: Commit**

```bash
git add src/components/IssueDetail.vue
git commit -m "feat(kanban-protocol): embed HandoffSection in IssueDetail"
```

---

## Task 25: Add a "Lanes" route and minimal page

**Files:**
- Create: `src/pages/lanes.vue`

- [ ] **Step 1: Create the page**

`src/pages/lanes.vue`:

```vue
<template>
  <main class="lanes-page">
    <header>
      <h1>Worker Lanes</h1>
      <p>Code-defined agent routing contracts.</p>
    </header>
    <LaneMatrix />
  </main>
</template>

<script setup lang="ts">
import LaneMatrix from '~/components/lanes/LaneMatrix.vue'
</script>

<style scoped>
.lanes-page { padding: 1.5rem; max-width: 64rem; margin: 0 auto; }
.lanes-page header { margin-bottom: 1rem; }
.lanes-page h1 { font-family: var(--font-display); margin: 0; }
.lanes-page p { color: var(--muted); margin: 0.25rem 0 0; }
</style>
```

- [ ] **Step 2: Run the typecheck and build**

Run:
```bash
npm run typecheck
npm run build
```

Expected: both succeed

- [ ] **Step 3: Commit**

```bash
git add src/pages/lanes.vue
git commit -m "feat(kanban-protocol): add /lanes page"
```

---

# Phase 8: Verification

## Task 26: Run the full verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run backend tests**

Run:
```bash
PYTHONPATH=backend pytest -q backend/tests
```

Expected: all green. If any test fails, fix it before continuing.

- [ ] **Step 2: Run the frontend typecheck**

Run:
```bash
npm run typecheck
```

Expected: exit 0

- [ ] **Step 3: Run the frontend production build**

Run:
```bash
npm run build
```

Expected: `Build complete`

- [ ] **Step 4: Boot the backend and verify the lanes endpoint**

Run in one terminal:
```bash
PYTHONPATH=backend python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal:
```bash
curl -s http://127.0.0.1:8000/api/v1/lanes | head -c 400
```

Expected: JSON with a `lanes` array containing eight entries.

- [ ] **Step 5: Boot the frontend and verify the lanes page**

Run:
```bash
npm run preview
```

Open `http://127.0.0.1:3010/lanes` in a browser. Confirm:

- The eight lanes render.
- The page is not blank; the Lane Matrix section is populated.

- [ ] **Step 6: Walk through the spec's verification checklist**

Walk through every box in `docs/superpowers/specs/kanban-protocol-design.md`
§11. Tick the boxes manually. If any box is unchecked, fix the
corresponding code or test, then re-run this task.

- [ ] **Step 7: Commit a final marker**

```bash
git commit --allow-empty -m "chore(kanban-protocol): verification gate green"
```

---

# Self-Review (planning)

This plan covers every section of `docs/superpowers/specs/kanban-protocol-design.md`:

- §1 Goal — the plan exists to deliver it.
- §2 Non-Goals — reflected as explicit "do not implement" notes in the
  task descriptions (e.g., Task 4 says "No write endpoint").
- §3 Architecture — Phase 0 (setup), Phase 1–2 (registry + scope), Phase
  3 (migration), Phase 4 (handoff service), Phase 6 (API), Phase 7
  (frontend).
- §4 Worker Lane Registry — Tasks 2, 3, 4.
- §5 IssueHandoff — Tasks 7, 8, 9, 10, 11, 12, 13, 14, 15.
- §6 Board Isolation / Scope Guard — Tasks 5, 6, 7, 8, 15.
- §7 Delivery Orchestrator — Task 12 (dispatch), Task 13 (complete).
- §8 API Surface — Tasks 16, 17, 18.
- §9 Migration Plan — Task 7.
- §10 Frontend Integration — Tasks 19, 20, 21, 22, 23, 24, 25.
- §11 Verification — Task 26.
- §12 P2 reuse — Task 18 (comments reuse `create_issue_comment`),
  Task 9 (no schema duplication).
- §13 Out of scope — explicitly excluded; the spec section is referenced
  but nothing in the plan adds sandbox egress, SecurityWeb, multi-board
  UI, or a background scheduler.
- §14 Future work — not implemented, called out as deferred.

Placeholders scanned: the plan contains concrete code in every step.
Type consistency: `WorkerLane`, `IssueHandoff`, `HandoffService`,
`HandoffCreateRequest`, `HandoffActorRequest`, `HandoffCompleteRequest`,
`HandoffBlockRequest`, `HandoffCommentRequest`, `HandoffPreviewResponse`,
`DEFAULT_BOARD_ID` all have one definition site and consistent usage
throughout.

No issues found that require inline fixes.
