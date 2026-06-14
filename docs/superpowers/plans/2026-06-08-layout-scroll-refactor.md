# Layout & Scroll System Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a site-wide layout/scroll contract so that every page and module has a clear scroll container — eliminating content truncation, broken scroll wheels, and inconsistent viewport behavior.

**Architecture:** App Shell (`app.vue`) owns a fixed viewport grid (`100dvh`, `overflow: hidden`). Each page opts into either "page scroll" or "module scroll" via shared CSS utility classes. No page sets its own `height: 100vh`. Shared classes (`page-shell`, `scroll-area`, `module-shell`) live in `main.css`. Each page is updated to use these classes instead of ad-hoc `100vh`/`overflow` rules.

**Tech Stack:** Vue 3 / Nuxt 3 (SPA mode), scoped CSS, CSS custom properties.

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|---------------|
| `src/assets/css/main.css` | Modify | Add shared layout contract classes + scrollbar tokens |
| `src/app.vue` | Modify | App shell: `height: 100dvh`, `min-height: 0`, `overflow: hidden` |
| `src/components/sidebar/Sidebar.vue` | Modify | Sidebar: `height: 100dvh`, internal scroll via `.sidebar__content` |
| `src/components/KanbanBoard.vue` | Modify | Board: remove `height: 100vh`, use `page-shell`, columns use `overflow-x: auto` |
| `src/components/KanbanColumn.vue` | Verify | Column cards already use `overflow-y: auto` (no change expected) |
| `src/pages/index.vue` | Modify | Board wrapper: use `page-shell` |
| `src/pages/command-center.vue` | Modify | Two-column scroll: page scroll + column module scroll |
| `src/pages/agents.vue` | Modify | Tabs fixed, matrix/roles scroll |
| `src/pages/runtime.vue` | Modify | Tabs fixed, workers page scroll, runs split scroll |
| `src/pages/backlog.vue` | Modify | Simple page scroll |
| `src/pages/runs.vue` | Modify | Simple page scroll |
| `src/pages/analytics.vue` | Modify | Simple page scroll |
| `src/pages/activity.vue` | Modify | Simple page scroll |
| `src/pages/settings/index.vue` | Modify | Simple page scroll |
| `src/pages/settings/webhooks.vue` | Modify | Add page-shell wrapper for consistency |
| `src/pages/games/snake.vue` | Verify | Canvas fixed, settings scroll (verify only) |
| `src/components/IssueDetail.vue` | Verify | Drawer: header/footer fixed, body scroll (verify only) |
| `src/components/common/JobDetailDrawer.vue` | Verify | Drawer: `max-height: calc(100dvh - 40px)`, body scroll (verify only) |

---

## Task 1: Add shared layout contract classes to `main.css`

**Files:**
- Modify: `src/assets/css/main.css:94-159` (after `:root` vars, before typography)

- [ ] **Step 1: Add layout contract CSS classes**

Append after the existing scrollbar rules (line ~151) in `src/assets/css/main.css`:

```css
/* ==========================================================================
   Layout Contract — Shared scroll/layout utilities
   ========================================================================== */

/* Page Shell — standard full-viewport page wrapper */
.page-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
}

/* Page Shell with page-level scroll (most pages) */
.page-shell--scroll {
  overflow-y: auto;
}

/* Page Shell without page-level scroll (board, command-center module scroll) */
.page-shell--clip {
  overflow: hidden;
}

/* Scroll Area — reusable scrollable region inside a page/module */
.scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* Module Shell — a card/section that contains its own scroll */
.module-shell {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.module-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* Sticky header/toolbar that should not scroll away */
.page-header {
  flex-shrink: 0;
}

/* Ensure 100dvh support (fallback for older browsers) */
@supports not (height: 100dvh) {
  .page-shell {
    height: 100vh;
  }
}
```

- [ ] **Step 2: Update body/html to use 100dvh**

In `src/assets/css/main.css`, change `body` rule (line ~109-118):

```css
body {
  font-family: var(--font-body);
  background-color: var(--canvas);
  color: var(--ink);
  line-height: 1.6;
  min-height: 100dvh;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

- [ ] **Step 3: Verify no visual regression**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/assets/css/main.css
git commit -m "feat(layout): add shared scroll/layout contract classes to main.css"
```

