"""Run-event proxy + locate denial matrix (T-15.3-60..65, plan 15.3-07).

**This file discharges an obligation handed over from another layer.** Plan 15.3-02
built the engine endpoint (``GET /api/runs/{run_id}/events``) and was asked to prove
that a cross-tenant, a user-role AND a null-space caller each get exactly 404. It
could only prove the first: the tribunal engine has no ``Identity`` — no role, no
``space_id`` — so its only isolation dimension is the JWT tenant plus the FORCE-RLS
GUC. ``Identity.role``, ``_superadmin_gate`` and ``space_id`` live on the INTAKE side
(:mod:`app.api.research_routes`), so the role and null-space denial arms for this feed
are provable HERE and nowhere else. 15.3-02 wrote the handover into its own test
file's scope note and its SUMMARY precisely so it could not evaporate at the seam.
If these tests are ever deleted, that boundary becomes unproven again.

Two brand-new READ surfaces, and a new surface is a fresh chance to reintroduce the
broken-RLS class of bug this project's hardest constraint exists to prevent:

* ``GET /intakes/{intake_id}/research/{run_id}/events`` — the backfill feed proxy;
* ``GET /intakes/research/runs/{run_id}/locate`` — run → intake, for a cold-open
  bookmarked ``/admin/pulse/runs/{runId}``.

| Test                                          | Proves                                      |
|-----------------------------------------------|---------------------------------------------|
| ``denial_matrix[events/locate x caller]``     | user-role, null-space and cross-space callers|
|                                               | each get the EXACT integer 404, no seam call.|
| ``events_unknown_intake_404``                 | superadmin, intake that does not exist → 404.|
| ``events_unknown_run_404`` / ``locate_...``   | superadmin, run that does not exist → 404.   |
| ``events_run_of_another_intake_404``          | a run borrowed from a DIFFERENT intake → 404.|
| ``events_run_from_another_space_404``         | a superadmin cannot mix another SPACE's run  |
|                                               | into this intake's path → 404.               |
| ``events_run_without_engine_id_404``          | WR-03: NULL ``tribunal_run_id`` → 404, never |
|                                               | a seam call against ``/api/runs/None/...``.  |
| ``locate_resolves_a_run_without_engine_id``   | the DELIBERATE asymmetry — see below.        |
| ``events_superadmin_returns_engine_json_...`` | the page JSON is returned VERBATIM (deep ==).|
| ``events_forwards_the_cursor_...``            | ``after_seq`` / ``limit`` reach the seam.    |
| ``locate_returns_exactly_two_ids``            | two keys, no run state (no 2nd source of     |
|                                               | truth that can disagree with the SSE frame). |
| ``events_seam_404/5xx/transport_...``         | 404 → 404, anything else → 502, never a 500. |
| ``locate_route_is_declared_before_...``       | declaration ORDER, not mere existence.       |

**The deliberate asymmetry on WR-03.** The events proxy 404s a run whose
``tribunal_run_id`` is NULL, because such a run can never resolve at the seam. The
LOCATE verb deliberately does NOT: ``trigger_research`` inserts the mirror row with
``status='queued'`` and NO ``tribunal_run_id`` (the poll driver mirrors the engine id
later), so a freshly triggered run has a NULL engine id for exactly as long as it
takes a human to open the page. Making locate 404 there would break the cold-open URL
on every single new run — a denial with nothing to deny, since "which intake owns this
run" is knowable without the engine ever having heard of it. That asymmetry is pinned
by a test in BOTH directions so neither half can be "tidied" into the other.

DESIGN mirrors ``test_research_cross_tenant.py``: the engine FACTORIES that
``session.py`` / ``ai_session.py`` import are patched to the conftest engines so the
REAL ``get_tenant_repo`` runs verbatim locally; ``get_current_identity`` is overridden
to a fabricated Identity (the IdP is the one boundary that cannot run locally). The
seam is monkeypatched per test — no live Tribunal call is ever made, and a denial is
asserted to make NO seam call at all (a feed read served behind a 404 would be a
cross-tenant read dressed up as a denial).
"""

