# Kanban Protocol — Agent-Native Kanban Design Spec

> **Naming note (read first):**
> This document defines a new product line, **Kanban Protocol** (also known as
> *Agent-Native Kanban*). It is **not** the same as the legacy `P3` defined in
> `docs/claude-code-execution-plan.md` (PR/CI automation + Paperclip session
> resume).
>
> **This supersedes the old "P3" naming for this design only.** Existing docs
> that define P3 as PR/CI + Session Resume remain legacy roadmap references
> and **should not be implemented in this phase**.
>
> To avoid being pulled back into the legacy P3 framing in future sessions,
> refer to this design as **Kanban Protocol** or **P2.5 Agent-Native Kanban**.

---

## 1. Goal

Promote DevFlow from a Kanban UI with a control-plane dispatch endpoint to a
**durable multi-agent work queue**. The core shift:

- A board movement is not a cosmetic transition. It is a **handoff** between
  named worker lanes.
- A handoff is a **durable queue item** with its own status machine, payload,
  and audit trail — not just an event in a log.
- Worker lanes are **typed subagent roles** (triage, frontend, qa, …) with
  declared contracts (allowed profiles, default provider/model, allowed
  commands, required completion fields, timeout/retry policy, next-lane
  rules, human approval requirement).
- The Delivery Orchestrator is **manual, rules-driven, and preview-first**.
  No background scheduler, no auto-routing daemon.

This is the Hermes-inspired framing: the system is a queue with typed workers
and explicit handoffs, not an event stream and not a CMS.

## 2. Non-Goals (Explicit Deferral)

The following are **explicitly out of scope** for Kanban Protocol MVP. They
remain deferred per `CLAUDE.md` and the legacy execution plan:

- Real Claude / Codex / Cursor execution by default. **Safe runner stays the
  default**, exactly as in the P0 loop. Real adapter execution is an opt-in
  env flag, unchanged.
- PR/CI automation webhooks.
- Paperclip-style session resume / session serialization.
- Sandbox egress policy, iptables, or any privileged container work.
- SecurityWeb / pentest / BGP / admin-retention / API-key rotation
  tooling. These are archived on
  `archive/security-scope-spike-2026-06-03` and must not merge into
  mainline.
- Dynamic lane CRUD UI, admin lane editor, runtime lane registration.
- Multi-board UI. The `board_id` field is reserved at the schema layer but
  the UI is single-board.
- Background scheduler / autopilot / cron-driven dispatch.
- Replacing the existing P2 collaboration records (IssueEvent,
  IssueComment, IssueArtifact). Kanban Protocol **builds on top of** them.

## 3. Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│  Nuxt 3 Frontend (Control Plane UI)                                 │
│                                                                     │
│  Board view  ──►  Issue detail panel  ──►  Handoff drawer           │
│       │                │                       │                    │
│       │                │   Lane Matrix (read)  │                    │
│       ▼                ▼                       ▼                    │
│  /api/v1/board    /api/v1/boards/{id}/issues/{id}                   │
│                   /api/v1/boards/{id}/issues/{id}/handoffs          │
│                   /api/v1/boards/{id}/handoffs/{id}/dispatch       │
│                   /api/v1/lanes                                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI Backend (Control Plane)                                    │
│                                                                     │
│  core/kanban_protocol/                                              │
│    lanes.py              ──► WorkerLane dataclass + WORKER_LANES    │
│    handoff.py            ──► HandoffService (status machine)        │
│    orchestrator.py       ──► manual dispatch + rules preview        │
│    board_scope.py        ──► board_id isolation helpers             │
│                                                                     │
│  api/v1/                                                             │
│    lanes.py              ──► GET /api/v1/lanes                      │
│    handoffs.py           ──► CRUD + dispatch endpoints              │
│    board.py              ──► existing board endpoints (board_id)    │
│                                                                     │
│  db/models.py (additions)                                            │
│    IssueHandoff          ──► durable queue item                     │
│    board_id column on    ──► Issue, IssueEvent, IssueComment,       │
│    existing tables           IssueArtifact, JobModel                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    Safe runner (unchanged P0 path)
                    Real adapter only via env flag