---

## Task 2: Refactor App Shell (`app.vue`) to use `100dvh`

**Files:**
- Modify: `src/app.vue:28-67`

- [ ] **Step 1: Update `.app-shell` and `.app-shell__main` CSS**

Replace the existing `.app-shell` and `.app-shell__main` rules in `src/app.vue`:

```css
.app-shell {
  --sidebar-w: 260px;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  height: 100dvh;
  background:
    radial-gradient(circle at top left, rgba(204, 120, 92, 0.08), transparent 30rem),
    var(--canvas);
  color: var(--ink);
}

.app-shell--sidebar-collapsed {
  --sidebar-w: 64px;
}

.app-shell__main {
  min-width: 0;
  min-height: 0;
  height: 100dvh;
  overflow: hidden;
}

@media (max-width: 920px) {
  .app-shell {
    --sidebar-w: 64px;
  }
  .app-shell--sidebar-collapsed {
    --sidebar-w: 64px;
  }
}

@media (max-width: 640px) {
  .app-shell {
    --sidebar-w: 0px;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  }
  .app-shell--sidebar-collapsed {
    --sidebar-w: 0px;
  }
}
```

Key changes:
- `min-height: 100vh` → `height: 100dvh` on `.app-shell` (exact fit, not min)
- `.app-shell__main`: `min-height: 100vh` → `height: 100dvh; min-height: 0` (allows children to fill exactly)

- [ ] **Step 2: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/app.vue
git commit -m "fix(layout): app shell uses 100dvh for exact viewport fit"
```

---

## Task 3: Refactor Sidebar to use `100dvh` and `min-height: 0`

**Files:**
- Modify: `src/components/sidebar/Sidebar.vue:290-304`

- [ ] **Step 1: Update sidebar root CSS**

Change the `.sidebar` rule:

```css
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  min-height: 0;
  width: var(--sidebar-w, 260px);
  padding: 18px 14px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  color: var(--sidebar-text);
  overflow: hidden;
  transition: width var(--duration-normal) var(--ease-out);
}
```

Key change: `height: 100vh` → `height: 100dvh; min-height: 0`.

- [ ] **Step 2: Verify `.sidebar__content` already has `overflow-y: auto`**

Read `src/components/sidebar/Sidebar.vue` around line 380-390 to confirm `.sidebar__content` has `overflow-y: auto`. This should already be correct from the existing code.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/components/sidebar/Sidebar.vue
git commit -m "fix(layout): sidebar uses 100dvh for mobile viewport consistency"
```

---

## Task 4: Refactor Kanban Board (`index.vue` + `KanbanBoard.vue`)

**Files:**
- Modify: `src/components/KanbanBoard.vue:163-172`
- Verify: `src/components/KanbanColumn.vue` (column cards scroll)

- [ ] **Step 1: Update `.kanban-board` to use `page-shell page-shell--clip`**

Replace the `.kanban-board` rule in `src/components/KanbanBoard.vue`:

```css
.kanban-board {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 14px;
  overflow: hidden;
}
```

Key changes:
- `height: 100vh` → `height: 100%` (inherits from `.app-shell__main`)
- Added `min-height: 0` for flex child behavior

- [ ] **Step 2: Verify `.kanban-board__columns` already has correct scroll**

Read `src/components/KanbanBoard.vue` around lines 375-390. The columns container should already have:
- `overflow-x: auto` (horizontal scroll)
- `flex: 1; min-height: 0` (fills remaining space)

- [ ] **Step 3: Verify `.kanban-column__cards` already has `overflow-y: auto`**

Read `src/components/KanbanColumn.vue` around lines 247-254. Should already have per-column vertical scroll.

