# Issue Detail — Evidence Display (HandoffCard scope) Design

**Date:** 2026-06-04
**Sprint:** P1.6 (follow-up to P1.5 Handoff Completion Metadata)
**Scope:** Display-only sprint. One component template + script change, two new e2e tests.
**Status:** Approved

---

## 1. Goal

Make completed handoff evidence (typed payload values, completion actor, completion
timestamp) visible inside the existing Issue Detail panel so that a reviewer can
see *what was actually delivered* on a handoff — not just the handoff's status
badge and lane.

The "evidence" surface lives **inside `HandoffCard.vue`** on the existing
`Handoffs` tab. It is **collapsed by default**, **shown only for completed
handoffs**, and is **component-local state** (no Pinia, no new tab, no global
panel). This is a surgical UI addition — not an evidence chain refactor.

This sprint is the **first slice** of the evidence chain. P2 (Artifacts v1) is
deferred per the user's roadmap; the spec leaves a typed seam so the next
sprint can attach artifact refs without breaking the display contract.

## 2. Non-Goals

Explicitly out of scope for this sprint:

- **No new tab, no new panel, no global Evidence section.** Evidence is a
  HandoffCard-internal collapsible region.
- **No Pinia state.** Toggle expanded/collapsed is `ref(false)` inside
  `HandoffCard.vue`.
- **No store changes.** `useBoardStore` is untouched. `Handoff` type untouched.
- **No HandoffSection.vue changes** beyond what's already shipped (explicit
  HandoffCard import, JSON.parse on list fields, structured 422 display).
- **No IssueDetail.vue changes** — the existing `Handoffs` tab keeps its layout.
- **No API / backend changes.** All data shown already exists on the
  `Handoff` payload and `completedBy` / `completedAt` fields.
- **No P2 Artifacts storage, model, or API.** Spec leaves a typed seam; the
  shape is not wired through.
- **No new validation, no schema edits, no typed-payload changes.** P1.5's
  payload contracts are the data source; we are read-only rendering.
- **No CSS framework changes.** Reuse the existing Tailwind utility classes
  already in `HandoffCard.vue` (zinc palette, `text-[10px]` / `text-[11px]`
  sizing, `rounded-md` / `rounded` radii).
- **No i18n, no theme tweaks, no design-quality pass.** This is a data
  visibility fix, not a polish pass.

## 3. Architecture

### 3.1 Component change — `src/components/lane/HandoffCard.vue`

**Sole production-code change.** Add an evidence toggle and an evidence body
to the existing card.

#### 3.1.1 Script additions

```ts
const expanded = ref(false)  // local-only; never read by parent

// Count of payload keys drives the toggle label. Recomputed on prop change
// so a re-fetched Handoff with a populated payload refreshes the count.
const payloadKeyCount = computed(
  () => Object.keys(props.handoff.payload ?? {}).length
)

// Show the toggle only for completed handoffs that actually carry
// typed-completion payload. accepted / in_progress / blocked / cancelled /
// pending are intentionally NOT eligible — they have no "evidence" to show.
const showEvidenceToggle = computed(
  () => props.handoff.status === 'completed' && payloadKeyCount.value > 0
)
```

No emits are added. The card still only emits the existing
`accept | dispatch | complete | block | unblock | cancel` events.

#### 3.1.2 Template additions

Inserted **between** the existing payload-keys chips (current lines 73–84)
and the action buttons (current lines 87–131). Placement: just below the
chips, just above the action buttons. This keeps the card's visual order as
`header → block reason → keys → evidence toggle → evidence body → actions`.

```vue
<!-- Evidence toggle (completed handoffs only) -->
<button
  v-if="showEvidenceToggle"
  type="button"
  data-testid="handoff-evidence-toggle"
  class="w-full mb-2 flex items-center justify-between px-2 py-1 rounded
         bg-zinc-800/60 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200
         text-[11px] transition-colors"
  :aria-expanded="expanded"
  @click="expanded = !expanded"
>
  <span>{{ expanded ? 'Hide evidence' : `View evidence (${payloadKeyCount} fields)` }}</span>
  <span aria-hidden="true">{{ expanded ? '−' : '+' }}</span>
</button>

<!-- Evidence body (only when expanded) -->
<div
  v-if="showEvidenceToggle && expanded"
  data-testid="handoff-evidence-body"
  class="mb-2 rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1.5"
>
  <div
    v-for="(value, key) in handoff.payload"
    :key="key"
    class="text-[11px]"
  >
    <div class="text-zinc-500 mb-0.5">{{ key }}</div>

    <!-- list[str] (e.g. screenshots, interfaces, acceptance_criteria) -->
    <ul
      v-if="Array.isArray(value)"
      class="list-disc list-inside text-zinc-300 space-y-0.5"
    >
      <li v-for="(item, i) in value" :key="i">{{ item }}</li>
    </ul>

    <!-- number (e.g. coverage_pct) -->
    <div v-else-if="typeof value === 'number'" class="text-zinc-300">
      {{ value }}{{ key === 'coverage_pct' ? '%' : '' }}
    </div>

    <!-- long string (>= 280 chars OR contains newline) -->
    <div
      v-else-if="typeof value === 'string' && (value.length >= 280 || value.includes('\n'))"
      class="text-zinc-300 max-h-48 overflow-y-auto whitespace-pre-wrap
             bg-zinc-950/40 rounded p-1.5 border border-zinc-800/60"
    >{{ value }}</div>

    <!-- short string -->
    <div v-else-if="typeof value === 'string'" class="text-zinc-300">
      {{ value }}
    </div>

    <!-- fallback (boolean, null, object) -->
    <div v-else class="text-zinc-300">{{ String(value) }}</div>
  </div>
</div>
```

