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
from app.db.admin_repo import AdminRepo
from app.db.base import get_engine, get_sessionmaker, get_superadmin_engine
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    IntakeSourceRepository,
    IntakeTemplateRepository,
    ResearchArtifactRepository,
    SkillRunRepository,
)
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


def get_intake_answer_repo(identity: Identity = Depends(get_current_identity)):
    """Yield a tenant-scoped :class:`IntakeAnswerRepository` for the current request.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to :func:`get_tenant_repo`
    (engine-by-role, default-deny 403 on a null user space BEFORE any session, ONE tx via
    ``maker.begin()``, GUC set for the user path only), differing ONLY in the repository
    class yielded.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield IntakeAnswerRepository(session, identity)


def get_intake_and_answer_repos(identity: Identity = Depends(get_current_identity)):
    """Yield BOTH an :class:`IntakeRepository` and an :class:`IntakeAnswerRepository`
    bound to the SAME session — for the answers write path's ownership-gated upsert.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to :func:`get_intake_answer_repo`
    (engine-by-role, default-deny 403 on a null user space BEFORE any session, ONE tx via
    ``maker.begin()``, GUC set for the user path only), differing ONLY in that it yields a
    TUPLE of two repositories constructed from the one ``session``.

    Why combined: ``upsert_answers`` must first verify the caller OWNS ``intake_id``
    (``IntakeRepository.get`` -> None -> 404, D-07) BEFORE upserting (``IntakeAnswerRepository``).
    Both must run on ONE transaction (D-02 — one tx/request); yielding both repos from the
    SAME ``session`` here keeps the ownership read and the write atomic, with NO second
    ``maker.begin()`` / second dependency.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield (
            IntakeRepository(session, identity),
            IntakeAnswerRepository(session, identity),
        )


def get_intake_and_source_repos(identity: Identity = Depends(get_current_identity)):
    """Yield BOTH an :class:`IntakeRepository` and an :class:`IntakeSourceRepository`
    bound to the SAME session — for the storage router's ownership-gated upload/delete.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to
    :func:`get_intake_and_answer_repos` (engine-by-role, default-deny 403 on a null user
    space BEFORE any session, ONE tx via ``maker.begin()``, GUC set for the user path
    only), differing ONLY in that the SECOND repository yielded is an
    :class:`IntakeSourceRepository`.

    Why combined: the storage upload/delete handlers must FIRST verify the caller OWNS
    ``intake_id`` (``IntakeRepository.get`` -> None -> 404, D-08) BEFORE writing/cleaning
    an ``intake_sources`` row (``IntakeSourceRepository``). Both must run on ONE
    transaction (D-02); yielding both repos from the SAME ``session`` here keeps the
    ownership read and the source-row create/delete atomic (D-07 / D-09), with NO second
    ``maker.begin()`` / second dependency. ``space_id`` on the source-row create is
    injected from the verified Identity (TENANT-02) — never a request/method arg.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield (
            IntakeRepository(session, identity),
            IntakeSourceRepository(session, identity),
        )


def get_skill_run_repo(identity: Identity = Depends(get_current_identity)):
    """Yield a tenant-scoped :class:`SkillRunRepository` for the current request.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to :func:`get_tenant_repo`,
    differing ONLY in the repository class yielded.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield SkillRunRepository(session, identity)


def get_research_artifact_repo(identity: Identity = Depends(get_current_identity)):
    """Yield a tenant-scoped :class:`ResearchArtifactRepository` for the current request.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to :func:`get_skill_run_repo`,
    differing ONLY in the repository class yielded. Backs the context-pack READ endpoint
    (07-09): engine-by-role, default-deny 403 on a null user space BEFORE any session
    (D-04 — mitigates T-7-09-03), ONE tx via ``maker.begin()`` (D-02), GUC set for the user
    path only (Pitfall 2). The scoped read walls cross-tenant artifacts out (T-7-09-01).
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield ResearchArtifactRepository(session, identity)


def get_intake_template_repo(identity: Identity = Depends(get_current_identity)):
    """Yield a tenant-scoped :class:`IntakeTemplateRepository` for the current request.

    Sync generator dependency (Pitfall 5) — body IDENTICAL to :func:`get_tenant_repo`,
    differing ONLY in the repository class yielded.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield IntakeTemplateRepository(session, identity)


