"""
DevFlow Backend - Authentication Endpoints

Provides JWT-based authentication for the DevFlow API.
Supports both username/password and API key authentication.
"""

from datetime import datetime, timedelta, timezone
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


# ============================================================================
# Pydantic Models
# ============================================================================

class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400


class UserResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    role: Optional[str] = None
    api_key_fingerprint: Optional[str] = None
    created_at: Optional[str] = None


class TenantInfo(BaseModel):
    id: str
    slug: str
    name: str
    plan: str
    is_active: bool = True


class MeResponse(BaseModel):
    """Shape returned by ``GET /auth/me`` post-Plan-J.

    The frontend (``useAuth``) reads this to populate the user store
    and the 4-way role gate (super_admin / admin / ops / user).
    """
    id: str
    username: str
    email: Optional[str] = None
    role: Optional[str] = None
    is_super_admin: bool = False
    tenant: Optional[TenantInfo] = None
    permissions: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=128)
    password: str = Field(..., min_length=8)
    email: Optional[str] = None


class ApiKeyResponse(BaseModel):
    api_key: str
    fingerprint: str


# ============================================================================
# JWT Helpers
# ============================================================================

def get_jwt_secret() -> str:
    import os
    return os.getenv("JWT_SECRET", "devflow-jwt-secret-change-in-production")


def get_jwt_algorithm() -> str:
    import os
    return os.getenv("JWT_ALGORITHM", "HS256")


def get_token_expiry_hours() -> int:
    import os
    return int(os.getenv("JWT_EXPIRY_HOURS", "24"))


def create_jwt_token(
    user_id: str,
    username: str,
    *,
    role: Optional[str] = None,
    tenant_id: Optional[str] = None,
    is_super_admin: Optional[bool] = None,
    permissions: Optional[list] = None,
) -> tuple[str, int]:
    # Symmetric with verify_jwt_token: prefer PyJWT (the library actually
    # installed in the Docker image) and fall back to python-jose for
    # environments that have it. Without this fallback, the login endpoint
    # crashes with ``ModuleNotFoundError: No module named 'jose'`` whenever
    # the operator tries to obtain a fresh token from the UI.
    try:
        import jwt as _pyjwt  # type: ignore
    except ImportError:  # pragma: no cover - jose fallback path
        from jose import jwt as _pyjwt  # type: ignore

    secret = get_jwt_secret()
    algorithm = get_jwt_algorithm()
    expiry_hours = get_token_expiry_hours()
    expires_in = expiry_hours * 3600
    expire = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }

    # Plan J phase 2 — multi-tenant claims. These are optional so
    # the codemod can keep calling ``create_jwt_token(user_id,
    # username)`` for legacy tests; the login endpoint re-issues
    # tokens with the full claim set on each successful login.
    if role is not None:
        payload["role"] = role
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if is_super_admin is not None:
        payload["is_super_admin"] = bool(is_super_admin)
    if permissions is not None:
        payload["permissions"] = list(permissions)

    token = _pyjwt.encode(payload, secret, algorithm=algorithm)
    return token, expires_in


def _dev_bypass_payload() -> dict:
    """Compute the dict that ``verify_jwt_token`` returns when
    ``DEV_AUTH_BYPASS=true``.

    Plan J phase 2 added two knobs so test suites can exercise the
    role / tenant / super_admin path without spinning up the full
    role matrix:

    * ``DEV_AUTH_BYPASS_ROLE`` (default ``"admin"``) — the role
      claim on the bypass user. Set to ``"ops"`` or ``"user"`` to
      simulate a non-admin caller; ``require_admin`` will then 403.
    * ``DEV_AUTH_BYPASS_SUPER_ADMIN`` (default ``false``) — flip
      the cross-tenant flag so tests can hit the super_admin-only
      code paths.
    * ``DEV_AUTH_BYPASS_TENANT`` (default ``tnt_default``) — the
      tenant the bypass user "belongs" to. super_admin ignores
      this; the listener uses it for the per-tenant query filter.

    Pre-Plan-J behaviour (role=admin, tenant=tnt_default) is
    preserved so the existing 727 tests keep working unchanged.
    """
    role = os.getenv("DEV_AUTH_BYPASS_ROLE", "admin").strip() or "admin"
    is_super_admin = (
        os.getenv("DEV_AUTH_BYPASS_SUPER_ADMIN", "false").lower()
        in ("1", "true", "yes")
    )
    tenant_id = None if is_super_admin else (
        os.getenv("DEV_AUTH_BYPASS_TENANT", "tnt_default").strip()
        or "tnt_default"
    )
    return {
        "user_id": "user_f29cff535b4d",
        "username": "leader",
        "role": role,
        "tenant_id": tenant_id,
        "is_super_admin": is_super_admin,
        "permissions": [],
        "bypass": True,
    }


