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
| ``superadmin_has_no_attempt_cap``      | REPLACES ``attempt_cap_3`` (D-23.6-01): a superadmin's    |
|                                        | 4th trigger after 3 failures starts run #4.               |
| ``attempt_cap_still_applies_to_non_``  | PURE: the 3-attempt cap (cancelled-exempt) still binds a  |
| ``superadmin``                         | role=user identity.                                       |
| ``attempt_cap_ignores_cancelled``      | AS SUPERADMIN: 2 failed + 1 cancelled → a 4th run starts. |
|                                        | Since 23.6 only proves a superadmin is never capped; the  |
|                                        | cancelled-exempt rule is pinned by the pure test above.   |
| ``attempt_cap_all_cancelled_never_caps``| AS SUPERADMIN: 3 cancellations never cap (same caveat).  |
| ``rerun_after_completed_run_202``      | in_research + completed/completed_degraded → 202, run #2. |
| ``rerun_after_parked_run_202_...``     | in_research + parked → 202; the parked row stays parked.  |
| ``rerun_refused_when_an_older_run_...``| an OLDER running run blocks the rerun (all runs checked). |
| ``rerun_on_delivered_intake_stays_...``| delivered → 202; still delivered after the driver ran;    |
|                                        | audit from=delivered,to=delivered (D-23.6-03).            |
| ``rerun_on_delivered_intake_refused_``  | delivered + queued/running/needs_report_spec → 409.      |
| ``trigger_on_archived_intake_409``     | archived → 409 even with a finished run.                  |
| ``rerun_with_no_prior_runs_409``       | in_research/delivered with ZERO runs → 409.               |
| ``completion_mail_to_trigger_user``    | the completed run mails the acting user (fake_resend).    |
| ``research_stream_terminal_set``       | the SSE stream closes on ``completed`` (does not hang) —  |
|                                        | RESEARCH_TERMINAL, not the skill-run success set.         |
| ``research_stream_cancelled_closes``   | a ``cancelled`` terminal also closes the stream.          |

DESIGN — driving the REAL routers against the testcontainer (mirrors test_intake_cross_tenant):
the engine FACTORIES that ``session.py`` / ``ai_session.py`` import are patched to the
conftest engines so the production ``get_tenant_repo`` + the poll driver's ``tenant_session``
writes run verbatim locally. ``get_current_identity`` is overridden to a fabricated Identity
(the one boundary that genuinely cannot run locally — the IdP).

ACTOR CHANGE, 23.1-17 + 23.1-18 (D-23.1-16). EVERY case in this file — the trigger cases
and, since 23.1-18, the two SSE-stream cases — acts as ``_superadmin()`` and takes the
``superadmin_engine`` fixture. Both routes are gated with ``superadmin_gate``, so the
role=``user`` actor these cases used before would get an existence-hidden 404 and make them
fail on the gate rather than on the behaviour they exist to pin.

* ``POST /intakes/{id}/research`` — gated in 23.1-17: the router's one SPENDING verb (~$45,
  ``NESTOR_TRIBUNAL_UNCAPPED=1``) and its last ungated write.
* ``GET /intakes/{id}/research/stream`` — gated in 23.1-18 (the D-23.1-16 addendum): the
  router's last ungated route of any kind. It serves the OPERATOR frame (engine stage
  trace, ``cost_usd_total``, chain-guard state, run-event cursor) and its exclusion from
  23.1-17 rested on a premise that turned out to be false — the frontend opens it with
  ``fetch()`` + ``Authorization: Bearer``, and ``EventSource`` appears nowhere in
  ``frontend/src``. The actor is the ONLY thing that changed in those two cases; not one
  assertion about the terminal-set discipline was touched.

