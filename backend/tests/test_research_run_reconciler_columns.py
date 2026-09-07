"""23.3-04 — the four facts a stateless reconciler needs, and the three it starts writing.

``run_poll_driver`` (``app/research/run_task.py``) is a ``while True`` inside a FastAPI
``BackgroundTask`` with no wall-clock cap. If that nestor-api instance recycles — a deploy,
a scale event, Cloud Run's own lifecycle — the driver dies silently: the engine keeps
executing and spending, ``research_runs`` is never mirrored or finalized, and nothing sweeps
it (DEF-23.2-03, 23.3-CONTEXT.md § 8). Plans 05/06 ship the sweep. THIS file pins the four
columns it cannot work without, and the three that start being written now.

Why each column, said once here so a later reader does not "simplify" one away:

* ``acting_user_id`` / ``acting_email`` — the Tribunal seam REQUIRES non-empty
  ``X-Acting-User-Id`` / ``X-Acting-User-Email`` and answers 400 without them, because the
  D-05 acting-user attribution is a hard legal constraint on a frozen audit chain
  (``tribunal/nestor_pulse_sdk/auth/internal_caller.py``). A sweep has no request identity
  of its own, so it must REPLAY the original human's — which means the row has to carry it.
  ``load_trigger_context`` (``run_task.py``) derives the actor from the LIVE ``Identity``
  and is therefore unavailable to a reconciler by construction.
* ``driver_heartbeat_at`` — there is NO ``updated_at`` on this table, and this project has
  already paid for the lesson that a creation timestamp is not a liveness signal (the D-E
  defect: a live 35-minute long-poll was indistinguishable from a process that died 35
  minutes ago, and the designed response to a dead process is to re-run at full cost).
* ``reconcile_lease_until`` — nestor-api runs ``maxScale=4``; two instances mirroring the
  same run concurrently is the defect this phase must not introduce (§ 8).

Test-style notes, both deliberate:

* Every schema/index assertion reads the DEPLOYED database (``information_schema`` /
  ``pg_indexes``), never this repository's migration source text — the style
  ``test_research_dispatch_dedup.py`` established, and the reason its sibling index carries
  a comment saying ``alembic check`` does NOT compare partial-index predicates
  (postgresql ``compare_indexes`` looks at the unique flag and the expressions only), so a
  drifted ``postgresql_where`` passes it silently (DEF-23.2-15).
* ``pytestmark = pytest.mark.integration`` because the only committed backend gate is
  ``cloudbuild.test.yaml``'s ``pytest tests -m integration``. Without the marker these
  proofs would be collected and then DESELECTED — green because they ran nothing.

ZERO PROVIDER SPEND: every seam is the ``fake_tribunal_client`` / ``fake_gcs`` /
``fake_resend`` fixture; no test here reaches a real provider, a real bucket or the real
Tribunal service.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

# External deps — skip-clean when not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")
run_task = pytest.importorskip("app.research.run_task")

from app.api import research_routes as research_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
TABLE = "research_runs"

#: The four columns 0017 adds. ALL NULLABLE with NO server default: a NOT NULL or a
#: defaulted column would rewrite a table that holds paid, in-flight runs.
RECONCILER_COLUMNS = (
    "acting_user_id",
    "acting_email",
    "driver_heartbeat_at",
    "reconcile_lease_until",
)

#: The two that are moments in time. ``timestamp with time zone``, never ``timestamp``:
#: a naive column would silently re-interpret every heartbeat in the server's local zone,
#: and the whole point of the column is comparing it to ``now()`` across instances.
TIMESTAMPTZ_COLUMNS = ("driver_heartbeat_at", "reconcile_lease_until")

#: The orphan-candidate index. BYTE-IDENTICAL to migration 0017's and to the model's
#: ``__table_args__`` entry — a mismatch is invisible at runtime (both create *an* index)
#: and only surfaces on a downgrade or the next autogenerate.
ORPHAN_INDEX = "ix_research_runs_orphan_candidates"

#: The THREE in-flight statuses. The SAME literals as
#: ``uq_research_runs_one_inflight_per_intake`` (0016) and for the same documented reason:
#: a POSITIVE ``IN (...)`` so an unknown FUTURE engine status fails OPEN — it simply is not
#: an orphan candidate — instead of being swept as one.
INFLIGHT = frozenset({"queued", "running", "needs_report_spec"})

_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only

#: A representative engine timestamp, as pydantic serialises it (ISO-8601 + Z). Used to
#: prove the heartbeat is NOT one of the seam's own timestamps.
_STARTED_ISO = "2026-07-27T08:09:00Z"
_STARTED_DT = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------

def _superadmin() -> "Identity":
    """The triggering human. Both research verbs are superadmin-gated (D-23.1-16)."""
    return Identity(
        uid="super-trigger", email="trigger@agenic.be", role="superadmin", space_id=None
    )


def _other_superadmin() -> "Identity":
    """A DIFFERENT human — the one who resumes. Must displace the triggerer on the row."""
    return Identity(
        uid="super-resume", email="resume@agenic.be", role="superadmin", space_id=None
    )


def _superadmin_without_email() -> "Identity":
    """``Identity.email`` is ``str | None`` — a token without one is a real shape."""
    return Identity(uid="super-no-mail", email=None, role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine plumbing (shape copied from test_research_dispatch_dedup.py)
# ---------------------------------------------------------------------------

def _patch_engines(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (the D-05 two-engine routing)."""
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER ROLE app_superadmin WITH LOGIN PASSWORD "
                f"'{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


