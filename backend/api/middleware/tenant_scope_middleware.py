"""
TenantContextMiddleware — Plan J phase 2.

The middleware runs *inside* every HTTP request and stamps the user
identity into a ``contextvars.ContextVar`` that the SQLAlchemy event
listener in ``db/tenant_scope.py`` reads on every ORM execution.

The flow:

1. The request arrives. The middleware parses the ``Authorization``
   header (and the ``?token=`` query for WebSocket) and resolves
   the user via ``verify_jwt_token`` — the same routine
   ``get_current_user`` uses, so dev-bypass / JWT / error semantics
   stay aligned.
2. The middleware binds the user dict into the contextvar before
   FastAPI's dependency layer runs, so the listener sees the same
   tenant_id the auth dep will eventually authorize against.
3. The endpoint calls ``session.execute(...)`` somewhere down the
   stack. The ``do_orm_execute`` listener reads
   ``get_request_context()`` and either:
     a) lets the query through (super_admin),
     b) appends ``WHERE tenant_id = :ctx.tenant_id`` (everyone else),
     c) raises 403 (no context at all).
4. The middleware, on the way out, calls ``reset_request_context`` so
   the next request starts clean.

Why a pure ASGI middleware and not ``BaseHTTPMiddleware``
=========================================================

``BaseHTTPMiddleware`` (Starlette 0.20+) spawns an internal anyio
task group for every request so it can run the inner app in the
background. That works fine for sync code, but with asyncpg +
SQLAlchemy async the connection pool is bound to the event loop of
the outer task. The inner task runs on a *different* loop, so the
session.execute() call resolves a Future "attached to a different
loop" and raises ``RuntimeError``. Implementing the middleware as a
plain ASGI callable (no task spawn) keeps everything on one event
loop and the cross-loop error goes away.

Why a middleware and not a FastAPI dependency
=============================================

A dependency runs *per route*, but a contextvar set inside the
dependency is only visible inside the awaited coroutine that set it.
The SQLAlchemy listener, however, fires from inside deeper stack
frames (the repository, the session.execute call) that are not
descendants of the dependency coroutine. A middleware wraps the
*whole* request, so the contextvar is visible for the lifetime of
the request.

What this middleware does NOT do
================================

* It does not enforce the role. ``require_*`` deps do that.
* It does not write audit rows. ``db/tenant_scope.py`` is read-only
  for tenant scoping; the audit log has its own writer path.
"""

import logging
import os
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("api.middleware.tenant_scope")


# Keys the middleware writes onto ``request.state``. ``user`` is
# the resolved auth dict; J-3 can read it for the
# ``/api/v1/tenants/{id}/members`` listing without re-decoding the
# JWT.
USER_STATE_KEY = "user"


class TenantContextMiddleware:
    """Bind / clear the per-request tenant context.

    Implemented as a pure ASGI3 middleware (no ``BaseHTTPMiddleware``)
    so asyncpg stays on a single event loop. See the module docstring
    for the long story.

    Parameters
    ----------
    app:
        The ASGI application this middleware wraps.
    skip_paths:
        Path prefixes that should not get a context. The
        ``/health`` and ``/docs`` routes are included by default —
        those endpoints run before the user exists, so there is no
        tenant to bind. The middleware is a no-op for them.
    """

    DEFAULT_SKIP_PATHS: tuple[str, ...] = (
        "/health",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
    )

    def __init__(self, app, *, skip_paths: Optional[tuple[str, ...]] = None):
        self.app = app
        self._skip_paths = tuple(skip_paths or self.DEFAULT_SKIP_PATHS)

    # ------------------------------------------------------------------
    # Token resolution (same as before; separated so the test can mock it)
    # ------------------------------------------------------------------
    def _resolve_user(self, path: str, headers: dict, query_string: bytes) -> Optional[dict]:
        """Decode the bearer / query token and return the user dict.

        Reuses ``verify_jwt_token`` so dev-bypass, JWT-decode, and
        error semantics stay identical to ``get_current_user``.
        """
        from api.v1.endpoints.auth import verify_jwt_token, _dev_bypass_payload

        # Mirror the bypass branch from get_current_user so the
        # listener sees the same context in both code paths.
        if os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true":
            return _dev_bypass_payload()

        # WebSocket path: token arrives as ?token=...
        from urllib.parse import parse_qs
        token: Optional[str] = None
        if query_string:
            qs = parse_qs(query_string.decode("latin-1"))
            if "token" in qs and qs["token"]:
                token = qs["token"][0]

        if not token:
            for hk in (b"authorization", b"Authorization"):
                hv = headers.get(hk)
                if hv:
                    hv = hv.decode("latin-1") if isinstance(hv, bytes) else hv
                    if hv.startswith("Bearer "):
                        token = hv[7:]
                    else:
                        token = hv
                    break

        if not token:
            return None

        try:
            return verify_jwt_token(token)
        except Exception:
            # Auth dep will raise the canonical 401; middleware
            # just steps out of the way.
            return None

    # ------------------------------------------------------------------
    # Pure ASGI3 entrypoint
    # ------------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Lifespan / websocket — let them pass through untouched.
            return await self.app(scope, receive, send)

        path: str = scope.get("path", "")
        if any(path.startswith(p) for p in self._skip_paths):
            return await self.app(scope, receive, send)

        # Lazy import: the middleware module is imported before
        # ``db.tenant_scope`` finishes its module-level setup, and
        # pulling ``register_tenant_scope_listener`` at module
        # import time would create a circular dependency.
        from db.tenant_scope import (
            set_request_context,
            reset_request_context,
            register_tenant_scope_listener,
        )

        # Make sure the listener is registered. Idempotent.
        register_tenant_scope_listener()

        headers = dict(scope.get("headers") or [])
        query_string = scope.get("query_string", b"")
        user = self._resolve_user(path, headers, query_string)

        ctx: Optional[dict] = None
        if user:
            ctx = {
                "user_id": user.get("user_id"),
                "username": user.get("username"),
                "role": user.get("role"),
                "tenant_id": user.get("tenant_id"),
                "is_super_admin": bool(user.get("is_super_admin", False)),
            }
        token = set_request_context(ctx)

        # Stash on the request.state-equivalent (we own the scope) so
        # J-3 endpoints can read the resolved user without re-decoding
        # the JWT. Starlette builds request.state out of scope["state"]
        # so we have to seed that dict before the request lands.
        scope_state = scope.setdefault("state", {})
        scope_state[USER_STATE_KEY] = user

        try:
            await self.app(scope, receive, send)
        finally:
            # Reset *after* the inner app returns so any late ORM
            # calls in response middleware still see the context.
            reset_request_context(token)