```

## 4. Worker Lane Registry (Code-Defined)

**Decision: MVP lane registry is static and code-defined.** This is to keep
the agent-routing contract reviewable in PRs and prevent scope drift into a
config CMS.

### 4.1 Backend location

```text
backend/core/kanban_protocol/lanes.py
```

### 4.2 `WorkerLane` dataclass

```python
from dataclasses import dataclass
from typing import List, Literal

RetryPolicy = Literal["none", "fixed", "exponential"]


@dataclass(frozen=True)
class WorkerLane:
    key: str                                      # e.g. "frontend"
    display_name: str                             # e.g. "Frontend"
    description: str                              # human-readable
    allowed_profiles: List[str]                   # subset of {frontend, backend, security, refactor, debug, general}
    default_provider: str                         # e.g. "claude-code"
    default_model: str                            # e.g. "claude-3-5-sonnet"
    allowed_commands: List[str]                   # e.g. ["/loop-start --profile=frontend"]
    required_completion_fields: List[str]         # payload keys that MUST be present before complete
    timeout_seconds: int                          # hard ceiling
    retry_policy: RetryPolicy                     # "none" | "fixed" | "exponential"
    retry_max: int                                # 0 = no retry
    next_lanes: List[str]                         # legal target lanes
    human_approval_required: bool                 # gates dispatch
```

### 4.3 `WORKER_LANES` registry

Eight lanes ship in MVP. Adding a lane requires a code change and PR review.

```python
WORKER_LANES: dict[str, WorkerLane] = {
    "triage":    WorkerLane(...),
    "product":   WorkerLane(...),
    "architect": WorkerLane(...),
    "frontend":  WorkerLane(...),
    "backend":   WorkerLane(...),
    "qa":        WorkerLane(...),
    "review":    WorkerLane(...),
    "delivery":  WorkerLane(...),
}
```

### 4.4 Public read API

```http
GET /api/v1/lanes
```

Returns the contents of `WORKER_LANES` for the frontend Lane Matrix view.
**No write endpoint.** No CRUD. No admin UI.

### 4.5 Out of scope (explicitly)

- No DB-backed lane table.
- No migration for lane definitions.
- No admin lane editor.
- No runtime lane registration.
- No code+override precedence logic.

A future Phase 2 may promote this to a DB-backed or code+override model.
That is not part of this spec.

## 5. IssueHandoff — Durable Queue Item

A handoff is the agent-native equivalent of a Kanban card movement. It is
**not** an event in a log. It is a queued unit of work with a status machine,
a payload, and an audit trail.

### 5.1 Data model

New table `issue_handoffs` (added via a new Alembic migration, see §9):

| Column              | Type            | Notes                                                  |
|---------------------|-----------------|--------------------------------------------------------|
| `id`                | `String(64)`    | PK                                                     |
| `board_id`          | `String(64)`    | FK-by-convention; nullable for legacy rows              |
| `issue_id`          | `String(64)`    | FK to `issues.id` (no constraint)                      |
| `from_lane`         | `String(32)`    | source lane key (nullable for initial handoff)         |
| `to_lane`           | `String(32)`    | target lane key; must be a key in `WORKER_LANES`       |
| `status`            | `String(32)`    | see §5.2 status machine                                |
| `payload`           | `JSON`          | completion fields + linked artifact IDs + notes; MUST include `approver` (string) when target lane's `human_approval_required` is `true` |
| `block_reason`      | `Text`          | populated when status transitions to `blocked`         |
| `created_by`        | `String(128)`   | actor identifier (user or agent)                       |
| `accepted_by`       | `String(128)`   | nullable; actor who moved to `accepted`                |
| `dispatched_by`     | `String(128)`   | nullable; actor who moved to `in_progress`             |
| `completed_by`      | `String(128)`   | nullable; actor who moved to `completed`               |
| `cancelled_by`      | `String(128)`   | nullable; actor who moved to `cancelled`               |
| `created_at`        | `DateTime(tz)`  |                                                        |
| `updated_at`        | `DateTime(tz)`  |                                                        |
| `completed_at`      | `DateTime(tz)`  | nullable                                               |

Indexes: `(board_id, status)`, `(issue_id, created_at)`, `(to_lane, status)`.

### 5.2 Status machine

```text
                  ┌────────────┐
                  │  pending   │  ← created
                  └─────┬──────┘
                        │ accept
                        ▼
                  ┌────────────┐
        ┌────────►│  accepted  │
        │         └─────┬──────┘
        │ cancel        │ dispatch
        │               ▼
        │         ┌────────────┐
        │         │ in_progress│
        │         └─────┬──────┘
        │               │ complete
        │               ▼
        │         ┌────────────┐
        │         │ completed  │
        │         └────────────┘
        │
        │  (any non-terminal)  ──block──►  ┌────────────┐
        │                                     │  blocked   │
        │                                     └─────┬──────┘
        │                                           │ unblock
        │                                           ▼
        │                                     (back to prior state)
        │
        └────── cancel ──────►  ┌────────────┐
                                 │ cancelled  │
                                 └────────────┘
