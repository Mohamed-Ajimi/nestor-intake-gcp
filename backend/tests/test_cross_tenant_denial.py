"""Full-stack cross-tenant denial suite (QA-01) — the required HTTP-level gate.

Drives the REAL Phase 4 surface over live Postgres through a FastAPI ``TestClient``:
``protected_router`` (default-deny) -> ``sample_router`` (list/get/patch over intakes,
plan 03) -> ``get_tenant_repo`` -> :class:`app.db.repository.IntakeRepository`
(explicit ``WHERE`` + RLS) -> the handler's 404/403 mapping. This is the end-to-end
proof that the substrate proven unit-level in ``test_tenant_repository.py`` denies
cross-tenant access at the HTTP boundary too (QA-01 / TENANT-02 / TENANT-03 / D-04 / D-07).

What each case proves (04-VALIDATION.md ``-k`` selectors; D-07 / Pitfall 4):

| Test (``-k`` selector)        | Proves                                                      |
|-------------------------------|------------------------------------------------------------|
| ``get_cross_tenant``          | user-A GET of user-B's intake-by-id -> EXACTLY 404 AND the |
|                               | body carries no space_b intake fields (no 200-with-data    |
|                               | leak; never ``in (403, 404)``) — BOLA/IDOR, T-04-10/11.    |
| ``list_scoped``               | user-A GET /sample/intakes -> ONLY space-A rows; space-B's |
|                               | intake id is absent — TENANT-02.                           |
| ``patch_cross_tenant``        | user-A PATCH of a space-B intake -> EXACTLY 404 AND the    |
|                               | space-B row is UNCHANGED on re-read as its owner — D-07.   |
| ``superadmin_reads_all``      | a superadmin GET /sample/intakes -> rows from BOTH spaces  |
|                               | visible (catches a mis-routed superadmin engine, Pitfall 2,|
|                               | T-04-13) — TENANT-03.                                       |
| ``null_space_403``            | a user Identity with space_id=None -> EXACTLY 403 on a     |
|                               | data route (the ONLY data-route 403, D-04); no session is  |
|                               | opened for it.                                             |

DESIGN — driving the real stack against the testcontainer (no live IdP, no Cloud SQL):
The production ``get_tenant_repo`` routes through ``get_engine()`` (URL/Cloud-SQL mode)
and ``get_superadmin_engine()`` (the Cloud SQL connector + Secret Manager password) —
neither connects inside a testcontainer. So this suite overrides BOTH boundaries with
test doubles that reproduce the production ROUTING verbatim against the conftest
``engine``:

* ``get_current_identity`` is overridden to return a fabricated :class:`Identity`
  (user-A / user-B / superadmin / null-space) per case — no live ``verify_id_token``.
* ``get_tenant_repo`` is overridden by ``_tenant_repo_for(identity, engine)`` which
  mirrors ``app.db.session.get_tenant_repo`` EXACTLY: null user space -> 403 BEFORE any
  session (D-04); superadmin -> ``SET ROLE app_superadmin`` (no GUC) so the 0003 bypass
  admits cross-tenant reach (Pitfall 2 — bypass is current_user-based, the testcontainer's
  ``app_superadmin`` role is created by conftest's ``_ensure_app_superadmin``); user ->
  the per-request GUC via ``set_space_context`` (SET LOCAL, true). It yields the REAL
  ``IntakeRepository`` bound to a real ``Session`` — so the explicit ``WHERE``, the RLS
  policy, and the handler's 404/403 mapping are all genuinely exercised.

Skip-clean (conftest discipline): ``pytestmark = pytest.mark.integration`` (skips when no
Docker / DATABASE_URL); ``firebase_admin`` and ``app.*`` imports are guarded with
``pytest.importorskip`` so the file COLLECTS on the dev box without erroring.

Analogs: ``test_auth_dependency.py`` (TestClient + ``dependency_overrides``, fabricated
Identity) and ``test_rls_isolation.py`` / ``test_tenant_repository.py`` (two-space seeding).
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import _sync_pg8000_url

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT
# error) when the Admin SDK / backend deps are not installed on this box (Wave 0).
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

# app.* lands in plans 02/03 — importorskip so this suite collects cleanly until then.
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
repository = pytest.importorskip("app.db.repository")
rls_mod = pytest.importorskip("app.db.rls")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
get_tenant_repo = session_mod.get_tenant_repo
IntakeRepository = repository.IntakeRepository
set_space_context = rls_mod.set_space_context

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id is None — no single space)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _null_space_user() -> "Identity":
    """A broken/forbidden ``user`` Identity with NO space (D-04 default-deny -> 403)."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Two-space seeding helpers (shape copied from test_tenant_repository.py)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    """Insert an organization (a space). ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID) -> None:
    """Insert one intake into a space, with the GUC set so the 0002 WITH CHECK passes."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
            "VALUES (:id, :space_id, 'draft')"
        ),
        {"id": intake_id, "space_id": space_id},
    )


# ---------------------------------------------------------------------------
# The real-stack-against-testcontainer get_tenant_repo override
# ---------------------------------------------------------------------------


def _tenant_repo_for(identity: "Identity", test_engine):
    """A ``get_tenant_repo`` override that reproduces production routing verbatim.

    Mirrors ``app.db.session.get_tenant_repo`` EXACTLY (engine selection by role, the
    null-space 403 BEFORE any session, one tx/request, GUC for the user path only),
    but binds to the conftest ``test_engine`` so it runs inside the testcontainer where
    the real ``get_engine``/``get_superadmin_engine`` (Cloud SQL connector) cannot dial.
    It yields the REAL :class:`IntakeRepository` — the explicit ``WHERE``, RLS, and the
    handler's 404/403 mapping are all genuinely exercised end-to-end.

    Returns a FastAPI dependency generator (closure over ``identity`` + ``test_engine``).
    """
    from fastapi import HTTPException, status
    from sqlalchemy.orm import Session

    def _dep():
        if identity.role == "superadmin":
            # Superadmin: SET ROLE app_superadmin so current_user matches the 0003
            # *_superadmin_all bypass policy (Pitfall 2 — NO GUC is set). The
            # app_superadmin role is created by conftest's _ensure_app_superadmin.
            from sqlalchemy import text

            conn = test_engine.connect()
            trans = conn.begin()
            try:
                conn.execute(text("SET ROLE app_superadmin"))
                session = Session(bind=conn)
                yield IntakeRepository(session, identity)
                trans.commit()
            except Exception:
                trans.rollback()
                raise
            finally:
                # RESET ROLE on a non-aborted connection before it returns to the pool
                # (SET ROLE is session-scoped — a leak would corrupt later requests).
                try:
                    conn.execute(text("RESET ROLE"))
                except Exception:  # noqa: BLE001 -- best-effort; connection closed next
                    pass
                conn.close()
            return

        # D-04 default-deny: a user with no space is rejected BEFORE any session/tx is
        # opened — an unset GUC must never reach a query. This is the ONLY data-route 403.
        if not identity.space_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No space — not authorized")

        # User path: one tx, set the tenant GUC (SET LOCAL, true), yield the real repo.
        with test_engine.begin() as conn:
            set_space_context(conn, identity.space_id)
            session = Session(bind=conn)
            yield IntakeRepository(session, identity)

    return _dep


# ---------------------------------------------------------------------------
# App + client builder (the REAL routers under test)
# ---------------------------------------------------------------------------


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + sample_router.

    Mirrors app/main.py's wiring (sample_router mounted UNDER the default-deny
    protected_router) without the health probes / lifespan / CORS — the surface under
    test is the routers, not the app lifecycle.
    """
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.sample_routes import sample_router

    protected_router.include_router(sample_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b):
    """Create two spaces + one intake each (each insert under its own-space GUC)."""
    with engine.begin() as conn:
        _create_space(conn, space_a, "Space A (denial suite)")
        _create_space(conn, space_b, "Space B (denial suite)")
    with engine.begin() as conn:
        _insert_intake(conn, set_space, space_a, intake_a)
    with engine.begin() as conn:
        _insert_intake(conn, set_space, space_b, intake_b)