- [ ] **Step 4: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/KanbanBoard.vue
git commit -m "fix(layout): board uses height 100% instead of 100vh for viewport fit"
```

---

## Task 5: Refactor all standard pages (backlog, runs, analytics, activity, settings)

These pages all share the same current pattern: `height: 100vh; overflow-y: auto`. They all become `height: 100%; overflow-y: auto` (or equivalently, keep `overflow-y: auto` and just fix the height).

**Files:**
- Modify: `src/pages/backlog.vue:72-78`
- Modify: `src/pages/runs.vue:146-148`
- Modify: `src/pages/analytics.vue:371-373`
- Modify: `src/pages/activity.vue:224-226`
- Modify: `src/pages/settings/index.vue:522-524`

- [ ] **Step 1: Update backlog.vue**

Change the `.backlog-page` rule:

```css
.backlog-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

- [ ] **Step 2: Update runs.vue**

Change the `.runs-page` rule:

```css
.runs-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

- [ ] **Step 3: Update analytics.vue**

Change the `.analytics-page` rule:

```css
.analytics-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

- [ ] **Step 4: Update activity.vue**

Change the `.activity-page` rule:

```css
.activity-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

- [ ] **Step 5: Update settings/index.vue**

Change the `.settings-page` rule:

```css
.settings-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

- [ ] **Step 6: Verify all five pages**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pages/backlog.vue src/pages/runs.vue src/pages/analytics.vue src/pages/activity.vue src/pages/settings/index.vue
git commit -m "fix(layout): standard pages use height 100% instead of 100vh"
```

---

## Task 6: Refactor Command Center page (module scroll)

**Files:**
- Modify: `src/pages/command-center.vue:44-95`

- [ ] **Step 1: Update `.command-center` page shell**

The command center has two columns that scroll independently. The page itself should NOT scroll. Change:

```css
.command-center {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow: hidden;
}
```

Key change: `height: 100vh` → `height: 100%`, `overflow: auto` → `overflow: hidden` (columns scroll independently).

- [ ] **Step 2: Verify `.command-center__col` already has `overflow-y: auto`**

Read `src/pages/command-center.vue` around lines 89-100. Each column should already have `overflow-y: auto` for independent scrolling.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/pages/command-center.vue
git commit -m "fix(layout): command center uses height 100% with module-level scroll"
```

---

## Task 7: Refactor Agents page (tabs fixed, content scroll)

**Files:**
- Modify: `src/pages/agents.vue:192-194`

- [ ] **Step 1: Update `.agents-page`**

Change:

```css
.agents-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: 22px;
  gap: 18px;
  overflow-y: auto;
}
```

Key change: `height: 100vh` → `height: 100%`.

- [ ] **Step 2: Verify matrix/roles scroll regions**

Read `src/pages/agents.vue` around lines 217-254. The matrix and roles sections should already have `overflow-x: auto` for horizontal scroll. If the tabs header needs to be sticky, it should have `position: sticky; top: 0; z-index: 1` (verify — this is a nice-to-have, not a blocker).

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/pages/agents.vue
git commit -m "fix(layout): agents page uses height 100% instead of 100vh"
```

---

## Task 8: Refactor Runtime page (split scroll)

**Files:**
- Modify: `src/pages/runtime.vue:255-259, 434-439`

- [ ] **Step 1: Update `.runtime-page` root**

Change:

```css
.runtime-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: var(--space-6);
  gap: var(--space-4);
  overflow-y: auto;
}
```

Key change: `height: 100vh` → `height: 100%`.

- [ ] **Step 2: Fix the runs tab grid height**

The runs tab uses `height: calc(100vh - 280px)`. Change to:

```css
.runtime-runs-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}
```

Replace the hardcoded `calc(100vh - 280px)` with `flex: 1; min-height: 0` so it fills remaining space naturally.

- [ ] **Step 3: Verify run list and log panel scroll**

Read the run list and log panel CSS to confirm `overflow-y: auto` is set on each.

- [ ] **Step 4: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pages/runtime.vue
git commit -m "fix(layout): runtime page uses height 100% and flex-based split scroll"
```

---

## Task 9: Refactor Settings/Webhooks page

**Files:**
- Modify: `src/pages/settings/webhooks.vue` (around line 542-543)

- [ ] **Step 1: Add page-shell wrapper**

The webhooks page currently has no `height` or `overflow` rule (it just uses padding). It should follow the same pattern as other pages. Find the root element in the template and ensure its CSS class includes:

```css
.webhooks-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  padding: var(--space-6);
  gap: var(--space-6);
  overflow-y: auto;
}
```