The DENIAL side of both gates — the 404s, the no-side-effect proof, the still-streams
counterweight and the ordering mutation — lives in ``tests/test_research_trigger_gate.py``
and ``tests/test_research_stream_gate.py``; this file stays the behaviour suite.
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
    """A superadmin Identity — the ONLY role either route in this file accepts.

    ``POST /intakes/{id}/research`` has been gated with ``superadmin_gate`` since 23.1-17
    (D-23.1-16): it is the router's one SPENDING verb (~$45 per call,
    ``NESTOR_TRIBUNAL_UNCAPPED=1``). ``GET /intakes/{id}/research/stream`` joined it in
    23.1-18 (the D-23.1-16 addendum), completing the router at 11 of 11 gated. A
    role=``user`` gets the existence-hidden 404 on both, so every case in this file acts as
    a superadmin. The denial sides live in ``tests/test_research_trigger_gate.py`` and
    ``tests/test_research_stream_gate.py``.
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


def _seed_research_run_at(
    engine, set_space, space_id, intake_id, run_id, status, *, attempt, created_at
) -> None:
    """Like :func:`_seed_research_run` but with an EXPLICIT ``created_at`` (ordering-safe).

    A separate helper rather than a new kwarg on ``_seed_research_run``, whose signature
    other files may import.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, attempt, created_at) "
                "VALUES (:id, :space_id, :intake_id, :status, :attempt, :created_at)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "attempt": attempt,
                "created_at": created_at,
            },
        )


def _read_run_column(engine, set_space, space_id, run_id, column):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT {column} FROM {SCHEMA}.research_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).scalar_one()


def _read_attempt(engine, set_space, space_id, run_id) -> int:
    return _read_run_column(engine, set_space, space_id, run_id, "attempt")


def _read_run_status(engine, set_space, space_id, run_id) -> str:
    return _read_run_column(engine, set_space, space_id, run_id, "status")


def _cleanup_audit(engine, space_id) -> None:
    """audit_log is deliberately NOT space-cascaded (0006, D-07) — clear it explicitly."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
        )


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


def test_superadmin_has_no_attempt_cap(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """A superadmin's 4th trigger (3 prior failed runs) STARTS a run (D-23.6-01).

    REPLACES ``test_attempt_cap_3``. That test asserted a superadmin's 4th trigger returned
    ``needs_investigation``; operator ruling D-23.6-01 (phase 23.6) removed the cap for
    ``role=superadmin``, so that assertion is now WRONG by decision, not by regression.
    Every rerun still costs ~$40 and the UI confirm says so. The cap itself survives for
    any non-superadmin identity and is pinned by the pure
    ``test_attempt_cap_still_applies_to_non_superadmin`` below.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
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
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body.get("status") != "needs_investigation", body
        assert body["research_run_id"] is not None, body
        assert _count_runs(engine, set_space, space, intake_id) == 4
        assert _read_attempt(engine, set_space, space, body["research_run_id"]) == 4
        assert len(fake_tribunal_client["create_run"]) == 1
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_attempt_cap_still_applies_to_non_superadmin():
    """PURE (no DB): the 3-attempt cap, cancelled-exempt, still binds non-superadmins.

    The trigger's gate admits only superadmins today, so this arm is unreachable in
    production; it is kept as defence-in-depth and pinned here so relaxing the gate cannot
    silently remove the cap too (D-23.6-01 exempts superadmins ONLY).
    """
    from types import SimpleNamespace

    cap = research_mod._attempt_cap_reached
    user = Identity(uid="u", email="u@x", role="user", space_id=str(uuid.uuid4()))
    runs = lambda *statuses: [SimpleNamespace(status=s) for s in statuses]  # noqa: E731

    assert cap(user, runs("failed", "failed", "failed")) == (True, 3)
    assert cap(user, runs("failed", "failed", "cancelled")) == (False, 2)
    assert cap(user, runs("cancelled", "cancelled", "cancelled")) == (False, 0)
    assert cap(_superadmin(), runs(*["failed"] * 10))[0] is False


def _post_trigger(app, intake_id):
    from fastapi.testclient import TestClient

    return TestClient(app).post(
        f"/intakes/{intake_id}/research",
        headers={"Authorization": "Bearer overridden"},
    )


