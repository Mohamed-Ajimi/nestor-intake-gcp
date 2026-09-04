"""The research SSE stream's denial suite (D-23.1-16 addendum) — plan 23.1-18.

WHAT THIS FILE PROVES. ``GET /intakes/{intake_id}/research/stream``
(:func:`app.api.research_routes.stream_research_run`) was the ELEVENTH and LAST route on
``research_router`` still taking a bare ``Depends(get_current_identity)``. It is a READ, not
a spend — but what it reads is the operator's diagnostic frame: the run id, the engine's
``current_stage`` / ``stage_detail`` trace, ``cost_usd_total``, the Phase-17 chain-guard
state (``chain_status`` / ``chain_broken_at`` / ``bundle_key``) and the run-event cursor
``event_seq``. None of that is client-facing, and the frontend never asks for it from a
client surface: ``openResearchStream`` (``frontend/src/lib/api/research.ts:551``) is mounted
ONLY from ``admin.pulse.intakes.$id.tsx`` and ``admin.pulse.runs.$runId.index.tsx``, both
via ``ResearchRunProgress``.

WHY IT WAS EXCLUDED, AND WHY THAT REASON WAS FALSE. D-23.1-16 left this route ungated on the
grounds that "it is SSE, an ``EventSource`` cannot set an Authorization header, so gating it
blind could break the live run feed". That premise does not hold for THIS codebase and the
addendum in ``23.1-CONTEXT.md`` section 15 records the correction: ``openResearchStream``
opens the stream with ``fetch()`` carrying ``Authorization: Bearer ${token}``
(``research.ts:572-577``) from the same ``currentIdToken()`` source ``apiFetch`` uses, and
reads ``resp.body`` as a stream. ``grep -rc "EventSource" frontend/src`` returns NOTHING —
the codebase does not use ``EventSource`` at all. No transport constraint ever blocked the
gate.

MEASURED RED (before the gate, this exact seeding, recorded in ``23.1-18-SUMMARY.md``):

* role=``user`` in the intake's OWN space -> **200** ``text/event-stream; charset=utf-8``
  with ONE full data frame: ``{"id": "...", "status": "completed", "current_stage": null,
  "stage_detail": null, "cost_usd_total": null, ..., "chain_status": null, "bundle_key":
  null, "event_seq": null}``. The operator frame was served verbatim to a role=``user``.
* a null-space ``user`` -> **403** ``{"detail":"No space — not authorized"}`` — the
  existence oracle, leaked by the in-body pre-flight's ``PermissionError`` arm.

| Test                                  | Proves                                            |
|---------------------------------------|---------------------------------------------------|
| ``user_role_404``                     | role=``user`` IN THE INTAKE'S OWN SPACE gets       |
|                                       | EXACTLY 404 with the gate's byte-exact detail, a   |
|                                       | JSON body (NOT ``text/event-stream``) and ZERO     |
|                                       | data frames.                                       |
| ``null_space_404``                    | a ``user`` with ``space_id=None`` gets EXACTLY     |
|                                       | 404, NOT the pre-flight's 403. Measured RED: 403.  |
| ``superadmin_still_streams``          | the operator's live run feed still OPENS and       |
|                                       | YIELDS the real row — asserted on the FRAME's      |
|                                       | contents, not on the status line. Without this arm |
|                                       | "404 for everyone" would pass the whole file.      |
| ``superadmin_emits_on_change``        | the TICK LOOP still runs under the gate: a second, |
|                                       | different frame after the row changes mid-stream,  |
|                                       | then the terminal close.                           |

ZERO PROVIDER SPEND BY CONSTRUCTION. This route never dispatches anything — but
``research_routes.run_poll_driver`` is replaced with a recorder for EVERY test here anyway
(``driver_calls``), and each test asserts the recorder stayed empty. If a future edit ever
wired a dispatch into the read path, this file fails rather than bills.

HARNESS PROVENANCE. Seeding + engine-patch scaffold COPIED (never imported — no private
symbol crosses a test module) from ``test_research_routes.py`` (``_seed_space``,
``_seed_intake``, ``_seed_research_run``, ``_patch_engines``, ``_build_app``,
``_data_payloads``) and ``test_research_trigger_gate.py`` (``superadmin_engine``,
``_patch_superadmin_engine``, ``driver_calls``, ``_cleanup``'s audit sweep).

Skip-clean: ``pytestmark = pytest.mark.integration``; ``importorskip`` guards so the file
COLLECTS on a box without the backend deps.
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
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Same literal test_mail_endpoints / test_operator_verb_gate / test_research_trigger_gate
#: use, so the app_superadmin role's password stays stable no matter which suite runs first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only

# The RESEARCH terminal literals (D-05 boundary) — never the skill-run success vocabulary.
TERMINAL_COMPLETED = "completed"
NON_TERMINAL_RUNNING = "running"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` scoped to the intake's OWN space — the arm that proves the ROLE gate.

    A CROSS-space user is already 404'd by the pre-flight's ``check_intake_in_scope`` and
    would prove nothing about the role gate.
    """
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the case the in-body pre-flight answered with a 403."""
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
    """Patch BOTH engine factories.

    ``ai_session.py`` is the one the STREAM actually rides: both
    ``stream_session.check_intake_in_scope`` (the pre-flight) and
    ``stream_session.read_latest_research_run_dict`` (every tick) reuse
    ``ai_session.tenant_session``. ``session.py`` is patched too so this file's app builds
    identically to the other research suites and a future signature that grows a
    ``get_tenant_repo`` cannot silently reach a real engine.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in BOTH namespaces (D-05 two-engine routing).

    A superadmin identity carries ``space_id=None``, so ``ai_session._engine_and_space``
    routes it to ``get_superadmin_engine`` and sets NO GUC — the stream's scoped reads
    would otherwise hit a real engine. ``session.py`` is patched alongside for the same
    reason ``_patch_engines`` patches it: plan 23.1-17 measured that patching ONE namespace
    leaves half the path pointed at production.
    """
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003/0011 bypass policies match. Shape copied from
    ``test_research_trigger_gate.superadmin_engine``.
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

    The stream is a READ and reaches no dispatch today, so this is deliberately a TRIPWIRE
    rather than a necessity: with ``run_poll_driver`` stubbed, no test in this file can
    start a ~$45 Tribunal run even if a future edit wired one into the read path, and every
    test asserts the recorder stayed empty so such an edit fails here instead of billing.
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
            {"id": space_id, "name": "Research stream gate space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="in_research") -> None:
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


def _seed_research_run(
    engine, set_space, space_id, intake_id, run_id, status, *, current_stage=None
) -> None:
    """Insert one research_runs row under the space GUC.

    ``current_stage`` is seeded on purpose in the positive arms: it is one of the operator
    diagnostic fields the frame carries, so asserting it came back proves the handler read
    THE SEEDED ROW rather than merely answering 200 with something.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, attempt, current_stage) "
                "VALUES (:id, :space_id, :intake_id, :status, 1, :stage)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "stage": current_stage,
            },
        )


