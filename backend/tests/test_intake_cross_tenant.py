"""Full-stack cross-tenant denial suite (QA-01 / TENANT-04) — the required HTTP-level gate.

Re-pointed from the throwaway disposable driver onto the REAL Phase-6 intake surface
(plan 04, Pitfall 5 — re-point BEFORE the disposable surface is deleted, so there is never
a coverage gap). Drives the production routers over live Postgres through a FastAPI
``TestClient``: ``protected_router`` (default-deny) -> the real ``intake_router``
(``/intakes`` list / get / patch, plan 03) -> the PRODUCTION
``app.db.session.get_tenant_repo`` -> the real :class:`app.db.repository.IntakeRepository`
(explicit ``WHERE`` + RLS) -> the handler's 404/403 mapping. This is the end-to-end proof
that the substrate proven unit-level in ``test_tenant_repository.py`` denies cross-tenant
access at the HTTP boundary too (QA-01 / TENANT-02 / TENANT-03 / TENANT-04 / D-04 / D-07).

What each case proves (D-07 / Pitfall 4):

| Test (``-k`` selector)        | Proves                                                      |
|-------------------------------|------------------------------------------------------------|
| ``get_cross_tenant``          | user-A GET of user-B's intake-by-id -> EXACTLY 404 AND the |
|                               | body carries no space_b intake fields (no 200-with-data    |
|                               | leak; never ``in (403, 404)``) — BOLA/IDOR, T-06-10.       |
| ``list_scoped``               | user-A GET /intakes -> ONLY space-A rows; space-B's        |
|                               | intake id is absent — TENANT-02.                           |
| ``patch_cross_tenant``        | user-A PATCH of a space-B intake -> EXACTLY 404 AND the    |
|                               | space-B row is UNCHANGED on re-read as its owner — D-07.   |
| ``superadmin_reads_all``      | a superadmin GET /intakes -> rows from BOTH spaces visible |
|                               | (catches a mis-routed superadmin engine, Pitfall 2,        |
|                               | T-04-13) — TENANT-03.                                      |
| ``null_space_403``            | a user Identity with space_id=None -> EXACTLY 403 on a     |
|                               | data route (the ONLY data-route 403, D-04); no session is  |
|                               | opened for it.                                             |

DESIGN — driving the REAL ``get_tenant_repo`` against the testcontainer (CR-01 fix):
The production ``get_tenant_repo`` (``app/db/session.py``) routes through
``app.db.base.get_engine()`` (Cloud-SQL/URL mode) and ``get_superadmin_engine()`` (the
Cloud SQL connector + Secret Manager password) — neither can dial inside a testcontainer.

This suite patches ONLY the engine FACTORIES that ``session.py`` imports
(``session_mod.get_engine`` / ``session_mod.get_superadmin_engine``) so the REAL
``get_tenant_repo`` body runs verbatim against the conftest engines:

* ``get_current_identity`` is overridden (dependency_overrides) to return a fabricated
  :class:`Identity` per case — no live ``verify_id_token``. This is legitimate: it stands
  in for the IdP, the one boundary that genuinely cannot run locally.
* ``session_mod.get_engine`` -> the conftest ``engine`` (the app/user path).
* ``session_mod.get_superadmin_engine`` -> a second engine that CONNECTS AS the
  ``app_superadmin`` role with a password (the ``superadmin_engine`` fixture) — NOT
  ``SET ROLE`` from a superuser. Connecting-as is faithful to production
  (``current_user = 'app_superadmin'`` -> the 0003 ``*_superadmin_all`` bypass policy) and,
  because ``app_superadmin`` is a plain non-superuser ``LOGIN`` role, it is subject to RLS
  and to the 0003 GRANTs — a missing GRANT or a broken bypass policy fails the test loudly.

The null-space 403 is asserted two ways: through the full HTTP stack (``null_space_403``)
AND by calling the real ``get_tenant_repo`` generator directly
(``null_space_403_real_dependency_direct``) so ``session.py``'s 403 raise has explicit,
DB-free coverage.

Skip-clean (conftest discipline): ``pytestmark = pytest.mark.integration`` (skips when no
Docker / DATABASE_URL); ``firebase_admin`` and ``app.*`` imports are guarded with
``pytest.importorskip`` so the file COLLECTS on the dev box without erroring.

Analogs: ``test_auth_dependency.py`` (TestClient + ``dependency_overrides``, fabricated
Identity) and ``test_rls_isolation.py`` / ``test_tenant_repository.py`` (two-space seeding).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT
# error) when the Admin SDK / backend deps are not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
repository = pytest.importorskip("app.db.repository")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
get_tenant_repo = session_mod.get_tenant_repo
IntakeRepository = repository.IntakeRepository

SCHEMA = "nestor"

# Password granted to the app_superadmin role for the connect-as superadmin engine. Local
# testcontainer credential only — never a production secret (production reads the password
# from Secret Manager via app.db.base._load_superadmin_password, Path B / D-05a).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


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
# Engine-factory patch: run the REAL get_tenant_repo against the testcontainer
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine, sa_engine=None) -> None:
    """Patch the engine factories ``session.py`` imported, so the REAL get_tenant_repo runs.

    ``app/db/session.py`` does ``from app.db.base import get_engine, get_superadmin_engine``,
    so the names to patch live in the ``session_mod`` namespace (not ``base``). After this,
    a request flows through the production ``get_tenant_repo`` body verbatim — only the
    engine SOURCE is swapped for the testcontainer (the one thing that can't dial Cloud SQL).
    ``get_sessionmaker`` is left real (it accepts any engine).
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    if sa_engine is not None:
        monkeypatch.setattr(
            session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
        )


# ---------------------------------------------------------------------------
# superadmin_engine fixture — a real engine that CONNECTS AS app_superadmin
# ---------------------------------------------------------------------------


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing: ``current_user = 'app_superadmin'`` makes
    the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach. Because
    ``app_superadmin`` is a plain non-superuser ``LOGIN`` role (created by conftest's
    ``_ensure_app_superadmin``), it is subject to RLS and to the 0003 GRANTs — so this
    proves the bypass POLICY and the GRANTs, not superuser ambient authority.
    """
    from sqlalchemy import create_engine, text

    # Give the role a password so it can authenticate (conftest creates it LOGIN, no pw).
    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'")
        )

    # Reuse the conftest engine's DSN (host/port/db/+pg8000 driver), swap the credentials.
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


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


def _insert_answer(
    conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID, field_key: str, value: str
) -> None:
    """Insert one intake_answers row, GUC set so the 0002 WITH CHECK passes.

    Mirrors :func:`_insert_intake`'s GUC-then-INSERT shape — sets ``app.current_space_id``
    to the OWNING space before the INSERT so the RLS WITH CHECK on ``intake_answers`` admits
    the row. Used to seed a space-B answer the cross-tenant PATCH must NOT overwrite.
    """
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intake_answers (space_id, intake_id, field_key, value) "
            "VALUES (:space_id, :intake_id, :field_key, :value)"
        ),
        {
            "space_id": space_id,
            "intake_id": intake_id,
            "field_key": field_key,
            "value": value,
        },
    )


# ---------------------------------------------------------------------------
# App + client builder (the REAL routers under test)
# ---------------------------------------------------------------------------


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + intake_router.

    Mirrors app/main.py's wiring (intake_router mounted UNDER the default-deny
    protected_router) without the health probes / lifespan / CORS — the surface under
    test is the routers, not the app lifecycle.
    """
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
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


def test_get_cross_tenant_returns_404_no_foreign_body(
    engine, set_space, two_spaces, monkeypatch
):
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

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_b}",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        # EXACT 404 — never `in (403, 404)` (D-07 / Pitfall 4 / T-06-10).
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


