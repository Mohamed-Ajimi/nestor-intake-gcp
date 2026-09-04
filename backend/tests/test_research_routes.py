"""Research trigger + SSE stream suite (SEAM-03 / RUN-01 / SEAM-04 / D-04) — integration.

Drives the REAL Phase-16 ``research_router`` over live Postgres through a FastAPI
``TestClient`` (``pytest.mark.integration`` — auto-skips without Docker/DATABASE_URL, runs
in Cloud Build). The internal Tribunal seam is faked (``fake_tribunal_client``) and mail is
faked (``fake_resend``) so NO test reaches the real internal API or sends a real mail.

What each case proves:

| Test                                   | Proves                                                    |
|----------------------------------------|-----------------------------------------------------------|
| ``trigger_decomposed_ok``              | POST on a decomposed intake → 202, status flipped to      |
|                                        | in_research, a queued research_runs row inserted, the     |
|                                        | driver scheduled (create_run called) — SEAM-03.           |
| ``trigger_wrong_status_409``           | POST on a non-decomposed intake → 409, no run inserted.   |
| ``brief_never_opts_into_gates``        | the brief handed to create_run has NO [INTERACTIVE_REPORT]|
|                                        | and enumerates the questions — SEAM-04 at the boundary.   |
| ``attempt_cap_3``                      | a 4th trigger → needs_investigation, NO create_run call.  |
| ``completion_mail_to_trigger_user``    | the completed run mails the acting user (fake_resend).    |
| ``research_stream_terminal_set``       | the SSE stream closes on ``completed`` (does not hang) —  |
|                                        | RESEARCH_TERMINAL, not the skill-run success set.         |
| ``research_stream_cancelled_closes``   | a ``cancelled`` terminal also closes the stream.          |

DESIGN — driving the REAL routers against the testcontainer (mirrors test_intake_cross_tenant):
the engine FACTORIES that ``session.py`` / ``ai_session.py`` import are patched to the
conftest engines so the production ``get_tenant_repo`` + the poll driver's ``tenant_session``
writes run verbatim locally. ``get_current_identity`` is overridden to a fabricated Identity
(the one boundary that genuinely cannot run locally — the IdP).

ACTOR CHANGE, 23.1-17 (D-23.1-16). Every TRIGGER case above now acts as ``_superadmin()``
and takes the ``superadmin_engine`` fixture. ``POST /intakes/{id}/research`` is the router's
one SPENDING verb (~$45, ``NESTOR_TRIBUNAL_UNCAPPED=1``) and was its last ungated write; it
is gated with ``superadmin_gate`` now, so the role=``user`` actor these cases used until
23.1-17 gets an existence-hidden 404 and would make every one of them fail on the gate
rather than on the behaviour they exist to pin. The two SSE-stream cases deliberately keep
``_user``: ``stream_research_run`` is NOT gated (an ``EventSource`` cannot set an
Authorization header — see D-23.1-16's out-of-scope note). The DENIAL side of the gate — the
404s, the no-side-effect proof and the ordering mutation — lives in
``tests/test_research_trigger_gate.py``; this file stays the behaviour suite.
"""

from __future__ import annotations

import json
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

# HARD imports of the impl under test.
from app.api import research_routes as research_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"

