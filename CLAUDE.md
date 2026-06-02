# DevFlow Claude Instructions

Read this file before making changes. These rules exist because this project can easily drift into over-engineering.

## Current Mission

DevFlow is an AI Kanban control plane. The current priority is **P0 product loop stability**, not full Paperclip architecture and not multi-model infrastructure.

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

Fix these before expanding architecture:

1. `GET /api/v1/board` currently returns empty columns, so the frontend shows zero cards.
2. Backend startup has a SQLAlchemy async DB initialization warning.
3. Backend smoke tests currently fail.
4. ECC dispatch is too close to real adapter execution before the safe P0 runner is stable.
5. E2E files exist, but Playwright is not installed in `devDependencies`.
6. There are duplicate sidebar paths: `AppSidebar.vue` and `components/sidebar/Sidebar.vue`.

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

Do not prioritize these until P0 and P1 are verified:

- Codex/Cursor/Gemini/OpenCode execution.
- Paperclip-style session serialization.
- Long-running session resume.
- Autopilot scheduling.
- AgentShield/security scan automation.
- PR/CI automation.
- Full auth and API-key rollout.
- Redis queue.

Adapter classes may remain in the repo, but P0 dispatch must not depend on the full adapter system being complete.

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
