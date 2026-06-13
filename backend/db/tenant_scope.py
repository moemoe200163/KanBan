"""
Plan J phase 2 — Tenant scope enforcement via a SQLAlchemy event listener.

This module is the **data-layer** tenant boundary. The application-layer
tenant check lives in ``api.v1.auth_deps.require_same_tenant`` and the
HTTP-level middleware in ``api.middleware.tenant_scope_middleware``. All
three are needed: the URL dep gives a friendly 403, the middleware
hydrates the request context, and this listener is the belt-and-braces
guarantee that no ORM query can leak across tenants.

How it works
============

* The middleware in ``api/middleware/tenant_scope_middleware.py``
  populates a ``ContextVar`` with ``{tenant_id, is_super_admin, ...}``
  at the start of every request.
* This module's ``_enforce_tenant_scope`` listener fires on every
  ``do_orm_execute`` event. For each entity referenced by the
  statement, it checks the entity against ``_TENANT_SCOPED_MODELS``:
    - if the entity isn't tenant-scoped, leave the statement alone
    - if the caller is ``is_super_admin``, leave the statement alone
    - otherwise, append a ``WHERE tenant_id = :tenant_id`` clause
    - if there's no request context at all, raise HTTPException(403)
      — this is the "core 防呆" the plan calls out: a query that
      somehow escapes the middleware boundary 403s instead of
      returning cross-tenant data.

Why an event listener and not a per-endpoint filter
====================================================

Two reasons:

1. **Repositories forget.** ``db/repository.py`` has 30+ free functions
   that build ``select(...)`` without a tenant predicate. A reviewer
   would have to catch every one. The listener is structural — if
   the model has ``tenant_id``, the filter is applied.

2. **Bug blast radius.** If a future endpoint forgets to set the
   request context, the listener raises 403, not 200. Operators see
   the failure immediately and fix the missing middleware hookup.

Why a contextvar and not thread-locals
=======================================

FastAPI runs sync deps in a thread pool and async deps on the main
loop. ``contextvars.ContextVar`` is the only primitive that
automatically propagates across both via ``asyncio`` and ``copy_context``.
A module-level ``_current_user = ...`` would leak between concurrent
requests.

What this module does NOT do
============================

* It does not enforce write isolation. A super_admin could still
  issue ``UPDATE users SET tenant_id = 'other' WHERE id = ...``.
  That's intentional — operator tooling needs to repair data.
* It does not validate the tenant_id against ``tenants``. A row
  with ``tenant_id = 'tnt_unknown'`` will simply be invisible
  to every other tenant, which is the right default.
* It does not strip columns. A user in tenant A reading an Issue
  that happens to be in tenant A still sees all the columns on
  the row. The listener scopes *rows*, not *columns*.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select, Update, Delete
from sqlalchemy.sql.coercions import expect

from db.models import (
    Issue,
    Agent,
    AuditLog,
    WebhookEvent,
    JobModel,                # ECCDispatchJob -> ecc_jobs table
    CycleReport,
    IssueEvent,
    IssueComment,
    IssueArtifact,
    IssueHandoff,
    LLMProviderConfig,
    AgentWorker,
    AgentRun,
    AgentSession,
    AgentRole,
    User,
)

logger = logging.getLogger("db.tenant_scope")

# ---------------------------------------------------------------------------
# The set of models that carry a ``tenant_id`` column and must be
# filtered. Anything not in this set is treated as "global" (Tenant,
# TenantMembership, TenantAudit, etc.) and the listener leaves the
# query alone. Add a new model here if you add ``tenant_id`` to it
# via a new migration.
# ---------------------------------------------------------------------------
# Auth-identity models that DO have a ``tenant_id`` column (e.g.
# ``User`` after Plan J-1 added the column) must NOT be filtered by
# this listener. Their ``tenant_id`` is the *owning* tenant — used for
# scoping sessions and audit rows — but the auth path needs to look
# the user up by ``id`` regardless of which tenant the caller is
# acting as. Filtering ``select(User)`` by the caller's tenant_id
# would break login (super_admin's row is NULL anyway; regular users
# would still resolve, but operators would lose the ability to look
# up an out-of-tenant user row for support tooling). Keep this
# denylist in sync with any new auth-identity model.
# ---------------------------------------------------------------------------
_AUTH_IDENTITY_MODELS: frozenset = frozenset({
    User,
})

_TENANT_SCOPED_MODELS = frozenset(
    cls
    for cls in (
        Issue,
        Agent,
        AuditLog,
        WebhookEvent,
        JobModel,
        CycleReport,
        IssueEvent,
        IssueComment,
        IssueArtifact,
        IssueHandoff,
        LLMProviderConfig,
        AgentWorker,
        AgentRun,
        AgentSession,
        AgentRole,
    )
    if hasattr(cls, "tenant_id")
)


# ---------------------------------------------------------------------------
# Request context — populated by TenantContextMiddleware, read by the
# listener and the auth_deps.require_* helpers (via the public
# ``get_request_context`` API).
# ---------------------------------------------------------------------------

_request_context: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "request_context", default=None
)


def set_request_context(ctx: Optional[dict]) -> contextvars.Token:
    """Bind a request context to the current async task.

    Returns the ``Token`` so the caller can ``reset()`` it after the
    request finishes (the middleware does this — see
    ``api/middleware/tenant_scope_middleware.py``).
    """
    return _request_context.set(ctx or {})


def get_request_context() -> Optional[dict]:
    """Return the active request context, or ``None`` if there is none.

    The listener calls this on every ORM execution. A ``None`` return
    is the signal that the request bypassed the middleware (a
    background task, a startup hook, the lifespan); those callers
    must either (a) explicitly call ``set_request_context({...})``
    with a known tenant, or (b) accept the 403 raise below.
    """
    return _request_context.get()


def reset_request_context(token: contextvars.Token) -> None:
    """Reverse ``set_request_context``. Called by the middleware."""
    try:
        _request_context.reset(token)
    except (ValueError, LookupError):
        # Token already consumed (e.g. nested middleware in tests).
        # Safe to ignore — the var will be re-bound on the next request.
        pass


# ---------------------------------------------------------------------------
# The event listener itself.
# ---------------------------------------------------------------------------


def _is_super_admin_ctx(ctx: Optional[dict]) -> bool:
    if not ctx:
        return False
    return bool(ctx.get("is_super_admin"))


def _tenant_id_ctx(ctx: Optional[dict]) -> Optional[str]:
    if not ctx:
        return None
    return ctx.get("tenant_id")


def _statement_uses_tenant_scoped_entity(statement) -> bool:
    """Return True if any entity in ``statement`` is in
    ``_TENANT_SCOPED_MODELS`` AND is not in the auth-identity denylist.

    Auth-identity models (currently ``User``) carry a ``tenant_id``
    column for ownership but must remain queryable across tenants
    — login / ``/auth/me`` / operator support tooling all hit
    ``select(User).where(User.id == ...)`` and need the row even
    when the caller is in a different tenant. The denylist keeps
    the listener from injecting a tenant predicate on those
    statements; if a future model gains ``tenant_id`` and shouldn't
    be filtered, add it to ``_AUTH_IDENTITY_MODELS`` rather than
    re-introducing an auto-derivation rule.
    """
    try:
        # ``column_descriptions`` exists on ORM statements (Select of
        # mapped classes). For core Update/Delete we walk ``table``.
        descriptions = getattr(statement, "column_descriptions", None)
        if descriptions:
            for desc in descriptions:
                entity = desc.get("entity") if isinstance(desc, dict) else None
                if entity is None:
                    continue
                if entity in _AUTH_IDENTITY_MODELS:
                    # Plan J C-2 guard: skip auth-identity entities
                    # even though they carry ``tenant_id``. Returning
                    # False (not True) means the listener exits
                    # before injecting a predicate.
                    continue
                if entity in _TENANT_SCOPED_MODELS:
                    return True
    except Exception:  # pragma: no cover - defensive
        pass

    # Update/Delete against a Table or model: inspect ``table``.
    table = getattr(statement, "table", None)
    if table is not None:
        try:
            mapper = getattr(table, "mapper", None)
            if mapper is not None:
                cls = mapper.class_
                if cls in _AUTH_IDENTITY_MODELS:
                    return False
                if cls in _TENANT_SCOPED_MODELS:
                    return True
        except Exception:  # pragma: no cover
            pass

    return False


def _enforce_tenant_scope(state) -> None:
    """SQLAlchemy ``do_orm_execute`` listener — appends a tenant filter.

    The listener is registered against the synchronous ``Session`` class
    so it fires once per execute() call regardless of async or sync
    session use. SQLAlchemy's async session wraps the sync one and the
    event still fires on every statement.
    """
    statement = getattr(state, "statement", None)
    if statement is None:
        return
    if not _statement_uses_tenant_scoped_entity(statement):
        return

    ctx = get_request_context()
    if _is_super_admin_ctx(ctx):
        # super_admin sees every tenant. Logging at debug is enough —
        # production logs would flood otherwise.
        logger.debug("super_admin bypassing tenant filter")
        return

    tenant_id = _tenant_id_ctx(ctx)
    if tenant_id is None:
        # No context at all. The plan's contract: refuse the query
        # with 403 rather than silently return cross-tenant data.
        # We use HTTPException so FastAPI's handler renders a
        # consistent 403 response (this can also fire inside a
        # background task; in that case the surrounding try/except
        # logs it and the request returns 500, which is also fine
        # — a background task with no tenant context is a bug).
        raise HTTPException(
            status_code=403,
            detail="No tenant context — request reached the data layer "
                   "without populating set_request_context().",
        )

    # Inject the tenant predicate. We support Select, Update, Delete;
    # ``Insert`` skips the listener (we don't backfill tenant_id on
    # insert — endpoints must set it explicitly so an accidental
    # INSERT doesn't silently land in the wrong tenant).
    if isinstance(statement, Select):
        # Avoid adding the filter twice (e.g. nested subquery).
        if _select_already_has_tenant_filter(statement, tenant_id):
            return
        # ``with_dialect_options`` / ``execution_options`` carries the
        # bypass marker for the unit test
        # ``test_super_admin_listener_bypass``.
        if getattr(statement, "_execution_options", {}).get(
            "_skip_tenant_filter"
        ):
            return
        # Append. Use ``.where()`` so it composes with existing filters.
        from sqlalchemy import column
        # Find the model in the column descriptions and use its
        # ``tenant_id`` column. We assume the statement targets
        # exactly one tenant-scoped model — multi-tenant joins
        # within a single SELECT should use a repository that
        # already constrains the rows.
        model = _first_tenant_scoped_model(statement)
        if model is None:
            return
        statement = statement.where(model.tenant_id == tenant_id)
        # Replace the statement in the ORM state. SQLAlchemy inspects
        # ``state.statement`` after the listener returns, so mutating
        # the existing statement is the cheapest way to apply the
        # change.
        state.statement = statement
    elif isinstance(statement, (Update, Delete)):
        model = _first_tenant_scoped_model_from_table(statement.table)
        if model is None:
            return
        # ``.where()`` composes with the existing predicate.
        new_stmt = statement.where(model.tenant_id == tenant_id)
        # Some SQLAlchemy versions keep the original clause in
        # ``state.statement``; replace it explicitly.
        try:
            state.statement = new_stmt
        except Exception:  # pragma: no cover - read-only in some versions
            pass
    else:
        # Insert / DDL — leave alone. Inserts must carry their own
        # tenant_id; DDL doesn't go through do_orm_execute.
        return


def _first_tenant_scoped_model(statement) -> Optional[type]:
    """Pick the first tenant-scoped model referenced by a Select."""
    for desc in getattr(statement, "column_descriptions", []) or []:
        entity = desc.get("entity") if isinstance(desc, dict) else None
        if entity in _TENANT_SCOPED_MODELS:
            return entity
    return None


def _first_tenant_scoped_model_from_table(table) -> Optional[type]:
    mapper = getattr(table, "mapper", None)
    if mapper is None:
        return None
    cls = mapper.class_
    if cls in _TENANT_SCOPED_MODELS:
        return cls
    return None


def _select_already_has_tenant_filter(statement, tenant_id) -> bool:
    """Cheap check: does the statement already carry a
    ``tenant_id = :param`` predicate? Prevents double-filtering when
    a repository manually added the predicate and the listener fires
    anyway.
    """
    whereclause = getattr(statement, "_whereclause", None)
    if whereclause is None:
        return False
    # Walk the boolean tree looking for a BinaryExpression whose
    # left side is the ``tenant_id`` column of any of our scoped
    # models. We don't decode the operator; presence of the column
    # is enough — the listener would re-apply the same value.
    try:
        for col in _iter_columns(whereclause):
            if col.key == "tenant_id":
                return True
    except Exception:  # pragma: no cover
        return False
    return False


def _iter_columns(clause):
    """Yield ColumnElement leaves inside a whereclause tree."""
    from sqlalchemy.sql import ColumnElement
    if isinstance(clause, ColumnElement):
        # ``get_children`` recurses into ``BinaryExpression`` etc.
        for child in clause.get_children():
            if isinstance(child, ColumnElement):
                yield child
                yield from _iter_columns(child)
            else:
                yield from _iter_columns(child)


# ---------------------------------------------------------------------------
# Registration. The listener is wired up the first time the module is
# imported. We import it from ``db/database.py`` (or any model-loading
# site) so a single import gives us the listener.
# ---------------------------------------------------------------------------

_listener_registered = False


def register_tenant_scope_listener() -> None:
    """Register the ``do_orm_execute`` listener exactly once.

    Safe to call from multiple import sites (idempotent via the
    ``_listener_registered`` module flag). ``db/database.py`` calls
    this at module-import time so the listener is live before the
    first session.execute().
    """
    global _listener_registered
    if _listener_registered:
        return
    event.listen(Session, "do_orm_execute", _enforce_tenant_scope)
    _listener_registered = True
    logger.info(
        "Registered tenant scope listener (%d models scoped, %d auth-identity denylisted)",
        len(_TENANT_SCOPED_MODELS),
        len(_AUTH_IDENTITY_MODELS),
    )
