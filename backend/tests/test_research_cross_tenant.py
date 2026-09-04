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
|                                         | (raised before the stream opens; never 403/200).         |
| ``stream_null_space_404``               | a null-space user → EXACTLY 404 from ``_superadmin_gate``|
|                                         | (never the pre-flight's null-space 403). Was ``_403``    |
|                                         | until 23.1-18 gated the stream — see below.              |
| ``resume_cross_tenant_404``             | space-B user POST of space-A's resume → EXACTLY 404,     |
|                                         | NO seam call, space-A run still ``parked``.              |
| ``resume_user_role_404``                | a user-role caller in the RIGHT space → EXACTLY 404      |
|                                         | (never 403 — the role gate is existence-hidden).         |
| ``resume_null_space_404``               | a null-space user → EXACTLY 404 from ``_superadmin_gate``|
|                                         | (never the null-space 403).                              |
| ``resume_superadmin_happy_path_...``    | superadmin resume of a ``parked`` run → 202, row         |
|                                         | ``queued``, ``attempt`` UNCHANGED (F-02 free resume).    |
| ``cancel_cross_tenant_404``             | space-B user POST of space-A's cancel → EXACTLY 404,     |
|                                         | NOT 403, NOT 200; no seam call; space-A run untouched.   |
| ``cancel_user_role_404``                | a ``user``-role caller in the RIGHT space → EXACTLY 404. |
| ``cancel_null_space_404``               | a null-space user → EXACTLY 404 from ``_superadmin_gate``|
| ``cancel_superadmin_resolves_...``      | superadmin cancel of a ``running`` run → 202, row        |
|                                         | ``cancelled`` — and ``cancelled`` IS retryable, which is |
|                                         | the whole point (``running`` is not).                    |
| ``cancel_no_run_404`` / ``..._no_engine_id_404`` | existence-hidden, never a seam 500 unshaped.     |
| ``cancel_already_terminal_...``         | a terminal run → 202 reporting its OWN status, NO state  |
|                                         | change (a no-op that reports itself, not an error).      |
| ``cancel_seam_404_...`` / ``..._5xx_...`` / ``..._transport_...`` | 404 → 404; anything else → 502. |

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


#: Sentinel for :func:`_seed_run`'s ``tribunal_run_id`` — "derive the usual
#: ``trib-{run_id}``". Passing ``None`` explicitly seeds a NULL engine id instead
#: (the WR-03 case: a run the seam could never resolve).
_TRID_AUTO = "__auto__"


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
    tribunal_run_id=_TRID_AUTO,
) -> None:
    """Seed a ``research_runs`` row so the availability gate is not what produces a 404.

    The bundle-url / verify-chain denial cases must fail on the SCOPE / ROLE wall, not on
    a missing run or the 409 availability gate — so seed a completed + chain-verified run.

    ``tribunal_run_id`` defaults to the derived ``trib-{run_id}`` (every pre-existing
    caller's behaviour, unchanged); pass ``None`` to seed a NULL engine id for the WR-03
    "no engine id can never resolve at the seam" arm.
    """
    from sqlalchemy import text

    trid = f"trib-{run_id}" if tribunal_run_id == _TRID_AUTO else tribunal_run_id
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
                "trid": trid,
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
    """space-B user GET of space-A's research stream → plain-GET 404, before any stream.

    MECHANISM NOTE, 23.1-18: the assertion is unchanged and still true, but WHICH wall
    answers moved. Until 23.1-18 this 404 came from the handler's in-body pre-flight
    (``check_intake_in_scope`` returning falsy for a foreign intake). The route is now
    gated with ``superadmin_gate``, which resolves as a DEPENDENCY — before the body — so
    a role=``user`` is refused on ROLE first and never reaches the tenant check. The
    pre-flight is still there and still correct (it is what 404s a SUPERADMIN asking about
    an intake that does not exist); it is simply defence in depth now. Kept as written
    because the caller-visible contract it pins — a foreign-space caller learns nothing —
    is exactly what must not regress, whichever wall enforces it.
    """
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
# stream_null_space — a null-space user → EXACTLY 404 from the gate (23.1-18)
# ===========================================================================