def _build_app():
    """Mount ``research_router`` under ``protected_router`` (mirrors app/main.py wiring)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


# ---------------------------------------------------------------------------
# Seeding + reading
# ---------------------------------------------------------------------------

def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Reconciler columns space"},
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
    """One decomposition + two prioritized questions, so the brief is never empty.

    Without these the handler short-circuits on the empty-brief 422 and never reaches the
    write transaction these tests exist to read.
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


def _seed_parked_run(
    engine, set_space, space_id, intake_id, run_id, *, actor_uid, actor_email
) -> None:
    """A parked run carrying the TRIGGERING actor — so a resume must be seen to displace it."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(id, space_id, intake_id, status, tribunal_run_id, attempt, "
                " acting_user_id, acting_email) "
                "VALUES (:id, :space_id, :intake_id, 'parked', :trid, 1, :uid, :email)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "trid": f"trib-{run_id}",
                "uid": actor_uid,
                "email": actor_email,
            },
        )


def _read_actor(engine, set_space, space_id, run_id) -> dict:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                f"SELECT acting_user_id, acting_email FROM {SCHEMA}.{TABLE} WHERE id = :id"
            ),
            {"id": run_id},
        ).one()
    return {"acting_user_id": row[0], "acting_email": row[1]}


def _read_terminal(engine, set_space, space_id, intake_id) -> dict:
    """The four values test 7 compares against HEAD's, newest run first."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                f"SELECT status, output_markdown, bundle_key, chain_status "
                f"FROM {SCHEMA}.{TABLE} WHERE intake_id = :iid "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"iid": intake_id},
        ).one()
    return {
        "status": row[0],
        "output_markdown": row[1],
        "bundle_key": row[2],
        "chain_status": row[3],
    }


def _only_run_id(engine, set_space, space_id, intake_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        rows = conn.execute(
            text(f"SELECT id FROM {SCHEMA}.{TABLE} WHERE intake_id = :iid"),
            {"iid": intake_id},
        ).all()
    assert len(rows) == 1, f"expected exactly one run row, got {len(rows)}"
    return rows[0][0]


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )
    # audit_log is deliberately NOT space-cascaded (0006, D-07) — the trail outlives its
    # subject — so its rows have to be cleared explicitly.
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
        )


def _no_driver(monkeypatch) -> list:
    """Schedule the driver but never RUN it — these tests are about the row, not the run."""
    scheduled: list = []
    monkeypatch.setattr(
        research_mod, "run_poll_driver",
        lambda *a, **k: scheduled.append(a), raising=False,
    )
    return scheduled


