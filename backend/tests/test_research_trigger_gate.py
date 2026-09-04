"""The PAID research trigger's denial suite (D-23.1-16) — plan 23.1-17.

WHAT THIS FILE PROVES. ``POST /intakes/{intake_id}/research``
(:func:`app.api.research_routes.trigger_research`) is the one verb on ``research_router``
that SPENDS: it flips ``decomposed -> in_research``, inserts the ``research_runs`` row and
schedules :func:`app.research.run_task.run_poll_driver` — a Tribunal run costing roughly
$45 and running with ``NESTOR_TRIBUNAL_UNCAPPED=1`` (``deploy-worker.sh``; the $25 governor
has never fired). Until this plan it took ``Depends(get_current_identity)`` and NO role
gate, so any role=``user`` in the intake's own space could spend it, without limit — while
every FREE verb on the same router (locate / resume / cancel / bundle-url / verify-chain /
verification / source / audit-body / events) was already gated. The asymmetry is what makes
it an oversight rather than a decision, and 23.1-CONTEXT.md § 15 records why the phase's
own scope survey missed it: it read ``intake_routes.py`` and never gave this file the same
treatment.

MEASURED RED (before the gate, this exact file): ``test_trigger_user_role_404`` observed
**202** with ``{"research_run_id": ..., "status": "queued"}``, the intake flipped to
``in_research``, ONE ``research_runs`` row inserted and the poll driver dispatched;
``test_trigger_null_space_404`` observed **403** ``{"detail":"No space — not authorized"}``.
Both are recorded in ``23.1-17-SUMMARY.md``.

| Test                                   | Proves                                            |
|----------------------------------------|---------------------------------------------------|
| ``user_role_404``                      | role=``user`` IN THE INTAKE'S OWN SPACE gets       |
|                                        | EXACTLY 404 with the byte-exact gate detail — and  |
|                                        | NO side effect (see below).                        |
| ``null_space_404``                     | a ``user`` with ``space_id=None`` gets EXACTLY 404 |
|                                        | and NOT ``get_tenant_repo``'s null-space 403. The  |
|                                        | ordering proof, end to end.                        |
| ``superadmin_still_works``             | a superadmin still gets 202 + the flip + the run   |
|                                        | row + the driver. Without this arm "gate it to     |
|                                        | 404" would pass the whole suite.                   |
| ``ordering_mutation_produces_the_403`` | the ordering is LOAD-BEARING, proved by mutating   |
|                                        | the REAL handler's signature and observing the     |
|                                        | live 403 that mis-ordering yields.                 |

THE NO-SIDE-EFFECT ASSERTIONS — the expensive half. A status code alone would not prove the
denial happened BEFORE the spend. Every denial arm additionally asserts that:

* ``research_runs`` holds ZERO rows for the intake (nothing was queued);
* the intake status is still ``decomposed`` (no half-transition the operator must undo);
* the poll-driver seam recorded NOTHING (a denied caller never reaches ``run_poll_driver``).

ZERO PROVIDER SPEND BY CONSTRUCTION. ``research_routes.run_poll_driver`` is monkeypatched to
a recorder in EVERY test here, including the superadmin happy path, so no test in this file
can dispatch the engine even if a future edit made the route succeed where it should deny.
The superadmin arm additionally takes ``fake_tribunal_client`` / ``fake_resend`` as
belt-and-braces: were the recorder ever removed, the seam and the mail egress are still
faked. The 202 arm therefore asserts the driver was SCHEDULED, never that a run happened.

OUT OF SCOPE, DELIBERATELY — ``GET /intakes/{id}/research/stream``
(:func:`app.api.research_routes.stream_research_run`) is the tenth route on this router that
takes only ``get_current_identity``. D-23.1-16 excludes it: it is SSE, an ``EventSource``
cannot set an ``Authorization`` header, so it may authenticate differently and gating it
blind could break the live run feed. It is a KNOWN gap, assessed and left, not an oversight
repeated. Those two are the only ungated routes on the router — the other nine are gated,
which ``test_superadmin_gate.test_every_gated_research_route_resolves_the_gate_before_the_
repo`` now pins at ten.

HARNESS PROVENANCE. Seeding + engine-patch scaffold COPIED (never imported — no private
symbol crosses a test module) from ``test_research_routes.py`` (``_seed_space``,
``_seed_intake``, ``_seed_decomposition_and_questions``, ``_read_intake_status``,
``_count_runs``, ``_patch_engines``, ``_build_app``) and ``test_operator_verb_gate.py``
(``superadmin_engine``, ``_patch_superadmin_engine``, ``_assert_denied``,
``_cleanup_spaces``' audit sweep).

Skip-clean: ``pytestmark = pytest.mark.integration``; ``importorskip`` guards so the file
COLLECTS on a box without the backend deps.
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
gates = pytest.importorskip("app.auth.gates")
repository_mod = pytest.importorskip("app.db.repository")

# HARD imports of the impl under test.
from app.api import research_routes as research_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

# Imported into THIS module's globals on purpose: the mutation test re-binds the REAL
# handler under a swapped ``__signature__``, and FastAPI resolves that signature's string
# annotations (research_routes has ``from __future__ import annotations``) against the
# owning function's ``__globals__`` — which, for the wrapper, is this module.
IntakeRepository = repository_mod.IntakeRepository

SCHEMA = "nestor"
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Same literal test_mail_endpoints / test_operator_verb_gate use, so the app_superadmin
#: role's password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` scoped to the intake's OWN space — the arm that proves the ROLE gate.

    A CROSS-space user is already 404'd by ``repo.get`` and would prove nothing here.
    """
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the case ``get_tenant_repo`` answers with the D-04 403."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches
# ---------------------------------------------------------------------------