```

Rules:

- `accept` requires `to_lane` to be a valid `WORKER_LANES` key.
- `dispatch` requires `human_approval_required` to be false **or** an
  approver field on the handoff. (If approval is required and missing,
  dispatch is rejected with a 409 and a `requires_approval: true` body.)
- `complete` requires every key in
  `WorkerLane.required_completion_fields` to be present in `payload`.
- `block` requires `block_reason` to be non-empty.
- `cancel` is allowed from any non-terminal state.

### 5.3 Tool semantics

Kanban Protocol exposes four tool-style actions. These are not separate APIs
per se — they are state transitions on a handoff — but they are named and
documented so the UI and any future agent can use them uniformly.

| Tool       | HTTP method / path                                                          | Effect                                       |
|------------|------------------------------------------------------------------------------|----------------------------------------------|
| `create`   | `POST /api/v1/boards/{board_id}/issues/{issue_id}/handoffs`                  | creates a handoff in `pending`               |
| `complete` | `POST /api/v1/boards/{board_id}/handoffs/{handoff_id}/complete`             | transitions to `completed` after validation  |
| `block`    | `POST /api/v1/boards/{board_id}/handoffs/{handoff_id}/block`                | transitions to `blocked` with reason         |
| `comment`  | `POST /api/v1/boards/{board_id}/handoffs/{handoff_id}/comments`             | appends to `IssueComment` (reuses P2 table)  |

`accept`, `dispatch`, and `cancel` are also first-class endpoints, but they
are orchestration-level and not in the user-facing tool set.

### 5.4 Validation

The `payload` JSON must include every key listed in
`WorkerLane.required_completion_fields` for `to_lane` before `complete` is
accepted. The endpoint returns a 422 with the missing keys.

## 6. Board Isolation / Scope Guard

### 6.1 Schema layer

Every Kanban Protocol record carries a `board_id`:

- `Issue.board_id` (nullable for legacy rows; default value applied on read)
- `IssueEvent.board_id`
- `IssueComment.board_id`
- `IssueArtifact.board_id`
- `JobModel.board_id`
- `IssueHandoff.board_id` (defined in §5.1)

A single migration (`0004_add_board_id_and_handoffs.py`) introduces these
columns with a default value and creates `issue_handoffs`.

### 6.2 Runtime layer

`core/kanban_protocol/board_scope.py` exposes:

```python
DEFAULT_BOARD_ID = "board-default"

def resolve_board_id(explicit: str | None) -> str:
    """MVP: returns DEFAULT_BOARD_ID if explicit is None."""
