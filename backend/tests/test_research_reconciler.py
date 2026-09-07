"""23.3-05 — the orphaned-run reconciler, proven against a KILLED driver.

``run_poll_driver`` is a ``while True`` inside a FastAPI ``BackgroundTask`` with no
wall-clock cap. When its nestor-api instance recycles, the driver dies silently: the engine
keeps executing and spending, ``research_runs`` is never mirrored or finalized, and nothing
sweeps it (DEF-23.2-03, 23.3-CONTEXT.md § 8). ``app/research/reconcile.py`` is the sweep
that closes it. This file is its proof.

Five things this file is careful about, each because the cheap version of the test would be
green and worthless:

1. **The driver is genuinely KILLED, not simulated absent** (§ 12 item 3). Test 1 starts a
   REAL ``run_poll_driver`` against a fake seam, watches it write two real mirror ticks, and
   then kills it with a ``BaseException`` — which ``run_with_session_release`` does NOT route
   to ``on_error``, so the row is left non-terminal exactly as an instance recycle leaves it.
   A plain ``Exception`` would have finalized the row ``failed``, i.e. the OPPOSITE of an
   orphan, and the test would have proved nothing.
2. **The two sweeps are genuinely concurrent** (trap 6). Test 2 holds sweep A INSIDE its
   claim transaction — after the UPDATE has taken the row lock, before COMMIT — and runs
   sweep B's ENTIRE claim in that window. A test that runs A to completion and then B passes
   on a broken implementation.
3. **Time is moved in the DATABASE, never in Python.** The claim's predicate is evaluated by
   Postgres, so a mocked Python clock would not move it and every one of these tests would
   pass for the wrong reason. Heartbeats are REWOUND with SQL.
4. **The cutoff is pinned against the driver's own budget.** A live driver is legitimately
   silent for up to 600 s while it tolerates a 401/403 rollout. Test 3 pins a 9-minute-silent
   row as NOT a candidate; test 9 pins the RELATIONSHIP between the two constants so they
   cannot drift apart in separate commits.
5. **``pytestmark = pytest.mark.integration``** because the only committed backend gate is
   ``cloudbuild.test.yaml``'s ``pytest tests -m integration``. Without the marker these
   proofs would be collected and then DESELECTED — green because they ran nothing.

ZERO PROVIDER SPEND: every seam is a fake. No test here reaches a real provider, a real
bucket, or the real Tribunal service.
"""

from __future__ import annotations

import threading
import uuid

import pytest

pytestmark = pytest.mark.integration

# External deps — skip-clean when not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")
run_task = pytest.importorskip("app.research.run_task")
reconcile = pytest.importorskip("app.research.reconcile")
tribunal_client = pytest.importorskip("app.research.tribunal_client")

Identity = identity_mod.Identity

SCHEMA = "nestor"
TABLE = "research_runs"

_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only

_ACTOR_UID = "super-orphan"
_ACTOR_EMAIL = "orphan@agenic.be"

#: Every outcome word :func:`reconcile.reconcile_one` is allowed to return. Test 8 asserts
#: membership rather than a specific value, because the POINT there is "an outcome string
#: came back instead of an exception going up".
_OUTCOMES = frozenset(
    {
        "mirrored",
        "finalized",
        "skipped_no_actor",
        "skipped_no_engine_run",
        "skipped_lost_cas",
        "error",
    }
)


# ---------------------------------------------------------------------------
# Fixtures / plumbing (shapes copied from test_research_run_reconciler_columns.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Collapse the driver's inter-tick sleep so test 1 finishes in milliseconds.

    ``_MAX_METRICS_AUTH_OUTAGE_SECONDS`` is bound at IMPORT time precisely so this
    collapse cannot rewrite the number test 9 asserts on — see ``run_task``'s comment.
    """
    monkeypatch.setattr(run_task, "POLL_SECONDS", 0.0)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (the D-05 two-engine routing).

    The claim runs cross-space with NO GUC, so the 0011 ``research_runs_superadmin_all``
    policy (``current_user = 'app_superadmin'``) is the thing that admits it. A test that
    ran the claim as the owner would be testing a different statement.
    """
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


