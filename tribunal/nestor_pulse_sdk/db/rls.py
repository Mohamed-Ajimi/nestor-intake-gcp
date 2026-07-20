"""
RLS helper -- canonical SET LOCAL pattern for `app.tenant_id`.

Authoritative reference: 01-RESEARCH.md lines 354-359 (verbatim).

CRITICAL -- 01-RESEARCH.md Pitfall 1:
    Use `set_config('app.tenant_id', :tid, true)`. The third argument
    `true` makes the setting **transaction-local** (equivalent to
    PostgreSQL's `SET LOCAL`). NEVER pass `false` -- that produces a
    session-scoped setting that leaks across pooled connections (e.g.
    PgBouncer transaction mode), which is a catastrophic cross-tenant
    data leak.

The caller MUST be inside an open transaction when invoking this helper:

    async with session.begin():            # opens a transaction
        await set_tenant_context(session, tenant_id)
        ...                                # all queries here see the var

See 01-RESEARCH.md § Anti-patterns line 583 for the worker-side guidance
(claim row with elevated role, then SET LOCAL the claimed run.tenant_id
before any further query).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, tenant_id) -> None:
    """SET LOCAL app.tenant_id = <tenant_id> for the current transaction.

    Third arg `true` == transaction-scoped (Pitfall 1). NEVER pass false.

    `tenant_id` may be a uuid.UUID, str, or anything stringifiable -- the
    Postgres-side RLS policy reads `current_setting('app.tenant_id')::uuid`
    so we always send the canonical string form here.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
