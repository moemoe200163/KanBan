"""
Plan J-3 — 6 new tenant endpoints (wired).

Endpoints (per J-3 prompt 必做項目 #3 + plan §九):
    POST   /tenants/{id}/invite                          require_role("admin")
    GET    /tenants/{id}/members                         require_auth
    PATCH  /tenants/{id}/members/{uid}/role              require_role("admin")
    DELETE /tenants/{id}/members/{uid}                   require_role("admin")
    GET    /tenants                                      require_super_admin
    POST   /tenants                                      require_super_admin

Style: ``Annotated[dict, Depends(require_role("admin"))]`` per J-3
prompt 寫法限制 #1. No body-internal ``if user.role != ...`` checks.
No router-level ``dependencies=[Depends(...)]`` blanket — every
endpoint carries its own gate so the per-endpoint role mix in this
file (admin vs auth vs super_admin) doesn't get conflated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from api.v1.auth_deps import (
    require_auth,
    require_role,
    require_same_tenant,
    require_super_admin,
)
from db import database as _db
from db.models import Tenant, TenantAudit, TenantMembership, User


router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------
class InviteRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=128)
    email: Optional[EmailStr] = None
    role: str = Field(default="user", description="user | ops | admin")


class InviteResponse(BaseModel):
    membership_id: str
    tenant_id: str
    user_id: str
    role: str


class MemberResponse(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    role: str
    is_super_admin: bool
    joined_at: str


class PatchRoleRequest(BaseModel):
    role: str = Field(..., description="user | ops | admin")


class TenantCreateRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    plan: str = Field(default="free")


class TenantResponse(BaseModel):
    id: str
    slug: str
    name: str
    plan: str
    is_active: bool


# ---------------------------------------------------------------------------
# 6 endpoints — every gate uses ``Annotated[..., Depends(...)]`` at the
# signature. No inline role checks below.
# ---------------------------------------------------------------------------
@router.post(
    "/tenants/{tenant_id}/invite",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tenants"],
)
async def invite_user(
    tenant_id: str,
    body: InviteRequest,
    _admin: Annotated[dict, Depends(require_role("admin"))],
    current_user: Annotated[dict, Depends(require_auth)],
) -> InviteResponse:
    """Admin invites a (new or existing) user to a tenant.

    Creates a ``tenant_memberships`` row. The user is looked up by
    username; if missing, a placeholder User row is created with
    a random password (the invited user resets it via the email
    flow that Plan K will ship — for now they cannot log in
    until an admin resets the password via ``PATCH .../role``).
    A ``tenant_audits`` row records the action.
    """
    if body.role not in {"user", "ops", "admin"}:
        raise HTTPException(
            status_code=422, detail=f"Invalid role: {body.role!r}"
        )

    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        # Verify tenant exists
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        if not tenant:
            raise HTTPException(
                status_code=404, detail=f"Tenant '{tenant_id}' not found"
            )

        # Cross-tenant: super_admin can act on any tenant; admin
        # caller must belong to this tenant.
        if not current_user.get("is_super_admin"):
            if current_user.get("tenant_id") != tenant_id:
                raise HTTPException(
                    status_code=403, detail="Cross-tenant access denied"
                )

        # Find or create the user
        user = (
            await session.execute(
                select(User).where(User.username == body.username)
            )
        ).scalar_one_or_none()
        if not user:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user = User(
                id=user_id,
                username=body.username,
                email=body.email,
                password_hash=None,  # invited user must reset
                tenant_id=tenant_id,
                role=body.role,
                is_super_admin=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.flush()
        else:
            user_id = user.id

        # Create membership (idempotent on (tenant_id, user_id) — J-2 0022
        # added a UniqueConstraint; if a row already exists, update its role)
        membership = (
            await session.execute(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            membership = TenantMembership(
                id=f"tmem_{uuid.uuid4().hex[:12]}",
                tenant_id=tenant_id,
                user_id=user_id,
                role=body.role,
                invited_by=current_user.get("user_id"),
                joined_at=datetime.now(timezone.utc),
            )
            session.add(membership)
        else:
            membership.role = body.role

        # Audit trail
        session.add(TenantAudit(
            id=f"taud_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            actor_id=current_user.get("user_id"),
            actor_username=current_user.get("username"),
            action="invite_user",
            target_user_id=user_id,
            details={"role": body.role, "username": body.username},
            created_at=datetime.now(timezone.utc),
        ))

        await session.commit()
        await session.refresh(membership)

        return InviteResponse(
            membership_id=membership.id,
            tenant_id=tenant_id,
            user_id=user_id,
            role=membership.role,
        )


@router.get(
    "/tenants/{tenant_id}/members",
    response_model=list[MemberResponse],
    tags=["Tenants"],
)
async def list_members(
    tenant_id: str,
    current_user: Annotated[dict, Depends(require_auth)],
) -> list[MemberResponse]:
    """List members of a tenant. Any authenticated user may read;
    the listener + super_admin short-circuit handle cross-tenant
    access. Same-tenant members see all members; cross-tenant
    callers (non-super) get 403 from the listener.
    """
    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        # Verify tenant exists
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        if not tenant:
            raise HTTPException(
                status_code=404, detail=f"Tenant '{tenant_id}' not found"
            )

        # Listener enforces tenant_id filter on TenantMembership reads.
        # super_admin short-circuit lets them read across tenants.
        result = await session.execute(
            select(TenantMembership, User)
            .join(User, User.id == TenantMembership.user_id)
            .where(TenantMembership.tenant_id == tenant_id)
        )
        rows = result.all()
        return [
            MemberResponse(
                user_id=u.id,
                username=u.username,
                email=u.email,
                role=m.role,
                is_super_admin=bool(u.is_super_admin),
                joined_at=m.joined_at.isoformat() if m.joined_at else "",
            )
            for m, u in rows
        ]


@router.patch(
    "/tenants/{tenant_id}/members/{user_id}/role",
    response_model=MemberResponse,
    tags=["Tenants"],
)
async def patch_member_role(
    tenant_id: str,
    user_id: str,
    body: PatchRoleRequest,
    _admin: Annotated[dict, Depends(require_role("admin"))],
    current_user: Annotated[dict, Depends(require_auth)],
) -> MemberResponse:
    """Admin updates a member's role inside the tenant."""
    if body.role not in {"user", "ops", "admin"}:
        raise HTTPException(
            status_code=422, detail=f"Invalid role: {body.role!r}"
        )

    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        membership = (
            await session.execute(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not membership:
            raise HTTPException(
                status_code=404,
                detail=f"Membership not found for user '{user_id}' in tenant '{tenant_id}'",
            )

        # Cross-tenant check
        if not current_user.get("is_super_admin"):
            if current_user.get("tenant_id") != tenant_id:
                raise HTTPException(
                    status_code=403, detail="Cross-tenant access denied"
                )

        membership.role = body.role
        session.add(TenantAudit(
            id=f"taud_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            actor_id=current_user.get("user_id"),
            actor_username=current_user.get("username"),
            action="patch_member_role",
            target_user_id=user_id,
            details={"new_role": body.role},
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        # Refresh user info for the response
        user = (
            await session.execute(
                select(User).where(User.id == user_id)
            )
        ).scalar_one()
        return MemberResponse(
            user_id=user.id,
            username=user.username,
            email=user.email,
            role=membership.role,
            is_super_admin=bool(user.is_super_admin),
            joined_at=membership.joined_at.isoformat() if membership.joined_at else "",
        )


@router.delete(
    "/tenants/{tenant_id}/members/{user_id}",
    tags=["Tenants"],
)
async def delete_member(
    tenant_id: str,
    user_id: str,
    _admin: Annotated[dict, Depends(require_role("admin"))],
    current_user: Annotated[dict, Depends(require_auth)],
) -> dict:
    """Admin removes a member from a tenant (soft delete: row gone
    from tenant_memberships, user row remains)."""
    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        membership = (
            await session.execute(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not membership:
            raise HTTPException(
                status_code=404,
                detail=f"Membership not found for user '{user_id}' in tenant '{tenant_id}'",
            )

        if not current_user.get("is_super_admin"):
            if current_user.get("tenant_id") != tenant_id:
                raise HTTPException(
                    status_code=403, detail="Cross-tenant access denied"
                )

        await session.delete(membership)
        session.add(TenantAudit(
            id=f"taud_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            actor_id=current_user.get("user_id"),
            actor_username=current_user.get("username"),
            action="delete_member",
            target_user_id=user_id,
            details={},
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()
    return {"deleted": True, "user_id": user_id}


@router.get(
    "/tenants",
    response_model=list[TenantResponse],
    tags=["Tenants"],
)
async def list_tenants(
    _super: Annotated[dict, Depends(require_super_admin)],
) -> list[TenantResponse]:
    """Super-admin only: list every tenant in the system."""
    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        # Super-admin bypasses the listener, so the SELECT
        # doesn't need a tenant_id filter.
        result = await session.execute(select(Tenant))
        rows = result.scalars().all()
        return [
            TenantResponse(
                id=t.id,
                slug=t.slug,
                name=t.name,
                plan=t.plan,
                is_active=bool(t.is_active),
            )
            for t in rows
        ]


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tenants"],
)
async def create_tenant(
    body: TenantCreateRequest,
    _super: Annotated[dict, Depends(require_super_admin)],
) -> TenantResponse:
    """Super-admin only: create a new tenant."""
    await _db.ensure_db_init()
    async with _db.AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(Tenant).where(Tenant.slug == body.slug)
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Tenant with slug '{body.slug}' already exists",
            )

        tenant_id = f"tnt_{uuid.uuid4().hex[:12]}"
        tenant = Tenant(
            id=tenant_id,
            slug=body.slug,
            name=body.name,
            plan=body.plan,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)

        return TenantResponse(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            plan=tenant.plan,
            is_active=bool(tenant.is_active),
        )