def _patch_engines(monkeypatch, user_engine, sa_engine) -> None:
    """Route every engine lookup the sweep and the driver make onto the test container."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    # ONE patch covers both the sweep's claim and every tenant_session write: the claim
    # goes through ``ai_session.superadmin_session``, which is where the D-03 seam
    # constructs engines. Nothing in app/research/ fetches an engine of its own — see
    # scripts/ci_no_raw_db_access.sh.
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


def _superadmin() -> "Identity":
    return Identity(uid=_ACTOR_UID, email=_ACTOR_EMAIL, role="superadmin", space_id=None)


# ---------------------------------------------------------------------------
# Seeding + reading
# ---------------------------------------------------------------------------

def _seed_space(engine, space_id, name="Reconciler space") -> None:
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
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
                "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status), :name)"
            ),
            {"id": intake_id, "space_id": space_id, "status": status, "name": "Acme"},
        )


def _seed_run(
    engine,
    set_space,
    space_id,
    intake_id,
    run_id,
    *,
    status="running",
    tribunal_run_id="trib-1",
    actor_uid=_ACTOR_UID,
    actor_email=_ACTOR_EMAIL,
    heartbeat_minutes_ago=None,
    bundle_key=None,
    output_markdown=None,
    chain_status=None,
) -> None:
    """Insert ONE research_runs row.

    ``heartbeat_minutes_ago`` is applied by Postgres (``NOW() - make_interval(...)``), never
    by a Python clock: the claim's predicate is evaluated by the database, so a Python-side
    value would be comparing the wrong two things.
    """
    from sqlalchemy import text

    heartbeat = (
        "NULL"
        if heartbeat_minutes_ago is None
        else f"NOW() - make_interval(mins => {int(heartbeat_minutes_ago)})"
    )
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(id, space_id, intake_id, status, tribunal_run_id, attempt, "
                " acting_user_id, acting_email, driver_heartbeat_at, bundle_key, "
                " output_markdown, chain_status) "
                f"VALUES (:id, :space_id, :intake_id, :status, :trid, 1, :uid, :email, "
                f"{heartbeat}, :bundle_key, :markdown, :chain)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "trid": tribunal_run_id,
                "uid": actor_uid,
                "email": actor_email,
                "bundle_key": bundle_key,
                "markdown": output_markdown,
                "chain": chain_status,
            },
        )


def _rewind_heartbeat(engine, set_space, space_id, run_id, minutes) -> None:
    """Move the driver's liveness stamp back IN THE DATABASE, standing in for wall clock."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        rowcount = conn.execute(
            text(
                f"UPDATE {SCHEMA}.{TABLE} "
                "SET driver_heartbeat_at = NOW() - make_interval(mins => :m) "
                "WHERE id = :id"
            ),
            {"m": int(minutes), "id": run_id},
        ).rowcount
    assert rowcount == 1, (
        "the rewind matched no row — every later assertion in this test would be about a "
        "row whose heartbeat was never moved, which is a setup failure, not a pass"
    )


def _read_run(engine, set_space, space_id, run_id) -> dict:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(f"SELECT * FROM {SCHEMA}.{TABLE} WHERE id = :id"), {"id": run_id}
        ).one()
    return dict(row._mapping)


def _cleanup(engine, *space_ids) -> None:
    from sqlalchemy import text

    for space_id in space_ids:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
            )
        # audit_log is deliberately NOT space-cascaded (0006, D-07).
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
            )


def _claimed_ids(rows) -> set:
    return {r["id"] for r in rows}


def _pick(rows, run_id) -> dict:
    for row in rows:
        if row["id"] == run_id:
            return row
    raise AssertionError(
        f"the sweep did not claim {run_id} — claimed {_claimed_ids(rows)!r}. Every "
        "assertion below would be about a row that was never taken, which is a setup "
        "failure, not a pass"
    )


# ---------------------------------------------------------------------------
# Seam control
# ---------------------------------------------------------------------------

class _Seam:
    """A ``get_metrics`` fake whose answer and whose failure mode the test steers.

    Counts calls so the "ZERO seam calls" assertions (test 6) are assertions about an
    observed number rather than about the absence of a side effect nobody looked for.
    """

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.raise_after = None      # kill the driver on the Nth call (BaseException)
        self.explode_with = None     # raise this on EVERY call

    def get_metrics(self, *args, **kwargs):
        self.calls += 1
        if self.explode_with is not None:
            raise self.explode_with
        if self.raise_after is not None and self.calls >= self.raise_after:
            raise _InstanceRecycled("instance recycled mid-run")
        return dict(self.payload) if isinstance(self.payload, dict) else self.payload