from __future__ import annotations

import inspect
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
from app.research import tribunal_client as tc_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"

#: Password granted to the app_superadmin role for the connect-as superadmin engine
#: (test only — mirrors test_research_cross_tenant._SUPERADMIN_TEST_PASSWORD).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

#: The canned engine page every happy-path test asserts VERBATIM equality against.
#: Deliberately carries a nested ``meta`` and a non-zero cursor: a proxy that "helpfully"
#: flattened, renamed or dropped a field would fail the deep-equality assertion rather
#: than quietly ship a page the frontend cannot read.
_ENGINE_PAGE = {
    "run_id": "trib-run",
    "events": [
        {
            "seq": 41,
            "ts": "2026-07-27T10:00:00Z",
            "stage": "deep_research",
            "kind": "dispatch",
            "text": "Dispatching 3 agents",
            "meta": {"angles": 3, "streams": ["a", "b"]},
        },
        {
            "seq": 42,
            "ts": "2026-07-27T10:00:04Z",
            "stage": "deep_research",
            "kind": "search",
            "text": "SerpAPI query",
            "meta": None,
        },
    ],
    "next_after_seq": 42,
    "has_more": True,
}


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="sa", email="sa@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _events_path(intake_id, run_id) -> str:
    return f"/intakes/{intake_id}/research/{run_id}/events"


def _locate_path(run_id) -> str:
    return f"/intakes/research/runs/{run_id}/locate"


def _patch_engines(monkeypatch, user_engine, sa_engine=None) -> None:
    """Patch the engine factories session.py + ai_session.py imported."""
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
    makes the 0003 ``*_superadmin_all`` bypass policy match. ``app_superadmin`` is a plain
    non-superuser LOGIN role (conftest's ``_ensure_app_superadmin``), so this proves the
    bypass POLICY + GRANTs, not superuser ambient authority — a superuser connection would
    make every RLS assertion in this file vacuously green.
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


def _seed_intake(engine, set_space, space_id, intake_id, status="in_research") -> None:
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
    status="running",
    tribunal_run_id=_TRID_AUTO,
) -> None:
    """Seed a ``research_runs`` row so a 404 is never merely "no run exists"."""
    from sqlalchemy import text

    trid = f"trib-{run_id}" if tribunal_run_id == _TRID_AUTO else tribunal_run_id
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, tribunal_run_id, attempt) "
                "VALUES (:id, :space_id, :intake_id, :status, :trid, 1)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
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


def _capture_events(monkeypatch, *, returns=None):
    """Record every ``tribunal_client.get_run_events`` call; return the recorder list.

    A denial MUST make no seam call at all: a feed page fetched behind a 404 would be a
    cross-tenant READ dressed up as a denial — the caller would not see the body, but the
    engine would still have served another tenant's run to this request.
    """
    calls: list = []

    def _fake_get_run_events(**kwargs):
        calls.append(kwargs)
        return dict(returns if returns is not None else _ENGINE_PAGE)

    monkeypatch.setattr(tc_mod, "get_run_events", _fake_get_run_events, raising=False)
    return calls


def _raise_http_status(status_code: int):
    """Return a fake seam getter that raises ``httpx.HTTPStatusError(status_code)``."""
    import httpx

    def _raiser(*args, **kwargs):
        req = httpx.Request("GET", "http://tribunal.local/api/runs/x/events")
        resp = httpx.Response(status_code, request=req)
        raise httpx.HTTPStatusError(
            f"{status_code} from seam", request=req, response=resp
        )

    return _raiser


def _raise_transport():
    """Return a fake seam getter that raises a TRANSPORT failure (no response at all)."""
    import httpx

    def _raiser(*args, **kwargs):
        raise httpx.ConnectTimeout("tribunal unreachable")

    return _raiser