def _patch_engines(monkeypatch, user_engine) -> None:
    """Patch BOTH engine factories: ``session.py`` backs ``get_tenant_repo``;
    ``ai_session.py`` backs ``read_brief_inputs`` + the trigger's own commit tx."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in both namespaces (the superadmin happy-path arm)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05). Shape copied from
    ``test_operator_verb_gate.superadmin_engine``.
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


@pytest.fixture
def driver_calls(monkeypatch):
    """Replace ``research_routes.run_poll_driver`` with a recorder — the SPEND SEAM.

    Two jobs, and the second is the reason it is applied to EVERY test in this file rather
    than only the denial arms:

    1. It is what "no background task scheduled" is asserted on. ``BackgroundTasks`` gives
       the caller no introspection, and ``TestClient`` flushes the task list after the
       response, so the recorder being empty is the observable form of "the denied caller
       never reached the driver".
    2. It makes provider spend IMPOSSIBLE from this file. ``run_poll_driver`` is what drives
       Tribunal; with it stubbed, no test here can start a ~$45 run even if a future edit
       let the route succeed where it should deny.

    The trigger calls it by BARE NAME (``research_routes.py``'s module-level import), so
    patching the attribute on that module is the real seam — not a copy of it.
    """
    calls: list[tuple] = []

    def _recorder(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(research_mod, "run_poll_driver", _recorder)
    return calls


# ---------------------------------------------------------------------------
# Seeding helpers (copied from test_research_routes.py)
# ---------------------------------------------------------------------------


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Research trigger gate space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="decomposed") -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
                "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status), :name)"
            ),
            {"id": intake_id, "space_id": space_id, "status": status, "name": "Acme"},
        )


def _seed_decomposition_and_questions(engine, set_space, space_id, intake_id) -> None:
    """Seed one decomposition + two questions so the empty-brief 422 guard does NOT fire.

    Load-bearing for the denial arms, not scaffolding: without it an UNGATED user call
    would be refused by the 422 empty-brief guard and a 404-vs-422 assertion would pass
    for the wrong reason. Seeded, the ungated route reaches 202 — which is exactly the
    RED this file measured.
    """
    from sqlalchemy import text

    decomp_id = uuid.uuid4()
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.decompositions (id, space_id, intake_id, summary) "
                "VALUES (:id, :space_id, :intake_id, :summary)"
            ),
            {
                "id": decomp_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "summary": "Marktverkenning voor Acme.",
            },
        )
        for prio, qtext in ((2, "Wat is de marktomvang?"), (1, "Wie zijn de concurrenten?")):
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.research_questions "
                    "(id, space_id, intake_id, decomposition_id, question_text, priority) "
                    "VALUES (:id, :space_id, :intake_id, :decomp_id, :qtext, :prio)"
                ),
                {
                    "id": uuid.uuid4(),
                    "space_id": space_id,
                    "intake_id": intake_id,
                    "decomp_id": decomp_id,
                    "qtext": qtext,
                    "prio": prio,
                },
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


def _cleanup(engine, space_id) -> None:
    """Drop the seeded space AND this suite's audit rows.

    The audit sweep is not belt-and-braces: ``audit_log.space_id`` has NO ForeignKey (the
    trail deliberately outlives its space), so dropping the organization does not cascade
    the rows away, and the superadmin arm legitimately writes an ``intake.status_changed``
    row. ``test_operator_verb_gate`` measured a pre-existing suite going red purely on
    collection order for exactly this reason.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
        )
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )


