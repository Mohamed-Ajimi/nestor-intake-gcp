"""Generic always-filter ``TenantRepository`` — the single tenant data-access seam.

This is the un-omittable repository layer (API-02): every read/write over a
tenant-owned table goes through a :class:`TenantRepository` subclass, which composes
an EXPLICIT ``WHERE space_id = <identity.space_id>`` for ``user`` requests. The
``space_id`` is taken ONLY from the verified :class:`app.auth.identity.Identity`,
NEVER from a method/handler argument — a repo method that accepted ``space_id`` would
reopen the exact "trust the client's tenant" hole this phase exists to kill
(TENANT-02 / D-01). There is no ``space_id`` parameter anywhere in this module.

Locked decisions realized here (04-CONTEXT.md / 04-RESEARCH.md):

* D-01 — belt-and-suspenders with RLS: the explicit ``WHERE`` excludes a foreign row
  INDEPENDENTLY of RLS. Even if the GUC were somehow wrong, the repo ``WHERE`` still
  filters; even if the ``WHERE`` were dropped, 0002's policy still denies. The
  ``where_filter`` test proves the repo wall on its own (RESEARCH Q3).
* D-05 — superadmin: ``identity.role == "superadmin"`` ⇒ ``_scope`` returns the
  statement UNCHANGED. Cross-tenant reach is the ``app_superadmin`` DB role + the 0003
  bypass policy (selected via the second engine in ``app/db/session.py``), NOT an
  app-layer filter and NOT a GUC (Pitfall 2).
* D-07 — existence hiding: ``get()`` returns ``None`` and ``patch()`` returns
  ``rowcount == 0`` for a cross-tenant id. The repo NEVER raises and NEVER leaks
  existence; the HTTP handler maps None/0 to a 404 (403 is reserved for the
  auth-layer / null-space denial — D-04).
* Pitfall 6 — ``Identity.space_id`` is a ``str`` but ``Intake.space_id`` is
  ``UUID(as_uuid=True)``; coerce to ``uuid.UUID(identity.space_id)`` so the pg8000
  bind/compare is unambiguous (a silently-broken coercion is caught by ``where_filter``).

The space_id-comes-only-from-Identity invariant (no method arg) is asserted by the
plan's AST/grep acceptance check and the threat register (T-04-05).
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.db.base import Base
from app.db.models.intake import Intake, IntakeAnswer, IntakeTemplate
from app.db.models.skill_run import SkillRun

M = TypeVar("M", bound=Base)


class TenantRepository(Generic[M]):
    """Base repository bound to a per-request ``Session`` + the request ``Identity``.

    Subclasses set ``model`` (e.g. :class:`IntakeRepository`). Every query is routed
    through :meth:`_scope`, which applies the explicit space filter for ``user`` and
    omits it for ``superadmin``. The ``space_id`` is derived ONLY from the injected
    ``Identity`` — there is deliberately no ``space_id`` method parameter (TENANT-02).
    """

    model: type[M]  # set by subclass (e.g. Intake)

    def __init__(self, session: Session, identity: Identity) -> None:
        self._s = session
        self._identity = identity
        self._is_super = identity.role == "superadmin"
        # space_id is ALWAYS from the verified Identity, NEVER a method arg (TENANT-02).
        # Coerce str -> uuid.UUID for the explicit WHERE (pg8000, Pitfall 6). For a
        # superadmin (space_id is None) there is no filter, so the coercion is skipped.
        self._space_id: uuid.UUID | None = (
            None if identity.space_id is None else uuid.UUID(identity.space_id)
        )

    def _scope(self, stmt):
        """Apply the tenant filter unless the identity is a superadmin.

        superadmin: return ``stmt`` unchanged — the 0003 bypass policy (matched by the
        ``app_superadmin`` connection) handles cross-tenant reach (D-05 / Pitfall 2).
        user: ``stmt.where(model.space_id == self._space_id)`` — the un-omittable wall
        (D-01). Callers never reach the raw statement, only these methods.
        """
        if self._is_super:
            return stmt
        return stmt.where(self.model.space_id == self._space_id)

    def list(self):
        """Return all rows visible to this identity (own space only for a user)."""
        return self._s.execute(self._scope(select(self.model))).scalars().all()

    def get(self, row_id):
        """Return the row by id within scope, or ``None`` (handler → 404, D-07)."""
        stmt = self._scope(select(self.model).where(self.model.id == row_id))
        return self._s.execute(stmt).scalar_one_or_none()

    def patch(self, row_id, **values):
        """Update the in-scope row by id; return rowcount (0 → handler 404, D-07).

        Never raises and never leaks existence: a cross-tenant ``row_id`` matches the
        scoped ``WHERE`` against nothing, so ``rowcount == 0`` and the foreign row is
        left untouched.
        """
        stmt = self._scope(update(self.model).where(self.model.id == row_id)).values(
            **values
        )
        result = self._s.execute(stmt)
        return result.rowcount

    @property
    def session(self) -> Session:
        """The request's bound ``Session`` — the user-path audit-write target (Pitfall 2).

        Mirrors :attr:`app.db.admin_repo.AdminRepo.session` verbatim. Exposed so a
        user-path status-transition handler can pass the SAME session to
        :func:`app.db.audit.log`, keeping the ``audit_log`` row inside the action's ONE
        transaction (D-02). The base — not only ``AdminRepo`` — must own this so the
        tenant (user) path can audit too. This is the request session, NOT a new
        engine/session, so the no-raw-DB grep-guard stays green.
        """
        return self._s

    def create(self, **values):
        """Insert one row in this identity's space and return it (user-path create).

        ``space_id`` is injected from the verified ``Identity`` (``self._space_id``) ONLY
        — it is NEVER accepted as a method kwarg (TENANT-02 / D-03 / T-06-01). For a
        ``user`` (``self._space_id is not None``) the tenant key is forced onto the row;
        a superadmin create (``self._space_id is None``) is out of scope for the tenant
        seam and goes through :class:`app.db.admin_repo.AdminRepo` against a chosen target
        space (Pitfall 3). The row is flushed so its server-side defaults / id are
        populated before return.
        """
        if self._space_id is not None:
            values["space_id"] = self._space_id  # identity-derived; never a kwarg
        row = self.model(**values)
        self._s.add(row)
        self._s.flush()
        return row


class IntakeRepository(TenantRepository[Intake]):
    """Sample/concrete repository over ``nestor.intakes`` (the Phase 4 seam driver).

    Thin subclass — all behaviour lives in :class:`TenantRepository`; Phase 6 adds one
    subclass per tenant entity the same way.
    """

    model = Intake