def get_me_session(identity: Identity = Depends(get_current_identity)):
    """Yield the request ``Session`` for the ``/me`` locale endpoints (Phase 11).

    ``GET /me`` / ``PATCH /me/locale`` read the caller's own membership + its organization
    (both ROOT tables — ``organization_memberships`` / ``organizations`` — NOT RLS-scoped),
    for BOTH roles. Unlike :func:`get_tenant_repo`, this does NOT default-deny a caller with
    no space: a ``superadmin`` legitimately has ``space_id`` None (and may have NO membership
    row at all — Open Q1), and the ``/me`` resolution must still return ``locale: null`` +
    ``space_default_locale: "nl"`` for them rather than 403.

    Engine-by-role mirrors the rest of ``session.py`` (D-05): a ``superadmin`` opens the tx on
    the ``app_superadmin`` engine (0003 bypass; NO GUC — Pitfall 2); a ``user`` opens it on the
    app engine and sets the tenant GUC so any incidental RLS-scoped read stays space-scoped
    (the two root tables this endpoint reads are not RLS-scoped, but the GUC-set keeps the
    user path identical to every other tenant dependency and safe if the read set ever grows).

    Sync generator dependency (Pitfall 5) — pg8000 is blocking; never ``async def``. Yields the
    bound ``Session`` directly (not a repo): ``/me`` needs cross-cutting reads of two root
    tables keyed on the verified ``identity``, not a tenant/admin repository surface.
    """
    if identity.role == "superadmin":
        engine = get_superadmin_engine()
        space_id = None
    else:
        # A ``user`` always carries a space (their membership's org); a null space is a
        # broken/forbidden state, rejected BEFORE any session opens (D-04 default-deny).
        if not identity.space_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No space — not authorized"
            )
        engine = get_engine()
        space_id = identity.space_id

    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        if space_id is not None:
            set_space_context(session, space_id)
        yield session


def get_admin_session(identity: Identity = Depends(get_current_identity)):
    """Yield an :class:`AdminRepo` for the current request — superadmin ONLY (Phase 5).

    The admin API's single data-access DI seam (USER-01/03, AUTH-04, QA-04). It mirrors
    :func:`get_tenant_repo`'s engine/tx wiring but with three deliberate differences:

    * **Superadmin-only gate (T-5-13, default-deny):** a non-superadmin Identity is
      rejected with **403 BEFORE any session/tx is opened** — the gate fires in the
      dependency, so every admin route is superadmin-only without per-route checks and a
      ``user`` never reaches an admin handler or a DB connection. This is the
      EoP-mitigating wall (verified by the user-role 403 test).
    * **Superadmin engine, NO GUC (Pitfall 2/3):** it opens the tx on
      :func:`app.db.base.get_superadmin_engine` (``app_superadmin`` -> the 0003 bypass
      policy) and sets NO ``app.current_space_id`` GUC — the bypass is current_user-based,
      not GUC-based — so the admin path reaches root + cross-space tables.
    * **Yields an** :class:`AdminRepo` **(not a TenantRepository):** the unfiltered root +
      cross-space accessors (no ``_scope`` / ``space_id ==`` filter, no delete).

    ONE transaction per request via ``with maker.begin()`` (D-02): every mutation handler
    writes its ``audit_log`` row on THIS same session (``app.db.audit.log``), so action +
    audit commit/rollback atomically (T-5-16 — no orphan/missing audit rows).

    Pitfall 5: this is a SYNC ``def`` generator (pg8000 is blocking; FastAPI runs sync
    dependencies in a threadpool). It MUST NOT be ``async def``.
    """
    # T-5-13 superadmin-only gate: reject FIRST, connect SECOND. A non-superadmin never
    # opens a session — the 403 fires before any engine selection / maker.begin().
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")

    # Superadmin engine (0003 bypass). NO GUC is set (Pitfall 2/3) — the bypass is
    # current_user-based, so the admin path reaches root + cross-space tables.
    engine = get_superadmin_engine()
    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx/request; commit/rollback + conn return
        yield AdminRepo(session, identity)
