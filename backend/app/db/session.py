"""``get_tenant_repo`` — the FastAPI dependency that wires Identity → engine → tx → repo.

This is the one place a protected feature endpoint acquires tenant-scoped data access.
It composes :func:`app.auth.dependencies.get_current_identity` (so auth — 401/403 split
— runs first), then derives EVERYTHING about the connection identity and tenant scope
from the verified :class:`app.auth.identity.Identity`, never from request input.

Locked decisions realized here (04-CONTEXT.md / 04-RESEARCH.md Pattern 2):

* D-02 — ONE transaction per request via ``with maker.begin()``: commit/rollback +
  connection return are guaranteed even on a handler exception (a failed cross-tenant
  write leaves no partial state). The tenant GUC is set ``SET LOCAL`` (tx-local) via
  :func:`app.db.rls.set_space_context` and reverts at COMMIT; the per-checkin RESET in
  ``app/db/base.py`` is the defensive backstop (Pitfall 1).
* D-04 — default-deny: a ``user`` with a null/empty ``space_id`` is a broken/forbidden
  state and is rejected with 403 BEFORE any session/tx is opened — an unset GUC must
  never reach a query.
* D-05 — two-engine routing keyed on ``Identity.role``: a ``superadmin`` opens a tx on
  :func:`app.db.base.get_superadmin_engine` (the ``app_superadmin`` role → 0003 bypass)
  and sets NO GUC (the bypass is current_user-based, not GUC-based — Pitfall 2); a
  ``user`` opens a tx on :func:`app.db.base.get_engine` (the app role) and sets the GUC.
* D-01 / D-07 — the dependency yields an :class:`app.db.repository.IntakeRepository`;
  the explicit ``WHERE`` (repo) + RLS (DB) are both in force, and the repo returns
  None/0-rows (→ handler 404) for a cross-tenant id, never the auth-layer 403.

The space_id used to scope the request comes ONLY from ``Identity`` (no request arg).

Pitfall 5: this dependency is a SYNC ``def`` generator (pg8000 is blocking; FastAPI
runs sync dependencies/handlers in a threadpool). It MUST NOT be ``async def`` — an
async dependency calling the sync engine would stall the event loop.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.db.base import get_engine, get_sessionmaker, get_superadmin_engine
from app.db.repository import IntakeRepository
from app.db.rls import set_space_context


def get_tenant_repo(identity: Identity = Depends(get_current_identity)):
    """Yield a tenant-scoped :class:`IntakeRepository` for the current request.

    Sync generator dependency (Pitfall 5). Selects the engine by ``identity.role``,
    enforces default-deny on a null user space BEFORE opening any session (D-04),
    opens ONE transaction (D-02), sets the tenant GUC for the user path only (D-05),
    and yields the repository bound to that session + identity.
    """
    if identity.role == "superadmin":
        # D-05: cross-tenant operator. The app_superadmin engine + 0003 bypass policy
        # provide cross-tenant reach; NO GUC is set (Pitfall 2 — bypass is
        # current_user-based, not GUC-based).
        engine = get_superadmin_engine()
        space_id = None
    else:
        # D-04 default-deny: a user with no space is a broken/forbidden state. Reject
        # FIRST, connect SECOND — never open a tx with an unset GUC.
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()  # app role; RLS-scoped via the GUC below
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            # SET LOCAL (tx-local, third arg true) — reverts at COMMIT (Pitfall 1).
            set_space_context(session, space_id)
        yield IntakeRepository(session, identity)
