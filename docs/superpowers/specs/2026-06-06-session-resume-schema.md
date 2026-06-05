# Session Resume — Schema-Only Design

> **Status:** Schema design (no implementation)
> **Date:** 2026-06-06
> **Prerequisite:** Real execution closed loop is stable (ALLOW_REAL_LLM_EXECUTION=true works end-to-end)

## Goal

Design the database schema and data model that enables Session Resume — the ability for a failed/timed-out/cancelled run to be resumed from a checkpoint rather than restarted from scratch.

## Design Principles

1. **Adapter-agnostic schema** — the DB stores conversation history and checkpoint data; adapters decide how to use it.
2. **Provider-specific resume refs** — some providers (Claude CLI, OpenAI Assistants) have native session continuation; others (generic chat APIs) resume by replaying history.
3. **Minimal blast radius** — new table + soft-reference FK on AgentRun; no changes to existing table columns.
4. **Opt-in per adapter** — adapters that don't support resume simply ignore the session data.

## Schema Design

### 1. New Table: `agent_sessions`

Groups multiple runs into a resumable conversation.

```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String(64), primary_key=True)          # sess_<hex16>
    board_id = Column(String(64), nullable=False, default=DEFAULT_BOARD_ID, index=True)
    issue_id = Column(String(64), nullable=True, index=True)
    issue_key = Column(String(32), nullable=True)

    # Adapter config (denormalized from the originating run)
    harness = Column(String(32), nullable=True)         # claude-code, api-model, etc.
    provider = Column(String(32), nullable=True)         # openai, anthropic, minimax, etc.
    model = Column(String(128), nullable=True)           # gpt-4o, claude-sonnet-4-20250514, etc.

    # Session lifecycle
    status = Column(String(32), nullable=False, default="active", index=True)
    # active    — session is in use (a run is running)
    # paused    — run ended (completed/failed/cancelled), session can be resumed
    # completed — session finished normally, no more resumption
    # expired   — session TTL exceeded, data purged

    # Resume data
    conversation_history = Column(JSON, nullable=True, default=list)
    # Format: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    # Full message array that can be re-sent to the provider on resume.
    #
    # Storage policy (see "Conversation History Policy" section):
    # - Max size: MAX_HISTORY_BYTES (default 256KB). Truncated oldest messages when exceeded.
    # - Redaction: tool outputs and logs are NOT stored by default.
    # - Secrets: checkpoint_data and conversation_history MUST NOT contain API keys, env vars, or raw secrets.
    # - Mutation: repository functions MUST reassign the full list/dict, never in-place append/mutate.
    #   SQLAlchemy JSON columns do not track nested mutations — use session.conversation_history = new_list.

    checkpoint_data = Column(JSON, nullable=True, default=dict)
    # Adapter-specific state. Examples:
    # - Claude CLI: {"cli_session_id": "...", "cli_session_path": "/tmp/..."}
    # - OpenAI Responses: {"response_id": "resp_...", "previous_response_id": "resp_..."}
    # - Generic: {"last_prompt": "...", "partial_output": "...", "step_index": 3}
    #
    # MUST NOT contain: API keys, environment variables, secrets, or full file contents.
    # This field is for adapter state pointers only, not data storage.

    provider_resume_ref = Column(String(512), nullable=True)
    # Provider-native continuation reference (if available).
    # Claude CLI: session ID or session name for `-r` / `--resume` flag.
    #             Adapter detects CLI version and uses appropriate resume argument.
    # OpenAI Responses: response_id for chaining via previous_response_id.
    # OpenAI Assistants: thread_id (only when using Assistants API path).
    # Anthropic Messages / Generic APIs: None (resume via conversation_history replay).
    #
    # This is a reference/ID, not a secret token. It is safe to log at debug level.

    # Metadata
    total_runs = Column(Integer, nullable=False, default=1)
    total_tokens = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    # TTL
    expires_at = Column(DateTime(timezone=True), nullable=True)
    # Sessions auto-expire after this time. Default: 7 days from creation.

    extra_metadata = Column(JSON, nullable=True, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_sessions_board_status", "board_id", "status"),
        Index("ix_agent_sessions_issue", "issue_id", "status"),
    )
```