```

All API endpoints accept `board_id` as a path segment. In MVP, only
`DEFAULT_BOARD_ID` is valid; requests for any other board id return 404.

### 6.3 Scope guard

A **Scope Guard** is a pre-dispatch rule that refuses to create handoffs
whose `to_lane` or `payload` matches out-of-scope work patterns. This is a
defensive measure to keep the archived security work from leaking back into
mainline.

```python
DENIED_LANES: set[str] = set()        # MVP: empty; no lane is denied
DENIED_PAYLOAD_KEYS: set[str] = {
    "sandbox_egress",
    "iptables_rules",
    "admin_keys",
    "pentest_findings",
}
```

If a handoff **at any state transition** (create, accept, dispatch,
complete, block, unblock, cancel, comment) carries any denied payload key,
the endpoint returns 422 with `scope_denied: true` and the offending key.

This is **not** a substitute for code review. It is a tripwire.

## 7. Delivery Orchestrator (Manual, Rules-Preview)

### 7.1 No daemon. No scheduler.

There is no background worker. There is no cron. There is no event-driven
auto-routing. Every transition is initiated by an HTTP request from a human
or from a future agent that calls the API.

### 7.2 Manual dispatch flow

```text
1. Human or future agent calls
   POST /api/v1/boards/{board_id}/issues/{issue_id}/handoffs
   with { to_lane, payload, ... }.
   → status: pending

2. Human reviews the handoff in the UI.
   The UI calls
   GET /api/v1/boards/{board_id}/handoffs/{handoff_id}/preview
   and shows:
     - target lane + display_name
     - default provider/model
     - allowed commands
     - required completion fields + which are present/missing
     - next-lane rules
     - human approval required?
     - timeout
   This is the "rules preview". The handoff is NOT dispatched yet.

3. Human calls
   POST /api/v1/boards/{board_id}/handoffs/{handoff_id}/accept
   → status: accepted

4. If human_approval_required is true, the UI must already show that an
   approver has signed off (recorded as a metadata field in the handoff).
   Otherwise dispatch is rejected with 409.

5. Human calls
   POST /api/v1/boards/{board_id}/handoffs/{handoff_id}/dispatch
   → status: in_progress
   → creates a JobModel row via the existing P0 dispatch path
      (safe runner, no real Claude execution by default).

6. When the job finishes:
   - Safe runner emits a completion event (unchanged from P0).
   - Orchestrator transitions handoff to `completed` (or `blocked` on
     failure, with block_reason populated).
