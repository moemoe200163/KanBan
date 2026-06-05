# DevFlow Claude Instructions

Read this file before making changes. These rules exist because this project can easily drift into over-engineering.

## Current Mission

DevFlow is an AI Kanban control plane. The P0 product loop is stable. Current focus is **P1 feature hardening and next product slices** (Artifacts v1, Review Gate).

The proven P0 loop:

```text
Issue exists
-> User moves card to In Progress
-> Backend creates an ECC job
-> A safe background runner emits logs
-> Frontend shows job/log state
-> Job ends as review_required, completed, or failed
-> Board reflects the result
```

Do not claim a phase is complete because files/classes exist. Completion requires the loop to work and verification to pass.

## Source Of Truth

Use these files in this order:

1. `CLAUDE.md` - agent rules and anti-drift constraints.
2. `docs/claude-code-execution-plan.md` - current execution plan and priority table.
3. `Design.md` - product/UI design source of truth.
4. `README.md` - ports, commands, current API contract.
5. Current code and tests.
6. `PLAN.md` and `SPEC.md` - historical/context references only unless they agree with the files above.

When documents conflict, follow the higher item in this list.

## Hard Constraints

- Frontend port is `3010`.
- Backend port is `8000`.
- Do not replace the current stack.
- Do not introduce a new UI framework.
- Do not build multi-harness execution before P0 is green.
- Do not implement session resume before real single-run execution is stable.
- Do not let `/api/v1/ecc/dispatch` block waiting for real Claude/ECC execution.
- Do not run arbitrary user-provided shell commands.
- Do not mark E2E complete unless `@playwright/test` is installed and `npm run e2e` passes.
- Do not leave the board empty after startup unless the user explicitly requested an empty board.

## Current Known Problems

All P0 issues are resolved. No blocking known problems.

- `GET /api/v1/board` returns seed issues ✅
- Backend startup clean (no DB warnings) ✅
- Backend tests pass (535/535) ✅
- E2E suite passes (37/37 desktop, Playwright installed) ✅
- Single sidebar path (`src/components/sidebar/Sidebar.vue`) ✅
- P1.5 Handoff typed payload + structured 422 ✅
- P1.6 Issue Detail evidence display (HandoffCard) ✅

## Allowed P0 Architecture

Use a narrow execution path first:

```python
ExecutionContext(
    task_id: str,
    issue_key: str,
    command: list[str],
    workspace_path: str,
    on_log: callable,
    on_status: callable,
)
```

Safe runner behavior:

```text
queued -> running -> review_required
```

The safe runner may emit deterministic logs such as:

```text
Analyzing issue DEV-001
Preparing execution context
Running safe quality check
Ready for human review
```

This safe runner should be the default until the board/job/log loop is proven.

## Deferred Architecture

Do not prioritize these until real execution is stable:

- ~~Real Claude/ECC execution (enable behind env flag; safe runner remains default).~~ ✅
- Paperclip-style session serialization (schema designed: `docs/superpowers/specs/2026-06-06-session-resume-schema.md`).
- Session resume implementation (requires real execution stable first).
- Autopilot scheduling.
- PR/CI automation.
- Full auth and API-key rollout.
- Redis queue.

Real LLM execution is opt-in via `ALLOW_REAL_LLM_EXECUTION=true`. Safe runner remains the default. Handoff dispatch respects the env flag.

## Scope Guardrails

DevFlow is a Kanban + LLM execution control plane. The following features are **out of scope** unless the user explicitly requests them:

**Do NOT add:**
- SecurityWeb / pentest tooling
- BGP / network security features
- Sandbox firewall / egress policy (iptables, ipset, sandbox-egress)
- Retention cleanup services
- Admin key management console
- API key rotation UI

**Next milestones (in order):**
1. ~~Kanban board + issue management~~ ✅
2. ~~Command Center (dispatch, live logs, job status)~~ ✅
3. ~~LLM Adapter layer (safe runner + ClaudeLocalAdapter)~~ ✅
4. ~~Job/Logs infrastructure~~ ✅
5. ~~Review Queue~~ ✅
6. ~~Handoff typed payload (P1.5)~~ ✅
7. ~~Issue Detail evidence display (P1.6)~~ ✅
8. ~~Artifacts v1 — typed evidence/artifact references on issues~~ ✅
9. ~~Review Gate — structured completion result with decision routing~~ ✅
10. ~~Delivery Orchestrator~~ ✅
11. ~~Real execution closed loop~~ ✅
12. Session resume schema design ✅ (spec at `docs/superpowers/specs/2026-06-06-session-resume-schema.md`, implementation deferred)

Completed spike work (admin keys, retention, sandbox egress) lives on
`archive/security-scope-spike-2026-06-03` — do not merge into mainline
without explicit user approval.

## Development Commands

Frontend:

```bash
npm run typecheck
npm run build
npm run dev
npm run preview
```

Backend:

```bash
PYTHONPATH=backend pytest -q backend/tests
PYTHONPATH=backend python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected local URLs:

- Frontend: `http://127.0.0.1:3010`
- Backend health: `http://127.0.0.1:8000/health`
- ECC jobs: `http://127.0.0.1:8000/api/v1/ecc/jobs`

## Required Verification

After backend changes:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

After frontend or TypeScript changes:

```bash
npm run typecheck
npm run build
```

After UI/data-flow changes, manually confirm:

- The board renders non-empty cards.
- Five workflow columns exist.
- Moving a card to `In Progress` creates an ECC job.
- The job status/logs are visible in the UI.
- Backend startup has no DB initialization warning.

If any command cannot run, report the exact reason and the remaining risk.

## Implementation Style

- Prefer small, reversible changes.
- Fix one failing loop at a time.
- Keep frontend/backend status/profile/harness strings aligned.
- Preserve the warm operational design from `Design.md`.
- Keep generated folders out of source control: `.nuxt`, `.output`, `e2e/.nuxt`, `node_modules`, `.pytest_cache`.
- Use tests and runtime behavior as evidence, not the presence of files.

## Completion Standard

A task is complete only when:

1. The requested user-visible behavior works.
2. Relevant tests pass.
3. Startup/runtime checks pass.
4. Any remaining risk is documented.

If the board is empty, backend tests fail, or startup prints DB errors, the project is not in a healthy state.