def _assert_exactly_404(resp, what: str) -> None:
    """Pin EXACTLY 404 — and name 403 and 200 as the regressions we fear.

    403 confirms the resource exists to a caller who must not learn that; 200 means the
    denial did not deny. Asserting only ``!= 200`` or ``>= 400`` would let either
    through, so both are pinned by name before the exact-integer assertion.
    """
    assert resp.status_code != 403, (
        f"{what} must NEVER be 403 — a 403 confirms the run exists to a caller who "
        f"must not learn that (body={resp.text!r})."
    )
    assert resp.status_code != 200, (
        f"{what} must NEVER be 200 — that is not a denial at all (body={resp.text!r})."
    )
    assert resp.status_code == 404, (
        f"{what} must be EXACTLY 404, got {resp.status_code} (body={resp.text!r})."
    )


# ===========================================================================
# THE DENIAL MATRIX — both verbs x three callers, every cell EXACTLY 404.
#
# (b) null_space is the cell that proves the DEPENDENCY ORDER: `_superadmin_gate`
# is declared BEFORE `get_tenant_repo` in both handler signatures, so it resolves
# first. Swap the two and this cell turns 403 — which leaks that the endpoint
# exists — while every other cell in the matrix stays green. That is why it is
# here as its own named case and not folded into "some 4xx".
# ===========================================================================


@pytest.mark.parametrize("verb", ["events", "locate"])
@pytest.mark.parametrize("caller", ["user_role", "null_space", "cross_space"])
def test_denial_matrix_is_exactly_404_with_no_seam_call(
    engine, set_space, two_spaces, monkeypatch, verb, caller
):
    """Every (verb x caller) cell → the EXACT integer 404, no seam call, no id leak.

    * ``user_role``    — a user who OWNS the intake's space. D-08 says a client can
      never reach the run page; the gate is existence-hidden, so 404 not 403.
    * ``null_space``   — a user Identity with ``space_id=None``. Proves the gate
      resolves BEFORE ``get_tenant_repo``'s null-space default-deny.
    * ``cross_space``  — a user in a DIFFERENT space than the seeded run.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, run_a = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (events denial)")
    _seed_space(engine, space_b, "Space B (events denial)")
    _seed_intake(engine, set_space, space_a, intake_a)
    _seed_run(engine, set_space, space_a, intake_a, run_a)
    _patch_engines(monkeypatch, engine)
    seam_calls = _capture_events(monkeypatch)

    identity = {
        "user_role": lambda: _user(space_a),
        "null_space": _null_space_user,
        "cross_space": lambda: _user(space_b),
    }[caller]()
    path = _events_path(intake_a, run_a) if verb == "events" else _locate_path(run_a)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(identity)
    try:
        r = TestClient(app).get(path, headers={"Authorization": "Bearer overridden"})
        _assert_exactly_404(r, f"a {caller} caller on the {verb} verb")
        assert str(run_a) not in r.text, "the 404 body leaked the run id."
        assert str(intake_a) not in r.text, "the 404 body leaked the intake id."
        assert seam_calls == [], (
            f"a denied {verb} read must make NO seam call — a page served behind a "
            f"404 is a cross-tenant read the caller merely does not get to see."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# Superadmin arms — the walls that are NOT the role gate. These need the
# connect-as app_superadmin engine, because a superadmin legitimately reaches
# across spaces (D-05) and the question is what stops it from reaching WRONG.
# ===========================================================================


def test_events_unknown_intake_404(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin GET of an intake id that does not exist → EXACTLY 404, no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    ghost_intake = uuid.uuid4()
    _seed_space(engine, space, "Space (events unknown intake)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(ghost_intake, run_id),
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "an unknown intake id on the events verb")
        assert seam_calls == [], "an unresolved intake must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_events_unknown_run_404(engine, superadmin_engine, set_space, monkeypatch):
    """A superadmin GET of a run id that does not exist → EXACTLY 404, no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    ghost_run = uuid.uuid4()
    _seed_space(engine, space, "Space (events unknown run)")
    _seed_intake(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, ghost_run),
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "an unknown run id on the events verb")
        assert seam_calls == [], "an unresolved run must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_locate_unknown_run_404(engine, superadmin_engine, set_space, monkeypatch):
    """A superadmin locate of a run id that does not exist → EXACTLY 404.

    The miss and the cross-tenant case take the IDENTICAL path and produce the
    IDENTICAL body — that non-distinguishability is the security property, not a
    rough edge: a distinguishable answer would confirm the run exists somewhere.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    ghost_run = uuid.uuid4()
    _seed_space(engine, space, "Space (locate unknown run)")
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _locate_path(ghost_run), headers={"Authorization": "Bearer overridden"}
        )
        _assert_exactly_404(r, "an unknown run id on the locate verb")
        assert str(ghost_run) not in r.text, "the 404 body leaked the run id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_events_run_of_another_intake_404(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A run belonging to a DIFFERENT intake in the SAME space → EXACTLY 404, no seam call.

    Both ids resolve individually; only the ``run.intake_id != intake_id`` cross-check
    catches the mismatch. Without it a caller could borrow one intake's authorization
    to read another intake's feed.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_1, intake_2, run_2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events wrong intake)")
    _seed_intake(engine, set_space, space, intake_1)
    _seed_intake(engine, set_space, space, intake_2)
    _seed_run(engine, set_space, space, intake_2, run_2)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        # intake_1's path, intake_2's run.
        r = TestClient(app).get(
            _events_path(intake_1, run_2),
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a run borrowed from another intake")
        assert seam_calls == [], "a run-scope mismatch must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_events_run_from_another_space_404(
    engine, superadmin_engine, set_space, two_spaces, monkeypatch
):
    """A superadmin cannot mix ANOTHER SPACE's run into this intake's path → EXACTLY 404.

    This is the arm the role gate cannot cover. A superadmin has genuine cross-space
    reach by design (D-05 — ``_scope`` is a no-op for them and the 0003 bypass policy
    matches), so nothing about the ROLE stops space-B's run being read under space-A's
    intake. The run-scope cross-check is what stops it, and this is the test that would
    fail if somebody deleted that line as "redundant with the scoped repo".
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b, run_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space_a, "Space A (events space mixing)")
    _seed_space(engine, space_b, "Space B (events space mixing)")
    _seed_intake(engine, set_space, space_a, intake_a)
    _seed_intake(engine, set_space, space_b, intake_b)
    _seed_run(engine, set_space, space_b, intake_b, run_b)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_a, run_b),
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "space-B's run read under space-A's intake path")
        assert str(run_b) not in r.text, "the 404 body leaked the foreign run id."
        assert seam_calls == [], "a cross-space run must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