If a `.webhooks-page` class doesn't exist, add one to the root element's class list and add the corresponding scoped style.

- [ ] **Step 2: Verify the webhook edit/add modal**

Read the modal section (around lines 896-953). It should already have:
- `max-height: 90vh` (or change to `calc(100dvh - 40px)`)
- `overflow: hidden` on the modal container
- `overflow-y: auto` on the modal body

If `max-height: 90vh` is found, change to `max-height: calc(100dvh - 40px)` for consistency.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/pages/settings/webhooks.vue
git commit -m "fix(layout): webhooks page uses page-shell pattern, modal uses 100dvh"
```

---

## Task 10: Update scrollbar tokens for dark mode + unify width

**Files:**
- Modify: `src/assets/css/main.css:133-150`

- [ ] **Step 1: Add dark mode scrollbar styles**

After the existing light scrollbar rules, add dark mode overrides:

```css
/* Custom Scrollbar — Dark theme */
.dark ::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
}

.dark ::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.25);
}

/* Firefox scrollbar styling */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--hairline) transparent;
}

.dark * {
  scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
}
```

- [ ] **Step 2: Verify scrollbar width is consistent (6px)**

The existing `::-webkit-scrollbar` already sets `width: 6px`. Confirm no page overrides this to a different value.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/assets/css/main.css
git commit -m "feat(layout): unify scrollbar styling for light/dark modes"
```

---

## Task 11: Full regression + manual verification

- [ ] **Step 1: Typecheck**

Run: `npm run typecheck`
Expected: PASS

- [ ] **Step 2: Build**

Run: `npm run build`
Expected: PASS

- [ ] **Step 3: Dev server manual check**

Run: `npm run dev`
Open `http://127.0.0.1:3010` and verify:

1. **Board `/`** — topbar/metrics/toolbar fixed; columns horizontal scroll; each column cards vertical scroll; no content truncated at bottom
2. **Command Center `/command-center`** — page does NOT scroll; left/right columns scroll independently
3. **Agents `/agents`** — tabs stay at top; matrix/roles sections scroll
4. **Runtime `/runtime`** — stats/tabs fixed; workers grid page scroll; runs tab: run list scrolls, log panel scrolls
5. **Backlog `/backlog`** — full page vertical scroll; content reaches bottom
6. **Runs `/runs`** — toolbar sticky area; run list scrolls; long commands ellipsis
7. **Activity `/activity`** — filters area visible; timeline scrolls; pagination at bottom
8. **Analytics `/analytics`** — filters visible; KPI/chart cards scroll; wide charts horizontal scroll inside card
9. **Settings `/settings`** — full page scroll; provider cards grid adapts
10. **Webhooks `/settings/webhooks`** — page scrolls; modal opens with internal scroll
11. **Snake `/games/snake`** — canvas fixed; settings panel scrolls on small screens

- [ ] **Step 4: Responsive check**

Resize browser to:
- `1280x900` — all pages fit
- `920x1024` — sidebar collapsed to 64px, pages adapt
- `390x844` — sidebar hidden, pages scroll, no horizontal overflow

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(layout): final scroll/layout adjustments from manual verification"
```

---

## Summary of Changes Per File

| File | Change | Risk |
|------|--------|------|
| `main.css` | Add layout contract classes, dark scrollbar, 100dvh fallback | Low — additive only |
| `app.vue` | `min-height: 100vh` → `height: 100dvh` | Medium — affects all pages |
| `Sidebar.vue` | `height: 100vh` → `100dvh; min-height: 0` | Low |
| `KanbanBoard.vue` | `height: 100vh` → `100%` | Medium — board is complex |
| 5 standard pages | `height: 100vh` → `100%` + add `min-height: 0` | Low — mechanical change |
| `command-center.vue` | `overflow: auto` → `overflow: hidden` + `height: 100%` | Medium — double-check columns scroll |
| `agents.vue` | `height: 100vh` → `100%` | Low |
| `runtime.vue` | `height: 100vh` → `100%` + fix `calc(100vh - 280px)` | Medium — split layout |
| `settings/webhooks.vue` | Add page-shell pattern + modal `100dvh` | Low |
