# Claude Code Execution Plan

This plan is for the next agent taking over DevFlow. The goal is to continue building product features on top of the proven P0 loop.

## Current Diagnosis

DevFlow's P0 product loop is stable. P1 features (handoff metadata, evidence display) are complete.

Working:

- Frontend builds, typechecks, and serves on `http://127.0.0.1:3010`.
- Backend starts clean on `http://127.0.0.1:8000` (no DB warnings).
- `GET /api/v1/board` returns seed issues with non-empty columns.
- `GET /health` and `GET /api/v1/ecc/jobs` work.
- ECC dispatch creates jobs and returns immediately.
- Safe runner transitions jobs through `queued -> running -> review_required`.
- Job state visible in UI (card detail panel, sidebar logs).
- E2E suite: 37 passed, 13 skipped (mobile), 0 failed.
- Backend tests: 211/211 passed.
- Single sidebar path (`src/components/sidebar/Sidebar.vue`).
- Handoff typed payload with lane-specific Pydantic validation (P1.5).
- Structured 422 error responses for invalid payloads (P1.5).
- Evidence display in HandoffCard for completed handoffs (P1.6).
- `ClaudeLocalAdapter` and safe runner path exist in `backend/core/adapters/`.

Not yet done:

- Real Claude/ECC execution (safe runner is default; real execution opt-in only).
- Artifacts v1 — typed evidence/artifact references on issues.
- Review Gate — structured completion result with decision routing.
- Delivery Orchestrator.
- Session resume.
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
| ~~P0~~ | ~~Make tests green~~ | ~~Done~~ | ~~211/211 backend tests pass~~ | — |
| ~~P0~~ | ~~Stabilize ECC dispatch~~ | ~~Done~~ | ~~Job created, returns immediately~~ | — |
| ~~P0~~ | ~~Add safe runner loop~~ | ~~Done~~ | ~~queued -> running -> review_required~~ | — |
| ~~P0~~ | ~~Show job state in UI~~ | ~~Done~~ | ~~Card detail shows job/logs~~ | — |
| ~~P1~~ | ~~Consolidate sidebar~~ | ~~Done~~ | ~~Single sidebar path~~ | — |
| ~~P1~~ | ~~E2E setup~~ | ~~Done~~ | ~~37/37 e2e tests pass~~ | — |
| ~~P1~~ | ~~Adapter integration~~ | ~~Done~~ | ~~ClaudeLocalAdapter exists, safe runner proven~~ | — |
| ~~P1~~ | ~~Handoff typed payload (P1.5)~~ | ~~Done~~ | ~~Lane-specific Pydantic + structured 422~~ | — |
| ~~P1~~ | ~~Evidence display (P1.6)~~ | ~~Done~~ | ~~HandoffCard toggle + type-aware body~~ | — |
| P2 | Artifacts v1 | Typed evidence/artifact references on issues | Issues can link to external artifacts with typed metadata | Do not build full file storage |
| P2 | Review Gate | Structured completion result with decision routing | Completed handoffs route to accept/reject/rework based on structured fields | Do not add ML-based routing |
| P2 | Real Claude/ECC execution | Enable real command execution behind env flag | Safe runner remains default; real runner opt-in works locally | Do not run arbitrary commands from user input |
| P3 | Delivery Orchestrator | Automated delivery pipeline | Handoff → review → merge/release flow | Do not start before P2 is green |
| P3 | PR/CI automation | Connect GitHub PR and CI webhooks | CI/PR state updates issue detail and status | Do not start before P2 is green |
| P3 | Session resume | Add Paperclip-style session persistence | Interrupted jobs can resume with stored session metadata | Do not implement before real runner is stable |

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