def test_stream_null_space_404(engine, set_space, monkeypatch):
    """A ``user`` with ``space_id=None`` → EXACTLY 404 from ``superadmin_gate``, not 403.

    STRENGTHENED, NOT WEAKENED, BY 23.1-18. This case was written as
    ``test_stream_null_space_403`` and asserted the pre-flight's default-deny 403. That was
    the correct expectation while the stream was the router's one ungated route — but the
    403 is an EXISTENCE ORACLE: it tells an unauthorized caller that
    ``/intakes/{id}/research/stream`` is a real endpoint, which is precisely what the
    existence-hidden convention exists to prevent (``app/auth/gates.py``). The stream is
    now gated (D-23.1-16 addendum), the gate resolves as a dependency BEFORE the handler
    body, and this caller gets the same silent 404 every other route on this router gives.

    The sibling rows ``resume_null_space_404`` and ``cancel_null_space_404`` in this same
    file have asserted exactly this since their routes were gated; this row now matches
    them instead of being the one exception. RED (pre-gate, measured):
    403 ``{"detail":"No space — not authorized"}``.

    The 403 arm has NOT been deleted from the code — ``check_intake_in_scope``'s
    ``PermissionError`` mapping is still in ``stream_research_run`` as defence in depth.
    It is simply no longer reachable by a non-superadmin, which is the point.
    """
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
        assert r.status_code == 404, (
            "null-space user must get the gate's existence-hidden 404 on the stream, "
            f"never the pre-flight's 403 (an existence oracle); got {r.status_code} "
            f"({r.text!r})"
        )
        assert r.json().get("detail") == "Intake not found", (
            f"the 404 detail is asserted byte-exact (app/auth/gates.py), got {r.json()!r}"
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


# ===========================================================================
# cancel (POST) denial trio + behaviour — D-D (plan 15.2-25). The Stop verb is the
# ONE new tenant-crossing surface this plan adds, so its denial trio lands WITH it
# (Pitfall 5), each case pinning ONE exact status code.
#
# WHY THIS SURFACE EXISTS AT ALL: before it, the only way an operator could stop a
# run they were paying for was to pause the whole tribunal-worker Cloud Run service —
# which does not stop the run (the in-flight process ran 16 more minutes) and nearly
# caused a fresh worker to RE-CLAIM it at full cost (D-E, 2026-07-27). Only resolving
# the ROW stops a run, and `running` is NOT in `_RETRYABLE_RUN_STATUSES` while
# `cancelled` IS — so resolving the row is also what un-blocks the intake.
# ===========================================================================


def _capture_cancel(monkeypatch, *, returns=None):
    """Record every ``tribunal_client.cancel_run`` call; return the recorder list.

    A denial MUST make no seam call at all: an engine run stopped behind a 404 would
    be a cross-tenant WRITE dressed up as a denial. ``returns`` overrides the fake's
    RunResponse (used by the already-terminal no-op case, where the engine returns
    the run AS-IS rather than flipping it).
    """
    from app.research import tribunal_client as tc_mod

    calls: list = []

    def _fake_cancel(**kwargs):
        calls.append(kwargs)
        if returns is not None:
            return returns
        return {"id": kwargs.get("run_id"), "status": "cancelled"}

    monkeypatch.setattr(tc_mod, "cancel_run", _fake_cancel, raising=False)
    return calls


def _assert_exactly_404(resp, what: str) -> None:
    """Pin EXACTLY 404 — and say out loud that 403 and 200 are the failures we fear.

    403 leaks that the resource exists (the non-distinguishability rule); 200 would
    mean the denial did not deny. Asserting only ``!= 200`` or ``>= 400`` would let
    either regression through, so both are pinned by name.
    """
    assert resp.status_code != 403, (
        f"{what} must NEVER be 403 — a 403 confirms the intake exists to a caller "
        f"who must not learn that (body={resp.text!r})."
    )
    assert resp.status_code != 200, (
        f"{what} must NEVER be 200 — that is not a denial at all (body={resp.text!r})."
    )
    assert resp.status_code == 404, (
        f"{what} must be EXACTLY 404, got {resp.status_code} (body={resp.text!r})."
    )


def test_cancel_cross_tenant_404(engine, set_space, two_spaces, monkeypatch):
    """space-B user POST of space-A's cancel → EXACTLY 404, no seam call, row untouched."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (cancel denial)")
    _seed_space(engine, space_b, "Space B (cancel denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a, status="running")
    _patch_engines(monkeypatch, engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a cross-tenant cancel")
        assert str(intake_a) not in r.text, "404 body leaked the foreign intake id."
        assert str(run_a) not in r.text, "404 body leaked the foreign run id."
        assert cancel_calls == [], "a denied cancel must make NO seam call."
        assert (
            _read_run_row(engine, set_space, space_a, run_a)["status"] == "running"
        ), "the space-A run must be untouched after a denied cancel."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_cancel_user_role_404(engine, set_space, two_spaces, monkeypatch):
    """A ``user``-role caller IN the correct space → EXACTLY 404 (never 403)."""
    from fastapi.testclient import TestClient

    space_a, _ = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (cancel user-role)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _seed_run(engine, set_space, space_a, intake_a, run_a, status="running")
    _patch_engines(monkeypatch, engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # OWNS the space
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_a}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a user-role cancel (the verb is superadmin-only)")
        assert str(run_a) not in r.text, "404 body leaked the run id."
        assert cancel_calls == [], "a denied cancel must make NO seam call."
        assert (
            _read_run_row(engine, set_space, space_a, run_a)["status"] == "running"
        ), "the run must be untouched after a denied cancel."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a)


def test_cancel_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` → EXACTLY 404 from _superadmin_gate, never the 403.

    This is what the dependency ORDER buys: ``_superadmin_gate`` is declared BEFORE
    ``get_tenant_repo`` in the handler signature, so it resolves first and the
    null-space default-deny 403 inside ``get_tenant_repo`` is never reached.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (cancel null-space)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="running")
    _patch_engines(monkeypatch, engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a null-space cancel")
        assert str(run_id) not in r.text, "404 body leaked the run id."
        assert cancel_calls == [], "a denied cancel must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_superadmin_resolves_the_run_row_and_unblocks_retry(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin cancelling a ``running`` run → 202 ``cancelled``, and the ROW resolves.

    This is the acceptance behaviour for run ``d6bb3aae``: that run is still
    ``running`` in the DB although its process is dead, and because
    ``_RETRYABLE_RUN_STATUSES`` excludes ``running`` its intake cannot be retried.
    Cancelling moves it to ``cancelled``, which IS retryable — so the stop and the
    unblocking are the SAME action. The membership assertion below is the part that
    would catch a "cancel" that merely looked like it worked.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (cancel happy-path)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="running")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 202, (
            f"a superadmin cancel of a running run must be 202, got {r.status_code} "
            f"(body={r.text!r})."
        )
        body = r.json()
        assert body["status"] == "cancelled", body
        assert body["research_run_id"] == str(run_id), body

        assert len(cancel_calls) == 1, (
            f"the cancel must make EXACTLY one seam call, got {len(cancel_calls)}."
        )
        assert cancel_calls[0]["run_id"] == f"trib-{run_id}", (
            "the seam must be called with the SEEDED tribunal_run_id — cancelling "
            "some other engine run would stop the wrong thing."
        )

        after = _read_run_row(engine, set_space, space, run_id)
        assert after["status"] == "cancelled", (
            f"the mirror row must RESOLVE to cancelled — a Stop that leaves the row "
            f"unresolved ships the appearance of a fix without the fix. Got {after}."
        )
        assert after["completed_at"] is not None, (
            "a resolved run must carry completed_at: the poll driver that would "
            "normally stamp it may itself be dead, which is exactly the condition "
            "that makes an operator reach for this button."
        )

        # The unblocking half, asserted against the production constant itself so a
        # future edit to that set cannot silently re-break retry for a cancelled run.
        assert "cancelled" in research_mod._RETRYABLE_RUN_STATUSES, (
            "cancelled MUST be retryable — that membership is what makes the Stop "
            "button unblock the intake."
        )
        assert "running" not in research_mod._RETRYABLE_RUN_STATUSES, (
            "running must NOT be retryable — that exclusion is the reason a run "
            "stuck at running blocks its intake in the first place."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_no_run_404(engine, superadmin_engine, set_space, monkeypatch):
    """An intake with NO research run at all → existence-hidden 404, no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space, "Space (cancel no-run)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a cancel of an intake with no run")
        assert cancel_calls == [], "there is nothing to cancel — no seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_run_without_engine_id_404(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A run carrying NO ``tribunal_run_id`` → 404 (WR-03), never a seam 500 leaking out.

    The seam URL would be ``/api/runs/None/cancel``. Refusing intake-side keeps the
    failure shaped and existence-hidden instead of letting an unshaped engine error
    reach the operator.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (cancel no-engine-id)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(
        engine, set_space, space, intake_id, run_id,
        status="running", tribunal_run_id=None,
    )
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    cancel_calls = _capture_cancel(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a cancel of a run with no engine id")
        assert cancel_calls == [], "a run with no engine id must not reach the seam."
        assert (
            _read_run_row(engine, set_space, space, run_id)["status"] == "running"
        ), "the row must be untouched."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_already_terminal_run_is_a_reporting_no_op(
    engine, superadmin_engine, set_space, monkeypatch
):
    """An ALREADY-TERMINAL run → 202 reporting its own status, and NO state change.

    The engine treats cancelling a terminal run as an idempotent no-op, not a
    conflict, so this route must not invent a 409 the engine never reports. It echoes
    whatever status the engine returned — and crucially does NOT re-stamp
    ``completed_at``, which would clobber the real completion time of a finished run.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (cancel terminal no-op)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="completed")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    # The engine returns the run AS-IS on a terminal cancel.
    cancel_calls = _capture_cancel(
        monkeypatch, returns={"id": f"trib-{run_id}", "status": "completed"}
    )

    before = _read_run_row(engine, set_space, space, run_id)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 202, (
            f"a terminal cancel is a no-op that REPORTS itself, not an error — "
            f"expected 202, got {r.status_code} (body={r.text!r}). There is no 409 "
            f"arm because the engine has none."
        )
        assert r.json()["status"] == "completed", (
            "the route must ECHO the engine's status, never assume 'cancelled'."
        )
        assert len(cancel_calls) == 1
        after = _read_run_row(engine, set_space, space, run_id)
        assert after == before, (
            f"a terminal cancel must make NO state change: {before} -> {after}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def _raise_cancel_http_status(monkeypatch, status_code: int):
    """Patch ``cancel_run`` to raise ``httpx.HTTPStatusError(status_code)``."""
    import httpx

    from app.research import tribunal_client as tc_mod

    def _raiser(*args, **kwargs):
        req = httpx.Request("POST", "http://tribunal.local/api/runs/x/cancel")
        resp = httpx.Response(status_code, request=req)
        raise httpx.HTTPStatusError(
            f"{status_code} from seam", request=req, response=resp
        )

    monkeypatch.setattr(tc_mod, "cancel_run", _raiser, raising=False)


def _cancel_seam_case(engine, set_space, space, intake_id, run_id, name):
    """Seed the shared scaffolding for the three seam-error mapping cases.

    Engine patching is left to the caller (each case needs the superadmin engine so the
    request reaches the seam call at all — the failure under test must be the SEAM's,
    never an earlier scope wall).
    """
    _seed_space(engine, space, name)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_run(engine, set_space, space, intake_id, run_id, status="running")


def test_cancel_seam_404_maps_to_existence_hidden_404(
    engine, superadmin_engine, set_space, monkeypatch
):
    """An engine-side 404 (missing OR cross-tenant run) → intake 404, row untouched."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _cancel_seam_case(
        engine, set_space, space, intake_id, run_id, "Space (cancel seam-404)"
    )
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    _raise_cancel_http_status(monkeypatch, 404)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "an engine-side 404 on cancel")
        assert (
            _read_run_row(engine, set_space, space, run_id)["status"] == "running"
        ), "a failed seam call must leave NO half-transitioned row."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_seam_5xx_maps_to_502(
    engine, superadmin_engine, set_space, monkeypatch
):
    """Any NON-404 seam failure → 502, never an unhandled 500, row untouched."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _cancel_seam_case(
        engine, set_space, space, intake_id, run_id, "Space (cancel seam-5xx)"
    )
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    _raise_cancel_http_status(monkeypatch, 500)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 502, (
            f"a non-404 seam failure must map to 502, got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert (
            _read_run_row(engine, set_space, space, run_id)["status"] == "running"
        ), "a failed seam call must leave NO half-transitioned row."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_cancel_seam_transport_failure_maps_to_502(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A TRANSPORT failure (timeout / connect error) → 502, never an unhandled 500.

    Distinct arm from the 5xx case: a ``ConnectTimeout`` is an ``httpx.HTTPError`` but
    NOT an ``httpx.HTTPStatusError``, so it misses the status-mapping except block
    entirely and would escape as a 500 without its own handler.
    """
    from fastapi.testclient import TestClient

    import httpx

    from app.research import tribunal_client as tc_mod

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _cancel_seam_case(
        engine, set_space, space, intake_id, run_id, "Space (cancel transport)"
    )
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    def _boom(*args, **kwargs):
        raise httpx.ConnectTimeout("engine unreachable")

    monkeypatch.setattr(tc_mod, "cancel_run", _boom, raising=False)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).post(
            f"/intakes/{intake_id}/research/cancel",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 502, (
            f"a transport failure must map to 502, got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert (
            _read_run_row(engine, set_space, space, run_id)["status"] == "running"
        ), "a failed seam call must leave NO half-transitioned row."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
