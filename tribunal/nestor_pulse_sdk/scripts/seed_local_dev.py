"""
Seed the fixed dev tenant for LOCAL_DEV_AUTH.

Inserts (idempotently) the dev `org` + dev `app_user` whose UUIDs match
nestor_pulse_sdk.auth.local_dev. Without these rows:
  - get_db_session sets app.tenant_id to a tenant with no org row, and
  - create_project's owner FK (app_user.id) would fail.

Run AFTER `alembic upgrade head`, with DATABASE_URL pointing at the local DB:

    $env:DATABASE_URL = "postgresql+asyncpg://postgres@localhost:5433/nestor"
    .venv\Scripts\python.exe -m nestor_pulse_sdk.scripts.seed_local_dev

Idempotent: safe to re-run. Connecting as the local superuser bypasses RLS,
so no tenant context is needed for the inserts.
"""
from __future__ import annotations

import asyncio

from nestor_pulse_sdk.auth.local_dev import (
    DEV_EMAIL,
    DEV_ORG_NAME,
    DEV_ORG_SLUG,
    DEV_PROVIDER_UID,
    DEV_TENANT_ID,
    DEV_USER_ID,
)
from nestor_pulse_sdk.db.base import get_sessionmaker
from nestor_pulse_sdk.db.models import Org, User


async def seed() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            org = await session.get(Org, DEV_TENANT_ID)
            if org is None:
                session.add(Org(id=DEV_TENANT_ID, name=DEV_ORG_NAME, slug=DEV_ORG_SLUG))
                print(f"+ org   {DEV_TENANT_ID}  '{DEV_ORG_NAME}'")
            else:
                print(f"= org   {DEV_TENANT_ID}  (exists)")

            user = await session.get(User, DEV_USER_ID)
            if user is None:
                session.add(User(
                    id=DEV_USER_ID,
                    tenant_id=DEV_TENANT_ID,
                    email=DEV_EMAIL,
                    provider_user_id=DEV_PROVIDER_UID,
                    role="admin",
                ))
                print(f"+ user  {DEV_USER_ID}  '{DEV_EMAIL}'")
            else:
                print(f"= user  {DEV_USER_ID}  (exists)")
    print("dev tenant seeded.")


if __name__ == "__main__":
    asyncio.run(seed())
