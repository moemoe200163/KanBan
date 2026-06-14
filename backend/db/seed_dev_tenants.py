"""
Dev seed for the Plan J multi-tenant refactor.

Idempotently creates:

* 1 ``Tenant`` — ``tnt_default`` (slug ``default``, name ``Default
  Tenant``, plan ``pro``, ``is_active=True``).
* 4 ``User`` accounts, all with password ``dev123!``:

  +-------------+------------------+------------------+----------------+
  | username    | role             | tenant_id        | super_admin    |
  +=============+==================+==================+================+
  | superadmin  | super_admin      | NULL (cross)     | True           |
  +-------------+------------------+------------------+----------------+
  | admin@default| admin           | tnt_default      | False          |
  +-------------+------------------+------------------+----------------+
  | ops@default  | ops             | tnt_default      | False          |
  +-------------+------------------+------------------+----------------+
  | user@default | user            | tnt_default      | False          |
  +-------------+------------------+------------------+----------------+

The 4 accounts let the operator exercise every role path in the
``auth_deps`` module without going through the registration flow
in dev. The ``@default`` suffix is so the emails stay unique when
``users.email`` carries a unique constraint — username is already
unique but the leader's dev environment has historically had a
single ``admin`` account collide with new test users.

Usage::

    cd backend
    python -m db.seed_dev_tenants

The script reads ``DATABASE_URL`` (or the default
``sqlite+aiosqlite:///./devflow.db``) and uses the same async
session factory as the rest of the backend. Safe to run on a
fresh DB and on a DB already at migration head — every step is
guarded by a SELECT-first check.

This is dev-only. Production deployments don't run this script.
The Alembic migration ``0021_tenants_and_tenant_id`` creates the
``tnt_default`` row on its own; this script is a superset that
also adds the 4 user accounts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Tenant, User

logger = logging.getLogger("seed_dev_tenants")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ---------------------------------------------------------------------------
# Defaults — keep in sync with the migration 0021
# ---------------------------------------------------------------------------

DEFAULT_TENANT_ID = "tnt_default"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default Tenant"
DEFAULT_TENANT_PLAN = "pro"

DEV_PASSWORD = "dev123!"

DEV_USERS = [
    # NOTE: the ``superadmin`` row intentionally has NO
    # ``tenant_memberships`` entry. A membership is a (tenant, user,
    # role) join row that means "this user has the given role in the
    # given tenant"; a super_admin has *no* home tenant, so writing
    # a membership for them would mean picking a tenant arbitrarily
    # (we'd choose ``tnt_default``) and that membership would
    # misrepresent the model. The ``users.is_super_admin`` flag is
    # the contract; the cross-tenant leader's role is read off that
    # flag, not from any membership row.
    #
    # This is *by design*. A test or endpoint that wants to know
    # "is this user a super admin?" reads ``User.is_super_admin``;
    # a test that wants "is this user a member of tenant X?" reads
    # ``TenantMembership``. The two questions are intentionally
    # orthogonal. If a future Plan K feature wants to attach a
    # super_admin to a specific tenant for "view-as" or
    # impersonation flows, that membership should be written
    # explicitly with ``invited_by=None`` and a meaningful
    # ``joined_at``, not auto-derived from this seed.
    {
        "id": "user_superadmin_0001",
        "username": "superadmin",
        "email": "superadmin@dev.local",
        "role": "super_admin",
        "tenant_id": None,           # cross-tenant
        "is_super_admin": True,
        "full_name": "Cross-Tenant Super Admin",
    },
    {
        "id": "user_admin_default01",
        "username": "admin@default",
        "email": "admin@dev.local",
        "role": "admin",
        "tenant_id": DEFAULT_TENANT_ID,
        "is_super_admin": False,
        "full_name": "Default Tenant Admin",
    },
    {
        "id": "user_ops_default00001",
        "username": "ops@default",
        "email": "ops@dev.local",
        "role": "ops",
        "tenant_id": DEFAULT_TENANT_ID,
        "is_super_admin": False,
        "full_name": "Default Tenant Ops",
    },
    {
        "id": "user_user_default001",
        "username": "user@default",
        "email": "user@dev.local",
        "role": "user",
        "tenant_id": DEFAULT_TENANT_ID,
        "is_super_admin": False,
        "full_name": "Default Tenant User",
    },
]


# ---------------------------------------------------------------------------
# Password hashing — sym-linked to ``api.v1.endpoints.auth`` so the
# seed users can log in through ``/api/v1/auth/token`` unchanged.
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return salt + key.hex()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_default_tenant(session: AsyncSession) -> Tenant:
    """Create ``tnt_default`` if it doesn't already exist. Returns
    the row (existing or freshly created)."""
    existing = (await session.execute(
        select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)
    )).scalar_one_or_none()
    if existing is not None:
        logger.info("tenant %s already exists; skipping", DEFAULT_TENANT_ID)
        return existing

    tenant = Tenant(
        id=DEFAULT_TENANT_ID,
        slug=DEFAULT_TENANT_SLUG,
        name=DEFAULT_TENANT_NAME,
        plan=DEFAULT_TENANT_PLAN,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(tenant)
    await session.flush()
    logger.info("created tenant %s (slug=%s)", tenant.id, tenant.slug)
    return tenant


async def _ensure_dev_user(session: AsyncSession, payload: dict) -> bool:
    """Create the named dev user if not present. Returns True if a
    new row was inserted, False if the user already existed."""
    existing = (await session.execute(
        select(User).where(User.username == payload["username"])
    )).scalar_one_or_none()
    if existing is not None:
        # Update role / tenant_id / super_admin in case the seed
        # defaults have changed since the last run. The password
        # hash is left alone — the operator can reset it through
        # /api/v1/auth/api-key or by deleting the row and re-running.
        existing.role = payload["role"]
        existing.tenant_id = payload["tenant_id"]
        existing.is_super_admin = payload["is_super_admin"]
        existing.email = payload["email"]
        existing.full_name = payload["full_name"]
        existing.is_active = True
        logger.info("user %s already exists; refreshed role/tenant", payload["username"])
        return False

    user = User(
        id=payload["id"],
        username=payload["username"],
        email=payload["email"],
        password_hash=_hash_password(DEV_PASSWORD),
        full_name=payload["full_name"],
        role=payload["role"],
        tenant_id=payload["tenant_id"],
        is_super_admin=payload["is_super_admin"],
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    await session.flush()
    logger.info("created user %s (role=%s, tenant=%s)", user.username, user.role, user.tenant_id)
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run() -> dict:
    """Seed the dev tenant + 4 user accounts. Returns a small report
    dict with the counts so the CLI can echo it."""
    # Import here so ``from db.seed_dev_tenants import run`` works
    # even if the engine is not configured yet.
    from db.database import _normalize_database_url, _raw_db_url

    url = _normalize_database_url(_raw_db_url)
    engine = create_async_engine(url, echo=False)
    Session: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )

    inserted_tenants = 0
    inserted_users = 0
    refreshed_users = 0

    try:
        # Best-effort: make sure the schema is up before we write.
        # On the Postgres path the lifespan already ran
        # ``alembic upgrade head``; on the SQLite pytest path the
        # test fixture has already done ``create_all``. The seed
        # script is a no-op on a brand-new DB only if the user has
        # already run ``alembic upgrade head`` or ``init_db``.
        from db.database import ensure_db_init, is_postgres
        if not is_postgres():
            # SQLite path: run create_all idempotently so the seed
            # script is self-contained for the dev loop
            # (``. /db/seed_dev_tenants.py`` from a clean checkout).
            from db.models import Base
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            # ``ensure_db_init`` is a no-op once ``init_db`` has
            # run, but a freshly-created engine hasn't flipped its
            # module-level flag — re-init on the SQLite path is
            # cheap and the only way to get ``create_all`` to
            # happen before our INSERTs.
            tenant_existed = (await session.execute(
                select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)
            )).scalar_one_or_none() is not None
            await _ensure_default_tenant(session)
            if not tenant_existed:
                inserted_tenants += 1

            for payload in DEV_USERS:
                if await _ensure_dev_user(session, payload):
                    inserted_users += 1
                else:
                    refreshed_users += 1

            await session.commit()
    finally:
        await engine.dispose()

    return {
        "tenants_inserted": inserted_tenants,
        "users_inserted": inserted_users,
        "users_refreshed": refreshed_users,
        "password": DEV_PASSWORD,
    }


def main() -> int:
    report = asyncio.run(run())
    print("\nDev seed complete:")
    print(f"  tenants inserted : {report['tenants_inserted']}")
    print(f"  users inserted   : {report['users_inserted']}")
    print(f"  users refreshed  : {report['users_refreshed']}")
    print(f"  dev password     : {report['password']}")
    print("\nLogin with one of:")
    for u in DEV_USERS:
        suffix = " (super_admin, cross-tenant)" if u["is_super_admin"] else f" (role={u['role']}, tenant={u['tenant_id']})"
        print(f"  - {u['username']:<18} {suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
