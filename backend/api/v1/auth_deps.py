"""
Shared authentication dependencies for API routers.

Usage in router files:
    from api.v1.auth_deps import require_auth, optional_auth, require_admin

    router = APIRouter(dependencies=[Depends(require_auth)])  # all endpoints require auth
    # or per-endpoint:
    @router.get("/thing")
    async def get_thing(user: dict = Depends(optional_auth)):
        ...
    @router.delete("/dangerous-thing")
    async def delete_thing(user: dict = Depends(require_admin)):
        ...
    @router.post("/invite")
    async def invite(user: dict = Depends(require_role("admin", "ops"))):
        ...
    @router.get("/x-tenant/{tid}")
    async def cross_tenant(user: dict = Depends(require_same_tenant(tid))):
        ...
"""

from typing import Iterable

from fastapi import Depends, HTTPException
from sqlalchemy import select

from api.v1.endpoints.auth import get_current_user, get_optional_user

# Alias for clarity when used as router-level dependency.
require_auth = get_current_user
optional_auth = get_optional_user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role.

    Plan J update: ``super_admin`` (cross-tenant leader) and ``admin``
    both pass. ``ops`` does NOT — ops has narrower scope (LLM / webhooks
    / board creation, not user / tenant management). This matches the
    role matrix in §三 of plans/J-multi-tenant-rbac.md.
    """
    from db.database import ensure_db_init, AsyncSessionLocal
    from db.models import User

    # super_admin short-circuit: don't even hit the DB.
    if current_user.get("is_super_admin"):
        return current_user

    await ensure_db_init()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == current_user["user_id"])
        )
        user = result.scalar_one_or_none()

        if not user or user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

    return current_user


# ---------------------------------------------------------------------------
# Plan J phase 2 — new role / tenant deps
# ---------------------------------------------------------------------------


async def require_ops(current_user: dict = Depends(get_current_user)) -> dict:
    """Require ``ops`` or ``admin`` (or ``super_admin``) role.

    Ops is the "I configure LLM providers, webhooks, agent roles, and
    create boards" role. Admin inherits ops powers (the role matrix
    in the plan makes admin a superset of ops).
    """
    if current_user.get("is_super_admin"):
        return current_user
    if current_user.get("role") in ("ops", "admin"):
        return current_user
    raise HTTPException(status_code=403, detail="OPS or admin role required")


async def require_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require the cross-tenant ``super_admin`` flag.

    Used for the operator-only endpoints (cross-tenant listing,
    tenant create, cross-tenant impersonation). The super_admin
    lives with ``tenant_id=NULL`` on the user row, so the tenant
    scope check on the listener also bypasses for them.
    """
    if not current_user.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Super admin required")
    return current_user


def require_role(*allowed_roles: str):
    """Factory: build a dep that requires the user's role to be in ``allowed_roles``.

    ``super_admin`` always passes — the cross-tenant leader can do
    anything an admin can. The factory exists so the J-3 codemod can
    stamp the right role on every existing endpoint without each
    endpoint having to repeat the same role list.

    Usage::

        @router.post("/configure")
        async def configure(user: dict = Depends(require_role("admin", "ops"))):
            ...
    """
    allowed: tuple[str, ...] = tuple(allowed_roles)

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("is_super_admin"):
            return current_user
        if current_user.get("role") in allowed:
            return current_user
        raise HTTPException(
            status_code=403,
            detail=f"Required role: {','.join(allowed)}",
        )

    return _check


async def require_same_tenant(
    target_tenant_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Verify ``current_user.tenant_id == target_tenant_id``.

    This is the *application-layer* tenant check — for endpoints that
    take a tenant id from the URL and need to confirm the caller is
    inside that tenant. The SQLAlchemy event listener in
    ``db/tenant_scope.py`` is the *data-layer* check (it scopes every
    ORM query by tenant). Both are needed: the URL check gives a clean
    403 with a helpful message, the listener is the belt-and-braces
    guarantee that no query leaks across tenants.

    ``super_admin`` always passes.
    """
    if current_user.get("is_super_admin"):
        return current_user
    if current_user.get("tenant_id") != target_tenant_id:
        raise HTTPException(
            status_code=403, detail="Cross-tenant access denied"
        )
    return current_user