def test_list_scoped_to_own_space(engine, set_space, two_spaces, monkeypatch):
    """user-A GET /intakes -> only space-A rows; space-B's intake id is absent."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            "/intakes", headers={"Authorization": "Bearer ignored-overridden"}
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


def test_patch_cross_tenant_returns_404_row_unchanged(
    engine, set_space, two_spaces, monkeypatch
):
    """user-A PATCH of a space-B intake -> EXACTLY 404, and the space-B row is unchanged.

    ``repo.patch`` matches the scoped ``WHERE`` against nothing -> ``rowcount == 0`` ->
    handler 404 (never 403, never a silent success). The patch targets ``client_name`` (the
    only benign mutable field on ``IntakePatch``; status moves only via the allow-listed
    transition verbs). The foreign row is re-read as its OWNER (space_b GUC) and asserted
    unchanged (``client_name`` still NULL — no cross-tenant write leaked through).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.patch(
            f"/intakes/{intake_b}",
            json={"client_name": "HACKED-by-space-A"},
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
            client_name = conn.execute(
                text(f"SELECT client_name FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_b},
            ).scalar_one()
        assert client_name != "HACKED-by-space-A", (
            f"cross-tenant PATCH leaked through: space_b row client_name={client_name!r} "
            "(expected unchanged — NULL)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: superadmin_reads_all — superadmin sees BOTH spaces (Pitfall 2)
# ===========================================================================


def test_superadmin_reads_all_spaces(
    engine, set_space, two_spaces, monkeypatch, superadmin_engine
):
    """A superadmin GET /intakes -> rows from BOTH spaces are visible.

    Positive cross-tenant test: the REAL get_tenant_repo routes a superadmin to
    ``get_superadmin_engine()`` (patched to the connect-as ``app_superadmin`` engine, no
    GUC), so ``current_user = 'app_superadmin'`` triggers the 0003 bypass and both seeded
    intake ids appear. A mis-routed/confined superadmin engine (one that set a GUC or used
    the app role), a broken bypass policy, or a missing 0003 GRANT would all fail here
    loudly (Pitfall 2 / T-04-13 / WR-04).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine, sa_engine=superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.get(
            "/intakes", headers={"Authorization": "Bearer ignored-overridden"}
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


def test_null_space_403_user_denied(engine, set_space, two_spaces, monkeypatch):
    """A ``user`` Identity with ``space_id=None`` -> EXACTLY 403 on a data route (D-04).

    Drives the REAL get_tenant_repo: the null-space user trips the 403 raise at
    ``session.py`` BEFORE any session/tx is opened (an unset GUC must never reach a query).
    This is the ONLY data-route 403 — distinct from the 404 cross-tenant-by-id codes (no
    enumeration confusion).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_null_space_user())
        client = TestClient(app)
        resp = client.get(
            "/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )

        # EXACT 403 — the null-space default-deny (D-04), NOT the 404 data-by-id code.
        assert resp.status_code == 403, (
            f"null-space user must be EXACTLY 403, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: null_space_403 (direct) — call the REAL dependency, assert session.py raises
# ===========================================================================


def test_null_space_403_real_dependency_direct():
    """Call the production ``get_tenant_repo`` generator directly with a null-space user.

    Proves ``session.py``'s default-deny 403 raise (D-04) with DB-free, explicit coverage:
    the raise happens BEFORE any engine is touched, so no testcontainer is needed for this
    assertion. Complements the HTTP-level ``null_space_403`` case by pinning the exact
    source-of-truth behavior of the real dependency body.
    """
    from fastapi import HTTPException

    gen = get_tenant_repo(identity=_null_space_user())
    with pytest.raises(HTTPException) as excinfo:
        next(gen)
    assert excinfo.value.status_code == 403, (
        f"real get_tenant_repo must raise EXACTLY 403 for a null-space user, "
        f"got {excinfo.value.status_code}."
    )


# ===========================================================================
# Case: upsert_answers_cross_tenant — user-A PATCH space-B answers -> 404, unchanged
# ===========================================================================


def test_upsert_answers_cross_tenant_returns_404_answers_unchanged(
    engine, set_space, two_spaces, monkeypatch
):
    """user-A PATCH of space-B's intake answers -> EXACTLY 404, space-B answer unchanged.

    Closes the CR-01 gap on the save-as-you-go WRITE path (TENANT-04 / INTAKE-03 / D-01).
    The real ``get_intake_and_answer_repos`` runs verbatim against the testcontainer (the
    factories ``session.py`` imported are patched). The handler's ownership gate
    (``intake_repo.get(intake_id) is None``) excludes space-B's intake from space-A's scope,
    so the PATCH is EXACTLY 404 (never 403, never 200/500; D-07 existence-hiding) and
    ``upsert_batch`` is never reached. The seeded space-B answer is re-read as its OWNER
    (space_b GUC) and asserted STILL ``"owned-by-B"`` — the cross-tenant write did not leak
    through (the foreign answer row is untouched).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        # Seed space-B an answer that the cross-tenant PATCH must NOT overwrite.
        with engine.begin() as conn:
            _insert_answer(conn, set_space, space_b, intake_b, "q1", "owned-by-B")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.patch(
            f"/intakes/{intake_b}/answers",
            json={"answers": [{"field_key": "q1", "value": "HACKED-by-space-A"}]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        # EXACT 404 — never `in (403, 404)`, never 200/500 (D-07 / T-06-10b).
        assert resp.status_code == 404, (
            f"cross-tenant PATCH /answers must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/200/500 would leak existence or write through."
        )

        # The foreign answer must be UNTOUCHED — re-read as the owner (space_b GUC).
        with engine.begin() as conn:
            set_space(conn, space_b)
            value = conn.execute(
                text(
                    f"SELECT value FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :id AND field_key = 'q1'"
                ),
                {"id": intake_b},
            ).scalar_one()
        assert value == "owned-by-B", (
            f"cross-tenant answers PATCH leaked through: space_b q1 value={value!r} "
            "(expected unchanged — 'owned-by-B')."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: superadmin_space_id_narrows — superadmin ?space_id=<B> -> only space-B
# ===========================================================================


def test_superadmin_space_id_param_narrows_list(
    engine, set_space, two_spaces, monkeypatch, superadmin_engine
):
    """A superadmin GET /intakes?space_id=<B> -> ONLY space-B's intake (space-A excluded).

    Proves TENANT-04's superadmin space-switcher filter: ``withActiveSpace`` appends
    ``?space_id=<id>`` and ``list_intakes`` now honors it for a superadmin by NARROWING the
    already-cross-tenant ``repo.list()`` result to the selected space at the HANDLER layer
    (T-06-22 — a UX view-filter, NEVER passed into the repo / never an authz input). The same
    superadmin GET /intakes WITHOUT the param still returns BOTH spaces (the all-spaces default
    is unchanged — no regression to ``test_superadmin_reads_all_spaces``).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine, sa_engine=superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        # With ?space_id=<B>: the superadmin view is NARROWED to space-B only.
        narrowed = client.get(
            f"/intakes?space_id={space_b}",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert narrowed.status_code == 200, (
            f"superadmin narrowed list should be 200, got {narrowed.status_code}."
        )
        narrowed_ids = {row["id"] for row in narrowed.json()}
        assert str(intake_b) in narrowed_ids, (
            "TENANT-04: superadmin ?space_id=<B> must INCLUDE space-B's intake "
            f"(visible ids={narrowed_ids})."
        )
        assert str(intake_a) not in narrowed_ids, (
            "TENANT-04: superadmin ?space_id=<B> must EXCLUDE space-A's intake — the "
            f"view-filter did not narrow (visible ids={narrowed_ids})."
        )

        # With NO param: the all-spaces default is unchanged — BOTH spaces visible.
        unfiltered = client.get(
            "/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )
        assert unfiltered.status_code == 200, (
            f"superadmin unfiltered list should be 200, got {unfiltered.status_code}."
        )
        all_ids = {row["id"] for row in unfiltered.json()}
        assert str(intake_a) in all_ids and str(intake_b) in all_ids, (
            "REGRESSION: superadmin GET /intakes with NO param must still return BOTH "
            f"spaces (visible ids={all_ids})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: user_space_id_inert — user-A ?space_id=<B> -> still ONLY space-A
# ===========================================================================


def test_user_space_id_param_is_inert(engine, set_space, two_spaces, monkeypatch):
    """user-A GET /intakes?space_id=<B> -> still ONLY space-A's intake (param inert).

    Proves the param can NEVER widen a non-superadmin's access (T-06-22 / T-06-23): a user's
    ``repo.list()`` is already ``_scope``-walled to their token-derived space, and the handler
    applies its narrowing ONLY for ``identity.role == "superadmin"``, so a user-supplied
    ``space_id`` is discarded server-side. A forged space-B param therefore returns space-A's
    own intake and NEVER space-B's — the repo scope is the sole authority.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes?space_id={space_b}",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, (
            f"user list should be 200, got {resp.status_code}."
        )
        ids = {row["id"] for row in resp.json()}
        assert str(intake_a) in ids, (
            "user ?space_id=<B> must still include their OWN space-A intake (param inert)."
        )
        assert str(intake_b) not in ids, (
            "TENANT-04 LEAK: user ?space_id=<B> widened access to space-B's intake — the "
            f"param was trusted as an authz input (visible ids={ids})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)