class _InstanceRecycled(BaseException):
    """A KILL, not an error — and the distinction is the whole point of test 1.

    ``run_with_session_release`` catches ``Exception`` and routes it to ``on_error``, which
    finalizes the row to EXACTLY ``failed``. A test that killed the driver with a plain
    ``Exception`` would therefore end with a TERMINAL row — the opposite of an orphan — and
    the sweep would have nothing to find. A ``BaseException`` escapes that handler the way a
    recycled container escapes it: ``run_poll_driver``'s outermost ``except BaseException``
    logs CRASHED and the row is left exactly where the last mirror tick put it.
    """


def _install_seam(monkeypatch, seam) -> None:
    """Patch the module attribute, so BOTH the driver and the sweep see the same fake."""
    monkeypatch.setattr(tribunal_client, "get_metrics", seam.get_metrics)


# ===========================================================================
# Test 1 — KILL the driver, then let the sweep finish its run
# ===========================================================================

def test_a_killed_drivers_run_is_finalized_by_the_sweep(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """§ 12 item 3, in full: the driver is KILLED, not simulated absent.

    A real ``run_poll_driver`` runs in a thread against a fake seam reporting ``running``,
    writes two real mirror ticks (asserted: ``driver_heartbeat_at`` MOVED, so the driver was
    provably alive and this is not a test about an empty row), and is then killed without
    finalizing. The heartbeat is rewound past the cutoff to stand in for wall clock, the seam
    flips to ``completed``, and ``sweep_once()`` must carry the run to its terminal state —
    with the ORIGINAL human's address on the mail.
    """
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(engine, set_space, space, intake_id, run_id, status="queued")
        _patch_engines(monkeypatch, engine, superadmin_engine)

        seam = _Seam({"status": "running", "current_stage": "delegation"})
        seam.raise_after = 3  # two full ticks, then the instance goes away
        _install_seam(monkeypatch, seam)

        # Record the heartbeat the REAL mirror_tick actually persisted, per tick.
        real_mirror = run_task.mirror_tick
        beats: list = []

        def _spy_mirror(identity, research_run_id, tribunal_run_id, metrics):
            real_mirror(identity, research_run_id, tribunal_run_id, metrics)
            beats.append(_read_run(engine, set_space, space, run_id)["driver_heartbeat_at"])

        monkeypatch.setattr(run_task, "mirror_tick", _spy_mirror)

        driver = threading.Thread(
            target=run_task.run_poll_driver,
            args=(_superadmin(), intake_id, run_id, "brief text", 1),
            name="poll-driver",
        )
        driver.start()
        driver.join(timeout=60)

        # ---- the driver was ALIVE, and then it was GONE --------------------------
        assert not driver.is_alive(), (
            "the poll driver thread is still running, so anything the sweep does below "
            "would be a race with a LIVE driver — this test would prove the opposite of "
            "what it claims"
        )
        assert len(beats) >= 2, (
            f"the driver must have written at least two mirror ticks before it was killed; "
            f"got {len(beats)}. Without them there is no evidence it was ever alive"
        )
        assert beats[1] > beats[0], (
            "driver_heartbeat_at did not MOVE between ticks — a liveness signal that does "
            f"not move is a creation timestamp wearing a liveness name ({beats[0]!r} -> "
            f"{beats[1]!r})"
        )
        mid = _read_run(engine, set_space, space, run_id)
        assert mid["status"] == "running", (
            f"the killed driver must leave the row NON-terminal (that is what an orphan "
            f"IS); got status={mid['status']!r}. If this says 'failed', the kill went "
            f"through on_error and this is not an orphan test"
        )
        assert mid["completed_at"] is None, mid

        # restore the real mirror before the sweep, so the sweep exercises production code
        monkeypatch.setattr(run_task, "mirror_tick", real_mirror)

        # ---- wall clock passes; the engine finishes without anyone watching ------
        _rewind_heartbeat(engine, set_space, space, run_id, ORPHANED := 20)
        assert ORPHANED > reconcile.ORPHAN_CUTOFF_MINUTES
        seam.raise_after = None
        seam.payload = {
            "status": "completed",
            "current_stage": "report",
            "cost_usd_total": 24.78,
            "elapsed_seconds": 3600,
        }
        fake_resend["calls"].clear()

        counts = reconcile.sweep_once()

        assert counts["finalized"] == 1, (
            f"the sweep must have finalized exactly the orphaned run; got {counts!r}"
        )
        final = _read_run(engine, set_space, space, run_id)
        assert final["status"] == "completed", (
            f"the terminal status is carried VERBATIM across the seam (D-05) — never the "
            f"skill-run 'succeeded'. got {final['status']!r}"
        )
        assert final["completed_at"] is not None, final
        assert final["output_markdown"] == "fake report", (
            f"the sweep must persist the report from the same fetch the bundle used (A4). "
            f"got {final['output_markdown']!r}"
        )
        assert final["chain_status"] == "verified", final
        assert final["bundle_key"], "a verified chain must materialize the bundle"
        assert final["reconcile_lease_until"] is None, (
            "the winner must release its lease in the same write that finalized the row; a "
            f"lease left behind blocks nothing but lies about who owns the run: {final!r}"
        )

        assert len(fake_resend["calls"]) == 1, (
            f"exactly one completion mail for a finalized run; got "
            f"{[c['subject'] for c in fake_resend['calls']]!r}"
        )
        mail = fake_resend["calls"][0]
        assert mail["to"] == [_ACTOR_EMAIL], (
            "the mail must go to the ORIGINAL human recorded on the row — the sweep has no "
            f"identity of its own and must never invent one. got {mail['to']!r}"
        )
        assert mail["subject"] == "Je onderzoek is klaar", mail["subject"]
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 2 — two sweeps, held at a REAL barrier, claim disjoint sets
# ===========================================================================

class _ClaimBarrier:
    """Holds sweep A INSIDE its claim transaction so sweep B runs in that window.

    ⚠ WHY NOT THE ``pg_stat_activity`` "wait until N backends are blocked" idiom from
    ``tribunal/nestor_pulse_sdk/tests/test_run_state_cas.py``: that barrier works because
    the statements under test BLOCK on a row lock. This claim uses ``FOR UPDATE SKIP
    LOCKED``, whose entire purpose is NOT to block — a third connection holding the
    candidate row would make BOTH sweeps skip it and claim nothing, and the test would
    "pass" against an implementation with no serialisation at all. So the interleaving is
    built the other way round: A itself is the lock holder, and B's ENTIRE claim executes
    between A's UPDATE and A's COMMIT.

    The self-check is the same one the tribunal barrier makes and for the same reason: if A
    did not really lock the row, this is a setup failure, not a pass.
    """

    THREAD = "sweep-A"

    def __init__(self):
        self.executed = threading.Event()
        self.release = threading.Event()

    def install(self, monkeypatch, sa_engine) -> None:
        from sqlalchemy.orm import Session, sessionmaker

        barrier = self

        class _PausingSession(Session):
            def execute(self, *args, **kwargs):
                result = super().execute(*args, **kwargs)
                if threading.current_thread().name == barrier.THREAD:
                    barrier.executed.set()
                    assert barrier.release.wait(timeout=60), (
                        "sweep A was never released — the test deadlocked rather than "
                        "measured anything"
                    )
                return result

        # Patched on the SEAM (``app.db.ai_session``), because that is where the session
        # the claim runs in is constructed — ``app/research/`` never builds one (D-03).
        monkeypatch.setattr(
            ai_session_mod,
            "get_sessionmaker",
            lambda eng=None: sessionmaker(
                eng if eng is not None else sa_engine,
                class_=_PausingSession,
                expire_on_commit=False,
                future=True,
            ),
        )


def _assert_row_locked(engine, set_space, space_id, run_id) -> None:
    """The barrier self-check: the row is VISIBLE but NOT lockable, i.e. A holds it."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        visible = conn.execute(
            text(f"SELECT id FROM {SCHEMA}.{TABLE} WHERE id = :id"), {"id": run_id}
        ).first()
        assert visible is not None, (
            "the probe cannot even SEE the row, so 'it is locked' would be indistinguishable "
            "from 'RLS hid it' — this is a setup failure, not a pass"
        )
        free = conn.execute(
            text(
                f"SELECT id FROM {SCHEMA}.{TABLE} WHERE id = :id FOR UPDATE SKIP LOCKED"
            ),
            {"id": run_id},
        ).first()
    assert free is None, (
        "sweep A is NOT holding a row lock on the candidate, so sweep B below would run "
        "against an unclaimed row and this test would degenerate into 'A then B' — which "
        "passes on an implementation with no serialisation at all. Setup failure, not a pass"
    )


def test_two_concurrent_sweeps_claim_disjoint_sets(
    engine, set_space, monkeypatch, superadmin_engine,
):
    """Exactly ONE sweep claims the row; the other claims zero — and the lease holds after.

    Two mechanisms, both required, both exercised here:

    * ``FOR UPDATE SKIP LOCKED`` covers the instant of claiming — B runs while A's
      transaction is still open (the barrier proves the lock is genuinely held);
    * the LEASE covers everything afterwards — a THIRD claim, issued after A has committed
      and its row lock is long gone, must still find nothing.
    """
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    barrier = _ClaimBarrier()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id, heartbeat_minutes_ago=30
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        barrier.install(monkeypatch, superadmin_engine)

        a_rows: list = []

        def _sweep_a():
            a_rows.extend(reconcile.claim_orphans())

        thread_a = threading.Thread(target=_sweep_a, name=_ClaimBarrier.THREAD)
        thread_a.start()
        try:
            assert barrier.executed.wait(timeout=30), (
                "sweep A never reached its claim UPDATE — nothing was interleaved"
            )
            # A's UPDATE has run and A has NOT committed. Prove it, then run B entirely
            # inside that window.
            _assert_row_locked(engine, set_space, space, run_id)
            b_rows = reconcile.claim_orphans()
        finally:
            barrier.release.set()
            thread_a.join(timeout=60)

        assert not thread_a.is_alive(), "sweep A never finished"

        assert run_id in _claimed_ids(a_rows), (
            f"sweep A held the row lock, so it must be the winner; it claimed "
            f"{_claimed_ids(a_rows)!r}"
        )
        assert run_id not in _claimed_ids(b_rows), (
            "sweep B claimed the SAME run while sweep A held it uncommitted. Two instances "
            "mirroring one run concurrently is the defect this phase must not introduce "
            f"(23.3-CONTEXT § 8). B claimed {_claimed_ids(b_rows)!r}"
        )

        # ---- and the lease keeps them disjoint AFTER the lock is gone -------------
        c_rows = reconcile.claim_orphans()
        assert run_id not in _claimed_ids(c_rows), (
            "a third sweep took the row after A committed. SKIP LOCKED only covers the "
            "instant of claiming; the 5-minute lease is what covers the seam call that "
            f"follows it. C claimed {_claimed_ids(c_rows)!r}"
        )
        row = _read_run(engine, set_space, space, run_id)
        assert row["reconcile_lease_until"] is not None, (
            f"the winner must have written a lease; got {row['reconcile_lease_until']!r}"
        )
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 3 — a LIVE driver is never swept (the most expensive possible mistake)
# ===========================================================================

def test_a_driver_silent_for_nine_minutes_is_not_a_candidate(
    engine, set_space, monkeypatch, superadmin_engine,
):
    """9 minutes of silence is HEALTH, not death — it is inside the driver's own budget.

    A live poll driver ``continue``s round its loop WITHOUT calling ``mirror_tick`` for up
    to ``_MAX_METRICS_AUTH_OUTAGE_SECONDS`` (600 s = 10 min) while it tolerates a 401/403
    from a Cloud Run revision rollout. The sweep's response to an orphan is to TAKE THE RUN
    OVER, so a cutoff regression to 5 or 10 minutes would seize healthy, paid runs. This
    test fails on any such regression.

    Two assertions, because an implementation that CLAIMS and then decides to skip has still
    taken the lease and still locked out the real driver's own recovery.

    The positive control (a 30-minute-silent row in a different intake IS claimed) is what
    stops this from passing vacuously against a claim that returns nothing at all.
    """
    space = uuid.uuid4()
    live_intake, dead_intake = uuid.uuid4(), uuid.uuid4()
    live_run, dead_run = uuid.uuid4(), uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, live_intake)
        _seed_intake(engine, set_space, space, dead_intake)
        _seed_run(
            engine, set_space, space, live_intake, live_run, heartbeat_minutes_ago=9
        )
        _seed_run(
            engine, set_space, space, dead_intake, dead_run, heartbeat_minutes_ago=30
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)

        claimed = reconcile.claim_orphans()

        assert live_run not in _claimed_ids(claimed), (
            "a driver silent for 9 minutes was claimed as an orphan. That is INSIDE its own "
            f"600 s auth-outage budget, so ORPHAN_CUTOFF_MINUTES "
            f"({reconcile.ORPHAN_CUTOFF_MINUTES}) has regressed below 10 and the sweep is "
            "now seizing live, paid runs"
        )
        assert dead_run in _claimed_ids(claimed), (
            "the positive control was not claimed either, so the assertion above proves "
            f"nothing about the cutoff. claimed={_claimed_ids(claimed)!r}"
        )

        live_row = _read_run(engine, set_space, space, live_run)
        assert live_row["reconcile_lease_until"] is None, (
            "the live run's lease was taken. An implementation that claims first and skips "
            "afterwards has still locked the row for LEASE_MINUTES and still lied about "
            f"who owns it: {live_row['reconcile_lease_until']!r}"
        )
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 4 — the run the driver finished first is left alone (no second mail)
# ===========================================================================

def test_a_run_the_driver_finalized_first_yields_a_lost_cas_and_no_mail(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """The live driver wins; the sweep must notice IN THE DATABASE and write nothing.

    The row is claimed, then finalized out from under the sweep exactly as a live driver
    would, and only then does ``reconcile_one`` reach its write. A read-then-write
    implementation — even inside one transaction, under READ COMMITTED — sends a SECOND
    completion mail and writes a second terminal on a run that cost ~$45. ``patch_if`` puts
    the precondition in the same UPDATE's WHERE, which is the D-23.1-05 guarantee.

    The mail spy's call count being 0 is the assertion a rollback-free implementation fails.

    (A bundle may be built and then discarded on this path — the ``bundle_key`` guard reads
    the value as it was AT CLAIM TIME. That costs no provider spend and no mail; what must
    never double is the terminal WRITE and the notification, and both are asserted here.)
    """
    from sqlalchemy import text

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id, heartbeat_minutes_ago=30
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        _install_seam(monkeypatch, _Seam({"status": "completed", "cost_usd_total": 1.5}))

        row = _pick(reconcile.claim_orphans(), run_id)

        # ---- the live driver gets there first --------------------------------------
        with engine.begin() as conn:
            set_space(conn, space)
            conn.execute(
                text(
                    f"UPDATE {SCHEMA}.{TABLE} SET status = 'completed', "
                    "completed_at = NOW(), output_markdown = :md, "
                    "chain_status = 'verified', bundle_key = :key WHERE id = :id"
                ),
                {
                    "md": "the driver's own report",
                    "key": "driver/own/bundle.zip",
                    "id": run_id,
                },
            )
        fake_resend["calls"].clear()

        outcome = reconcile.reconcile_one(row)

        assert outcome == "skipped_lost_cas", (
            f"the sweep must lose the compare-and-swap against the driver's terminal "
            f"write; got {outcome!r}"
        )
        assert len(fake_resend["calls"]) == 0, (
            "a SECOND completion mail was sent for a run the driver already finished and "
            f"already mailed about: {[c['subject'] for c in fake_resend['calls']]!r}"
        )
        after = _read_run(engine, set_space, space, run_id)
        assert after["output_markdown"] == "the driver's own report", (
            f"the driver's values must survive untouched; got "
            f"{after['output_markdown']!r}"
        )
        assert after["bundle_key"] == "driver/own/bundle.zip", after
        assert after["status"] == "completed", after
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 5 — an already-materialized bundle is never rebuilt
# ===========================================================================

def test_an_existing_bundle_is_not_rebuilt(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """``build_completion`` is not called at all, and the existing values survive.

    Rebuilding would re-run ``verify_chain``, re-fetch the report and re-upload to GCS for
    nothing. The spy asserting ZERO calls is the point; the second half asserts the thing an
    over-eager "reuse the finalize path" implementation gets wrong — writing NULL over a
    persisted report, chain verdict and bundle key because it had no completion dict to
    hand.
    """
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id,
            heartbeat_minutes_ago=30,
            bundle_key="already/built/bundle.zip",
            output_markdown="the report that already exists",
            chain_status="verified",
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        _install_seam(monkeypatch, _Seam({"status": "completed", "cost_usd_total": 2.0}))

        builds: list = []

        def _spy_build(*args, **kwargs):
            builds.append(args)
            raise AssertionError("build_completion must not run for an existing bundle")

        monkeypatch.setattr(run_task, "build_completion", _spy_build)

        row = _pick(reconcile.claim_orphans(), run_id)
        outcome = reconcile.reconcile_one(row)

        assert len(builds) == 0, (
            "build_completion was called for a run whose bundle_key was already set — that "
            "re-runs verify_chain, re-fetches the report and re-uploads to GCS for nothing"
        )
        assert len(fake_gcs["uploads"]) == 0, (
            f"nothing may be uploaded on this path; got {len(fake_gcs['uploads'])} uploads"
        )
        assert outcome == "finalized", f"the run must still reach its terminal; got {outcome!r}"

        after = _read_run(engine, set_space, space, run_id)
        assert after["status"] == "completed", after
        assert after["bundle_key"] == "already/built/bundle.zip", (
            f"the existing bundle key must survive; got {after['bundle_key']!r}"
        )
        assert after["output_markdown"] == "the report that already exists", (
            "the persisted report was overwritten (with NULL, most likely) by a finalize "
            f"that had no report to write: {after['output_markdown']!r}"
        )
        assert after["chain_status"] == "verified", (
            f"the chain verdict was overwritten: {after['chain_status']!r}"
        )
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 6 — no recorded actor, no invented one, and no seam call at all
# ===========================================================================

def test_a_run_with_no_actor_is_skipped_and_makes_zero_seam_calls(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """A NULL ``acting_email`` is skipped loudly — never papered over with a placeholder.

    The Tribunal seam REQUIRES both acting headers and answers 400 without them, because
    D-05 attribution is a hard legal constraint on a FROZEN audit chain. So the only correct
    move is to skip and say so. **The seam spy recording ZERO calls is the assertion that
    catches a placeholder address**: an implementation that substituted one would call the
    seam happily and this counter would read 1.
    """
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id,
            heartbeat_minutes_ago=30, actor_email=None,
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        seam = _Seam({"status": "completed"})
        _install_seam(monkeypatch, seam)

        row = _pick(reconcile.claim_orphans(), run_id)
        assert row["acting_email"] is None, row
        before = _read_run(engine, set_space, space, run_id)

        outcome = reconcile.reconcile_one(row)

        # The seam counter is asserted FIRST on purpose. Under the defect this test exists
        # to catch — an implementation that substitutes a placeholder address — the
        # informative failure is "the seam was called", not "the outcome word was wrong":
        # the outcome would then be whatever the invented call happened to produce, which
        # tells the next reader nothing about WHY.
        assert seam.calls == 0, (
            f"the seam was called {seam.calls} time(s) for a run with no actor. Either an "
            "actor was invented, or the 400 the seam answers for empty acting headers is "
            "being relied on as the guard — both are wrong"
        )
        assert outcome == "skipped_no_actor", (
            f"a row with no recorded human must be skipped by name; got {outcome!r}"
        )
        assert len(fake_resend["calls"]) == 0, fake_resend["calls"]
        assert _read_run(engine, set_space, space, run_id) == before, (
            "the row must be left exactly as the claim left it — a skipped run is one a "
            "human has to look at, and rewriting it hides that"
        )
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 7 — the sweep writes ONLY to the row it claimed
# ===========================================================================

def test_the_sweep_never_touches_another_spaces_row(
    engine, set_space, monkeypatch, superadmin_engine,
    fake_tribunal_client, fake_gcs, fake_resend,
):
    """Two orphans in two different spaces; reconciling one leaves the other byte-identical.

    The claim runs cross-space with no GUC by necessity — it cannot know which space a lost
    run belongs to until it reads the row — so "the writes address the claimed primary key
    only" is a property that has to be asserted rather than assumed.
    """
    space_a, space_b = uuid.uuid4(), uuid.uuid4()
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()
    run_a, run_b = uuid.uuid4(), uuid.uuid4()
    try:
        _seed_space(engine, space_a, name="Space A")
        _seed_space(engine, space_b, name="Space B")
        _seed_intake(engine, set_space, space_a, intake_a)
        _seed_intake(engine, set_space, space_b, intake_b)
        _seed_run(engine, set_space, space_a, intake_a, run_a, heartbeat_minutes_ago=30)
        _seed_run(engine, set_space, space_b, intake_b, run_b, heartbeat_minutes_ago=30)
        _patch_engines(monkeypatch, engine, superadmin_engine)
        _install_seam(monkeypatch, _Seam({"status": "completed", "cost_usd_total": 3.0}))

        claimed = reconcile.claim_orphans()
        row_a = _pick(claimed, run_a)
        _pick(claimed, run_b)  # both are candidates — the neighbour is genuinely reachable

        before_b = _read_run(engine, set_space, space_b, run_b)
        outcome = reconcile.reconcile_one(row_a)
        after_b = _read_run(engine, set_space, space_b, run_b)

        assert outcome == "finalized", outcome
        assert _read_run(engine, set_space, space_a, run_a)["status"] == "completed"
        assert after_b == before_b, (
            "reconciling space A's run changed space B's row. Differing columns: "
            f"{ {k: (before_b[k], after_b[k]) for k in before_b if before_b[k] != after_b[k]} }"
        )
    finally:
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# Test 8 — reconcile_one NEVER raises
# ===========================================================================

@pytest.mark.parametrize(
    "payload, explode",
    [
        (None, httpx.ConnectError("the seam is unreachable")),
        ({"status": 12345, "cost_usd_total": "not a number"}, None),
        ({}, None),
        ([], None),
    ],
    ids=["transport-error", "malformed-dict", "empty-dict", "not-a-dict"],
)
def test_reconcile_one_never_raises(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend, payload, explode,
):
    """Four failure shapes, four outcome STRINGS, zero exceptions.

    This runs on a timer over a BATCH of rows. An exception escaping here would kill the
    sweep for every other orphan in the batch — the sweep would itself become the thing that
    silently stops working, which is the failure it exists to end.
    """
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id, heartbeat_minutes_ago=30
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        seam = _Seam(payload)
        seam.explode_with = explode
        _install_seam(monkeypatch, seam)

        row = _pick(reconcile.claim_orphans(), run_id)
        outcome = reconcile.reconcile_one(row)

        assert outcome in _OUTCOMES, (
            f"reconcile_one must answer with one of {sorted(_OUTCOMES)}; got {outcome!r}"
        )
        assert len(fake_resend["calls"]) == 0, (
            f"nothing may be mailed about a run whose state could not be established: "
            f"{fake_resend['calls']!r}"
        )
    finally:
        _cleanup(engine, space)


def test_sweep_once_survives_a_row_that_fails(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend,
):
    """One bad row must not cost the batch: the sweep still tallies and still returns."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_run(
            engine, set_space, space, intake_id, run_id, heartbeat_minutes_ago=30
        )
        _patch_engines(monkeypatch, engine, superadmin_engine)
        seam = _Seam(None)
        seam.explode_with = httpx.ConnectError("the seam is unreachable")
        _install_seam(monkeypatch, seam)

        counts = reconcile.sweep_once()

        assert counts["claimed"] >= 1, counts
        assert counts["errors"] >= 1, counts
        assert set(counts) == {"claimed", "mirrored", "finalized", "skipped", "errors"}, (
            f"the tally shape is the sweep's only observable output; got {sorted(counts)}"
        )
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 9 — the two constants are a PAIR (DB-free source gate)
# ===========================================================================

