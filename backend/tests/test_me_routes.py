"""I18N-01/02 ``/me`` locale endpoint suite — drives the REAL ``me_router`` over Postgres.

The endpoint-level proof for the locale resolution chain (D-07) and the persist round-trip.
It mounts the REAL ``app.api.me_routes.me_router`` under the default-deny ``protected_router``,
overrides ``get_current_identity`` with a fabricated Identity (no live IdP), and patches ONLY
the engine FACTORIES that ``session.py`` imports (``session_mod.get_engine`` /
``session_mod.get_superadmin_engine``) to the conftest testcontainer engines — so the PRODUCTION
path (``get_me_session`` -> the real handlers -> the membership/org read + override write on the
request tx) runs verbatim.

What each case pins (11-02 PLAN Task 2 acceptance criteria / threat register):

| Test                              | Proves                                                          |
|-----------------------------------|----------------------------------------------------------------|
| ``get_returns_membership_and_org``| GET /me returns membership.locale + org default_locale (D-07). |
| ``patch_persists_and_reread``     | PATCH /me/locale 'fr' persists; a subsequent GET returns 'fr'  |
|                                   | (persist -> re-read-at-boot round-trip).                       |
| ``patch_invalid_locale_rejected`` | PATCH 'de'/'xx' -> 422 and does NOT persist (T-11-04).         |
| ``identity_from_token_not_body``  | locale is derived from the token — a body cannot set another   |
|                                   | user's locale (T-11-03 EoP).                                    |
| ``superadmin_no_membership``      | a superadmin with NO membership -> locale null + 'nl' default; |
|                                   | PATCH persists nothing (Open Q1 / T-11-06).                    |

Skip-clean (conftest discipline): ``pytestmark = pytest.mark.integration`` (skips without
Docker / DATABASE_URL); ``firebase_admin`` + ``app.*`` imports are ``importorskip``-guarded so
the file COLLECTS on the dev box without erroring (this box has no Python/Docker — the Cloud
Build suite is the phase-gate runner; see MEMORY dev-machine-no-python-docker).

Authoritative references:
- backend/tests/test_intake_routes.py (fabricated-Identity + _patch_engine_factories + _build_app)
- backend/tests/test_admin_routes.py (superadmin_engine fixture + membership seeding idiom)
- backend/app/api/me_routes.py (the router under test) / backend/app/db/session.py get_me_session
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box (dev box has none).
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
me_routes = pytest.importorskip("app.api.me_routes")
auth_routes = pytest.importorskip("app.api.auth_routes")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
me_router = me_routes.me_router
protected_router = auth_routes.protected_router

SCHEMA = "nestor"

# Local testcontainer credential ONLY for the connect-as app_superadmin engine (mirrors
# test_admin_routes.py / test_intake_routes.py) — never a production secret.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(uid: str, space_id: uuid.UUID) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=uid, email="u@x", role="user", space_id=str(space_id))


def _superadmin(uid: str = "super") -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no own space)."""
    return Identity(uid=uid, email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches: run the REAL get_me_session against the testcontainer
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the app-engine factory ``session.py`` imported (the user path in get_me_session)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin-engine factory session.py imported (the superadmin path)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (connect-as, not SET ROLE).

    ``current_user = 'app_superadmin'`` makes the 0003 ``*_superadmin_all`` bypass policy match,
    so a superadmin ``/me`` read reaches the root membership/org tables. Mirrors
    test_admin_routes.py / test_intake_routes.py.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )

    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


