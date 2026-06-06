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
"""

from fastapi import Depends, HTTPException
from sqlalchemy import select

from api.v1.endpoints.auth import get_current_user, get_optional_user

# Alias for clarity when used as router-level dependency.
require_auth = get_current_user
optional_auth = get_optional_user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role."""
    from db.database import ensure_db_init, AsyncSessionLocal
    from db.models import User

    await ensure_db_init()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == current_user["user_id"])
        )
        user = result.scalar_one_or_none()

        if not user or user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

    return current_user