# The RESEARCH terminal literals (D-05 boundary) — never the skill-run success value.
TERMINAL_COMPLETED = "completed"
TERMINAL_CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _superadmin() -> "Identity":
    """A superadmin Identity — the ONLY role the trigger accepts since 23.1-17.

    ``POST /intakes/{id}/research`` is gated with ``superadmin_gate`` (D-23.1-16): it is
    the router's one SPENDING verb (~$45 per call, ``NESTOR_TRIBUNAL_UNCAPPED=1``) and a
    role=``user`` now gets the existence-hidden 404. Every trigger case below therefore
    acts as a superadmin; the SSE-stream cases keep ``_user`` because
    ``stream_research_run`` is deliberately NOT gated (SSE / ``EventSource`` cannot set an
    Authorization header). The denial side lives in ``tests/test_research_trigger_gate.py``.
    """
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _patch_engines(monkeypatch, user_engine) -> None:
    """Patch the engine factories both session.py and ai_session.py imported.

    ``session.py`` backs the trigger's ``get_tenant_repo``; ``ai_session.py`` backs the
    poll driver's ``tenant_session`` (mirror ticks + finalize) AND the stream's scoped
    reads. Both read ``get_engine`` from their OWN namespace, so patch both.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


#: Same literal test_mail_endpoints / test_operator_verb_gate use, so the app_superadmin
#: role's password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in BOTH namespaces.

    Needed since 23.1-17 gated the trigger: a superadmin caller routes through
    ``get_superadmin_engine`` (D-05 two-engine routing) in ``session.py`` for
    ``get_tenant_repo`` AND in ``ai_session.py`` for ``read_brief_inputs`` + the trigger's
    own short commit tx. Patching one namespace only would leave half the path pointed at
    a real engine.
    """
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003/0011 bypass policies match. Shape copied from
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


# ---------------------------------------------------------------------------
# App builder + seeding helpers
# ---------------------------------------------------------------------------


def _build_app():
    """Mount ``research_router`` under ``protected_router`` (mirrors app/main.py wiring)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Research suite space"},
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
    """Seed one decomposition + two prioritized questions so the brief enumerates them."""
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


def _seed_research_run(engine, set_space, space_id, intake_id, run_id, status, attempt=1) -> None:
    """Insert one research_runs row under the space GUC (mirrors the SSE-stream seeder)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, attempt) "
                "VALUES (:id, :space_id, :intake_id, :status, :attempt)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "attempt": attempt,
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
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def _data_payloads(resp) -> list:
    """Collect the JSON body of every ``data:`` SSE line (heartbeats ignored)."""
    payloads = []
    for line in resp.iter_lines():
        if line.startswith("data:"):
            payloads.append(json.loads(line[5:].strip()))
    return payloads


# ===========================================================================
# Trigger — happy path (SEAM-03)
# ===========================================================================