def test_events_run_without_engine_id_404(
    engine, superadmin_engine, set_space, monkeypatch
):
    """WR-03: a run with a NULL ``tribunal_run_id`` → EXACTLY 404, and NO seam call.

    The seam URL would be ``/api/runs/None/events``. Letting that go out would turn an
    intake-side data gap into an unshaped engine error; worse, ``None`` is a string the
    engine has no reason to treat specially. Existence-hidden 404 instead.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events no engine id)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id, tribunal_run_id=None)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, run_id),
            headers={"Authorization": "Bearer overridden"},
        )
        _assert_exactly_404(r, "a run carrying no tribunal_run_id")
        assert seam_calls == [], (
            "a run with no engine id must make NO seam call — /api/runs/None/events "
            "must never leave this process."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_locate_resolves_a_run_without_engine_id(
    engine, superadmin_engine, set_space, monkeypatch
):
    """The DELIBERATE asymmetry: locate does NOT apply WR-03 — and must not.

    ``trigger_research`` inserts the mirror row with ``status='queued'`` and NO
    ``tribunal_run_id``; the poll driver mirrors the engine id in later. So a run has a
    NULL engine id for exactly the window in which an operator opens the run page. A
    WR-03 404 here would break the cold-open bookmarkable URL (D-01) on EVERY new run,
    while denying nothing: which intake owns a run is knowable without the engine ever
    having heard of it, and locate makes no seam call at all.

    This test exists so that asymmetry cannot be "tidied away" into symmetry by someone
    pattern-matching the events handler.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (locate queued run)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(
        engine, set_space, space, intake_id, run_id,
        status="queued", tribunal_run_id=None,
    )
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _locate_path(run_id), headers={"Authorization": "Bearer overridden"}
        )
        assert r.status_code == 200, (
            f"a freshly queued run (no engine id yet) MUST locate — this is the exact "
            f"window in which the operator opens the page. Got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert r.json() == {
            "intake_id": str(intake_id),
            "research_run_id": str(run_id),
        }
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Happy paths — what the page actually gets.
# ===========================================================================