def _capture_route_log(monkeypatch) -> list:
    """Every WARNING/ERROR ``research_routes`` logs, by REPLACING its logger.

    NOT ``caplog``: ``test_research_run_task.py``'s ``warning_sink`` records that both
    ``caplog`` and a directly-attached handler captured NOTHING for this app's loggers under
    the backend suite (D24-1, cause unconfirmed). Replacing the logger object sidesteps the
    framework and asserts the thing that actually matters — that the module CALLED
    ``log.warning`` with the right content.
    """
    seen: list[str] = []

    class _RecordingLog:
        def _record(self, msg, args) -> None:
            try:
                seen.append(str(msg) % args if args else str(msg))
            except Exception:  # noqa: BLE001 - a bad format string is the code's bug
                seen.append(str(msg))

        def warning(self, msg, *args, **kwargs) -> None:
            self._record(msg, args)

        def error(self, msg, *args, **kwargs) -> None:
            self._record(msg, args)

        def exception(self, msg, *args, **kwargs) -> None:
            self._record(msg, args)

        def info(self, msg, *args, **kwargs) -> None:
            pass

        def debug(self, msg, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(research_mod, "_log", _RecordingLog())
    return seen


def _capture_repo_patch(monkeypatch) -> list:
    """Record the values ``mirror_tick`` PATCHes, without a session or a database.

    Reads the values the REAL ``mirror_tick`` writes rather than trusting that a stub was
    called — the discipline ``test_research_run_task.py::_capture_repo_patch`` applies to
    the same seam.
    """
    import contextlib

    calls: list = []

    class _Repo:
        def __init__(self, session, identity) -> None:
            pass

        def patch(self, row_id, **values):
            calls.append(dict(values))
            return 1

    @contextlib.contextmanager
    def _fake_tenant_session(identity):
        yield object()

    monkeypatch.setattr(run_task, "ResearchRunRepository", _Repo)
    monkeypatch.setattr(run_task, "tenant_session", _fake_tenant_session)
    return calls


def _indexdef(engine, name: str) -> str | None:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = :t AND indexname = :n"
            ),
            {"s": SCHEMA, "t": TABLE, "n": name},
        ).first()
    return None if row is None else row[0]


def _statuses_in(predicate: str) -> frozenset[str]:
    """Every single-quoted literal in a predicate string.

    Postgres renders the deployed predicate as
    ``WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, ...])::text[]))`` —
    the ``::character varying`` casts are NOT quoted, so the quoted literals are exactly the
    status values.
    """
    return frozenset(re.findall(r"'([^']*)'", predicate))


def _where_of(indexdef: str) -> str:
    upper = indexdef.upper()
    assert "WHERE" in upper, f"the index must be PARTIAL, got: {indexdef}"
    return indexdef[upper.index("WHERE"):]


# ===========================================================================
# Test 1 — the four columns exist, are nullable, and carry no default
# ===========================================================================