def _build_app():
    """Mount ``research_router`` under ``protected_router`` (mirrors app/main.py wiring)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _assert_denied(resp) -> None:
    """EXACTLY 404 with the gate's byte-exact detail — never 403 / 401 / 422 / 202."""
    assert resp.status_code == 404, (
        "POST /research: an unauthorized caller must get EXACTLY 404 (existence-hidden, "
        f"D-23.1-02/D-23.1-16), got {resp.status_code} ({resp.text!r}). A 403 is an "
        "existence oracle; a 202 means the ~$45 run was authorized."
    )
    assert resp.json().get("detail") == "Intake not found", (
        "POST /research: the 404 detail is part of the convention and is asserted "
        f"byte-exact (app/auth/gates.py), got {resp.json()!r}"
    )


def _assert_no_spend(engine, set_space, space, intake_id, driver_calls) -> None:
    """The expensive half: a denied call must leave NO trace of the paid path."""
    assert _count_runs(engine, set_space, space, intake_id) == 0, (
        "a denied trigger must insert NO research_runs row — a queued row is a run the "
        "worker would claim"
    )
    assert _read_intake_status(engine, set_space, space, intake_id) == "decomposed", (
        "a denied trigger must not flip the intake off `decomposed` — a half-transition "
        "is state an operator has to undo by hand"
    )
    assert driver_calls == [], (
        "a denied trigger must schedule NO background task: run_poll_driver is what "
        f"drives the ~$45 Tribunal run, and it was reached {len(driver_calls)} time(s)"
    )


# ===========================================================================
# The gate — denial arms
# ===========================================================================


def test_trigger_user_role_404(engine, set_space, monkeypatch, driver_calls):
    """role=``user`` in the intake's OWN space cannot spend the ~$45 run (D-23.1-16).

    RED (pre-gate, measured): 202 ``{"status":"queued"}``, intake flipped to
    ``in_research``, one ``research_runs`` row, driver dispatched once.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        resp = TestClient(app).post(f"/intakes/{intake_id}/research", headers=_HDR)
        _assert_denied(resp)
        _assert_no_spend(engine, set_space, space, intake_id, driver_calls)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_trigger_null_space_404(engine, set_space, monkeypatch, driver_calls):
    """A null-space ``user`` gets the gate's 404, NOT ``get_tenant_repo``'s 403.

    THE ORDERING PROOF, end to end. ``get_tenant_repo`` answers a null-space user with the
    D-04 default-deny 403 (``app/db/session.py``). ``trigger_research`` declares its repo
    parameter FIRST in source order, so this is the router's hardest signature: unless the
    gate is moved ABOVE ``repo``, FastAPI resolves the repo first and this caller learns the
    endpoint exists. RED (pre-gate, measured): 403 ``{"detail":"No space — not authorized"}``.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        resp = TestClient(app).post(f"/intakes/{intake_id}/research", headers=_HDR)
        _assert_denied(resp)
        _assert_no_spend(engine, set_space, space, intake_id, driver_calls)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# The gate — the counterweight (without it, "404 everything" would pass)
# ===========================================================================