def verify_jwt_token(token: str) -> dict:
    # Dev-only bypass. The plan was to ship a single admin (leader)
    # for the kanban P5 rollout and not gate development on
    # account/registration work. Setting DEV_AUTH_BYPASS=true makes
    # any token (or even an empty string) resolve to the leader admin
    # user. This is the simplest way to keep the API contract intact
    # (every endpoint still calls ``verify_jwt_token`` / ``get_current_user``)
    # while removing the day-to-day friction of pasting a token into
    # every fetch.
    if os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true":
        return _dev_bypass_payload()

    # The codebase ships with `python-jose` declared in requirements but
    # the Docker image only has `PyJWT`. Use the latter so verify works
    # in the container, falling back to `jose` for environments that
    # actually have it installed.
    try:
        import jwt as _pyjwt  # type: ignore
        from jwt import PyJWTError as JWTError  # type: ignore
    except ImportError:  # pragma: no cover - jose fallback path
        from jose import jwt as _pyjwt  # type: ignore
        from jose import JWTError  # type: ignore

    secret = get_jwt_secret()
    algorithm = get_jwt_algorithm()

    try:
        payload = _pyjwt.decode(token, secret, algorithms=[algorithm])
        return {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
            "role": payload.get("role"),
            "tenant_id": payload.get("tenant_id"),
            "is_super_admin": bool(payload.get("is_super_admin", False)),
            "permissions": payload.get("permissions") or [],
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
        }
    except JWTError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )


# ============================================================================
# Password/ApiKey Hashing
# ============================================================================

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    import hashlib
    import secrets
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return salt + key.hex(), salt


def verify_password(password: str, hashed: str) -> bool:
    import hashlib
    salt = hashed[:32]
    stored_key = hashed[32:]
    computed_hash, _ = hash_password(password, salt)
    return computed_hash[32:] == stored_key


def hash_api_key(api_key: str) -> str:
    import hashlib
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    import secrets
    full_key = f"df_{secrets.token_urlsafe(32)}"
    fingerprint = hash_api_key(full_key)
    return full_key, fingerprint


# ---------------------------------------------------------------------------
# Plan J: role -> permission matrix
# ---------------------------------------------------------------------------
# The frontend (``usePermissions``) is the primary consumer, but
# exposing the same set in ``/auth/me`` keeps the gate logic in
# one place: the server computes the list, the UI just renders
# it. The matrix mirrors §三.2 of plans/J-multi-tenant-rbac.md;
# ``super_admin`` is intentionally absent because the cross-tenant
# leader gets the union of every role's permissions.
# ---------------------------------------------------------------------------

_PERMISSIONS_BY_ROLE: dict[str, list[str]] = {
    "admin": [
        "tenant.manage",
        "tenant.delete",
        "llm.configure",
        "board.create",
        "issue.create",
        "issue.delete",
        "agent.dispatch",
        "agent.role.edit",
        "webhook.toggle",
        "audit.view",
        "analytics.view",
    ],
    "ops": [
        "llm.configure",
        "board.create",
        "issue.create",
        "issue.delete",
        "agent.dispatch",
        "agent.role.edit",
        "webhook.toggle",
        "audit.view",
        "analytics.view",
    ],
    "user": [
        "issue.create",
        "agent.dispatch",
    ],
}


def compute_permissions(role: Optional[str], is_super_admin: bool) -> list[str]:
    """Return the list of permission strings for a caller.

    ``super_admin`` gets the union of every defined role so the
    cross-tenant leader isn't artificially restricted on
    any tenant.
    """
    if is_super_admin:
        # Flatten + de-dup while preserving the order in the table.
        seen: set[str] = set()
        merged: list[str] = []
        for perms in _PERMISSIONS_BY_ROLE.values():
            for p in perms:
                if p not in seen:
                    seen.add(p)
                    merged.append(p)
        return merged
    return list(_PERMISSIONS_BY_ROLE.get(role or "", []))