def test_the_four_reconciler_columns_exist_nullable_and_undefaulted(engine):
    """0017's four columns, read out of the DEPLOYED schema.

    NULLABLE with NO server default is not a style choice: ``research_runs`` holds paid,
    in-flight rows, and a NOT NULL or defaulted column would rewrite that table under a
    live deploy. NULL here means "this run predates the reconciler", which is exactly what
    plan 05 must be able to observe and skip.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable, data_type, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :tbl "
                "AND column_name = ANY(:cols)"
            ),
            {"schema": SCHEMA, "tbl": TABLE, "cols": list(RECONCILER_COLUMNS)},
        ).all()
    by_name = {r[0]: {"nullable": r[1], "type": r[2], "default": r[3]} for r in rows}

    # ANTI-VACUITY: count the columns actually checked, so a typo in RECONCILER_COLUMNS
    # (or an empty result set) cannot make this loop pass by iterating over nothing.
    checked = 0
    for col in RECONCILER_COLUMNS:
        assert col in by_name, (
            f"missing column {col} on {SCHEMA}.{TABLE} — a reconciler cannot replay an "
            f"actor or judge liveness without it (present: {sorted(by_name)})"
        )
        assert by_name[col]["nullable"] == "YES", (
            f"column {col} must be NULLABLE — every pre-existing run row carries NULL and "
            f"a NOT NULL column would fail the migration on a live table "
            f"(is_nullable={by_name[col]['nullable']!r})"
        )
        assert by_name[col]["default"] is None, (
            f"column {col} must carry NO server default — the app is the sole writer, and "
            f"a default would also force a table rewrite "
            f"(column_default={by_name[col]['default']!r})"
        )
        checked += 1

    assert checked == 4, f"expected to check 4 columns, checked {checked}"
    assert checked == len(RECONCILER_COLUMNS)

    for col in TIMESTAMPTZ_COLUMNS:
        assert by_name[col]["type"] == "timestamp with time zone", (
            f"{col} must be timestamptz — a naive column re-interprets every heartbeat in "
            f"the server's local zone, and the column exists to be compared to now() "
            f"across instances (data_type={by_name[col]['type']!r})"
        )


# ===========================================================================
# Test 2 — the orphan-candidate index, pinned against the DEPLOYED definition
# ===========================================================================

def test_the_orphan_candidate_index_is_partial_over_the_three_inflight_statuses(engine):
    """``pg_indexes.indexdef`` — NOT ``alembic check``, and NOT the model.

    ``alembic check``'s postgresql ``compare_indexes`` inspects the unique flag and the
    expressions only; it never looks at ``postgresql_where``. A predicate that drifted from
    the migration passes it SILENTLY (DEF-23.2-15, and the same comment sits above
    ``uq_research_runs_one_inflight_per_intake`` in the model). So the deployed definition
    is the only thing worth asserting on.
    """
    indexdef = _indexdef(engine, ORPHAN_INDEX)
    assert indexdef is not None, (
        f"missing index {ORPHAN_INDEX} on {SCHEMA}.{TABLE} — the orphan scan would seq-scan "
        f"a table of paid runs on every sweep"
    )
    assert "driver_heartbeat_at" in indexdef, (
        f"the index must be keyed on driver_heartbeat_at (the liveness column the sweep "
        f"orders and filters by), got: {indexdef}"
    )

    where = _where_of(indexdef)
    assert _statuses_in(where) == INFLIGHT, (
        f"the predicate must name EXACTLY {sorted(INFLIGHT)} — the same three literals as "
        f"uq_research_runs_one_inflight_per_intake. 'needs_report_spec' is the one that is "
        f"easy to miss: a run sitting there is ALIVE, awaiting an operator's report spec, "
        f"and dropping it would make the sweep blind to a whole live state. got: {indexdef}"
    )
    assert "NOT IN" not in where.upper(), (
        f"the predicate must be a POSITIVE list, never a negated terminal set: statuses are "
        f"written VERBATIM from the engine, so an unknown FUTURE status must fail OPEN (not "
        f"a candidate) rather than be swept as an orphan. got: {indexdef}"
    )


# ===========================================================================
# Test 3 — THE load-bearing one: the heartbeat is UNCONDITIONAL
# ===========================================================================

def test_the_heartbeat_is_stamped_on_a_tick_that_carries_no_optional_field(monkeypatch):
    """A metrics dict of ONLY ``{"status": "running"}`` must still stamp the heartbeat.

    This is the mistake the implementation invites: every OTHER value in ``mirror_tick``'s
    dict is mirrored FROM the seam and is skipped when absent, so the natural thing is to
    gate the new one the same way. A gated implementation passes every happy-path test in
    the suite and fails only here — and in production it makes a driver that is alive but
    receiving sparse metrics look DEAD, at which point the sweep "recovers" a run that was
    never lost, at ~$45 a time.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(_superadmin(), uuid.uuid4(), "trib-1", {"status": "running"})

    assert calls, "the mirror write never happened"
    values = calls[-1]
    assert "driver_heartbeat_at" in values, (
        "`driver_heartbeat_at` was not patched for a metrics dict with no optional "
        "fields — it must be asserted by the driver about itself, never mirrored from "
        f"the seam. patched: {sorted(values)}"
    )
    assert values["driver_heartbeat_at"] is not None
    assert values["driver_heartbeat_at"].tzinfo is not None, (
        "the heartbeat must be timezone-aware — a naive value lands in a timestamptz "
        "column re-interpreted in the server's zone, which is a silent hour-scale error "
        "in exactly the comparison the sweep makes"
    )
    # The control: the seam-mirrored optionals really WERE absent, so the assertion above
    # is not passing because this tick happened to carry them.
    for absent in (
        "current_stage", "stage_detail", "cost_usd_total", "started_at", "completed_at",
    ):
        assert absent not in values, (
            f"{absent} must not be patched when the tick omits it — the present-only rule "
            f"for seam-mirrored fields is unchanged by this plan: {values}"
        )