def test_events_superadmin_returns_engine_json_verbatim(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin GET → 200 and the engine page returned VERBATIM (deep equality).

    Deep equality rather than a field spot-check on purpose: the proxy's contract is
    that it reshapes NOTHING, so a future field the engine adds reaches the page with
    no change here. A handler that started renaming, flattening or filtering would
    fail this and not a smoke test.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events happy path)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, run_id),
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 200, (
            f"superadmin same-space events must be 200, got {r.status_code} "
            f"(body={r.text!r})."
        )
        assert r.json() == _ENGINE_PAGE, (
            "the proxy must return the engine page VERBATIM — any reshaping here "
            "silently desynchronises the page from the engine's own schema."
        )
        assert len(seam_calls) == 1, (
            f"the happy path must make EXACTLY one seam call, got {len(seam_calls)}."
        )
        assert seam_calls[0]["run_id"] == f"trib-{run_id}", (
            "the seam must be called with the SEEDED tribunal_run_id — reading some "
            "other engine run would show the operator the wrong feed."
        )
        assert seam_calls[0]["space_id"] == str(space), (
            "TENANT-02: the tenant sent to the seam must come from the RESOLVED "
            "intake's space, never from the request."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_events_forwards_the_cursor_and_limit_to_the_seam(
    engine, superadmin_engine, set_space, monkeypatch
):
    """``after_seq`` / ``limit`` reach the seam with the values the caller sent.

    A proxy that dropped them would silently re-serve page 1 forever: the page would
    look alive, keep re-rendering the same rows, and never advance — a failure mode
    indistinguishable from a stalled run.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events cursor)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, run_id),
            params={"after_seq": 41, "limit": 7},
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 200, r.text
        assert seam_calls[0]["after_seq"] == 41, seam_calls[0]
        assert seam_calls[0]["limit"] == 7, seam_calls[0]
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_events_rejects_a_non_integer_cursor_before_the_handler(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A non-integer ``after_seq`` is a 422 from the typed query param — never a 500."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events bad cursor)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)
    seam_calls = _capture_events(monkeypatch)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, run_id),
            params={"after_seq": "'; DROP TABLE run_event; --"},
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 422, (
            f"a non-integer cursor must be rejected by the typed param (422), "
            f"got {r.status_code} (body={r.text!r})."
        )
        assert seam_calls == [], "a rejected cursor must make NO seam call."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_locate_returns_exactly_two_ids(
    engine, superadmin_engine, set_space, monkeypatch
):
    """Locate → 200 with EXACTLY ``{intake_id, research_run_id}`` and nothing else.

    The key-set is asserted exactly, not merely "contains". Adding a status or a stage
    here would make locate a SECOND source of truth for run state that can disagree
    with the SSE frame the page is already subscribed to (D-05) — and two answers that
    disagree about "is it over" are worse than one.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (locate happy path)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _locate_path(run_id), headers={"Authorization": "Bearer overridden"}
        )
        assert r.status_code == 200, (
            f"a superadmin locate of an in-scope run must be 200, got "
            f"{r.status_code} (body={r.text!r})."
        )
        body = r.json()
        assert set(body) == {"intake_id", "research_run_id"}, (
            f"locate must answer ONE question and carry no run state; got keys "
            f"{sorted(body)}."
        )
        assert body["intake_id"] == str(intake_id)
        assert body["research_run_id"] == str(run_id)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Seam-failure mapping — 404 -> 404, everything else -> 502, NEVER a 500.
