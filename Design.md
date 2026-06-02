# DevFlow Design Specification

DevFlow is an AI delivery control plane: a Kanban board that turns human workflow decisions into agent dispatch, quality gates, and review loops. The interface should feel like an operations cockpit for senior engineers, not a generic Jira clone and not a marketing page.

This document is the product and visual design source of truth for the current rebuild.

## 1. Product Positioning

DevFlow combines three layers:

1. **Kanban interaction layer**: humans create, triage, drag, review, unblock, and finish issues.
2. **Backend control-plane layer**: FastAPI receives state changes, validates workflow transitions, and dispatches automation jobs.
3. **AI execution layer**: ECC-compatible commands map issues to agent profiles, harnesses, quality gates, and review outcomes.

The board is not merely a status tracker. Moving a card is an operational command.

## 2. Design Direction

The target mood is **warm operational editorial**:

- Warm cream canvas for the main work area.
- Dark compact sidebar for control-plane navigation and runtime status.
- Coral as the primary action and execution accent.
- Sage, dusty blue, amber, and clay red for semantic workflow states.
- Dense but readable information layout.
- No oversized hero sections, decorative blobs, marketing cards, or empty visual spectacle.

The UI should read as "Claude-inspired" in warmth and restraint, while remaining a practical developer tool.

## 3. Core UX Principles

### Board First

The first screen must be the usable Kanban board. DevFlow should not open on a landing page, product pitch, or onboarding hero.

### Every Visible Element Has Work To Do

Sidebar items, metrics, filters, issue chips, and badges should communicate runtime state or enable a workflow. Avoid decorative labels and repeated explanatory copy.

### Dense, Not Cramped

This is an operations tool. It should support scanning many cards quickly, but text must never overlap, overflow its controls, or resize layouts unpredictably.

### State Changes Are Commands

Dragging a card to `In Progress` is not cosmetic. It dispatches an ECC job. Dragging to `Human Review` implies verification and decision. Dragging to `Done` implies release readiness.

### Human Review Stays Explicit

AI may execute and summarize, but the interface must preserve a clear human decision stage before completion.

## 4. Visual System

### Color Tokens

Use the tokens in `src/assets/css/main.css` as the implementation source of truth.

```css
--canvas: #f4f2ed;
--surface-soft: #ebe7de;
--surface-card: #ffffff;
--surface-cream-strong: #ded8cc;

--surface-dark: #181715;
--surface-dark-elevated: #252320;
--surface-dark-soft: #1f1e1b;

--primary: #cc785c;
--primary-hover: #d4896a;
--primary-active: #a9583e;

--sage: #7D9E7D;
--dusty-blue: #6B8BA4;
--amber: #D4A84B;
--clay-red: #B85C4D;

--ink: #171615;
--body: #3f3b36;
--muted: #69635b;
--muted-soft: #8b8479;
--hairline: #ddd7ce;
```

### Usage Rules

- Main board uses `--canvas` and `--surface-card`.
- Sidebar uses `--sidebar-bg`, `--sidebar-surface`, and `--sidebar-panel`.
- Primary actions use coral.
- Running/active execution uses coral.
- Done/success uses sage.
- Human review uses dusty blue.
- Blocked/warning uses amber or clay red depending on severity.
- Do not let the UI collapse into a single beige, brown, purple, or slate palette.

## 5. Typography

Implementation fonts:

```css
--font-display: "Outfit", sans-serif;
--font-body: "Source Sans 3", sans-serif;
--font-mono: "JetBrains Mono", monospace;
```

Usage:

- `Outfit`: page titles, sidebar brand, section headings.
- `Source Sans 3`: cards, buttons, body text, forms.
- `JetBrains Mono`: issue keys, command names, metadata, webhook/event labels.

Rules:

- Do not scale font size with viewport width.
- Letter spacing should stay neutral except small uppercase metadata labels.
- Long titles clamp instead of stretching cards.
- Buttons must keep labels legible at mobile widths.