def test_the_orphan_cutoff_exceeds_the_drivers_own_silence_budget():
    """Asserts on the NUMBERS from BOTH modules, so they cannot drift apart silently.

    ``run_task`` tolerates a 401/403 from a Cloud Run revision rollout for
    ``_MAX_METRICS_AUTH_RETRIES x POLL_SECONDS`` seconds and, throughout that window,
    ``continue``s WITHOUT calling ``mirror_tick`` — so a perfectly healthy driver writes no
    heartbeat for ten minutes. The sweep's answer to a missing heartbeat is to take the run
    over. Any change that raises one of these budgets without raising the other reintroduces
    exactly the incident the first one was sized from (2026-07-28).
    """
    outage = run_task._MAX_METRICS_AUTH_OUTAGE_SECONDS
    assert outage == 600.0, (
        f"the driver's tolerated auth outage changed to {outage}s. That is the number "
        f"ORPHAN_CUTOFF_MINUTES was derived from — re-derive it here, deliberately, rather "
        f"than letting this assertion be edited to match"
    )
    assert run_task._MAX_METRICS_AUTH_RETRIES == 200, run_task._MAX_METRICS_AUTH_RETRIES

    cutoff_seconds = reconcile.ORPHAN_CUTOFF_MINUTES * 60
    assert cutoff_seconds > outage, (
        f"ORPHAN_CUTOFF_MINUTES ({reconcile.ORPHAN_CUTOFF_MINUTES} min = {cutoff_seconds}s) "
        f"must EXCEED the driver's tolerated silence ({outage}s), or the sweep seizes live, "
        f"paid runs mid-rollout and duplicates their work at ~$45 each"
    )
    assert cutoff_seconds >= outage * 1.5, (
        f"the margin has been shaved to {cutoff_seconds / outage:.2f}x. 15 minutes against "
        f"600s is 1.5x by design — a cutoff that merely exceeds the budget leaves no room "
        f"for the write lag between the driver's last tick and its persisted heartbeat"
    )
    assert reconcile.LEASE_MINUTES * 60 > 30.0, (
        f"the lease ({reconcile.LEASE_MINUTES} min) must outlast one get_metrics call "
        f"(tribunal_client._TIMEOUT_S = 30s) or a sweep loses its own claim mid-call"
    )