# ===========================================================================


@pytest.mark.parametrize(
    "seam_failure,expected",
    [
        ("engine_404", 404),
        ("engine_500", 502),
        ("engine_429", 502),
        ("transport", 502),
    ],
)
def test_events_seam_failures_map_to_404_or_502_never_500(
    engine, superadmin_engine, set_space, monkeypatch, seam_failure, expected
):
    """Every seam failure surfaces as 404 or 502 — an unhandled 500 is the regression.

    The engine's 404 is a missing OR cross-tenant run, deliberately indistinguishable,
    so it must arrive as this proxy's own existence-hidden 404. Everything else — a
    500, a rate limit, a connect timeout with no response object at all — is the
    engine being unavailable, which is a 502 and not the caller's fault.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id, run_id = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space, "Space (events seam mapping)")
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id)
    _patch_engines(monkeypatch, engine, sa_engine=superadmin_engine)

    raiser = {
        "engine_404": lambda: _raise_http_status(404),
        "engine_500": lambda: _raise_http_status(500),
        "engine_429": lambda: _raise_http_status(429),
        "transport": _raise_transport,
    }[seam_failure]()
    monkeypatch.setattr(tc_mod, "get_run_events", raiser, raising=False)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        r = TestClient(app).get(
            _events_path(intake_id, run_id),
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code != 500, (
            f"a {seam_failure} seam failure must never surface as an unhandled 500 "
            f"(body={r.text!r})."
        )
        assert r.status_code == expected, (
            f"a {seam_failure} seam failure must map to {expected}, got "
            f"{r.status_code} (body={r.text!r})."
        )
        if expected == 404:
            assert str(run_id) not in r.text, "the mapped 404 leaked the run id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Structural gates — cheap, DB-free, and they run on EVERY future build.
#
# Three of these stand in for `<automated>` checks in the plan that are
# `cd backend && python -c ...` one-liners. This machine has no Python (a
# recorded project constraint), so rather than skip them or claim a run that
# did not happen, they are folded in here where Cloud Build DOES execute them —
# strictly stronger, because they now run forever instead of once.
# ===========================================================================


def test_locate_route_is_declared_before_every_parameterised_intake_route():
    """Route ORDER, not mere existence — a shadowed locate looks like a working denial.

    FastAPI matches in DECLARATION order. ``/intakes/research/runs/{run_id}/locate``
    and ``/intakes/{intake_id}/research/{run_id}/events`` differ at the literal second
    segment, so today they cannot shadow each other — but "it happens not to shadow"
    is not a property anyone should have to re-derive from the segment list. If a
    future route ever did capture this path, a perfectly authorized caller would get a
    404 that is byte-identical to the existence-hidden one, and the bug would be
    invisible in every log.
    """
    paths = [r.path for r in research_mod.research_router.routes]
    assert "/intakes/research/runs/{run_id}/locate" in paths, paths
    locate_at = paths.index("/intakes/research/runs/{run_id}/locate")
    parameterised = [
        i for i, p in enumerate(paths) if p.startswith("/intakes/{intake_id}")
    ]
    assert parameterised, "expected at least one /intakes/{intake_id}/... route"
    assert locate_at < min(parameterised), (
        f"locate is declared at index {locate_at}, after the first parameterised "
        f"intake route at {min(parameterised)}: {paths}"
    )


def test_get_run_events_signature_carries_the_bounded_cursor_surface():
    """Task-1 gate: the seam verb's keyword-only surface, asserted rather than assumed."""
    params = set(inspect.signature(tc_mod.get_run_events).parameters)
    assert {
        "service_url",
        "space_id",
        "acting_user_id",
        "acting_email",
        "run_id",
        "after_seq",
        "limit",
    } <= params, params