Notes on the rendering rules:

- **Array values use `<ul>`**, never `JSON.stringify`. This is the explicit
  constraint from the user (option B's spec note).
- **Long strings (>= 280 chars OR multiline)** get `max-h-48 overflow-y-auto`
  with `whitespace-pre-wrap` so diffs and design notes stay readable without
  breaking the card's vertical layout. We do NOT clamp / truncate — the
  evidence must remain complete; users can scroll.
- **Short strings** render inline.
- **`coverage_pct`** gets a `%` suffix because the Pydantic schema constrains
  it to `int(0..100)` and the unit is meaningful.
- **Boolean / null / object** fall back to `String(value)` so we never throw
  on a weird payload shape.

The existing `payload-keys` chips (current lines 73–84) are **left in place**
on all statuses. They are an at-a-glance hint ("here are the fields the user
typed"), distinct from the new evidence body which shows the *values*. Both
serve different readability needs and there is no visual collision because
the chips are small zinc-800 pills, the evidence body is a bordered block
with section dividers.

### 3.2 Data seam for P2 Artifacts (deferred)

The spec reserves a typed seam on the `Handoff` aggregate. The seam is
**shape-only** — no API, no storage, no fetch logic is added in this sprint.

```ts
// src/types/handoffs.ts (NOT ADDED THIS SPRINT — recorded for P2)
export interface ArtifactRef {
  id: string
  kind: 'screenshot' | 'diff' | 'log' | 'document'
  href: string           // backend route or external URL
  label?: string
  createdAt: string
}

export interface IssueEvidence {
  handoffs: Handoff[]
  artifacts: ArtifactRef[]
}
```

When P2 lands, the evidence body in `HandoffCard.vue` will gain an optional
sibling block reading from `IssueEvidence.artifacts` filtered by
`handoffId === handoff.id`. **This is not implemented now** — the seam is
recorded so the P2 designer knows the consumer is a `HandoffCard`-local
collapsible body, not a global panel.

### 3.3 Files changed

| File | Change |
|---|---|
| `src/components/lane/HandoffCard.vue` | + `ref`, + `computed`, + toggle button, + body block, + 3 helper templates (array / long-string / fallback) |
| `e2e/handoff-completion.spec.ts` | + 2 new tests (see §5) |

No other production files change. No store, no API, no type file, no other
component.

## 4. Data flow

User opens Issue Detail panel → IssueDetail renders HandoffSection →
HandoffSection's `v-for` renders one HandoffCard per handoff. For each
completed handoff with non-empty payload:

1. `showEvidenceToggle` evaluates `true`.
2. `expanded` defaults to `false`, so the toggle is visible and the body
   is hidden.
3. User clicks the toggle. `expanded` flips to `true`. Body renders the
   payload key/value list with type-aware formatting.
4. User clicks again. `expanded` flips back to `false`. Body disappears.

No data is fetched, re-fetched, or transformed. Everything is read straight
from the existing `Handoff` prop. State is component-local. Refreshing the
issue or switching tabs and back will reset `expanded` to `false` (the
component remounts or the `ref` re-initializes). This is intentional —
expansion is a transient interaction state, not a persistent preference.

## 5. E2E coverage

Two new tests in `e2e/handoff-completion.spec.ts`, file-scoped to the desktop
project (the existing tests in this file already `test.skip(isMobile, ...)`
for the same reason).

### 5.1 `completed handoff shows View evidence toggle and expands`

```ts
test('completed handoff shows View evidence toggle and expands', async ({
  page, request, isMobile
}) => {
  test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

  // 1. Seed: issue + handoff + accept + complete with a typed payload
  //    that exercises both string and list[str] field rendering.
  const title = `E2E handoff evidence ${Date.now()}`
  const issue = await createIssue(request, { title, profile: 'frontend' })
  const handoff = await createAcceptedHandoff(request, issue.id, 'frontend')
  await request.post(
    `http://127.0.0.1:8000/api/v1/boards/board-default/issues/${issue.id}/handoffs/${handoff.id}/complete`,
    {
      data: {
        actor: 'e2e',
        payload: {
          diff_summary: 'Adds the evidence toggle to HandoffCard.',
          screenshots: ['shot-1.png', 'shot-2.png']
        }
      }
    }
  )

  // 2. Open the issue via the e2e store hook (see §6 for the UX bug
  //    note on why we don't click the card).
  await page.goto('/')
  await openIssueAndSwitchToHandoffsTab(page, issue.id)

  // 3. Toggle visible, body hidden by default
  const toggle = page.getByTestId('handoff-evidence-toggle')
  await expect(toggle).toBeVisible()
  await expect(toggle).toContainText('View evidence (2 fields)')
  await expect(page.getByTestId('handoff-evidence-body')).toHaveCount(0)

  // 4. Click to expand
  await toggle.click()
  const body = page.getByTestId('handoff-evidence-body')
  await expect(body).toBeVisible()
  await expect(body).toContainText('diff_summary')
  await expect(body).toContainText('Adds the evidence toggle to HandoffCard.')
  await expect(body).toContainText('screenshots')
  await expect(body).toContainText('shot-1.png')
  await expect(body).toContainText('shot-2.png')

  // 5. Click again to collapse
  await toggle.click()
  await expect(page.getByTestId('handoff-evidence-body')).toHaveCount(0)
  await expect(toggle).toContainText('View evidence (2 fields)')
})
```

### 5.2 `non-completed handoff hides evidence toggle`

```ts
test('non-completed handoff hides evidence toggle', async ({
  page, request, isMobile
}) => {
  test.skip(isMobile, 'handoff detail flow is covered in the desktop project')

  // Seed: issue + handoff + accept, do NOT complete.
  const title = `E2E handoff no evidence ${Date.now()}`
  const issue = await createIssue(request, { title, profile: 'frontend' })
  await createAcceptedHandoff(request, issue.id, 'frontend')

  await page.goto('/')
  await openIssueAndSwitchToHandoffsTab(page, issue.id)

  await expect(
    page.getByTestId('handoff-evidence-toggle')
  ).toHaveCount(0)
})
```

### 5.3 What is NOT covered by e2e

- Long-string scroll behavior — visual / CSS-only, no DOM event to assert.
- P2 artifacts block — not implemented.
- Multiple completed handoffs in one issue each expanding independently —
  covered by per-card `ref` isolation; if it ever breaks, the existing
  e2e for the form-opening flow (one handoff per issue) is sufficient
  signal. Adding a "two completed handoffs expand independently" test is
  YAGNI for this sprint.

## 6. Out of scope — UX issues to track (not fixed here)

The current e2e suite opens issues via the `__DEVFLOW_E2E__.store.selectIssue`
hook instead of clicking the card. The reason is a real layout / pointer-
routing bug: with many seeded issues, the kanban columns container and
the review-queue overlay can sit on top of an issue card's bounding box
and intercept the click. `dependency.spec.ts` already documents the same
workaround.

**This is not a test methodology preference — it is a layout bug.** This
sprint keeps the workaround because:
- The P1.5 / evidence-display feature itself is not on the card click path.
- Fixing overlay z-order / pointer-events is a separate concern with its
  own blast radius (review queue, drag-and-drop, command center drawer).

The bug should be tracked for the **next sprint** as a layout pass, with
its own spec. Likely surfaces: review-queue overlay z-index, board column
container `pointer-events`, draggable column drop-zones. No fix is
attempted in this sprint.

## 7. Completion standard

The sprint is complete when:

1. `src/components/lane/HandoffCard.vue` renders the toggle + body per §3.1.
2. `npm run typecheck` passes.
3. `npm run build` passes.
4. `npm run e2e` reports `35 passed` (the pre-sprint baseline) **plus the
   two new tests in §5**, with no regressions. Mobile skips remain at
   `11 skipped` (the pre-sprint baseline).
5. `PYTHONPATH=backend pytest -q backend/tests` still passes (sanity check
   that no incidental backend touch happened).
6. The "View evidence" toggle is visually verified in a running preview
   server against a completed frontend handoff. The body shows diff_summary
   as a string and screenshots as a 2-item list.

The card-click overlay bug from §6 is **explicitly NOT a completion blocker**
for this sprint; it is tracked as a follow-up.
