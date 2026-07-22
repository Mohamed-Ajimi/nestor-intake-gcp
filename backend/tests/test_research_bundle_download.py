"""Raw-output download + re-verify happy-path / lock / recovery suite (RUN-03 SC1, Plan 03).

The download endpoint (``GET /intakes/{id}/research/{run}/bundle-url``) and the re-verify
endpoint (``POST /intakes/{id}/research/{run}/verify-chain``) are the ONLY client-facing-
adjacent research surfaces — the isolation wall is proven separately in
``test_research_cross_tenant.py`` (superadmin-only + space-scoped + existence-hidden). This
suite proves the SUPERADMIN happy paths + the D-06 lock + the driver-death recovery:

| Test                                    | Proves                                                     |
|-----------------------------------------|------------------------------------------------------------|
| ``bundle_url_happy``                    | verified + bundle_key → 200 {url, expires_in}; TTL ≤900.   |
| ``bundle_url_not_verified_409``         | completed but chain_status="broken" → 409 (D-06 lock).     |
| ``bundle_url_builds_on_missing_key``    | verified + bundle_key NULL → 200; ONE lazy upload; key set.|
| ``reverify_lifts_lock``                 | broken → verify_verdict ok → 200 chain_status="verified".  |

DESIGN mirrors ``test_storage_upload.py``: the superadmin path connects AS the
``app_superadmin`` role (the ``superadmin_engine`` fixture) so the 0003 bypass policy admits
the cross-space read/patch; ``get_current_identity`` is overridden to a superadmin Identity;
``fake_gcs`` captures the signed-url mint + the lazy upload; ``fake_tribunal_client`` fakes the
seam (get_report / get_research_bundle / verify_chain).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")

from app.api import research_routes as research_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer overridden"}

# Local testcontainer credential ONLY for the connect-as app_superadmin engine (mirrors
# test_storage_upload.py) — never a production secret.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no own space, CR-02)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin engine factory in BOTH session.py + ai_session.py.

    ``get_tenant_repo`` (session.py) opens the request tx on the superadmin engine; the
    lazy-rebuild WRITE + the re-verify patch open a fresh ``tenant_session`` (ai_session.py)
    on the SAME superadmin engine — both must point at the connect-as ``app_superadmin`` DSN.
    """
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Mirrors test_storage_upload.py: ``current_user = 'app_superadmin'`` makes the 0003
    ``*_superadmin_all`` bypass policy match, so the superadmin download/re-verify path can
    READ + PATCH the space-scoped ``research_runs`` row cross-tenant.
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


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_space(engine, space_id, name) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": name},
        )


def _seed_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'in_research')"
            ),
            {"id": intake_id, "space_id": space_id},
        )


def _seed_run(
    engine,
    set_space,
    space_id,
    intake_id,
    run_id,
    *,
    status="completed",
    chain_status="verified",
    chain_broken_at=None,
    bundle_key=None,
) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, chain_status, chain_broken_at, "
                " bundle_key, output_markdown, tribunal_run_id, attempt) "
                "VALUES (:id, :space_id, :intake_id, :status, :chain_status, "
                " :broken_at, :bundle_key, :md, :trid, 1)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "chain_status": chain_status,
                "broken_at": chain_broken_at,
                "bundle_key": bundle_key,
                "md": "# persisted report",
                "trid": f"trib-{run_id}",
            },
        )


def _read_run_bundle_key(engine, set_space, space_id, run_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT bundle_key FROM {SCHEMA}.research_runs WHERE id = :id"),
            {"id": run_id},
        ).scalar_one()


def _read_run_chain_status(engine, set_space, space_id, run_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT chain_status FROM {SCHEMA}.research_runs WHERE id = :id"),
            {"id": run_id},
        ).scalar_one()


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ===========================================================================
# Happy path — verified + bundle_key → 200 {url, expires_in}; TTL clamped ≤900
# ===========================================================================