def _update_run(engine, set_space, space_id, run_id, *, status, current_stage) -> None:
    """Mutate the mirrored run row mid-stream — the emit-on-change lever."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"UPDATE {SCHEMA}.research_runs SET status = :status, "
                "current_stage = :stage WHERE id = :id"
            ),
            {"id": run_id, "status": status, "stage": current_stage},
        )


def _cleanup(engine, space_id) -> None:
    """Drop the seeded space AND this suite's audit rows.

    ``audit_log.space_id`` has NO ForeignKey (the trail deliberately outlives its space), so
    dropping the organization does not cascade those rows away — ``test_operator_verb_gate``
    measured a pre-existing suite going red purely on collection order for this reason.
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


def _data_payloads(resp) -> list:
    """Collect the JSON body of every ``data:`` SSE line (heartbeats ignored)."""
    payloads = []
    for line in resp.iter_lines():
        if line.startswith("data:"):
            payloads.append(json.loads(line[5:].strip()))
    return payloads


def _assert_denied(resp) -> None:
    """EXACTLY 404, the gate's byte-exact detail, and NOT an opened stream."""
    assert resp.status_code == 404, (
        "GET /research/stream: an unauthorized caller must get EXACTLY 404 "
        f"(existence-hidden, D-23.1-02/D-23.1-16), got {resp.status_code} ({resp.text!r}). "
        "A 403 is an existence oracle; a 200 means the operator frame was served."
    )
    assert resp.json().get("detail") == "Intake not found", (
        "GET /research/stream: the 404 detail is part of the convention and is asserted "
        f"byte-exact (app/auth/gates.py), got {resp.json()!r}"
    )
    assert not resp.headers["content-type"].startswith("text/event-stream"), (
        "the denial must be a plain JSON error, never an opened event-stream — got "
        f"content-type {resp.headers['content-type']!r}"
    )
    assert "data:" not in resp.text, (
        "a denied caller must receive ZERO SSE data frames; the operator frame carries the "
        f"run id, the engine stage trace, cost_usd_total and the chain-guard state — got "
        f"{resp.text!r}"
    )