# ============================================================================
# Database Helpers (Lazy Import)
# ============================================================================

def get_user_model():
    from db.models import User
    return User


def get_db_session():
    from db.database import AsyncSessionLocal
    return AsyncSessionLocal


# ============================================================================
# Authentication Dependencies
# ============================================================================

async def get_current_user(
    authorization: Optional[str] = Header(None),
    token_query: Optional[str] = Query(None, alias="token")
) -> dict:
    """
    Dependency to get the current authenticated user from JWT.

    Supports:
    - Authorization: Bearer <token> header
    - ?token=<token> query parameter (for WebSocket)
    - DEV_AUTH_BYPASS=true: skip auth entirely and act as the seed
      'leader' admin user. Dev-mode convenience only — the flag is
      always off in production.

    Plan J phase 2 — the returned dict carries ``tenant_id``,
    ``is_super_admin``, ``role``, and ``permissions`` so the
    SQLAlchemy event listener in ``db/tenant_scope.py`` and the
    new ``require_*`` deps can authorize without an extra DB
    round-trip. Legacy keys (``user_id`` / ``username``) are
    preserved for backward compatibility.
    """
    # Dev-only bypass. Reads the env var on every call so toggling
    # the backend (e.g. via docker compose restart) takes effect
    # without a code change.
    if os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true":
        return _dev_bypass_payload()

    token = None

    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization

    if not token and token_query:
        token = token_query

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return verify_jwt_token(token)


async def get_optional_user(
    authorization: Optional[str] = Header(None)
) -> Optional[dict]:
    """Optional authentication - returns None if not authenticated."""
    try:
        return await get_current_user(authorization=authorization)
    except HTTPException:
        return None


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/auth/token", response_model=TokenResponse, tags=["Authentication"])
async def login(request: TokenRequest):
    """Authenticate with username and password to receive a JWT token.

    Plan J phase 2 — the issued JWT carries ``role`` / ``tenant_id``
    / ``is_super_admin`` / ``permissions`` so the listener and the
    new ``require_*`` deps can authorize from the token alone.
    """
    from db.database import ensure_db_init

    await ensure_db_init()
    async with get_db_session()() as session:
        User = get_user_model()
        result = await session.execute(
            select(User).where(User.username == request.username)
        )
        user = result.scalar_one_or_none()

        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        # Plan J: touch last_login_at so the audit trail has a
        # timestamp. Best-effort — we still issue the token even
        # if the UPDATE fails.
        try:
            user.last_login_at = datetime.now(timezone.utc)
            await session.commit()
        except Exception:  # pragma: no cover - non-fatal
            await session.rollback()

        token, expires_in = create_jwt_token(
            user.id,
            user.username,
            role=user.role,
            tenant_id=user.tenant_id,
            is_super_admin=bool(user.is_super_admin),
            permissions=[],
        )
        return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/auth/me", response_model=MeResponse, tags=["Authentication"])
async def get_current_user_info(
    current_user: dict = Depends(get_current_user),
):
    """Get information about the currently authenticated user.

    Plan J phase 2 — the response carries the user's ``tenant`` and
    a pre-computed ``permissions`` list so the front-end doesn't
    need to re-derive them. ``super_admin`` users get
    ``tenant = None`` (they live cross-tenant).
    """
    from db.database import ensure_db_init
    from db.models import Tenant

    await ensure_db_init()
    async with get_db_session()() as session:
        User = get_user_model()
        result = await session.execute(
            select(User).where(User.id == current_user["user_id"])
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        tenant_info: Optional[TenantInfo] = None
        if user.tenant_id is not None:
            tres = await session.execute(
                select(Tenant).where(Tenant.id == user.tenant_id)
            )
            t = tres.scalar_one_or_none()
            if t is not None:
                tenant_info = TenantInfo(
                    id=t.id,
                    slug=t.slug,
                    name=t.name,
                    plan=t.plan,
                    is_active=bool(t.is_active),
                )

        is_super_admin = bool(user.is_super_admin) or bool(
            current_user.get("is_super_admin")
        )
        role = user.role or current_user.get("role")
        permissions = compute_permissions(role, is_super_admin)

        return MeResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=role,
            is_super_admin=is_super_admin,
            tenant=tenant_info,
            permissions=permissions,
        )