# ---------------------------------------------------------------------------
# Seeding helpers (a single space + one membership keyed on the caller's uid)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str, default_locale: str = "nl") -> None:
    """Insert an organization (a space) with an explicit default_locale. Root table (no RLS)."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organizations (id, name, default_locale) "
            "VALUES (:id, :name, :dl)"
        ),
        {"id": space_id, "name": name, "dl": default_locale},
    )


def _create_membership(
    conn,
    space_id: uuid.UUID,
    provider_user_id: str,
    *,
    role: str = "user",
    locale: str | None = None,
) -> uuid.UUID:
    """Insert one membership keyed on ``provider_user_id`` (= the caller's Identity uid).

    ``locale`` is the per-user override (nullable — 0010). Returns the membership id.
    ``organization_memberships`` is a root table (NOT RLS-scoped) so a direct insert is fine.
    """
    from sqlalchemy import text

    membership_id = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organization_memberships "
            "(id, organization_id, provider_user_id, email, role, status, locale) "
            "VALUES (:id, :org, :uid, :email, :role, 'active', :locale)"
        ),
        {
            "id": membership_id,
            "org": space_id,
            "uid": provider_user_id,
            "email": f"{provider_user_id}@x.com",
            "role": role,
            "locale": locale,
        },
    )
    return membership_id


def _cleanup_space(engine, space_id: uuid.UUID) -> None:
    """Delete the seeded organization as the owner (CASCADE removes its memberships)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def _read_membership_locale(engine, membership_id: uuid.UUID):
    """Read a membership's persisted ``locale`` directly (verification read)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT locale FROM {SCHEMA}.organization_memberships WHERE id = :id"),
            {"id": membership_id},
        ).scalar_one()


# ---------------------------------------------------------------------------
# App builder (the REAL router under test)
# ---------------------------------------------------------------------------


def _build_app():
    """Mount the REAL ``me_router`` under the default-deny ``protected_router`` (mirrors main.py)."""
    from fastapi import FastAPI

    from app.api.errors import CodedError
    from fastapi.responses import JSONResponse

    protected_router.include_router(me_router)
    app = FastAPI()
    app.include_router(protected_router)

    # Register the same CodedError handler main.py wires, so PATCH's INVALID_LOCALE raise
    # renders as a 422 {detail, code} here rather than a bare 500.
    @app.exception_handler(CodedError)
    def _coded(_request, exc: CodedError):  # noqa: ANN202 -- test-local handler
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code}, status_code=exc.status_code
        )

    return app


# ===========================================================================
# (a) GET /me — returns membership.locale + org default_locale (D-07)
# ===========================================================================


def test_get_returns_membership_and_org_default(engine, monkeypatch):
    """A user GET /me returns their membership ``locale`` and the org ``default_locale``."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    uid = f"u-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Get Me Space", default_locale="fr")
            _create_membership(conn, space_id, uid, locale="en")

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_user(uid, space_id))

        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Bearer ignored-overridden"})

        assert resp.status_code == 200, f"GET /me should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["locale"] == "en", "GET /me must return the membership override locale"
        assert body["space_default_locale"] == "fr", (
            "GET /me must return the org default_locale for the caller's space (D-07)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_get_returns_null_override_when_membership_locale_unset(engine, monkeypatch):
    """A user with no override (membership.locale NULL) -> GET /me locale is null (inherit)."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    uid = f"u-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Null Override Space", default_locale="nl")
            _create_membership(conn, space_id, uid, locale=None)

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_user(uid, space_id))

        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Bearer ignored-overridden"})

        assert resp.status_code == 200, f"GET /me should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["locale"] is None, "no override -> locale must be null (inherit space default)"
        assert body["space_default_locale"] == "nl"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (b) PATCH /me/locale — persists + re-read-at-boot round-trip
# ===========================================================================


def test_patch_persists_and_subsequent_get_returns_it(engine, monkeypatch):
    """PATCH /me/locale 'fr' persists the override; a subsequent GET /me returns 'fr'."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    uid = f"u-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Patch Space", default_locale="nl")
            membership_id = _create_membership(conn, space_id, uid, locale=None)

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_user(uid, space_id))

        client = TestClient(app)
        patch = client.patch(
            "/me/locale",
            json={"locale": "fr"},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert patch.status_code == 200, (
            f"PATCH /me/locale should be 200, got {patch.status_code} ({patch.text!r})"
        )
        assert patch.json()["locale"] == "fr", "PATCH response must reflect the new override"

        # Persisted in PG (the write hit the caller's own membership row).
        assert _read_membership_locale(engine, membership_id) == "fr", (
            "PATCH must persist membership.locale='fr'"
        )

        # Re-read at boot: a fresh GET returns the persisted override.
        get = client.get("/me", headers={"Authorization": "Bearer ignored-overridden"})
        assert get.status_code == 200
        assert get.json()["locale"] == "fr", "a subsequent GET must return the persisted override"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (c) PATCH invalid locale -> 422 + INVALID_LOCALE code; does NOT persist (T-11-04)
# ===========================================================================


@pytest.mark.parametrize("bad", ["de", "xx", "EN", "", "nl-BE"])
def test_patch_invalid_locale_rejected_and_not_persisted(engine, monkeypatch, bad):
    """PATCH with a locale outside {nl,fr,en} -> 422 (INVALID_LOCALE) and no write happens."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    uid = f"u-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Invalid Locale Space", default_locale="nl")
            membership_id = _create_membership(conn, space_id, uid, locale="nl")

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_user(uid, space_id))

        client = TestClient(app)
        resp = client.patch(
            "/me/locale",
            json={"locale": bad},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 422, (
            f"PATCH with invalid locale {bad!r} must be 422, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("code") == "INVALID_LOCALE", (
            "the rejection must carry the INVALID_LOCALE code (first CodedError consumer)"
        )
        # The pre-existing 'nl' override is untouched — a rejected PATCH never writes.
        assert _read_membership_locale(engine, membership_id) == "nl", (
            "a rejected PATCH must NOT persist any change (T-11-04)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (d) identity from token, not body — a body cannot set another user's locale (T-11-03)
# ===========================================================================


def test_locale_is_derived_from_token_not_body(engine, monkeypatch):
    """The write targets the caller's OWN membership (identity.uid), never another user's.

    Two memberships (the caller + a victim) share the space. The caller PATCHes their locale;
    the VICTIM's membership row must be untouched — locale is scoped to the verified token, so
    a client-supplied value can only change the caller's own display (T-11-03 EoP).
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    caller_uid = f"caller-{uuid.uuid4()}"
    victim_uid = f"victim-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Token Identity Space", default_locale="nl")
            caller_mid = _create_membership(conn, space_id, caller_uid, locale="nl")
            victim_mid = _create_membership(conn, space_id, victim_uid, locale="nl")

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        # The verified identity is the CALLER — the body carries no identity input.
        app.dependency_overrides[get_current_identity] = _as(_user(caller_uid, space_id))

        client = TestClient(app)
        resp = client.patch(
            "/me/locale",
            json={"locale": "fr"},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 200, f"PATCH should be 200, got {resp.status_code} ({resp.text!r})"

        # The caller's own row flipped; the victim's row is untouched.
        assert _read_membership_locale(engine, caller_mid) == "fr", "the caller's own row must flip"
        assert _read_membership_locale(engine, victim_mid) == "nl", (
            "another user's membership must be UNTOUCHED — locale is token-scoped (T-11-03)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (e) superadmin with no membership -> locale null + 'nl' default; PATCH persists nothing
# ===========================================================================


def test_superadmin_no_membership_resolves_null_and_nl(engine, monkeypatch, superadmin_engine):
    """A superadmin with NO membership row -> GET /me locale null + default 'nl' (Open Q1)."""
    from fastapi.testclient import TestClient

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    # A superadmin uid with NO membership row anywhere.
    app.dependency_overrides[get_current_identity] = _as(_superadmin(f"super-{uuid.uuid4()}"))
    try:
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Bearer ignored-overridden"})
        assert resp.status_code == 200, f"GET /me should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["locale"] is None, "superadmin with no membership -> locale null (Open Q1)"
        assert body["space_default_locale"] == "nl", (
            "superadmin with no space -> default 'nl' fallback (Open Q1)"
        )
    finally:
        app.dependency_overrides.clear()


def test_superadmin_no_membership_patch_persists_nothing(
    engine, monkeypatch, superadmin_engine
):
    """A superadmin with NO membership PATCHing a valid locale persists nothing (localStorage-only)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    super_uid = f"super-{uuid.uuid4()}"
    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin(super_uid))
    try:
        client = TestClient(app)
        resp = client.patch(
            "/me/locale",
            json={"locale": "fr"},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        # Valid locale -> 200 + resolved Me, but NO membership row was created/written.
        assert resp.status_code == 200, f"PATCH should be 200, got {resp.status_code} ({resp.text!r})"

        with engine.connect() as conn:
            count = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.organization_memberships "
                    "WHERE provider_user_id = :uid"
                ),
                {"uid": super_uid},
            ).scalar_one()
        assert count == 0, (
            "a superadmin with no membership must NOT get a row created by PATCH (Open Q1 / T-11-06)"
        )
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# (f) WR-03 regression — duplicate membership rows must never 500 the endpoint
# ===========================================================================


def test_get_me_survives_duplicate_membership_rows(engine, monkeypatch):
    """A uid with ACTIVE membership rows in TWO spaces -> GET /me is 200 (never 500).

    Nothing in the schema prevents one ``provider_user_id`` from holding rows in two
    organizations (uniqueness is on ``(organization_id, user_id)``). The resolver must
    stay deterministic: scope to the caller's OWN ``space_id`` and ``first()`` a stable
    ordering — never ``scalar_one_or_none`` -> ``MultipleResultsFound`` -> 500 (WR-03).
    """
    from fastapi.testclient import TestClient

    space_a = uuid.uuid4()
    space_b = uuid.uuid4()
    uid = f"u-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Dup Space A", default_locale="nl")
            _create_space(conn, space_b, "Dup Space B", default_locale="fr")
            _create_membership(conn, space_a, uid, locale="en")
            _create_membership(conn, space_b, uid, locale="fr")

        _patch_engine_factories(monkeypatch, engine)
        app = _build_app()
        # Identity scoped to space B — the resolver must pick B's row deterministically.
        app.dependency_overrides[get_current_identity] = _as(_user(uid, space_b))

        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Bearer ignored-overridden"})

        assert resp.status_code == 200, (
            f"GET /me with duplicate membership rows must be 200 (never 500), "
            f"got {resp.status_code} ({resp.text!r})"
        )
        body = resp.json()
        assert body["locale"] == "fr", (
            "the resolver must pick the caller's OWN space's membership row (WR-03)"
        )
        assert body["space_default_locale"] == "fr"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_a)
        _cleanup_space(engine, space_b)