# ===========================================================================
# The gate — denial arms
# ===========================================================================


def test_stream_user_role_404(engine, set_space, monkeypatch, driver_calls):
    """role=``user`` in the intake's OWN space cannot read the operator frame.

    RED (pre-gate, measured): 200 ``text/event-stream; charset=utf-8`` with one full frame
    carrying the run id, status, stage trace, ``cost_usd_total``, ``chain_status``,
    ``bundle_key`` and ``event_seq``.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id)
    _seed_research_run(
        engine, set_space, space, intake_id, run_id, status=TERMINAL_COMPLETED
    )
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        with TestClient(app).stream(
            "GET", f"/intakes/{intake_id}/research/stream", headers=_HDR
        ) as resp:
            resp.read()  # materialize the body before .text / .json()
            _assert_denied(resp)
        assert driver_calls == [], "the read path must dispatch nothing"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_stream_null_space_404(engine, set_space, monkeypatch, driver_calls):
    """A null-space ``user`` gets the gate's 404, NOT the pre-flight's 403.

    THE ORDERING PROOF for this route. ``stream_research_run`` carries its scope check in
    the HANDLER BODY (``check_intake_in_scope`` in the threadpool), and a null-space
    identity makes ``tenant_session`` raise ``PermissionError`` which that body maps to
    403 ``{"detail":"No space — not authorized"}`` — an existence oracle. A dependency
    resolves BEFORE the body runs, so the gate wins and the caller learns nothing.
    RED (pre-gate, measured): exactly that 403.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id)
    _seed_research_run(
        engine, set_space, space, intake_id, run_id, status=TERMINAL_COMPLETED
    )
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        with TestClient(app).stream(
            "GET", f"/intakes/{intake_id}/research/stream", headers=_HDR
        ) as resp:
            resp.read()
            _assert_denied(resp)
        assert driver_calls == [], "the read path must dispatch nothing"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# The counterweight — the operator's live run feed must still WORK
# ===========================================================================


