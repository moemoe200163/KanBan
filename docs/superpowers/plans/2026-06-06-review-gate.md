# Review Gate — Structured Completion Result with Decision Routing

## Summary

The Review Gate is the decision point where a human reviewer approves, rejects, or requests changes on a completed handoff. It routes the issue to the appropriate next lane based on the decision, and syncs issue status accordingly.

## Architecture

### Decision Routing

| Decision | New Handoff Status | Issue Status | Next Lane |
|----------|-------------------|--------------|-----------|
| `approve` | `approved` | `in_progress` (for delivery/frontend/backend/qa) | First in `lane.next_lanes` |
| `reject` | `rejected` | `backlog` | `triage` |
| `request_changes` | `rework` | `in_progress` (for originating lane) | `from_lane` (or `triage` if missing) |

### Components

- **DB**: `IssueHandoff` model has `decision`, `review_comment`, `reviewed_at`, `reviewed_by` columns
- **Service**: `HandoffService.review()` — validates decision, guards against re-review, creates routing handoffs, syncs issue status
- **API**: `POST /boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/review`
- **Frontend**: HandoffCard review actions (approve/rework/reject buttons + optional comment textarea)

### Guards

- Only `completed` handoffs can be reviewed
- Re-review is rejected (decision already set)
- Decision must be one of: `approve`, `reject`, `request_changes`

### Review Flow

1. Handoff reaches `completed` status (via `/complete` endpoint)
2. Frontend shows review action buttons when `handoff.toLane === 'review' && !handoff.decision`
3. Reviewer clicks Approve/Rework/Reject (optionally enters a comment)
4. Backend `HandoffService.review()` processes the decision:
   - Sets `decision` and new `status` on the handoff
   - Creates next handoff based on routing rules
   - Syncs issue status to match target lane
5. Frontend updates: decision badge shown, review buttons hidden

### Endpoints

```
POST /boards/{board_id}/issues/{issue_id}/handoffs/{handoff_id}/review
Body: { decision: "approve" | "reject" | "request_changes", actor?: string, comment?: string }
Response: { handoff: {...}, routing: { action, next_handoff, next_lane } }
```

### Frontend

- `HandoffCard.vue`: Shows review actions (textarea + 3 buttons) for completed review handoffs
- `HandoffSection.vue`: Handles `@review` event with confirmation dialog, calls `boardStore.reviewHandoff()`
- `board.ts`: `reviewHandoff()` action calls API, updates local state, appends routing-created next handoff

### Tests

- Backend: `test_handoff_review.py` — approve/reject/rework routing, guards, issue status sync
- Backend: `test_handoffs_api.py` — API-level review tests, approve auto-route test
- E2E: `e2e/review-gate.spec.ts` — approve and rework flows in browser

## What's NOT in Scope

- ML-based routing (intentionally excluded)
- Multiple review rounds (single review per handoff)
- Review delegation or escalation