def _rerun_setup(engine, set_space, monkeypatch, superadmin_engine, intake_status):
    """Seed a space + an intake in ``intake_status`` with questions; return (space, intake, app)."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status=intake_status)
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    return space, intake_id, app


@pytest.mark.parametrize("finished", ["completed", "completed_degraded"])
def test_rerun_after_completed_run_202(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend,
    finished,
):
    """in_research + a finished (successful) run -> 202, a 2nd row, attempt 2 (D-23.6-03)."""
    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "in_research"
    )
    try:
        _seed_research_run(engine, set_space, space, intake_id, uuid.uuid4(), finished)
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["status"] == "queued"
        assert _count_runs(engine, set_space, space, intake_id) == 2
        assert _read_attempt(engine, set_space, space, body["research_run_id"]) == 2
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
        assert len(fake_tribunal_client["create_run"]) == 1
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_rerun_after_parked_run_202_leaves_parked_row_parked(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """in_research + a parked run -> 202; the parked row is NOT touched (its checkpoints stay)."""
    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "in_research"
    )
    parked_id = uuid.uuid4()
    try:
        _seed_research_run(engine, set_space, space, intake_id, parked_id, "parked")
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 2
        assert _read_run_status(engine, set_space, space, parked_id) == "parked"
        assert len(fake_tribunal_client["create_run"]) == 1
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_rerun_refused_when_an_older_run_is_in_flight_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """An OLDER running run + a NEWER completed run -> 409: ALL runs are checked, not prior[0]."""
    from datetime import datetime, timedelta, timezone

    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "in_research"
    )
    now = datetime.now(timezone.utc)
    try:
        _seed_research_run_at(
            engine, set_space, space, intake_id, uuid.uuid4(), "running",
            attempt=1, created_at=now - timedelta(hours=2),
        )
        _seed_research_run_at(
            engine, set_space, space, intake_id, uuid.uuid4(), "completed",
            attempt=2, created_at=now - timedelta(hours=1),
        )
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 2
        assert not fake_tribunal_client["create_run"]
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_rerun_on_delivered_intake_stays_delivered(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """delivered + a completed run -> 202; the intake is STILL delivered after the driver ran.

    D-23.6-03: GET /intakes/{id}/report is an equality check on ``delivered``, so a status
    step-back would take the delivered report away from the client. The same-tx audit row
    is still written, with from == to == delivered (T-23.6-04).
    """
    from sqlalchemy import text

    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "delivered"
    )
    try:
        _seed_research_run(engine, set_space, space, intake_id, uuid.uuid4(), "completed")
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 202, f"expected 202, got {resp.status_code} ({resp.text!r})"
        # TestClient flushed BackgroundTasks: the fake driver has run to completion.
        assert len(fake_tribunal_client["create_run"]) == 1
        assert _count_runs(engine, set_space, space, intake_id) == 2
        assert _read_intake_status(engine, set_space, space, intake_id) == "delivered"

        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT metadata FROM {SCHEMA}.audit_log "
                    "WHERE target = :t AND event_type = 'intake.status_changed'"
                ),
                {"t": str(intake_id)},
            ).all()
        assert [r[0] for r in rows] == [{"from": "delivered", "to": "delivered"}], rows
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
        _cleanup_audit(engine, space)


@pytest.mark.parametrize("in_flight", ["queued", "running", "needs_report_spec"])
def test_rerun_on_delivered_intake_refused_while_in_flight_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, in_flight
):
    """delivered + a run in any RESEARCH_IN_FLIGHT status -> 409, nothing written."""
    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "delivered"
    )
    try:
        _seed_research_run(engine, set_space, space, intake_id, uuid.uuid4(), in_flight)
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 1
        assert not fake_tribunal_client["create_run"]
        assert _read_intake_status(engine, set_space, space, intake_id) == "delivered"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_trigger_on_archived_intake_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """archived + a completed run -> 409 (unarchive with the status override first)."""
    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, "archived"
    )
    try:
        _seed_research_run(engine, set_space, space, intake_id, uuid.uuid4(), "completed")
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 1
        assert not fake_tribunal_client["create_run"]
        assert _read_intake_status(engine, set_space, space, intake_id) == "archived"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


@pytest.mark.parametrize("intake_status", ["in_research", "delivered"])
def test_rerun_with_no_prior_runs_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, intake_status
):
    """in_research / delivered with ZERO runs -> 409: a rerun requires an existing run."""
    space, intake_id, app = _rerun_setup(
        engine, set_space, monkeypatch, superadmin_engine, intake_status
    )
    try:
        resp = _post_trigger(app, intake_id)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({resp.text!r})"
        assert _count_runs(engine, set_space, space, intake_id) == 0
        assert not fake_tribunal_client["create_run"]
        assert _read_intake_status(engine, set_space, space, intake_id) == intake_status
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_attempt_cap_ignores_cancelled(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """2 failed + 1 cancelled prior runs -> NOT capped (D-23.4-07).

    Runs as SUPERADMIN. Since phase 23.6 (D-23.6-01) a superadmin is never capped at all,
    so this case now only proves that; the cancelled-exempt rule itself is pinned by the
    pure role="user" test ``test_attempt_cap_still_applies_to_non_superadmin``.

    A ``cancelled`` run is a DELIBERATE stop that spent nothing, and it is already a legal
    retry trigger via ``_RETRYABLE_RUN_STATUSES``. Counting it toward a cap whose stated
    purpose (D-04) is "a runaway retrigger must not re-charge Tribunal" punishes the one
    operator action that PREVENTS spend.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    # Three prior rows, but only TWO of them are cap-eligible.
    for i, run_status in enumerate(("failed", "cancelled", "failed")):
        _seed_research_run(
            engine, set_space, space, intake_id, uuid.uuid4(), status=run_status, attempt=i + 1
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
        assert body.get("status") != "needs_investigation", (
            f"a cancelled run must NOT consume one of the three attempts, got {body!r}"
        )
        assert body["research_run_id"] is not None, (
            f"the trigger must have started a real run, got {body!r}"
        )
        # A 4th row IS inserted, the intake DID flip, and the seam WAS called.
        assert _count_runs(engine, set_space, space, intake_id) == 4
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
        assert fake_tribunal_client["create_run"], "create_run must have been called"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_attempt_cap_all_cancelled_never_caps(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client
):
    """3 cancelled runs and 0 failures -> never capped (D-23.4-07).

    Runs as SUPERADMIN. Since phase 23.6 (D-23.6-01) a superadmin is never capped at all,
    so this case now only proves that; the cancelled-exempt rule itself is pinned by the
    pure role="user" test ``test_attempt_cap_still_applies_to_non_superadmin``.

    Cancelling is free and deliberate; no number of cancellations may lock an intake out of
    the research it has not yet had.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="decomposed")
    _seed_decomposition_and_questions(engine, set_space, space, intake_id)
    for i in range(3):
        _seed_research_run(
            engine, set_space, space, intake_id, uuid.uuid4(), status="cancelled", attempt=i + 1
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
        assert body.get("status") != "needs_investigation", (
            f"three cancellations must not cap the intake, got {body!r}"
        )
        assert body["research_run_id"] is not None
        assert _count_runs(engine, set_space, space, intake_id) == 4
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research"
        assert fake_tribunal_client["create_run"], "create_run must have been called"
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


def test_research_stream_terminal_set(engine, set_space, monkeypatch, superadmin_engine):
    """The SSE stream closes on ``completed`` (does not hang past the terminal).

    Seeding the terminal run BEFORE connecting is the mandatory no-hang lever: the stream
    emits the at-connect snapshot, sees ``completed`` in RESEARCH_TERMINAL, and closes to EOF.

    ACTOR ONLY, 23.1-18: ``_user`` -> ``_superadmin`` + ``_patch_superadmin_engine``, because
    ``stream_research_run`` is now gated. Not one assertion below changed — what this case
    pins is the RESEARCH terminal set, and it must keep pinning exactly that.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_research_run(engine, set_space, space, intake_id, run_id, status=TERMINAL_COMPLETED)
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
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


def test_research_stream_cancelled_closes(engine, set_space, monkeypatch, superadmin_engine):
    """A ``cancelled`` terminal also closes the stream (RESEARCH_TERMINAL, not success-set).

    ACTOR ONLY, 23.1-18 (see ``test_research_stream_terminal_set``): the route is gated, so
    the fixture changed and nothing else did.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _seed_research_run(engine, set_space, space, intake_id, run_id, status=TERMINAL_CANCELLED)
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
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