def test_get_run_events_never_interpolates_the_cursor_into_the_url():
    """The cursor and the bound travel as query PARAMS, never as URL path text.

    ``seq`` is caller-controlled. Interpolating a caller-controlled value into a
    request PATH is how an extra segment or a traversal gets built by accident; a
    query parameter is escaped by the transport.
    """
    src = inspect.getsource(tc_mod.get_run_events)
    assert "params=" in src, "after_seq/limit must be sent via httpx params=."
    url_lines = [ln for ln in src.splitlines() if "/api/runs/" in ln]
    assert url_lines, src
    for line in url_lines:
        assert "after_seq" not in line, f"cursor interpolated into the URL: {line!r}"
        assert "limit" not in line, f"limit interpolated into the URL: {line!r}"


def test_neither_new_handler_is_async_and_the_sse_handler_is_still_the_only_one():
    """pg8000 is blocking; this module's ONE ``async def`` is the SSE handler, on purpose."""
    assert not inspect.iscoroutinefunction(research_mod.get_research_events)
    assert not inspect.iscoroutinefunction(research_mod.locate_research_run)
    assert inspect.iscoroutinefunction(research_mod.stream_research_run), (
        "the SSE handler must remain the deliberate async one."
    )


def test_neither_new_handler_takes_a_space_id_from_the_request():
    """TENANT-02: ``space_id`` is never a request input on either new verb."""
    for handler in (research_mod.get_research_events, research_mod.locate_research_run):
        params = set(inspect.signature(handler).parameters)
        for forbidden in ("space_id", "org_id", "tenant_id"):
            assert forbidden not in params, (
                f"{handler.__name__} must not accept {forbidden!r} from the request."
            )


def test_neither_new_handler_contains_a_forbidden_status_literal():
    """No forbidden-status arm may exist in either handler — pinned, not reviewed.

    The literal is built at runtime from ``str(403)`` so this assertion does not itself
    plant the number it forbids (the 15.3-02 convention). The docstrings say
    "forbidden" in words for the same reason.
    """
    forbidden_literal = str(403)
    for handler in (research_mod.get_research_events, research_mod.locate_research_run):
        src = inspect.getsource(handler)
        assert forbidden_literal not in src, (
            f"{handler.__name__} contains the forbidden status literal — every "
            f"denial on these verbs is existence-hidden 404."
        )


def test_events_client_clamps_an_absurd_limit_before_the_round_trip(monkeypatch):
    """The client-side clamp is a FACT, not a comment: limit=99999 leaves as 1000.

    The engine's clamp is the authority; this one only stops an obviously wrong caller
    from spending a round trip. Asserted by recording what actually left the process,
    because a clamp that exists only in a docstring is not a clamp. ``after_seq=-999``
    floors to 0 for the same reason.

    ``_mint_id_token`` is stubbed because minting a real OIDC token needs ADC, which
    no test environment has; ``httpx.get`` is stubbed so nothing leaves the process at
    all. The TestClient uses ``httpx.Client``, not the module-level ``get``, so no
    other test in this file is affected.
    """
    import httpx

    recorded: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return _ENGINE_PAGE

    def _fake_get(url, **kwargs):
        recorded["url"] = url
        recorded["params"] = kwargs.get("params")
        recorded["headers"] = kwargs.get("headers")
        return _Resp()

    monkeypatch.setattr(tc_mod, "_mint_id_token", lambda service_url: "tok")
    monkeypatch.setattr(httpx, "get", _fake_get)
    tc_mod.get_run_events(
        service_url="http://tribunal.local",
        space_id="space-a",
        acting_user_id="uid",
        acting_email="e@x",
        run_id="trib-1",
        after_seq=-999,
        limit=99999,
    )

    assert recorded["params"]["limit"] == 1000, recorded
    assert recorded["params"]["after_seq"] == 0, recorded
    assert recorded["url"] == "http://tribunal.local/api/runs/trib-1/events", recorded
    assert recorded["headers"]["X-Nestor-Tenant-Id"] == "space-a", (
        "the tenant header is the engine's only isolation dimension for this feed "
        "(15.3-02 has no Identity) — it must carry the caller's resolved space."
    )
