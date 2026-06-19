"""RLS helper — the canonical transaction-local ``SET LOCAL`` pattern for
``app.current_space_id``.

This is the Phase 3 (auth) / Phase 4 (repository) contract: every request that
touches a tenant-owned table MUST call :func:`set_space_context` once, inside an
open transaction, before any tenant-scoped query. The RLS policies authored in
the ``0002`` migration read the value back via
``NULLIF(current_setting('app.current_space_id', true), '')::uuid``.

CRITICAL — 01-RESEARCH.md Pitfall 1 (transaction-local GUC):
    The third argument to ``set_config`` is ``true``, which makes the setting
    **transaction-local** (equivalent to PostgreSQL's ``SET LOCAL``). NEVER pass
    ``false`` and NEVER use a bare ``SET app.current_space_id = ...`` — a
    session-scoped GUC leaks across pooled connections (PgBouncer transaction
    mode), which is a catastrophic cross-tenant data leak. The pooled-reuse
    regression ``test_concurrent_different_spaces_stay_isolated`` exists to
    guard exactly this.

Driver note (Q1 RESOLVED, mirrors ``app/db/base.py``): Phase 1 standardizes on
the **sync pg8000** driver, so this helper is synchronous and takes either a
SQLAlchemy ``Connection`` or ``Session`` (anything exposing ``.execute``). The
sibling repo ``MOELD/Nestor/nestor_pulse_sdk/db/rls.py`` is the async asyncpg
variant; this is the sync equivalent with the global rename applied
(``app.tenant_id`` -> ``app.current_space_id``).

The caller MUST be inside an open transaction when invoking this helper::

    with engine.begin() as conn:              # opens a transaction
        set_space_context(conn, space_id)
        ...                                   # all queries here see the GUC
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

# The transaction-local GUC key. MUST match the policy expression authored in
# 0002_rls_policies.py and the test harness (tests/conftest.py SPACE_GUC_KEY).
SPACE_GUC_KEY = "app.current_space_id"


def set_space_context(conn_or_session: Any, space_id: Any) -> None:
    """``SET LOCAL app.current_space_id = <space_id>`` for the current tx.

    Third arg ``true`` == transaction-scoped (Pitfall 1). NEVER pass ``false``.

    ``space_id`` may be a ``uuid.UUID``, ``str``, or anything stringifiable —
    the Postgres-side RLS policy reads
    ``NULLIF(current_setting('app.current_space_id', true), '')::uuid`` so we
    always send the canonical string form here.

    ``conn_or_session`` is a sync SQLAlchemy ``Connection`` or ``Session``
    (matches ``app/db/base.py``'s sync pg8000 engine and the conftest
    ``set_space`` fixture, which both call ``.execute`` synchronously).
    """
    conn_or_session.execute(
        text("SELECT set_config('app.current_space_id', :sid, true)"),
        {"sid": str(space_id)},
    )