def test_stream_superadmin_still_streams(
    engine, set_space, monkeypatch, superadmin_engine, driver_calls
):
    """A superadmin still opens the stream AND receives the seeded run's real frame.

    This is the half that matters most: the run feed is a live operator feature mounted on
    ``admin.pulse.intakes.$id`` and ``admin.pulse.runs.$runId``. Asserted on the FRAME's
    CONTENTS — the run id and the seeded ``current_stage`` — not on the status line, so
    "200 with an empty body" cannot pass. Without this arm, gating the route to 404 for
    everybody would satisfy both denial tests above.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id)
    _seed_research_run(
        engine,
        set_space,
        space,
        intake_id,
        run_id,
        status=TERMINAL_COMPLETED,
        current_stage="finalize",
    )
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        with TestClient(app).stream(
            "GET", f"/intakes/{intake_id}/research/stream", headers=_HDR
        ) as resp:
            assert resp.status_code == 200, (
                "the gate must not brick the operator's run feed, got "
                f"{resp.status_code}"
            )
            assert resp.headers["content-type"].startswith("text/event-stream"), (
                f"the stream must still be SSE, got {resp.headers['content-type']!r}"
            )
            payloads = _data_payloads(resp)  # returns => the server closed the stream
        assert payloads, "expected at least the at-connect snapshot data event"
        frame = payloads[-1]
        assert frame is not None, "the frame must carry the run, not ``data: null``"
        assert frame["id"] == str(run_id), (
            f"the frame must be THE SEEDED RUN, got {frame['id']!r}"
        )
        assert frame["status"] == TERMINAL_COMPLETED
        assert frame["current_stage"] == "finalize", (
            "the operator diagnostic fields must survive the gate — the stage trace is "
            f"what the run page renders, got {frame['current_stage']!r}"
        )
        # The full RUN-01 / RUN-03 / 15.3-06 wire shape, unchanged by the gate.
        for key in (
            "stage_detail",
            "cost_usd_total",
            "chain_status",
            "bundle_key",
            "event_seq",
        ):
            assert key in frame, f"the gate must not drop {key!r} from the frame"
        assert driver_calls == [], "reading the feed must dispatch nothing"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_stream_superadmin_emits_on_change(
    engine, set_space, monkeypatch, superadmin_engine, driver_calls
):
    """The TICK LOOP still runs under the gate — a live second frame, not just a snapshot.

    ``test_stream_superadmin_still_streams`` proves the at-connect snapshot. That alone
    would also pass if the per-tick scoped read had stopped working under the gated
    identity, because the handler would simply close. Here the run is seeded NON-terminal,
    the snapshot is consumed, the row is then mutated mid-stream, and the handler must
    emit a SECOND, DIFFERENT frame (emit-on-change) and close on the terminal.

    ``TICK_SECONDS`` is monkeypatched down so this costs well under a second; the knob is
    module-level for exactly this reason (``research_routes.py``).

    ORDERING IS DETERMINISTIC, NOT TIMED. The row must not flip until the snapshot read
    has happened, or the test would silently collapse into the single-frame case it exists
    to go beyond. Rather than sleep and hope, ``read_latest_research_run_dict`` is wrapped
    in a COUNTING PASS-THROUGH (it still calls the real function — nothing about the read
    is stubbed) and the flipping thread waits on the first call. The body is drained with
    ``_data_payloads`` after the handler closes, so the test never depends on httpx
    yielding SSE lines incrementally.
    """
    import threading

    from fastapi.testclient import TestClient

    monkeypatch.setattr(research_mod, "TICK_SECONDS", 0.2)

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id)
    _seed_research_run(
        engine,
        set_space,
        space,
        intake_id,
        run_id,
        status=NON_TERMINAL_RUNNING,
        current_stage="dispatch",
    )
    _patch_engines(monkeypatch, engine)
    _patch_superadmin_engine(monkeypatch, superadmin_engine)

    # Observe the snapshot read WITHOUT replacing it — the real helper still runs.
    snapshot_read = threading.Event()
    real_read = research_mod.read_latest_research_run_dict

    def _observed_read(*args, **kwargs):
        result = real_read(*args, **kwargs)
        snapshot_read.set()
        return result

    monkeypatch.setattr(research_mod, "read_latest_research_run_dict", _observed_read)

    def _flip_after_snapshot():
        if not snapshot_read.wait(timeout=30):  # pragma: no cover - hang guard
            return
        _update_run(
            engine,
            set_space,
            space,
            run_id,
            status=TERMINAL_COMPLETED,
            current_stage="finalize",
        )

    flipper = threading.Thread(target=_flip_after_snapshot, daemon=True)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        flipper.start()
        with TestClient(app).stream(
            "GET", f"/intakes/{intake_id}/research/stream", headers=_HDR
        ) as resp:
            assert resp.status_code == 200
            payloads = _data_payloads(resp)  # returns => the handler closed on terminal
        assert len(payloads) >= 2, (
            "the tick loop must emit a SECOND frame after the row changed — one frame "
            f"means the stream went silent under the gate (a snapshot-only feed), got "
            f"{payloads!r}"
        )
        assert payloads[0]["status"] == NON_TERMINAL_RUNNING, (
            f"frame 1 must be the pre-flip snapshot, got {payloads[0]!r}"
        )
        assert payloads[0]["current_stage"] == "dispatch"
        assert payloads[-1]["status"] == TERMINAL_COMPLETED, (
            f"the live frame must carry the new status, got {payloads[-1]!r}"
        )
        assert payloads[-1]["current_stage"] == "finalize"
        assert payloads[-1] != payloads[0], (
            "emit-on-change: the second frame must actually differ from the snapshot"
        )
        assert driver_calls == [], "reading the feed must dispatch nothing"
    finally:
        flipper.join(timeout=5)
        app.dependency_overrides.clear()
        _cleanup(engine, space)
