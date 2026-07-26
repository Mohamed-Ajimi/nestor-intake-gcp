"""Research-surface cross-tenant denial suite (T-16-08 / QA-01 / D-04) — the day-one gate.

The Phase-16 research seam adds two new tenant-crossing surfaces — the trigger
(``POST /intakes/{id}/research``) and the SSE progress stream
(``GET /intakes/{id}/research/stream``). Pitfall 5: a fresh tenant surface is a fresh chance
to reintroduce the broken-RLS class of bug, so the denial tests land WITH the surface (never
after). This suite is the HTTP-level proof that both new surfaces deny cross-tenant access:

| Test                                    | Proves                                                   |
|-----------------------------------------|----------------------------------------------------------|
| ``trigger_cross_tenant_404``            | space-B user POST of space-A's intake → EXACTLY 404      |
|                                         | (existence-hidden), space-A intake NOT flipped, no run.  |
| ``stream_cross_tenant_404``            | space-B user GET of space-A's intake stream → EXACTLY 404|
|                                         | (raised pre-stream; never 403/200).                      |
| ``stream_null_space_403``               | a null-space user's stream pre-flight → EXACTLY 403.     |
| ``resume_cross_tenant_404``             | space-B user POST of space-A's resume → EXACTLY 404,     |
|                                         | NO seam call, space-A run still ``parked``.              |
| ``resume_user_role_404``                | a user-role caller in the RIGHT space → EXACTLY 404      |
|                                         | (never 403 — the role gate is existence-hidden).         |
| ``resume_null_space_404``               | a null-space user → EXACTLY 404 from ``_superadmin_gate``|
|                                         | (never the null-space 403).                              |
| ``resume_superadmin_happy_path_...``    | superadmin resume of a ``parked`` run → 202, row         |
|                                         | ``queued``, ``attempt`` UNCHANGED (F-02 free resume).    |

DESIGN mirrors ``test_intake_cross_tenant.py``: the engine FACTORIES that ``session.py`` /
``ai_session.py`` import are patched to the conftest engines so the REAL ``get_tenant_repo``
+ the stream's ``tenant_session`` reads run verbatim locally; ``get_current_identity`` is
overridden to a fabricated Identity (the IdP is the one boundary that cannot run locally).
The trigger runs as a superadmin (the real actor) via the connect-as ``app_superadmin``
engine; a superadmin scoping a chosen client is space-narrowed by the intake's own space, so
a space-B superadmin path can't reach space-A here because the override yields a SPACE-B
*user* for the denial cases (the existence-hidden 404 is the user-path wall).
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


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


#: Password granted to the app_superadmin role for the connect-as superadmin engine (test
#: only — mirrors test_intake_cross_tenant._SUPERADMIN_TEST_PASSWORD). The role is created
#: LOGIN (no pw) by conftest's _ensure_app_superadmin; the superadmin_engine fixture sets a pw.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


def _patch_engines(monkeypatch, user_engine, sa_engine=None) -> None:
    """Patch the engine factories session.py + ai_session.py imported (see test_research_routes).

    ``sa_engine`` (when provided) also swaps ``get_superadmin_engine`` in both namespaces so a
    superadmin request flows through the production ``get_tenant_repo`` verbatim against the
    testcontainer's connect-as ``app_superadmin`` engine (the happy-path proof).
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    if sa_engine is not None:
        monkeypatch.setattr(
            session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
        )
        monkeypatch.setattr(
            ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
        )


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach.
    ``app_superadmin`` is a plain non-superuser LOGIN role (conftest's _ensure_app_superadmin),
    so it proves the bypass POLICY + GRANTs, not superuser ambient authority. Shape mirrors
    test_intake_cross_tenant.superadmin_engine.
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


def _seed_intake(engine, set_space, space_id, intake_id, status="decomposed") -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status))"
            ),
            {"id": intake_id, "space_id": space_id, "status": status},
        )