# ===========================================================================
# Test 4 — the heartbeat MOVES (this is what separates it from created_at)
# ===========================================================================

def test_the_heartbeat_strictly_increases_between_ticks(monkeypatch):
    """Two ticks a measurable interval apart produce a strictly increasing value.

    The D-E defect in one assertion: ``created_at`` and ``started_at`` are stamped once and
    never move, so "35 minutes since that timestamp" says nothing about whether the process
    is alive. A liveness signal is the one that MOVES. The second half of this test proves
    the value is not simply one of the seam's own timestamps copied across.
    """
    calls = _capture_repo_patch(monkeypatch)
    rid = uuid.uuid4()

    run_task.mirror_tick(
        _superadmin(), rid, "trib-1", {"status": "running", "started_at": _STARTED_ISO}
    )
    time.sleep(0.05)
    run_task.mirror_tick(
        _superadmin(), rid, "trib-1", {"status": "running", "started_at": _STARTED_ISO}
    )

    assert len(calls) == 2, f"expected two mirror writes, got {len(calls)}"
    first = calls[0]["driver_heartbeat_at"]
    second = calls[1]["driver_heartbeat_at"]
    assert second > first, (
        "the heartbeat must STRICTLY increase between ticks — a value that does not move "
        "is a creation timestamp wearing a liveness name, which is precisely the D-E "
        f"defect (first={first!r} second={second!r})"
    )
    # NOT the engine's clock: both ticks carried the same seam start time, and the
    # heartbeat is neither equal to it nor derived from it.
    assert calls[0]["started_at"] == _STARTED_DT, "the seam timestamp must still mirror"
    assert first != _STARTED_DT and first > _STARTED_DT, (
        "the heartbeat is the DRIVER's assertion about itself at the moment it ticked — "
        f"never a copy of a seam timestamp (heartbeat={first!r} seam={_STARTED_DT!r})"
    )


# ===========================================================================
# Test 5 — the actor round-trips: trigger stamps it, resume DISPLACES it
# ===========================================================================