def test_trigger_superadmin_still_works(
    engine,
    set_space,
    monkeypatch,
    superadmin_engine,
    driver_calls,
    fake_tribunal_client,
    fake_resend,
):
    """A superadmin still gets 202 + the flip + the run row + a scheduled driver.

    NO RUN IS EVER STARTED: ``driver_calls`` has replaced ``run_poll_driver``, so this arm
    asserts the driver was SCHEDULED — the seam — and never that Tribunal was reached.
    ``fake_tribunal_client`` / ``fake_resend`` are belt-and-braces: were the recorder ever
    removed, the engine seam and the mail egress would still be faked.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(f"/intakes/{intake_id}/research", headers=_HDR)
        assert resp.status_code == 202, (
            f"the gate must not brick the operator, got {resp.status_code} ({resp.text!r})"
        )
        body = resp.json()
        assert body["research_run_id"], "202 must carry a research_run_id"
        assert body["status"] == "queued"
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
        assert _count_runs(engine, set_space, space, intake_id) == 1
        assert len(driver_calls) == 1, (
            "the superadmin path must schedule the poll driver exactly once — "
            f"recorded {len(driver_calls)}"
        )
        # The driver was handed the run it should drive, not some other one.
        assert driver_calls[0][0][2] == body["research_run_id"]
        assert not fake_tribunal_client["create_run"], (
            "the recorder stands in for the driver, so the Tribunal seam must stay "
            "untouched — a create_run call here would mean a real run was dispatched"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# The ordering contract — proved by MUTATION, not by assertion alone
# ===========================================================================


def test_ordering_mutation_produces_the_403_existence_oracle(
    engine, set_space, monkeypatch, driver_calls
):
    """Moving the gate BELOW the repo makes the route leak its existence — observed live.

    ``test_superadmin_gate.test_every_gated_research_route_resolves_the_gate_before_the_repo``
    asserts the parameter INDEXES. This test proves those indexes MATTER, by re-registering
    the REAL ``trigger_research`` under a signature whose gate/repo parameters are swapped
    and driving a null-space user at it. If the ordering were inert, this would answer 404
    like the correctly-ordered route does and the assertion below would fail.

    The mutation is of the real handler, not a hand-written copy: the same function object
    is re-bound behind a ``__signature__`` FastAPI reads to build the dependant, so the
    handler body, its dependencies and its response model are all the production ones.
    """
    import inspect

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.auth_routes import protected_router
    from app.db.session import get_tenant_repo

    real = research_mod.trigger_research
    sig = inspect.signature(real)
    params = list(sig.parameters.values())

    gate_pos = next(
        i
        for i, p in enumerate(params)
        if getattr(p.default, "dependency", None) is gates.superadmin_gate
    )
    repo_pos = next(
        i
        for i, p in enumerate(params)
        if getattr(p.default, "dependency", None) is get_tenant_repo
    )
    assert gate_pos < repo_pos, (
        "precondition: the shipped signature must already be correctly ordered "
        f"(gate {gate_pos}, repo {repo_pos})"
    )

    swapped = list(params)
    swapped[gate_pos], swapped[repo_pos] = swapped[repo_pos], swapped[gate_pos]

    def _misordered(**kwargs):
        return real(**kwargs)  # pragma: no cover - the denial fires before the body

    _misordered.__signature__ = sig.replace(parameters=swapped)
    _misordered.__name__ = "trigger_research_misordered"

    mutant = FastAPI()
    mutant_router = protected_router.__class__(prefix="/intakes", tags=["mutant"])
    mutant_router.post("/{intake_id}/research", status_code=202)(_misordered)
    mutant.include_router(mutant_router)

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine)
    mutant.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        resp = TestClient(mutant).post(f"/intakes/{intake_id}/research", headers=_HDR)
        assert resp.status_code == 403, (
            "MUTATION PROOF: with the gate declared BELOW get_tenant_repo a null-space "
            f"caller must hit the repo's 403 first — got {resp.status_code} "
            f"({resp.text!r}). If this is 404 the ordering has stopped being load-bearing "
            "and the index assertion in test_superadmin_gate is decoration."
        )
        assert resp.json().get("detail") == "No space — not authorized", (
            f"the leaked denial is get_tenant_repo's D-04 default-deny, got {resp.json()!r}"
        )
        # Even the mis-ordered route denies before spending — the leak is the existence
        # oracle, not a run.
        _assert_no_spend(engine, set_space, space, intake_id, driver_calls)
    finally:
        mutant.dependency_overrides.clear()
        _cleanup(engine, space)
