"""
DevFlow Backend - Authentication Endpoints

Provides JWT-based authentication for the DevFlow API.
Supports both username/password and API key authentication.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

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


def create_jwt_token(user_id: str, username: str) -> tuple[str, int]:
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
        "type": "access"
    }

    token = _pyjwt.encode(payload, secret, algorithm=algorithm)
    return token, expires_in


def verify_jwt_token(token: str) -> dict:
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
    """
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
    """Authenticate with username and password to receive a JWT token."""
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

        token, expires_in = create_jwt_token(user.id, user.username)
        return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/auth/me", response_model=UserResponse, tags=["Authentication"])
async def get_current_user_info(
    current_user: dict = Depends(get_current_user)
):
    """Get information about the currently authenticated user."""
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

        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            api_key_fingerprint=user.api_key_fingerprint,
            created_at=user.created_at.isoformat() if user.created_at else None
        )


@router.post("/auth/register", response_model=UserResponse, status_code=201, tags=["Authentication"])
async def register(request: UserCreate):
    """Register a new user account."""
    from db.database import ensure_db_init
    import uuid

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
            created_at=datetime.now(timezone.utc)
        )

        session.add(user)
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