def test_the_acting_identity_round_trips_through_trigger_and_resume(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """The triggering human lands on the row; a DIFFERENT resuming human replaces them.

    A resume is a NEW human action on the same row. If the row kept the original triggerer,
    a later sweep would replay the wrong person's attribution across a legally load-bearing
    audit seam — and the D-10 completion mail would go to someone who did not ask for it.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="decomposed")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        _no_driver(monkeypatch)

        # ---- trigger ------------------------------------------------------
        triggerer = _superadmin()
        app.dependency_overrides[get_current_identity] = _as(triggerer)
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, (
            f"expected 202, got {resp.status_code} ({resp.text!r})"
        )

        run_id = _only_run_id(engine, set_space, space, intake_id)
        actor = _read_actor(engine, set_space, space, run_id)
        assert actor["acting_user_id"] == triggerer.uid, (
            "the trigger must persist the acting uid IN THE SAME INSERT that creates the "
            "row — a follow-up patch is a window in which the driver can start against a "
            f"row with no actor. got {actor!r}"
        )
        assert actor["acting_email"] == triggerer.email, actor

        # ---- resume, by somebody else -------------------------------------
        # A parked run in its own intake, seeded carrying the TRIGGERER, so the assertion
        # below is about displacement and not merely about "something got written".
        resume_intake = uuid.uuid4()
        resume_run = uuid.uuid4()
        _seed_intake(engine, set_space, space, resume_intake, status="in_research")
        _seed_parked_run(
            engine, set_space, space, resume_intake, resume_run,
            actor_uid=triggerer.uid, actor_email=triggerer.email,
        )

        resume_calls: list = []

        def _fake_resume(**kwargs):
            resume_calls.append(kwargs)
            return {"id": kwargs.get("run_id"), "status": "queued"}

        monkeypatch.setattr(
            research_mod.tribunal_client, "resume_run", _fake_resume, raising=False
        )
        monkeypatch.setattr(
            research_mod, "read_brief_inputs",
            lambda identity, iid: {
                "intake": {"id": str(iid)},
                "questions": [],
                "decomposition": {},
                "context_pack_text": None,
            },
            raising=False,
        )
        monkeypatch.setattr(
            research_mod.brief_mod, "validated_questions", lambda i, q: ["Q1"],
            raising=False,
        )
        monkeypatch.setattr(
            research_mod.brief_mod, "assemble_brief", lambda *a, **k: "brief text",
            raising=False,
        )

        resumer = _other_superadmin()
        assert resumer.uid != triggerer.uid and resumer.email != triggerer.email
        app.dependency_overrides[get_current_identity] = _as(resumer)
        r = TestClient(app).post(
            f"/intakes/{resume_intake}/research/resume",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 202, f"expected 202, got {r.status_code} ({r.text!r})"
        assert len(resume_calls) == 1, "the resume must make exactly one seam call"

        after = _read_actor(engine, set_space, space, resume_run)
        assert after["acting_user_id"] == resumer.uid, (
            "a resume is a NEW human action — the row must carry whoever resumed it, not "
            f"whoever triggered it hours earlier. got {after!r}"
        )
        assert after["acting_email"] == resumer.email, after
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Test 6 — no actor, no invention
# ===========================================================================

def test_a_trigger_without_an_email_stores_null_and_says_so(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """``Identity.email`` is ``str | None``. A missing one stores NULL — never a placeholder.

    A fabricated address on a legally load-bearing attribution chain is worse than a
    skipped sweep: plan 05's reconciler must SKIP such a row rather than call a seam that
    answers 400 for an empty header. The WARNING exists so the gap is visible BEFORE it
    matters, which is the only moment it is cheap.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="decomposed")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        _no_driver(monkeypatch)
        logged = _capture_route_log(monkeypatch)

        actor = _superadmin_without_email()
        assert actor.email is None, "the fixture must actually carry no email"
        app.dependency_overrides[get_current_identity] = _as(actor)
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, (
            f"expected 202, got {resp.status_code} ({resp.text!r})"
        )

        run_id = _only_run_id(engine, set_space, space, intake_id)
        row = _read_actor(engine, set_space, space, run_id)
        assert row["acting_user_id"] == actor.uid, row
        assert row["acting_email"] is None, (
            "a missing email must store SQL NULL — not '', not a placeholder address. An "
            "invented actor corrupts the D-05 attribution the reconciler exists to replay. "
            f"got {row['acting_email']!r}"
        )

        assert any(str(run_id) in line for line in logged), (
            "the missing email must be logged at WARNING naming the run id — a silent gap "
            f"is one nobody finds until a sweep needs the address. Seen: {logged}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Test 7 — COMPARABILITY GUARD (expected GREEN at HEAD, and still green after)
# ===========================================================================

def test_a_full_trigger_mirror_finalize_cycle_reaches_the_same_terminal(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """The whole point of this plan is that NOTHING existing changes.

    Deliberately NOT a defect gate: this passes at HEAD and must go on passing. 23.3-CONTEXT
    § 9 forbids any plan in this phase from altering what a run produces, so the assertion
    is on the values the operator actually consumes — the terminal status, the persisted
    report body, the chain verdict and the materialized bundle key.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="decomposed")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 202, (
            f"expected 202, got {resp.status_code} ({resp.text!r})"
        )

        # BackgroundTasks flush after the response → the REAL driver drove the REAL
        # mirror_tick and the REAL completion path against the fake seam.
        assert fake_tribunal_client["create_run"], "the poll driver must call create_run"

        final = _read_terminal(engine, set_space, space, intake_id)
        assert final["status"] == "completed", (
            f"the default metrics script ends in the 'completed' terminal, carried VERBATIM "
            f"(never the skill-run 'succeeded'). got {final!r}"
        )
        assert final["output_markdown"] == "fake report", (
            f"the report body must still be persisted from the SAME fetch (A4). got "
            f"{final['output_markdown']!r}"
        )
        assert final["chain_status"] == "verified", final
        assert final["bundle_key"], (
            "a verified chain must still materialize the bundle exactly once. got "
            f"{final['bundle_key']!r}"
        )
        assert final["bundle_key"].startswith(f"{space}/{intake_id}/artifacts/"), (
            f"the bundle key must stay server-authored and space-scoped (D-05). got "
            f"{final['bundle_key']!r}"
        )
        assert len(fake_gcs["uploads"]) == 1, (
            f"exactly one bundle upload per completed run. got {len(fake_gcs['uploads'])}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