def test_bundle_url_happy(
    engine, set_space, superadmin_engine, fake_gcs, monkeypatch
):
    """A superadmin GET of a verified run's bundle-url → 200 {url, expires_in}; TTL ≤900.

    The seam records the persisted bundle_key with a ttl ≤ 900 (D-10). No lazy build (the
    key already exists), so ``fake_gcs["uploads"]`` stays empty.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/artifacts/abc-raw-output.zip"
    _seed_space(engine, space, "Space (bundle happy)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id, bundle_key=key)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/bundle-url", headers=AUTH
        )
        assert r.status_code == 200, (
            f"verified bundle-url should be 200, got {r.status_code} (body={r.text!r})."
        )
        body = r.json()
        assert "url" in body and body["url"], "response must carry a signed url."
        assert isinstance(body.get("expires_in"), int), "response must carry expires_in."
        assert body["expires_in"] <= 900, "advertised TTL must be clamped ≤ 900s (D-10)."
        assert len(fake_gcs["signed_urls"]) == 1, "exactly one signed-url mint expected."
        signed = fake_gcs["signed_urls"][0]
        assert signed["key"] == key, "the seam must sign the PERSISTED bundle_key."
        assert signed["ttl_seconds"] <= 900, "the requested TTL must be ≤ 900s."
        assert not fake_gcs["uploads"], "no lazy build when bundle_key already exists."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Not verified — completed but chain_status="broken" → 409 (D-06 lock)
# ===========================================================================


def test_bundle_url_not_verified_409(
    engine, set_space, superadmin_engine, fake_gcs, monkeypatch
):
    """A completed run with chain_status="broken" → 409; NEVER mints a url (D-06 lock)."""
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (bundle locked)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(
        engine,
        set_space,
        space,
        intake_id,
        run_id,
        chain_status="broken",
        chain_broken_at=3,
        bundle_key=None,
    )
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/bundle-url", headers=AUTH
        )
        assert r.status_code == 409, (
            f"a broken-chain run must be locked (409), got {r.status_code} (body={r.text!r})."
        )
        assert not fake_gcs["signed_urls"], "a locked run must NEVER mint a signed url."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Build-on-download-if-missing — verified + bundle_key NULL → 200; one lazy upload
# ===========================================================================


def test_bundle_url_builds_on_missing_key(
    engine, set_space, superadmin_engine, fake_gcs, fake_tribunal_client, monkeypatch
):
    """A verified run with bundle_key NULL → 200; ONE lazy upload under the artifacts key;
    the row's bundle_key is then set (driver-death recovery, Pattern 2).
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (bundle recovery)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(
        engine, set_space, space, intake_id, run_id, chain_status="verified", bundle_key=None
    )
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/bundle-url", headers=AUTH
        )
        assert r.status_code == 200, (
            f"a verified run with NULL bundle_key must build-on-download → 200, "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, (
            f"exactly one lazy build+upload expected, got {len(fake_gcs['uploads'])}."
        )
        uploaded_key = fake_gcs["uploads"][0]["key"]
        assert uploaded_key.startswith(f"{space}/{intake_id}/artifacts/"), (
            f"the lazy-built key must be server-authored under the space's artifacts "
            f"prefix, got {uploaded_key!r}."
        )
        # The persisted bundle_key is now set (the WRITE patched it) and IS the signed key.
        persisted = _read_run_bundle_key(engine, set_space, space, run_id)
        assert persisted == uploaded_key, "the row's bundle_key must be the built key."
        assert fake_gcs["signed_urls"][0]["key"] == uploaded_key, (
            "the mint must sign the freshly-built key."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Re-verify lifts lock — broken → verify_verdict ok → 200 chain_status="verified"
# ===========================================================================


def test_reverify_lifts_lock(
    engine, set_space, superadmin_engine, fake_tribunal_client, monkeypatch
):
    """A broken run + a now-passing verify_verdict → 200 chain_status="verified"; row updated."""
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (re-verify)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(
        engine,
        set_space,
        space,
        intake_id,
        run_id,
        chain_status="broken",
        chain_broken_at=3,
        bundle_key=None,
    )
    # The chain now passes on re-verification.
    fake_tribunal_client["verify_verdict"] = {"ok": True, "broken_at": None}
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/{run_id}/verify-chain", headers=AUTH
        )
        assert r.status_code == 200, (
            f"re-verify should be 200, got {r.status_code} (body={r.text!r})."
        )
        assert r.json().get("chain_status") == "verified", (
            "a now-passing re-verify must return chain_status='verified'."
        )
        assert fake_tribunal_client["verify_chain_calls"] == 1, (
            "the re-verify must call the verify_chain seam exactly once."
        )
        # The row's lock is lifted (persisted).
        assert _read_run_chain_status(engine, set_space, space, run_id) == "verified", (
            "the row's chain_status must be persisted as 'verified' (lock lifted)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
