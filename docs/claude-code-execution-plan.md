# Claude Code Execution Plan

This plan is for the next agent taking over DevFlow. The goal is to continue building product features on top of the proven P0 loop.

## Current Diagnosis

DevFlow's P0 product loop is stable. P1 features (handoff metadata, evidence display) are complete. P2 (Artifacts v1, Review Gate, Real execution closed loop) are complete. P3 (Delivery Orchestrator) is complete. P4 (Log Sync + Evidence Panel) and P5 (Real LLM Pipeline) are complete.

Working:

- Frontend builds, typechecks, and serves on `http://127.0.0.1:3010`.
- Backend starts clean on `http://127.0.0.1:8000` (no DB warnings).
- `GET /api/v1/board` returns seed issues with non-empty columns.
- `GET /health` and `GET /api/v1/ecc/jobs` work.
- ECC dispatch creates jobs and returns immediately.
- Safe runner transitions jobs through `queued -> running -> review_required`.
- Job state visible in UI (card detail panel, sidebar logs).
- Backend tests: 535/535 passed.
- Single sidebar path (`src/components/sidebar/Sidebar.vue`).
- Handoff typed payload with lane-specific Pydantic validation (P1.5).
- Structured 422 error responses for invalid payloads (P1.5).
- Evidence display in HandoffCard for completed handoffs (P1.6).
- `ClaudeLocalAdapter` and safe runner path exist in `backend/core/adapters/`.
- AgentRun events bridged into IssueDetail timeline via job_id filter (P4).
- WebSocket broadcast for real-time AgentRun log streaming (P4).
- Dispatch gate: `ALLOW_REAL_LLM_EXECUTION` env controls api-agent vs safe-runner routing (P5).
- HarnessRegistry resolves provider to APIModelAdapter (P5).
- APIModelExecutor handles provider config, API key resolution, HTTP calls (P5).
- `get_llm_provider_config_with_key()` internal function for executor key access (P5).
- Kanban Protocol handoff dispatch respects `ALLOW_REAL_LLM_EXECUTION` flag.
- ECC cancel triggers `orchestrator.cancel_run()` for linked AgentRuns.
- `POST /runtime/runs/{run_id}/cancel` endpoint for direct run cancellation.
- `cancel_run()` syncs linked ECC job to cancelled status.
- `find_active_runs_for_job_id()` repo function for reverse lookup.

Not yet done:

- Session resume implementation (schema designed at `docs/superpowers/specs/2026-06-06-session-resume-schema.md`, requires real execution stable first).
- PR/CI automation.

## Product Completion Principle

Do not mark a phase complete because files/classes exist. A phase is complete only when the user-visible loop works and has passing verification.

The P0 loop is:

```text
Issue exists
-> User moves card to In Progress
-> Backend creates an ECC job
-> A safe background runner emits logs
-> Frontend can show job/log state
-> Job ends as review_required, completed, or failed
-> Board reflects the result
```

## Priority Table

| Priority | Work Item | Concrete Task | Acceptance Criteria | Do Not Do Yet |
|---|---|---|---|---|
| ~~P0~~ | ~~Restore visible board data~~ | ~~Done~~ | ~~Board shows non-empty cards~~ | — |
| ~~P0~~ | ~~Fix backend DB startup warning~~ | ~~Done~~ | ~~No greenlet_spawn warning~~ | — |
| ~~P0~~ | ~~Make tests green~~ | ~~Done~~ | ~~535/535 backend tests pass~~ | — |
| ~~P0~~ | ~~Stabilize ECC dispatch~~ | ~~Done~~ | ~~Job created, returns immediately~~ | — |
| ~~P0~~ | ~~Add safe runner loop~~ | ~~Done~~ | ~~queued -> running -> review_required~~ | — |
| ~~P0~~ | ~~Show job state in UI~~ | ~~Done~~ | ~~Card detail shows job/logs~~ | — |
| ~~P1~~ | ~~Consolidate sidebar~~ | ~~Done~~ | ~~Single sidebar path~~ | — |
| ~~P1~~ | ~~E2E setup~~ | ~~Done~~ | ~~37/37 e2e tests pass~~ | — |
| ~~P1~~ | ~~Adapter integration~~ | ~~Done~~ | ~~ClaudeLocalAdapter exists, safe runner proven~~ | — |
| ~~P1~~ | ~~Handoff typed payload (P1.5)~~ | ~~Done~~ | ~~Lane-specific Pydantic + structured 422~~ | — |
| ~~P1~~ | ~~Evidence display (P1.6)~~ | ~~Done~~ | ~~HandoffCard toggle + type-aware body~~ | — |
| ~~P2~~ | ~~Artifacts v1~~ | ~~Done~~ | ~~Issues can link to external artifacts with typed metadata~~ | — |
| ~~P2~~ | ~~Review Gate~~ | ~~Done~~ | ~~Completed handoffs route to accept/reject/rework based on structured fields~~ | — |
| ~~P2~~ | ~~Real Claude/ECC execution~~ | ~~Done~~ | ~~Safe runner default; real runner opt-in via ALLOW_REAL_LLM_EXECUTION=true~~ | Do not run arbitrary commands from user input |
| ~~P3~~ | ~~Delivery Orchestrator~~ | ~~Done~~ | ~~Handoff → review → delivery → done flow works end-to-end~~ | — |
| P3 | PR/CI automation | Connect GitHub PR and CI webhooks | CI/PR state updates issue detail and status | Do not start before P2 is green |
| P3 | Session resume | Schema designed; implementation pending real execution stability | Interrupted jobs can resume with stored session metadata | Do not implement before real runner is stable |

## Required Verification

Run after every backend change:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Run after every frontend or shared TypeScript change:

```bash
npm run typecheck
npm run build
```

Manual smoke check:

```bash
PYTHONPATH=backend python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
npm run preview
```

Expected URLs:

- Frontend: `http://127.0.0.1:3010`
- Backend health: `http://127.0.0.1:8000/health`
- ECC jobs: `http://127.0.0.1:8000/api/v1/ecc/jobs`

## Architecture Guardrails

Use the Paperclip architecture as a direction, not as the next implementation target.

Allowed now:

- A narrow `ExecutionContext`.
- A safe process/log runner.
- Job lifecycle events.
- WebSocket or in-memory log streaming.
- A single Claude-local-compatible path after the safe runner works.

Deferred:

- Multi-harness execution.
- Session resume.
- Agent session serialization.
- Full auth/API-key rollout.
- Autopilot scheduling.
- PR/CI automation.

## Stop Conditions

Stop and report instead of continuing if:

- Backend tests fail after a change.
- Frontend builds but the board has zero cards.
- Dispatch request blocks waiting for real CLI execution.
- A change requires adding a new framework or broad dependency.
- The task drifts into multi-harness/session-resume before P0 is verified.