def _cleanup_spaces(engine, space_a, space_b):
    """Delete the seeded organizations as the owner (CASCADE removes the intakes)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
            {"a": space_a, "b": space_b},
        )


# ===========================================================================
# Case: get_cross_tenant — user-A GET user-B's intake-by-id -> EXACTLY 404
# ===========================================================================


def test_get_cross_tenant_returns_404_no_foreign_body(engine, set_space, two_spaces):
    """user-A GET of user-B's intake-by-id -> 404 (exact), with NO space_b fields.

    The repo's scoped ``WHERE`` (+ RLS) excludes space_b's row, so ``repo.get`` returns
    ``None`` and the handler raises 404 — never 403, never 200-with-data (no BOLA/IDOR
    disclosure, no enumeration via code differences; pinned EXACT, never ``in (403, 404)``).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        app.dependency_overrides[get_tenant_repo] = _tenant_repo_for(
            _user(space_a), engine
        )
        client = TestClient(app)
        resp = client.get(
            f"/sample/intakes/{intake_b}",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        # EXACT 404 — never `in (403, 404)` (D-07 / Pitfall 4 / T-04-11).
        assert resp.status_code == 404, (
            f"cross-tenant GET-by-id must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/200 would leak existence (BOLA/IDOR)."
        )
        # No space_b intake fields leaked in the body (no 200-with-data path).
        body = resp.text
        assert str(intake_b) not in body, "404 body leaked the foreign intake id."
        assert str(space_b) not in body, "404 body leaked the foreign space_id."
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: list_scoped — user-A list -> ONLY space-A rows
# ===========================================================================


def test_list_scoped_to_own_space(engine, set_space, two_spaces):
    """user-A GET /sample/intakes -> only space-A rows; space-B's intake id is absent."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        app.dependency_overrides[get_tenant_repo] = _tenant_repo_for(
            _user(space_a), engine
        )
        client = TestClient(app)
        resp = client.get(
            "/sample/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )

        assert resp.status_code == 200, f"own-space list should be 200, got {resp.status_code}."
        ids = {row["id"] for row in resp.json()}
        assert str(intake_a) in ids, "own-space list() should include space_a's intake."
        assert str(intake_b) not in ids, (
            "TENANT-02 LEAK: own-space list() returned space_b's intake."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: patch_cross_tenant — user-A PATCH space-B intake -> 404, row unchanged
# ===========================================================================


def test_patch_cross_tenant_returns_404_row_unchanged(engine, set_space, two_spaces):
    """user-A PATCH of a space-B intake -> EXACTLY 404, and the space-B row is unchanged.

    ``repo.patch`` matches the scoped ``WHERE`` against nothing -> ``rowcount == 0`` ->
    handler 404 (never 403, never a silent success). The foreign row is re-read as its
    OWNER (space_b GUC) and asserted unchanged (still ``draft``).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        app.dependency_overrides[get_tenant_repo] = _tenant_repo_for(
            _user(space_a), engine
        )
        client = TestClient(app)
        resp = client.patch(
            f"/sample/intakes/{intake_b}",
            json={"status": "submitted"},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        # EXACT 404 — never `in (403, 404)` (D-07).
        assert resp.status_code == 404, (
            f"cross-tenant PATCH must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r})."
        )

        # The foreign row must be UNTOUCHED — re-read as the owner (space_b GUC).
        with engine.begin() as conn:
            set_space(conn, space_b)
            status = conn.execute(
                text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_b},
            ).scalar_one()
        assert status == "draft", (
            f"cross-tenant PATCH leaked through: space_b row status={status!r} "
            "(expected unchanged 'draft')."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: superadmin_reads_all — superadmin sees BOTH spaces (Pitfall 2)
# ===========================================================================


def test_superadmin_reads_all_spaces(engine, set_space, two_spaces):
    """A superadmin GET /sample/intakes -> rows from BOTH spaces are visible.

    Positive cross-tenant test: the superadmin path SET ROLE app_superadmin (no GUC)
    triggers the 0003 bypass, so both seeded intake ids appear. A mis-routed/confined
    superadmin engine (e.g. one that set a GUC or used the app role) would fail here
    loudly (Pitfall 2 / T-04-13).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        app.dependency_overrides[get_tenant_repo] = _tenant_repo_for(
            _superadmin(), engine
        )
        client = TestClient(app)
        resp = client.get(
            "/sample/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )

        assert resp.status_code == 200, f"superadmin list should be 200, got {resp.status_code}."
        ids = {row["id"] for row in resp.json()}
        assert str(intake_a) in ids and str(intake_b) in ids, (
            "TENANT-03: superadmin must read across BOTH spaces — a mis-routed "
            f"superadmin engine confined the read (visible ids={ids})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: null_space_403 — user with space_id=None -> EXACTLY 403, no session opened
# ===========================================================================


def test_null_space_403_user_denied(engine, set_space, two_spaces):
    """A ``user`` Identity with ``space_id=None`` -> EXACTLY 403 on a data route (D-04).

    This is the ONLY data-route 403 — the default-deny on a broken/forbidden null-space
    user, rejected BEFORE any session/tx is opened (an unset GUC must never reach a
    query). Distinct from the 404 cross-tenant-by-id codes (no enumeration confusion).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        app.dependency_overrides[get_current_identity] = _as(_null_space_user())
        app.dependency_overrides[get_tenant_repo] = _tenant_repo_for(
            _null_space_user(), engine
        )
        client = TestClient(app)
        resp = client.get(
            "/sample/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )

        # EXACT 403 — the null-space default-deny (D-04), NOT the 404 data-by-id code.
        assert resp.status_code == 403, (
            f"null-space user must be EXACTLY 403, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)
