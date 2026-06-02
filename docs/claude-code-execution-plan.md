# Claude Code Execution Plan

This plan is for the next agent taking over DevFlow. The goal is not to finish the Paperclip architecture. The goal is to restore and prove the smallest working product loop.

## Current Diagnosis

DevFlow has useful pieces, but the product loop is not yet stable.

Working:

- Frontend builds and typechecks.
- Frontend preview responds on `http://127.0.0.1:3010`.
- Backend starts on `http://127.0.0.1:8000`.
- `GET /health` works.
- `GET /api/v1/ecc/jobs` works.
- Adapter-related files exist.

Not working or not proven:

- `/api/v1/board` returns empty columns, so the board has zero cards.
- Backend startup reports a database initialization warning.
- Backend smoke tests currently fail.
- ECC dispatch is too eager to enter adapter/real execution before the P0 loop is stable.
- E2E tests exist but Playwright is not installed in `devDependencies`.
- Two sidebar implementations exist and should be consolidated later.

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
| P0 | Restore visible board data | Make `GET /api/v1/board` return seed issues, or make frontend fallback when the API returns empty columns | Opening `http://127.0.0.1:3010/` shows non-empty cards across columns | Do not redesign the board while fixing data |
| P0 | Fix backend DB startup warning | Fix async SQLAlchemy table creation in `backend/db/database.py` | Backend starts without `greenlet_spawn` warning | Do not add migrations yet |
| P0 | Make tests green | Fix route/test mismatch and unstable dispatch behavior | `PYTHONPATH=backend pytest -q backend/tests` passes | Do not rewrite all tests |
| P0 | Stabilize ECC dispatch semantics | `POST /api/v1/ecc/dispatch` creates a job and returns immediately | API response contains job id, status `queued`, events array | Do not block request on real Claude/ECC execution |
| P0 | Add safe runner loop | Implement an `ExecutionContext` or narrow runner that emits fake/safe logs first | Job transitions `queued -> running -> review_required` with events | Do not enable real Claude Code by default |
| P0 | Show job state in UI | Ensure card/detail panel show job id/status/message/logs | Moving a card creates visible job state | Do not add multi-harness UI complexity |
| P1 | Consolidate sidebar direction | Choose either `AppSidebar.vue` or `components/sidebar/Sidebar.vue` | Only one sidebar path is active and matches `Design.md` | Do not keep duplicate design systems |
| P1 | E2E setup | Install or remove Playwright from required gates | `npm run e2e` either runs or is clearly documented as pending | Do not pretend E2E is complete without dependency |
| P1 | Adapter integration | Wrap the proven P0 runner into `ClaudeLocalAdapter` | Adapter calls the same proven execution path | Do not add Codex/Cursor/Gemini behavior yet |
| P2 | Real Claude/ECC execution | Enable real command execution behind env flag | Safe runner remains default; real runner opt-in works locally | Do not run arbitrary commands from user input |
| P2 | Persistence | Persist issues/jobs/events with SQLite/Postgres | Restart does not lose board/job state | Do not build full multi-tenant schema |
| P3 | PR/CI automation | Connect GitHub PR and CI webhooks | CI/PR state updates issue detail and status | Do not start before P0/P1 are green |
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