### 2. AgentRun Changes

Add one nullable column as a soft reference to `agent_sessions.id`:

```python
# On AgentRun model:
session_id = Column(String(64), nullable=True, index=True)  # soft ref to agent_sessions.id
```

**Why soft reference, not ForeignKey constraint:**
- The project uses SQLite for local dev/testing, which has limited FK support.
- The session may expire and be purged while the run still exists — FK would block deletion or require CASCADE.
- The reference is always validated at the application layer (repository functions).
- If the session is deleted, `session_id` becomes a dangling ref — the application treats it as a standalone run.

- `session_id = None` → standalone run (no resume support, current behavior)
- `session_id = "sess_xxx"` → part of a resumable session

No other AgentRun columns change.

### 3. AgentRunEvent — No Changes

AgentRunEvent is the append-only audit/log timeline. It captures execution events (status changes, errors, log lines), NOT LLM conversation data.

Resume reads `conversation_history` from `agent_sessions`, not from run events. These are separate concerns:

| Source | Purpose | Content |
|--------|---------|---------|
| `agent_sessions.conversation_history` | LLM conversation replay for resume | user/assistant message pairs |
| `agent_run_events` | Audit trail, UI timeline, debugging | status changes, errors, log lines |

Do NOT reconstruct conversation from events. Do NOT store conversation in events.

## Conversation History Policy

This section defines the storage constraints that the implementation phase must enforce.

### Size Limits

- **Max history bytes:** `MAX_HISTORY_BYTES = 256 * 1024` (256KB)
- When history exceeds this limit, the adapter/repository truncates the oldest messages, keeping the most recent context.
- A `history_truncated` boolean on the session indicates whether truncation occurred.

### What Gets Stored

- User messages and assistant messages (text content only).
- If the provider returns structured content (e.g., tool_use blocks), only the text summary is stored, not raw tool payloads.

### What Does NOT Get Stored

- Tool call outputs / tool results (these can be large and contain filesystem contents).
- Raw log lines (these belong in AgentRunEvent).
- System prompts (these are derived from adapter config, not user conversation).
- API keys, environment variables, secrets, or credentials of any kind.

### Redaction

- First implementation: no automatic redaction. The adapter is responsible for not storing secrets.
- Future: `redaction_version` integer on the session, bumped when redaction rules change.
- If a session is suspected compromised, mark status=expired and purge conversation_history.

### Expiration

- Default TTL: 7 days from creation (`expires_at = created_at + 7 days`).
- Expired sessions have `conversation_history` set to `null` and `status = "expired"`.
- A periodic cleanup job (implementation phase) deletes expired sessions.

### Encryption (future consideration)

- Not in schema-only scope. If needed later, add `encryption_key_id` column and store conversation_history encrypted at rest.
- For now, the DB file itself is the security boundary.

## Resume Flow

### Creating a Session

```
Dispatch request
  → create_run_for_dispatch(session_id=None)
  → Worker claims run
  → Worker checks: should this run have a session?
     - If adapter.supports_resume() AND execution_mode != safe-runner:
       session = create_session(issue_id, harness, provider, model)
       run.session_id = session.id
     - Else: run.session_id = None (standalone)
  → Adapter.execute(prompt, session=session)
```

### Saving Checkpoint (after each execution step)

```
Adapter.execute() returns partial result
  → Worker calls save_checkpoint(session_id, {
       conversation_history: [...],       # full reassignment, not append
       checkpoint_data: {...},            # state pointers only, no secrets
       provider_resume_ref: "..."         # provider-native ref (or None)
     })
  → DB updated atomically via repository function (reassign JSON fields, not mutate)
```

### Resuming a Session

```
User clicks "Resume" on a failed/cancelled run
  → create_run_for_dispatch(session_id=existing_session.id)
  → Worker claims new run
  → Worker loads session from DB
  → Adapter.execute(prompt, session=session)
     - If session.provider_resume_ref exists: use provider-native resume
       (adapter determines exact CLI flags / API params)
     - Else: re-send session.conversation_history + new prompt
  → Session.total_runs += 1
  → Normal completion/failure cycle
```

### Session Lifecycle Transitions