@router.post("/auth/register", response_model=UserResponse, status_code=201, tags=["Authentication"])
async def register(request: UserCreate):
    """Register a new user account.

    Plan J phase 1: every freshly-registered user is attached to
    the seed tenant ``tnt_default`` so the multi-tenant invariant
    ``users.tenant_id IS NOT NULL`` (introduced in migration 0021)
    is satisfied without forcing the registration payload to
    grow. Plan K will introduce an ``invite_code`` parameter
    that lets an admin attach a new user to a different tenant;
    for now every new account lives in the default tenant.

    Plan J phase 2 also writes a ``tenant_memberships`` row
    alongside the ``users`` row so future multi-tenant code
    (Plan K's switcher UI, J-5's member listing) doesn't have
    to backfill from scratch.
    """
    from db.database import ensure_db_init
    import uuid

    # Plan J: lazy import keeps the model import surface small
    # and avoids a circular import between ``db.models`` and
    # ``api.v1.endpoints.auth`` on first call.
    from db.models import DEFAULT_TENANT_ID, TenantMembership

    await ensure_db_init()
    async with get_db_session()() as session:
        User = get_user_model()

        existing = await session.execute(
            select(User).where(User.username == request.username)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")

        if request.email:
            existing_email = await session.execute(
                select(User).where(User.email == request.email)
            )
            if existing_email.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already registered")

        password_hash, _ = hash_password(request.password)

        user = User(
            id=f"user_{uuid.uuid4().hex[:12]}",
            username=request.username,
            email=request.email,
            password_hash=password_hash,
            # Plan J: attach to the seed tenant. The pre-J behaviour
            # left ``tenant_id`` NULL which would now fail the
            # implicit ``tenant_id IS NOT NULL`` contract enforced
            # by J-2's event listener.
            tenant_id=DEFAULT_TENANT_ID,
            role="user",
            is_super_admin=False,
            created_at=datetime.now(timezone.utc)
        )

        session.add(user)
        await session.flush()  # need user.id for the membership row

        # Plan J phase 2 — write the membership row in the same
        # transaction so ``/auth/me`` and the listener see a
        # consistent state. ``role`` mirrors the user's role;
        # ``invited_by`` is None because registrations are
        # self-serve in MVP (admin invite flow lands in Plan K).
        session.add(TenantMembership(
            id=f"tmb_{uuid.uuid4().hex[:12]}",
            tenant_id=DEFAULT_TENANT_ID,
            user_id=user.id,
            role="user",
            invited_by=None,
            joined_at=datetime.now(timezone.utc),
        ))

        await session.commit()
        await session.refresh(user)

        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at.isoformat() if user.created_at else None
        )


@router.post("/auth/api-key", response_model=ApiKeyResponse, tags=["Authentication"])
async def create_api_key(
    current_user: dict = Depends(get_current_user)
):
    """Generate a new API key for programmatic access."""
    from db.database import ensure_db_init

    await ensure_db_init()
    async with get_db_session()() as session:
        User = get_user_model()
        result = await session.execute(
            select(User).where(User.id == current_user["user_id"])
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        full_key, fingerprint = generate_api_key()
        user.api_key_fingerprint = fingerprint
        await session.commit()

        return ApiKeyResponse(api_key=full_key, fingerprint=fingerprint)


@router.delete("/auth/api-key", status_code=204, tags=["Authentication"])
async def revoke_api_key(
    current_user: dict = Depends(get_current_user)
):
    """Revoke the current user's API key."""
    from db.database import ensure_db_init

    await ensure_db_init()
    async with get_db_session()() as session:
        User = get_user_model()
        result = await session.execute(
            select(User).where(User.id == current_user["user_id"])
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.api_key_fingerprint = None
        await session.commit()


@router.post("/auth/api-key/verify", tags=["Authentication"])
async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Verify an API key and get a JWT token in exchange."""
    from db.database import ensure_db_init

    await ensure_db_init()

    provided_fingerprint = hash_api_key(x_api_key)

    async with get_db_session()() as session:
        User = get_user_model()
        result = await session.execute(
            select(User).where(User.api_key_fingerprint == provided_fingerprint)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")

        token, expires_in = create_jwt_token(user.id, user.username)
        return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)