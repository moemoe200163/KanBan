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

Why a middleware and not a FastAPI dependency
=============================================

A dependency runs *per route*, but a contextvar set inside the
dependency is only visible inside the awaited coroutine that set it.
The SQLAlchemy listener, however, fires from inside deeper stack
frames (the repository, the session.execute call) that are not
descendants of the dependency coroutine. A middleware wraps the
*whole* request and uses the underlying ``asyncio`` context, which
the listener *does* see.

Why a BaseHTTPMiddleware and not the older ``@app.middleware``
================================================================

``BaseHTTPMiddleware`` (added in Starlette 0.20+) is the modern,
supported API. The decorator form is deprecated. We use the class so
the unit tests can instantiate it directly without going through the
full app.

What this middleware does NOT do
================================

* It does not enforce the role. ``require_*`` deps do that.
* It does not write audit rows. ``db/tenant_scope.py`` is read-only
  enforcement; writes happen in the endpoint that calls
  ``repo.create_tenant_audit(...)`` (added in J-3).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("api.middleware.tenant_scope")


# Keys the middleware writes onto ``request.state``. ``user`` is
# the resolved auth dict; J-3 can read it for the
# ``/api/v1/tenants/{id}/members`` listing without re-decoding the
# JWT.
USER_STATE_KEY = "user"


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Bind / clear the per-request tenant context.

    Parameters
    ----------
    app:
        The Starlette / FastAPI application.
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
        super().__init__(app)
        self._skip_paths = tuple(skip_paths or self.DEFAULT_SKIP_PATHS)

    def _resolve_user(self, request: Request) -> Optional[dict]:
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
        token = request.query_params.get("token")

        if not token:
            auth = request.headers.get("authorization") or request.headers.get(
                "Authorization"
            )
            if auth:
                if auth.startswith("Bearer "):
                    token = auth[7:]
                else:
                    token = auth

        if not token:
            return None

        try:
            return verify_jwt_token(token)
        except Exception:
            # Auth dep will raise the canonical 401; middleware
            # just steps out of the way.
            return None

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self._skip_paths):
            return await call_next(request)

        # Lazy import: the middleware module is imported before
        # ``db.tenant_scope`` finishes its module-level setup, and
        # pulling ``register_tenant_scope_listener`` at module
        # import time would create a circular dependency.
        from db.tenant_scope import (
            set_request_context,
            reset_request_context,
            register_tenant_scope_listener,
        )

        # Make sure the listener is registered.
        # ``register_tenant_scope_listener`` is idempotent so calling
        # it on every request is fine.
        register_tenant_scope_listener()

        user = self._resolve_user(request)
        # Stash on request.state too so J-3 endpoints (and tests)
        # can read the resolved user without re-decoding.
        setattr(request.state, USER_STATE_KEY, user)

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
        try:
            response = await call_next(request)
            return response
        finally:
            # Reset *after* the response is fully written so any
            # late ORM calls in the response middleware still see
            # the context. ContextVar.reset is a no-op once the
            # token's binding is gone, but we keep the try/finally
            # for clarity and to survive middleware-raised
            # exceptions.
            reset_request_context(token)