def test_trigger_decomposed_ok(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """POST on a decomposed intake → 202, status flipped, queued run, driver scheduled."""
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
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["research_run_id"], "202 must carry a research_run_id"
        assert body["status"] == "queued"

        # Status flipped decomposed → in_research.
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
        # A research_runs row was inserted.
        assert _count_runs(engine, set_space, space, intake_id) == 1
        # The driver ran (BackgroundTasks flush after the response) → create_run was called.
        assert fake_tribunal_client["create_run"], "the poll driver must call create_run"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_trigger_wrong_status_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """POST on a non-decomposed intake → 409, no run inserted, no seam call."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="submitted")
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 0
        assert not fake_tribunal_client["create_run"], "a 409 must make no create_run call"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_trigger_no_questions_422(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """POST on a decomposed intake with ZERO validated questions → 422 (empty-brief guard).

    Live finding 2026-07-21: an empty brief makes the engine park the run as
    ``needs_input`` — a state the intake side has no surface for. The guard
    refuses before any status flip, run insert, or seam call.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    # Deliberately NO _seed_decomposition_and_questions and no question answers.
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({resp.text!r})"
        # No half-transition: status unchanged, no run row, no seam call.
        assert _read_intake_status(engine, set_space, space, intake_id) == "decomposed"
        assert _count_runs(engine, set_space, space, intake_id) == 0
        assert not fake_tribunal_client["create_run"], "a 422 must make no create_run call"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_retrigger_after_dead_run_202(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """POST on an in_research intake whose latest run is parked/dead → 202 (retry path).

    Live finding 2026-07-21: the 16-04 failure-card retry was unreachable — the
    transition map 409'd everything but ``decomposed``. A retry is allowed when
    the latest run is ``failed``/``cancelled``/``needs_input``.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _seed_research_run(
        engine, set_space, space, intake_id, uuid.uuid4(), "needs_input", attempt=1
    )
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        assert resp.json()["status"] == "queued"
        assert _count_runs(engine, set_space, space, intake_id) == 2
        assert fake_tribunal_client["create_run"], "the retry must reach create_run"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_retrigger_while_running_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """POST on an in_research intake with an ACTIVE run → 409, no second run."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _seed_research_run(
        engine, set_space, space, intake_id, uuid.uuid4(), "running", attempt=1
    )
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 1
        assert not fake_tribunal_client["create_run"], "an active run must block create_run"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_brief_never_opts_into_gates(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """The brief handed to create_run has NO [INTERACTIVE_REPORT] and enumerates questions."""
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
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202
        assert fake_tribunal_client["create_run"], "create_run must have been called"
        brief = fake_tribunal_client["create_run"][0]["brief"]
        assert brief, "the brief must be non-empty"
        assert "[INTERACTIVE_REPORT]" not in brief, (
            "SEAM-04: the brief must NEVER opt into the interactive-report pause gate."
        )
        # The enumerated questions are present (priority order → concurrents (prio 1) first).
        assert "Wie zijn de concurrenten?" in brief
        assert "Wat is de marktomvang?" in brief
        assert "Onderzoeksvragen:" in brief
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_attempt_cap_3(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """A 4th trigger (3 prior runs) → needs_investigation, NO create_run call, no flip."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    # Seed 3 prior research runs → the cap is already reached.
    for i in range(3):
        _seed_research_run(
            engine, set_space, space, intake_id, uuid.uuid4(), status="failed", attempt=i + 1
        )
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, f"expected 202 wrapper, got {resp.status_code}"
        body = resp.json()
        assert body["status"] == "needs_investigation", (
            f"the 4th attempt must return needs_investigation, got {body!r}"
        )
        assert body["research_run_id"] is None
        # NO new run inserted (still 3), NO status flip, NO seam call (D-04).
        assert _count_runs(engine, set_space, space, intake_id) == 3
        assert _read_intake_status(engine, set_space, space, intake_id) == "decomposed"
        assert not fake_tribunal_client["create_run"], (
            "the 4th attempt must make NO create_run call (no double-charge)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_completion_mail_to_trigger_user(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """A completed run mails the acting user (fake_resend recipient == the trigger user)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    # Default metrics_script ends in completed → the completion mail path runs.
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    acting = _superadmin()
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(acting)
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202
        # BackgroundTasks flushed after the response → the driver drove to completed + mailed.
        assert fake_resend["calls"], "a completed run must send a completion mail"
        assert fake_resend["calls"][-1]["to"] == [acting.email], (
            f"the completion mail must go to the acting user, got {fake_resend['calls'][-1]['to']!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# SSE stream — terminal-set discipline (RUN-01 / Pitfall 3)
# ===========================================================================


def test_research_stream_terminal_set(engine, set_space, monkeypatch):
    """The SSE stream closes on ``completed`` (does not hang past the terminal).

    Seeding the terminal run BEFORE connecting is the mandatory no-hang lever: the stream
    emits the at-connect snapshot, sees ``completed`` in RESEARCH_TERMINAL, and closes to EOF.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_research_run(engine, set_space, space, intake_id, run_id, status=TERMINAL_COMPLETED)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        with TestClient(app).stream(
            "GET",
            f"/intakes/{intake_id}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            payloads = _data_payloads(resp)  # returns => the server closed the stream
        assert payloads, "expected at least the at-connect snapshot data event"
        assert payloads[-1] is not None
        assert payloads[-1]["status"] == TERMINAL_COMPLETED, (
            f"the stream must close on the completed terminal, got {payloads[-1]!r}"
        )
        # The dynamic stage trace fields are carried on the frame (RUN-01).
        assert "current_stage" in payloads[-1]
        assert "stage_detail" in payloads[-1]
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_research_stream_cancelled_closes(engine, set_space, monkeypatch):
    """A ``cancelled`` terminal also closes the stream (RESEARCH_TERMINAL, not success-set)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_research_run(engine, set_space, space, intake_id, run_id, status=TERMINAL_CANCELLED)
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        with TestClient(app).stream(
            "GET",
            f"/intakes/{intake_id}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        ) as resp:
            assert resp.status_code == 200
            payloads = _data_payloads(resp)
        assert payloads[-1]["status"] == TERMINAL_CANCELLED, (
            f"the stream must close on the cancelled terminal, got {payloads[-1]!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