## 6. App Shell

### Desktop Structure

```text
┌────────────────────┬──────────────────────────────────────────┐
│ AppSidebar          │ KanbanBoard                              │
│ - Brand             │ - Topbar                                 │
│ - Workspace nav     │ - Runtime metrics                        │
│ - Control status    │ - Search and filters                     │
│ - Harness selector  │ - Kanban lanes                           │
└────────────────────┴──────────────────────────────────────────┘
```

### Sidebar Requirements

The sidebar is a control-plane rail, not just navigation.

Required content:

- DevFlow brand and "AI Control Plane" subtitle.
- Workspace navigation: Board, Backlog, Agents, Runs, Webhooks, Analytics, Settings.
- Backend status.
- Active runs count.
- Human review count.
- Blocked count.
- Current harness.
- Theme toggle.

Sidebar behavior:

- Fixed full-height on desktop.
- Compact icon rail on tablet/narrow widths.
- Never cover board content.
- Buttons use icons from `lucide-vue-next`.

## 7. Kanban Board

### Required Lanes

| Status | Label | Purpose |
|---|---|---|
| `backlog` | Backlog | Ideas and ready-to-triage work |
| `in_progress` | In Progress | Agent or human execution is active |
| `blocked` | Blocked | Dependency, runtime, budget, or failure stop |
| `human_review` | Human Review | Verification and approval required |
| `done` | Done | Accepted and complete |

### Board Topbar

Required:

- Workspace breadcrumb.
- Board title.
- Visible issue count.
- Local/backend connection pill.
- New issue button.

### Metrics Row

Required tiles:

- Active Runs.
- Human Review.
- Blocked.
- Harness.

These tiles must be compact and functional, not decorative cards.

### Toolbar

Required:

- Search by issue key, title, or label.
- Status filter.
- Priority filter.
- Reset filters button.
- Agent readiness/running indicator.

## 8. Issue Card

Issue cards must be dense, scannable, and stable in height.

Required fields:

- Issue key.
- Title, clamped to two lines.
- Priority indicator.
- Profile or agent category.
- Harness when relevant.
- Labels.
- Assignee or AI ownership.
- Story points.
- Dependency count.
- AI status.
- PR/CI hints when available.

Card states:

- Hover: subtle border and elevation.
- Dragging: lifted state with stable dimensions.
- Running: clear AI status marker.
- Blocked: warning marker and stronger border.
- Review: dusty-blue review marker.

Cards emit selection events explicitly. Clicking a card opens the detail panel.

## 9. Issue Detail Panel

The detail panel is a right-side slide-over for deep inspection and action.

Required sections:

- Header with issue key, status badge, close button.
- Title and description.
- Metadata: assignee, priority, story points, profile, harness.
- Labels and dependencies.
- AI execution status.
- Activity timeline.
- PR/CI information when available.
- Quick actions for status transitions.

Behavior:

- Opens from card click.
- Closes with close button and Escape.
- Does not block board scrolling on desktop.
- On mobile, becomes full-width or near full-width.

## 10. AI/ECC Workflow Mapping

Board movement maps to control-plane commands:

| Board Action | Command Intent | Expected Backend Endpoint |
|---|---|---|
| Move to `in_progress` | Start agent execution loop | `POST /api/v1/ecc/dispatch` |
| Move to `blocked` | Pause or mark stopped | Future: pause endpoint |
| Move to `human_review` | Run verification gate | Future: quality endpoint |
| Move to `done` | Mark release-ready | Future: release endpoint |
| Move back to `backlog` | Reset/triage | Future: reset endpoint |

Dispatch payload should include:

```json
{
  "issue_id": "issue-id",
  "issue_key": "DEV-142",
  "command": "/loop-start --profile=frontend",
  "profile": "frontend",
  "harness": "codex"
}
```

Frontend runtime config:

```ts
runtimeConfig.public.apiBase = "http://127.0.0.1:8000/api/v1"
```

Local frontend port:

```text
http://127.0.0.1:3010/
```

Local backend port:

```text
http://127.0.0.1:8000/
```

## 11. Backend Control Plane

Backend responsibilities:

- Expose health and readiness endpoints.
- Validate issue status values.
- Validate profile and harness values.
- Accept ECC dispatch requests.
- Return stable job IDs.
- Maintain job status until a durable queue is introduced.
- Provide API contracts that match frontend types.

Current accepted issue statuses:

```text
backlog
in_progress
blocked
human_review
done
```

Current accepted profiles:

```text
frontend
backend
security
refactor
debug
general
```

## 12. Responsive Rules

Desktop:

- Sidebar visible.
- Board columns scroll horizontally when needed.
- Columns retain stable min width.

Tablet:

- Sidebar compresses to icon rail.
- Toolbar wraps without overlap.
- Metrics become a smaller grid.

Mobile:

- Board area scrolls vertically.
- Kanban columns remain usable and must not collapse to tiny height.
- Detail panel becomes full-width.
- Buttons preserve icons and readable labels.

Hard rule: no text overlap, no hidden primary controls, no 8px-tall board column collapse.

## 13. Accessibility

Minimum requirements:

- Buttons have visible focus states.
- Icon-only buttons have `title` or `aria-label`.
- Selects have `aria-label`.
- Text contrast must pass practical readability on both light and dark modes.
- Card selection should be keyboard reachable in a future pass.
- Drag-and-drop must eventually have keyboard alternatives.

## 14. Implementation Boundaries

Use existing stack:

- Nuxt 3 / Vue 3.
- Pinia.
- `vuedraggable`.
- `lucide-vue-next`.
- FastAPI.
- Pytest for backend smoke tests.
- Nuxt typecheck and production build for frontend verification.

Do not add a new UI framework unless the existing stack cannot satisfy a specific requirement.

## 15. Verification Checklist

Before considering a UI/control-plane change complete:

- `npm run typecheck` passes.
- `npm run build` passes.
- `PYTHONPATH=backend pytest -q backend/tests` passes.
- Frontend opens at `http://127.0.0.1:3010/`.
- Backend opens at `http://127.0.0.1:8000/`.
- Board renders issue cards.
- Sidebar renders and remains usable at desktop and mobile widths.
- Clicking an issue card opens the detail panel.
- Moving a card to `In Progress` attempts ECC dispatch.
- If backend is unavailable, frontend degrades gracefully with local telemetry.
- Mobile layout does not collapse columns or hide primary actions.

## 16. Near-Term Roadmap

### Phase 1: Stabilize The Fire

- Fix build/type errors.
- Align frontend/backend status contracts.
- Rebuild app shell, sidebar, board, columns, and cards.
- Add backend smoke tests.
- Verify locally.

### Phase 2: Real Control Plane

- Replace in-memory ECC job registry with durable queue/storage.
- Add job cancellation and pause.
- Add quality-gate endpoint.
- Add CI/PR status ingestion.
- Persist issues instead of relying only on seeded client state.

### Phase 3: Agent Operations

- Add real ECC process runner.
- Add budget/runtime enforcement.
- Add logs and streamed job output.
- Add review summaries and failed-test drilldown.
- Add audit trail for every AI-triggered change.

### Phase 4: Production Readiness

- Add authentication.
- Add workspace/project isolation.
- Add Tailscale deployment profile.
- Add GitHub integration.
- Add end-to-end browser tests for board flows.

## 17. Non-Goals

For the current rebuild, do not prioritize:

- Marketing landing pages.
- Multi-tenant SaaS billing.
- Custom vector memory infrastructure.
- Replacing ECC with a bespoke agent framework.
- Decorative illustration systems.

The priority is a coherent, usable AI Kanban control plane.