```

### 7.3 What the Orchestrator is NOT

- It is not a queue worker. No consumer thread, no `asyncio.Task`.
- It is not a stateful agent. It does not call any LLM.
- It does not implement session resume.
- It does not implement auto-advance. It does not move handoffs forward
  without an HTTP request.

## 8. API Surface

All paths are under `/api/v1/`. `board_id` is required in the path; in MVP
the only valid value is `board-default`.

### 8.1 Read

```http
GET  /api/v1/lanes
GET  /api/v1/boards/{board_id}/issues/{issue_id}/handoffs
GET  /api/v1/boards/{board_id}/handoffs/{handoff_id}
GET  /api/v1/boards/{board_id}/handoffs/{handoff_id}/preview
```

### 8.2 Write

```http
POST   /api/v1/boards/{board_id}/issues/{issue_id}/handoffs          # create
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/accept        # accept
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/dispatch      # dispatch (creates JobModel)
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/complete      # complete
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/block         # block
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/unblock       # unblock
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/cancel        # cancel
POST   /api/v1/boards/{board_id}/handoffs/{handoff_id}/comments      # append comment (P2 reuse)
```

`PATCH` is **not** used. All transitions are explicit POSTs so the audit
trail is unambiguous.

## 9. Migration Plan

A single new Alembic migration: `0004_add_board_id_and_handoffs.py`.

Operations:

1. `ALTER TABLE` to add `board_id` to `issues`, `issue_events`,
   `issue_comments`, `issue_artifacts`, `ecc_jobs`. Default value
   `"board-default"`. Nullable for safety on existing rows.
2. `CREATE TABLE issue_handoffs (...)` with the columns in §5.1.
3. Backfill `board_id` on existing rows to `"board-default"`.

No destructive operations. No renames. No data loss.

## 10. Frontend Integration (Indicative)

This spec does not lock down UI implementation, but the frontend must:

- Render a **Lane Matrix** view from `GET /api/v1/lanes`.
- In the issue detail panel, add a **Handoffs** section listing handoffs
  for the issue, grouped by status.
- Each handoff row shows: from → to lane, status, payload summary,
  block reason (if any), and the action buttons that match the current
  state: accept, dispatch, complete, block, unblock, cancel
  (each enabled only when the transition is legal in the current state).
- Before any dispatch, the UI calls `/preview` and shows the rules preview
  described in §7.2 step 2.

No design tokens, color choices, or layout details are in this spec — they
belong in `Design.md` and any future visual design pass.

## 11. Verification

Acceptance criteria for Kanban Protocol MVP:

- [ ] `PYTHONPATH=backend pytest -q backend/tests` passes.
- [ ] `npm run typecheck` passes.
- [ ] `npm run build` passes.
- [ ] `GET /api/v1/lanes` returns the eight MVP lanes.
- [ ] `POST /api/v1/boards/board-default/issues/{id}/handoffs` creates a
      handoff in `pending`.
- [ ] `GET /api/v1/boards/board-default/handoffs/{id}/preview` returns
      the rules preview described in §7.2.
- [ ] A complete transition is rejected with 422 when a required
      completion field is missing.
- [ ] A block transition is rejected with 422 when `block_reason` is
      empty.
- [ ] A dispatch with `human_approval_required=true` and no approver
      metadata returns 409.
- [ ] Dispatch creates a `JobModel` row via the existing safe runner
      path; no real Claude/Codex execution happens by default.
- [ ] Board isolation: a request for any `board_id` other than
      `board-default` returns 404.
- [ ] Scope guard: a handoff whose payload contains a `DENIED_PAYLOAD_KEYS`
      entry is rejected with 422.
- [ ] The frontend Lane Matrix renders the eight lanes from
      `GET /api/v1/lanes`.
- [ ] No real adapter execution is triggered by Kanban Protocol
      endpoints (verified by `JobModel.execution_mode == "safe_runner"`).

## 12. Relationship to Existing P2 Collaboration Records

| Concept              | Owner                | Status                                  |
|----------------------|----------------------|-----------------------------------------|
| Issue events         | P2 (existing)        | Reused. `type` values may include `handoff_created`, `handoff_accepted`, etc. |
| Issue comments       | P2 (existing)        | Reused. Handoff comments append here.   |
| Issue artifacts      | P2 (existing)        | Reused. Handoff payload may link artifact IDs. |
| IssueHandoff         | Kanban Protocol (new) | Durable queue item with status machine. |
| JobModel             | P0 (existing)        | Created by handoff dispatch.            |

Kanban Protocol **extends** P2; it does not replace it.

## 13. Out of Scope (Reminder)

- Real Claude / Codex / Cursor execution by default.
- PR/CI automation.
- Session resume / Paperclip serialization.
- Sandbox egress.
- SecurityWeb / pentest / BGP / admin-retention work.
- Dynamic lane CRUD, admin UI, runtime lane registration.
- Multi-board UI (the `board_id` column is reserved, not exposed).
- Background scheduler, cron, or daemon.
- Auth / JWT rollout (separate work item; tracked in 6/2 daily log).

## 14. Future Work (Not Part of This Spec)

- Promote `WorkerLane` to a DB-backed registry with a code-override hook.
- Multi-board UI after the schema is stable.
- Auto-suggest next lane based on the rules preview (still human-approved).
- Wire `agent_audit` rows to handoff transitions for richer audit trail.
- Connect real adapter execution behind the existing env flag once the
  safe-runner path is proven.