```
active ──→ paused    (run ended, session can be resumed)
active ──→ completed (terminal: user explicitly finished)
paused ──→ active    (resume started a new run)
paused ──→ expired   (TTL exceeded)
active ──→ expired   (TTL exceeded, should not happen but defensive)
```

## Adapter Protocol Extension

> **Scope note:** The adapter protocol below is a **future interface definition** for the implementation phase. It is NOT implemented in the schema-only phase. It is included here to validate that the schema supports the intended usage.

Adapters that support resume implement two optional methods:

```python
class BaseAIAdapter(ABC):
    # ... existing methods ...

    def supports_resume(self) -> bool:
        """Return True if this adapter can resume sessions."""
        return False

    async def execute_with_session(
        self,
        task_id: str,
        prompt: str,
        workspace: str,
        session: dict,          # loaded from agent_sessions
        on_log: Callable,
    ) -> ExecutionResult:
        """Execute with resume context. Default: ignore session, call execute()."""
        return await self.execute(task_id, prompt, workspace, on_log)
```

### Provider-Specific Resume Behavior

| Provider | Resume Strategy | checkpoint_data | provider_resume_ref |
|----------|----------------|-----------------|---------------------|
| Claude CLI | CLI-supported resume argument (`-r` / `--resume`); adapter detects version and uses appropriate flag | `{"cli_session_id": "..."}` | CLI session ID or name |
| OpenAI Chat Completions | Replay conversation_history | `{}` | None |
| OpenAI Responses API | Chain via `previous_response_id` | `{}` | response_id |
| OpenAI Assistants | Use thread_id (only when using Assistants API) | `{"thread_id": "..."}` | thread_id |
| Anthropic Messages | Replay conversation_history | `{}` | None |
| Generic API | Replay conversation_history | `{}` | None |

## API Endpoints (planned, not implemented)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/runtime/sessions` | GET | List sessions (filtered by board/issue) |
| `GET /api/v1/runtime/sessions/{id}` | GET | Get session detail + history |
| `POST /api/v1/runtime/sessions/{id}/resume` | POST | Create a new run that resumes this session |
| `DELETE /api/v1/runtime/sessions/{id}` | DELETE | Expire/delete a session |

## File Structure (planned)

```
backend/
├── db/models.py              # Add AgentSession model, AgentRun.session_id soft ref
├── db/repository.py          # Add session CRUD functions (reassign pattern, not mutate)
├── core/runtime/session.py   # Session lifecycle management (new file)
├── core/adapters/base.py     # Add supports_resume(), execute_with_session()
└── api/v1/endpoints/sessions.py  # Session API endpoints (new file)
```

## Implementation Requirements (next phase, not this spec)

These items are NOT part of the schema-only design. They are listed here for planning purposes:

- `AgentRun.to_dict()` must include `session_id` field.
- `create_run()` must accept optional `session_id` parameter.
- `list_runs_by_board()` must support `session_id` filter.
- Repository functions for JSON fields must use reassignment pattern:
  ```python
  # CORRECT — full reassignment
  session.conversation_history = new_history
  await session.save()

  # WRONG — in-place mutation (SQLAlchemy won't detect)
  session.conversation_history.append(new_message)
  ```
- Alembic migration must be hand-reviewed for SQLite/JSONB compatibility and index creation.
- Session cleanup cron job for expired sessions.

## What This Design Does NOT Do

- Does not implement resume logic (schema only)
- Does not change existing AgentRun lifecycle
- Does not require adapters to support resume (opt-in)
- Does not add multi-harness execution
- Does not add session serialization to disk (DB-only for now)
- Does not add automatic checkpointing (adapters opt-in to call save_checkpoint)
- Does not add encryption or redaction (future consideration)
- Does not implement the adapter protocol (defined here for validation only)

## Migration Impact

- **Additive only**: new table + one nullable column on AgentRun
- No existing columns modified
- No existing data affected
- `session_id=None` preserves current standalone behavior
- Alembic migration: hand-write or autogenerate then review for:
  - SQLite vs PostgreSQL JSON column differences
  - FK constraint intentionally omitted (soft reference)
  - Composite index creation order
  - Default values for existing rows (`session_id = NULL`)
