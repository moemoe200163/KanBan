# Audit Coverage

The `audit_logs` table is the system-wide change log. Every meaningful
action — leader reviews, ECC dispatches, budget breaches, AC
mutations, archive/unarchive — writes a row there with a stable
`action` + `resource` + (optional) `resource_id` triple, so the
`GET /audit-logs?resource=X&resource_id=Y` query can reconstruct
the full history of any one object.

This file is the source of truth for *which* actions land in the
log. It is the first thing to update when adding a new write site,
and the first thing to check when an audit query returns no rows
for something the operator knows happened.

## Production write sites

| File:line | action | resource | resource_id | Triggered by |
| --- | --- | --- | --- | --- |
| `api/v1/endpoints/cycle_reports.py:394` | `cycle_report.review` | `cycle_report` | `report.id` | `POST /cycle-reports/{id}/review` (leader approve / request-changes) |
| `core/security.py:410` | `security.auth` | (none) | n/a | auth flow side-effect; rare |
| `core/budget_controller.py:286` | `budget.exceeded` | `agent` | `agent.id` | per-agent token / cost cap breach |
| `db/repository.py:1059` | (varies) | (varies) | (varies) | ECC job status transitions (`job.running`, `job.completed`, `job.failed`, etc.) |
| `db/repository.py:1079` | `ecc.dispatch` | `ecc_job` | `job.id` | `POST /ecc/dispatch` (job creation) |
| `db/repository.py:1100` | (varies) | `issue` | `issue.id` | `seed_if_empty` (dev-mode only — does not fire in production) |

## What lands in `details` and `changes`

`log_audit_event(action, resource, resource_id, details, changes)`
takes both a free-form `details` dict and a structured `changes`
dict. Convention:

- `details` — contextual metadata that *describes* the event
  (e.g. the reviewer's user id, the cycle report's parent issue,
  the LLM provider that returned a 401). Always JSON-serialisable.
- `changes` — the diff itself, when the event is a mutation
  (e.g. `{"verdict": {"from": "pending", "to": "pass"}}`). Only
  populated by endpoints that touch a specific record. Read-only
  events leave `changes={}`.

## Query patterns the UI relies on

- `GET /audit-logs?resource=cycle_report&resource_id={id}` — the
  full review history of one cycle report. The IssueDetail cycles
  tab renders this as a read-only timeline under each row.
- `GET /audit-logs?resource=issue&resource_id={id}` — the change
  history of one issue. Reserved for a future "issue history"
  panel; not yet surfaced in the UI.
- `GET /audit-logs?action=ecc.dispatch` — the dispatch ledger.
  Used by the analytics throughput calculation.

## Intentionally not logged

- **Read-only GETs.** Volume, no operator value.
- **WebSocket broadcasts.** The state change is logged by the
  endpoint that triggered the broadcast, not the broadcast itself.
- **PR / CI webhook pings that don't mutate.** 404 / 401 / 422
  responses are surfaced through the regular API error path, not
  the audit log.
- **Dev-mode `seed_if_empty` and `test_reset`.** These run only
  when the corresponding env flags are set; their audit rows
  carry `agent_name="system"` so they are filterable.

## How to add a new write site

1. Call `log_audit_event(action, resource, resource_id, details, changes)`
   from the endpoint, after the mutation succeeds and *before* the
   response is returned. `log_audit_event` is fire-and-forget; a
   failure to write the audit row must not roll back the mutation.
2. Update the table in this file with the new row.
3. If the action is reviewer-visible (leader / operator UI), add
   a `GET /audit-logs?resource=X` query hook in the relevant page.
4. Cover the new path with a row in `scripts/e2e-audit-trail.sh`.
