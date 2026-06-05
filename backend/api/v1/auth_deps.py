"""
Shared authentication dependencies for API routers.

Usage in router files:
    from api.v1.auth_deps import require_auth, optional_auth

    router = APIRouter(dependencies=[Depends(require_auth)])  # all endpoints require auth
    # or per-endpoint:
    @router.get("/thing")
    async def get_thing(user: dict = Depends(optional_auth)):
        ...
"""

from api.v1.endpoints.auth import get_current_user, get_optional_user

# Alias for clarity when used as router-level dependency.
require_auth = get_current_user
optional_auth = get_optional_user