def _read_intake_status(engine, set_space, space_id, intake_id) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _count_runs(engine, set_space, space_id, intake_id) -> int:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.research_runs WHERE intake_id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _seed_run(
    engine,
    set_space,
    space_id,
    intake_id,
    run_id,
    *,
    status="completed",
    chain_status="verified",
    bundle_key=None,
) -> None:
    """Seed a ``research_runs`` row so the availability gate is not what produces a 404.

    The bundle-url / verify-chain denial cases must fail on the SCOPE / ROLE wall, not on
    a missing run or the 409 availability gate — so seed a completed + chain-verified run.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, chain_status, bundle_key, "
                " tribunal_run_id, attempt) "
                "VALUES (:id, :space_id, :intake_id, :status, :chain_status, "
                " :bundle_key, :trid, 1)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "chain_status": chain_status,
                "bundle_key": bundle_key or f"{space_id}/{intake_id}/artifacts/x-raw.zip",
                "trid": f"trib-{run_id}",
            },
        )


def _cleanup(engine, *space_ids) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": sid},
            )


def _superadmin() -> "Identity":
    return Identity(uid="sa", email="sa@x", role="superadmin", space_id=None)


# ===========================================================================
# trigger_cross_tenant — space-B user POST space-A intake → EXACTLY 404
# ===========================================================================


def test_trigger_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user POST of space-A's research trigger → 404; space-A intake untouched.

    The scoped ``repo.get`` excludes space-A's intake from space-B's scope → ``None`` →
    the handler raises an existence-hidden 404 (never 403/200). No status flip, no run
    inserted, no seam call — the cross-tenant write never begins.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a = uuid.uuid4()
    _seed_space(engine, space_a, "Space A (research denial)")
    _seed_space(engine, space_b, "Space B (research denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="decomposed")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))  # caller = space-B
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_a}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 404, (
            f"cross-tenant trigger must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/200 would leak existence (BOLA/IDOR)."
        )
        assert str(intake_a) not in resp.text, "404 body leaked the foreign intake id."
        # The foreign intake is untouched (still decomposed) and no run was inserted.
        assert _read_intake_status(engine, set_space, space_a, intake_a) == "decomposed"
        assert _count_runs(engine, set_space, space_a, intake_a) == 0
        assert not fake_tribunal_client["create_run"], "no seam call for a denied trigger."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# stream_cross_tenant — space-B user GET space-A stream → EXACTLY 404
# ===========================================================================


def test_stream_cross_tenant_404(engine, set_space, two_spaces, monkeypatch):
    """space-B user GET of space-A's research stream → plain-GET 404 raised pre-stream."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a = uuid.uuid4()
    _seed_space(engine, space_a, "Space A (stream denial)")
    _seed_space(engine, space_b, "Space B (stream denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))  # caller = space-B
    try:
        # Plain GET (NOT streaming): the 404 is raised in the pre-flight BEFORE the stream.
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant stream must be existence-hidden 404, never 403/200; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# stream_null_space — a null-space user's stream pre-flight → EXACTLY 403
# ===========================================================================


def test_stream_null_space_403(engine, set_space, monkeypatch):
    """A ``user`` Identity with ``space_id=None`` → EXACTLY 403 on the stream pre-flight (D-04)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space, "Space (null-space stream)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 403, (
            f"null-space user must be default-denied 403 on the pre-flight; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# bundle-url (GET) denial — RUN-03 SC2 (Plan 03 Task 1). Three cases prove the
# raw-output download is superadmin-only + space-scoped + existence-hidden.
# ===========================================================================


def test_bundle_url_cross_tenant_404(engine, set_space, two_spaces, monkeypatch):
    """space-B user GET of space-A's bundle-url → EXACTLY 404 (foreign ids not in body).

    The superadmin role-check fires FIRST (a user is denied before the scope wall even
    runs), so a space-B *user* is 404 for the same existence-hidden reason a cross-tenant
    caller is. Seed a completed + verified run so the availability gate is NOT the cause.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (bundle-url denial)")
    _seed_space(engine, space_b, "Space B (bundle-url denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/bundle-url",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant bundle-url must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r}); 403/200 leaks existence."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_bundle_url_user_role_404(engine, set_space, two_spaces, monkeypatch):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (superadmin-only gate).

    Even a user who owns the intake's space can NEVER reach the raw output (RUN-03: clients
    never). The role gate is existence-hidden (404, not 403). Seed a completed + verified
    run so the 404 is the ROLE wall, not the availability gate.
    """
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (bundle-url user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/bundle-url",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(run_a) not in r.text, "404 body leaked the run id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_bundle_url_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` → EXACTLY 404 (the superadmin role-check fires first, D-08).

    The superadmin gate runs BEFORE any DB/scope read, so a null-space user is denied by the
    role check (404) — NOT by the null-space default-deny 403 (which only the DB-touching
    stream pre-flight reaches). Pins the ordering the Task-1 gate produces.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (bundle-url null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/bundle-url",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, got {r.status_code}."
        )
        assert str(run_id) not in r.text, "404 body leaked the run id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# verify-chain (POST) denial — RUN-03 SC2 (Plan 03 Task 1). Same three cases as
# bundle-url: superadmin-only + space-scoped + existence-hidden.
# ===========================================================================


def test_verify_chain_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user POST of space-A's verify-chain → EXACTLY 404; no seam call."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (verify-chain denial)")
    _seed_space(engine, space_b, "Space B (verify-chain denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/{run_a}/verify-chain",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant verify-chain must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
        assert fake_tribunal_client["verify_chain_calls"] == 0, (
            "a denied verify-chain must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_verify_chain_user_role_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """A ``user``-role caller in the correct space → EXACTLY 404 (superadmin-only); no seam call."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (verify-chain user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/{run_a}/verify-chain",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code}."
        )
        assert str(run_a) not in r.text, "404 body leaked the run id."
        assert fake_tribunal_client["verify_chain_calls"] == 0, (
            "a role-denied verify-chain must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_verify_chain_null_space_404(
    engine, set_space, monkeypatch, fake_tribunal_client
):
    """A null-space ``user`` → EXACTLY 404 (superadmin role-check fires first); no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (verify-chain null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/{run_id}/verify-chain",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, got {r.status_code}."
        )
        assert fake_tribunal_client["verify_chain_calls"] == 0, (
            "a role-denied verify-chain must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# verification (GET) denial — ENGINE-09 / 16-D-08 (Plan 15-04 Task 3). Three
# cases prove the verification-report proxy is superadmin-only + space-scoped +
# existence-hidden, with NO seam call on denial.
# ===========================================================================


def test_verification_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user GET of space-A's verification → EXACTLY 404; no seam call."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (verification denial)")
    _seed_space(engine, space_b, "Space B (verification denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/verification",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant verification must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r}); 403/200 leaks existence."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
        assert fake_tribunal_client["get_verification_calls"] == 0, (
            "a denied verification must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_verification_user_role_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (superadmin-only); no seam call."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (verification user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/verification",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(run_a) not in r.text, "404 body leaked the run id."
        assert fake_tribunal_client["get_verification_calls"] == 0, (
            "a role-denied verification must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_verification_null_space_404(
    engine, set_space, monkeypatch, fake_tribunal_client
):
    """A null-space ``user`` → EXACTLY 404 (superadmin role-check fires first); no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (verification null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/verification",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, got {r.status_code}."
        )
        assert fake_tribunal_client["get_verification_calls"] == 0, (
            "a role-denied verification must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_verification_superadmin_happy_path(
    engine, superadmin_engine, set_space, monkeypatch, fake_tribunal_client
):
    """A superadmin same-space GET → 200 with a non-empty funnel (distilled > 0).

    Pre-UAT proof (warning fix) that the full intake → seam → (fake tribunal) path
    returns REAL funnel data, not just that denials 404. The fake_tribunal_client's
    ``verification_report`` default carries ``funnel.distilled == 3``. The superadmin
    reads through the connect-as ``app_superadmin`` engine (the 0003 bypass), so the
    seeded intake+run resolve cross-space and the seam call fires exactly once.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (verification happy-path)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    app = _build_app()
    # A superadmin scoping this client is space-narrowed by the intake's own space.
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/verification",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 200, (
            f"superadmin same-space verification must be 200, got {r.status_code} "
            f"(body={r.text!r})."
        )
        body = r.json()
        assert body.get("funnel"), "verification body must carry a non-empty funnel."
        assert body["funnel"].get("distilled", 0) > 0, (
            "the funnel must report a distilled count > 0 (real data through the seam)."
        )
        assert fake_tribunal_client["get_verification_calls"] == 1, (
            "the superadmin happy path must make EXACTLY one seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# research-source (GET) denial — ENGINE-09 / 16-D-08 (Plan 15-04 Task 3). The
# source route has no run in its path (source_id is tribunal-scoped by the tenant
# header), so the trio pins the role + intake-scope + null-space walls.
# ===========================================================================


def test_research_source_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user GET of space-A's research source → EXACTLY 404; no seam call."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, source_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (source denial)")
    _seed_space(engine, space_b, "Space B (source denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/sources/{source_a}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant source must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r}); 403/200 leaks existence."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(source_a) not in r.text, "404 body leaked the foreign source id."
        assert fake_tribunal_client["get_source_calls"] == 0, (
            "a denied source must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_research_source_user_role_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (superadmin-only); no seam call."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, source_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (source user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/sources/{source_a}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(source_a) not in r.text, "404 body leaked the source id."
        assert fake_tribunal_client["get_source_calls"] == 0, (
            "a role-denied source must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_research_source_null_space_404(
    engine, set_space, monkeypatch, fake_tribunal_client
):
    """A null-space ``user`` → EXACTLY 404 (superadmin role-check fires first); no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, source_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (source null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/sources/{source_id}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, got {r.status_code}."
        )
        assert fake_tribunal_client["get_source_calls"] == 0, (
            "a role-denied source must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# audit-body (GET) denial — ENGINE-09 / T-15-11b (Plan 15-04 Task 3). The feed
# drill-down proxy: superadmin-only + space-scoped + existence-hidden, no seam
# call on denial.
# ===========================================================================


def test_audit_body_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user GET of space-A's audit body → EXACTLY 404; no seam call."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a, audit_a = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (audit-body denial)")
    _seed_space(engine, space_b, "Space B (audit-body denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/audit/{audit_a}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant audit body must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r}); 403/200 leaks existence."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
        assert str(audit_a) not in r.text, "404 body leaked the foreign audit id."
        assert fake_tribunal_client["get_audit_body_calls"] == 0, (
            "a denied audit body must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_audit_body_user_role_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (superadmin-only); no seam call."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a, audit_a = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (audit-body user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/{run_a}/audit/{audit_a}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(audit_a) not in r.text, "404 body leaked the audit id."
        assert fake_tribunal_client["get_audit_body_calls"] == 0, (
            "a role-denied audit body must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_audit_body_null_space_404(
    engine, set_space, monkeypatch, fake_tribunal_client
):
    """A null-space ``user`` → EXACTLY 404 (superadmin role-check fires first); no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id, audit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (audit-body null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/{run_id}/audit/{audit_id}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, got {r.status_code}."
        )
        assert fake_tribunal_client["get_audit_body_calls"] == 0, (
            "a role-denied audit body must make NO seam call."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# WR-03 — seam-error mapping: a tribunal-side 404 surfaces as the pinned
# existence-hidden 404 (never an unhandled httpx.HTTPStatusError → 500), and
# any other seam failure surfaces as 502. Exercised on the most exposed proxy
# (get_research_source: source_id is a free path input never validated
# intake-side) via the superadmin happy-path scaffolding.
# ===========================================================================


def _raise_http_status(status_code: int):
    """Return a fake seam getter that raises httpx.HTTPStatusError(status_code)."""
    import httpx

    def _raiser(*args, **kwargs):
        req = httpx.Request("GET", "http://tribunal.local/api/sources/x")
        resp = httpx.Response(status_code, request=req)
        raise httpx.HTTPStatusError(
            f"{status_code} from seam", request=req, response=resp
        )

    return _raiser


def test_source_seam_404_maps_to_existence_hidden_404(
    engine, superadmin_engine, set_space, monkeypatch, fake_tribunal_client
):
    """A tribunal-side 404 (RLS miss / unknown source_id) → intake 404, not 500."""
    from fastapi.testclient import TestClient

    from app.research import tribunal_client as tc_mod

    space = uuid.uuid4()
    intake_id, source_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (seam-404 mapping)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    monkeypatch.setattr(tc_mod, "get_source", _raise_http_status(404))

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/sources/{source_id}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a tribunal-side 404 must map to the existence-hidden 404, "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(source_id) not in r.text, "404 body leaked the source id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_source_seam_5xx_maps_to_502(
    engine, superadmin_engine, set_space, monkeypatch, fake_tribunal_client
):
    """A non-404 seam failure (tribunal 500) → 502 Research engine unavailable."""
    from fastapi.testclient import TestClient

    from app.research import tribunal_client as tc_mod

    space = uuid.uuid4()
    intake_id, source_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (seam-5xx mapping)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    monkeypatch.setattr(tc_mod, "get_source", _raise_http_status(500))

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/sources/{source_id}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 502, (
            f"a non-404 seam failure must map to 502, got {r.status_code} "
            f"(body={r.text!r})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# resume (POST) denial + happy path — F-01 / F-02 (plan 15.2-19). The Resume verb
# is the ONE new tenant-crossing surface this plan adds, so its denial trio lands
# WITH it (Pitfall 5), each case pinning ONE exact status code. Every run is
# seeded ``parked`` so the 404 is the SCOPE / ROLE wall and never the 409 state
# gate.
# ===========================================================================


def _capture_resume(monkeypatch):
    """Record every ``tribunal_client.resume_run`` call; return the recorder list.

    A denial MUST make no seam call at all: an engine run re-queued behind a 404
    would be a cross-tenant write dressed up as a denial.
    """
    from app.research import tribunal_client as tc_mod

    calls: list = []

    def _fake_resume(**kwargs):
        calls.append(kwargs)
        return {"id": kwargs.get("run_id"), "status": "queued"}

    monkeypatch.setattr(tc_mod, "resume_run", _fake_resume, raising=False)
    return calls


def _read_run_row(engine, set_space, space_id, run_id) -> dict:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                f"SELECT status, attempt, error_message, completed_at "
                f"FROM {SCHEMA}.research_runs WHERE id = :id"
            ),
            {"id": run_id},
        ).one()
    return {
        "status": row[0],
        "attempt": row[1],
        "error_message": row[2],
        "completed_at": row[3],
    }


def test_resume_cross_tenant_404(engine, set_space, two_spaces, monkeypatch):
    """space-B user POST of space-A's resume → EXACTLY 404, no seam call, row untouched."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (resume denial)")
    _seed_space(engine, space_b, "Space B (resume denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a, status="parked")
    _patch_engines(monkeypatch, engine)
    resume_calls = _capture_resume(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/resume",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant resume must be EXACTLY 404, got {r.status_code} "
            f"(body={r.text!r}); 403/200 leaks existence."
        )
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
        assert resume_calls == [], "a denied resume must make NO seam call."
        assert (
            _read_run_row(engine, set_space, space_a, run_a)["status"] == "parked"
        ), "the space-A run must still be parked after a denied resume."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_resume_user_role_404(engine, set_space, two_spaces, monkeypatch):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (never 403, RUN-03)."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (resume user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a, status="parked")
    _patch_engines(monkeypatch, engine)
    resume_calls = _capture_resume(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/resume",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a user-role caller must be existence-hidden 404 (superadmin-only), "
            f"got {r.status_code} (body={r.text!r}); 403 leaks existence."
        )
        assert str(run_a) not in r.text, "404 body leaked the run id."
        assert resume_calls == [], "a denied resume must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_resume_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` → EXACTLY 404 from _superadmin_gate, never the 403."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (resume null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="parked")
    _patch_engines(monkeypatch, engine)
    resume_calls = _capture_resume(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/resume",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"a null-space user hits the superadmin role gate FIRST → 404, "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert str(run_id) not in r.text, "404 body leaked the run id."
        assert resume_calls == [], "a denied resume must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_resume_superadmin_happy_path_requeues_without_consuming_an_attempt(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin resuming a parked run → 202, row queued, attempt UNCHANGED (F-02).

    A checkpoint resume is free and unlimited: it must NOT increment
    ``research_runs.attempt`` and must NOT consult the 3-attempt cap. The seam is
    called exactly once with the seeded ``tribunal_run_id`` (the SAME engine run —
    a new one would re-charge everything), and the driver is scheduled, not run.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (resume happy-path)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="parked")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    resume_calls = _capture_resume(monkeypatch)

    # The driver must be SCHEDULED, never executed, in a test.
    scheduled: list = []
    monkeypatch.setattr(
        research_mod,
        "run_poll_driver",
        lambda *a, **k: scheduled.append(a),
        raising=False,
    )
    # The resume recomposes the brief only to satisfy the driver's signature.
    monkeypatch.setattr(
        research_mod,
        "read_brief_inputs",
        lambda identity, iid: {
            "intake": {"id": str(iid)},
            "questions": [],
            "decomposition": {},
            "context_pack_text": None,
        },
        raising=False,
    )
    monkeypatch.setattr(
        research_mod.brief_mod, "validated_questions", lambda i, q: ["Q1"], raising=False
    )
    monkeypatch.setattr(
        research_mod.brief_mod,
        "assemble_brief",
        lambda *a, **k: "brief text",
        raising=False,
    )

    before = _read_run_row(engine, set_space, space, run_id)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/resume",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 202, (
            f"a superadmin resume of a parked run must be 202, got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert len(resume_calls) == 1, (
            f"the resume must make EXACTLY one seam call, got {len(resume_calls)}."
        )
        assert resume_calls[0]["run_id"] == f"trib-{run_id}", (
            "the seam must be called with the SEEDED tribunal_run_id — resuming the "
            "SAME engine run is what makes the checkpoints reusable."
        )
        after = _read_run_row(engine, set_space, space, run_id)
        assert after["status"] == "queued", after
        assert after["error_message"] is None, "the park reason must be cleared on resume."
        assert after["completed_at"] is None
        assert after["attempt"] == before["attempt"], (
            f"F-02: a checkpoint resume is FREE and must not consume an attempt "
            f"({before['attempt']} -> {after['attempt']})."
        )
        assert len(scheduled) == 1, "exactly one fresh poll driver must be scheduled."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
