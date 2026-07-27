"""D-E — the stale reclaim must recover DEAD workers and never re-run LIVE ones.

Plan 15.2-20. These are SQL-LEVEL proofs: they seed rows directly and then run
`worker.CLAIM_SQL`, `worker.REAP_SQL` and `worker._HEARTBEAT_SQL` — the SAME
`text()` objects the production module exports — against a real Postgres. No
engine, no LLM, no provider stub, and no assertion on log text. The claim is
proven by the ROW it leaves behind, because that row is the only thing that
actually spends money.

Why this file exists
--------------------
On 2026-07-27 the first live run was aborted by killing the worker. That started
a fresh worker which was seconds from re-executing the same run at full cost,
unattended, because the run was older than `NESTOR_WORKER_STALE_MINUTES`. The
old rule measured staleness by `started_at`, which is stamped once at claim time
and never moves — so a live process holding a 35-minute deep-research long-poll
was indistinguishable from a process that died 35 minutes ago. The fix is
`run.heartbeat_at` (a real liveness signal) plus `run.reclaim_count` (a ceiling,
past which the run is FAILED rather than started again).

What each test proves

| Test | Proves | Threat |
|------|--------|--------|
| test_fresh_heartbeat_is_never_reclaimed | a live long-poll is never re-run, at any age | T-15.2-200 |
| test_dead_heartbeat_is_reclaimed_and_counted | a dead worker IS recovered, and only reclaims count | T-15.2-200 |
| test_reclaim_ceiling_stops_the_loop | past the ceiling the run is no longer claimable | T-15.2-200 |
| test_reap_fails_over_ceiling_runs_with_a_sentence | the run is failed WITH WORDS, never left silently running | T-15.2-203 |
| test_heartbeat_loop_writes_then_stops_on_cancel | the liveness writer works, and does not outlive its run | T-15.2-202 |

Harness
-------
Requires `DATABASE_URL` (a `postgresql+asyncpg://` DSN) pointing at a MIGRATED,
DISPOSABLE tribunal schema — `tribunal/cloudbuild.test-critical.yaml` is that
harness. The module runs `alembic upgrade head` itself so migration 0014 is
guaranteed present; it must NOT be pointed at production, because CLAIM_SQL and
REAP_SQL are run unmodified and will happily claim or reap any other claimable
row in the database.

**A SKIP IN THIS FILE IS NOT A PASS.** Both skip messages say so. This
repository has a documented history of gates that were green because they ran
nothing; if you are reading a build log, read the `collecting:` block and the
`-rs` skip summary, not the exit status.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration

_SDK_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Harness guards — both skip LOUDLY, never silently
# ---------------------------------------------------------------------------

def _require_database_url() -> str:
    """The DSN, or a loud skip that says a skip is not a pass."""
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql+asyncpg://"):
        pytest.skip(
            "DATABASE_URL is unset (or is not a postgresql+asyncpg:// DSN), so "
            "the D-E stale-reclaim proofs did NOT run. THIS IS NOT A PASS: the "
            "money defect these tests cover is unproven in this build. The "
            "harness that runs them faithfully is "
            "tribunal/cloudbuild.test-critical.yaml."
        )
    return url


@pytest.fixture
async def worker_db():
    """(sessionmaker, tenant_id, project_id) against a migrated tribunal schema.

    Skips CLEANLY and LOUDLY when there is no DSN, or when the connected role
    cannot reach `run` rows without a tenant context.

    The role guard is the mirror image of `test_rls_isolation.py`'s
    `require_non_superuser`: in production the claim, the reap and the heartbeat
    are all issued by the RLS-exempt `worker_user` role (policy `run_worker_all`,
    migration 0008). Under an ordinary `app_user` DSN the `run` row is invisible
    without `app.tenant_id`, so these statements would match zero rows and the
    tests would pass VACUOUSLY — asserting nothing while looking green. Skip
    loudly instead.
    """
    sa = pytest.importorskip("sqlalchemy")
    sa_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")
    url = _require_database_url()

    from alembic import command  # type: ignore
    from alembic.config import Config  # type: ignore

    alembic_ini = _SDK_ROOT / "alembic.ini"
    cfg = Config(str(alembic_ini)) if alembic_ini.exists() else Config()
    cfg.set_main_option("script_location", str(_SDK_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    from nestor_pulse_sdk.db import base as base_mod

    # 13-REVIEW WR-06: get_engine() is lru_cached, so a later test on a NEW
    # pytest-asyncio event loop would otherwise reuse asyncpg connections that
    # belong to a closed loop. _heartbeat_loop uses the CACHED sessionmaker, so
    # the cache must be primed against this DSN and cleared afterwards.
    base_mod.get_engine.cache_clear()
    engine = sa_asyncio.create_async_engine(url, future=True)
    sessionmaker = base_mod.get_sessionmaker(engine)

    async with sessionmaker() as session:
        async with session.begin():
            role_ok = (
                await session.execute(
                    sa.text(
                        "SELECT current_setting('is_superuser') = 'on' "
                        "OR current_user = 'worker_user'"
                    )
                )
            ).scalar_one()
    if not role_ok:
        await engine.dispose()
        base_mod.get_engine.cache_clear()
        pytest.skip(
            "connected as a role that is neither a superuser nor worker_user, so "
            "RLS hides the seeded `run` rows and CLAIM_SQL / REAP_SQL would match "
            "nothing. THIS IS NOT A PASS — it is a vacuous green refused. In "
            "production these statements are issued by worker_user (policy "
            "run_worker_all, migration 0008); run this file under "
            "tribunal/cloudbuild.test-critical.yaml."
        )

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            await session.execute(
                sa.text("INSERT INTO org (id, name, slug) VALUES (:id, :n, :s)"),
                {
                    "id": str(tenant_id),
                    "n": f"stale-reclaim-{tenant_id}",
                    "s": f"stale-reclaim-{tenant_id.hex[:12]}",
                },
            )
            await session.execute(
                sa.text(
                    "INSERT INTO project (id, tenant_id, name) VALUES (:id, :t, :n)"
                ),
                {"id": str(project_id), "t": str(tenant_id), "n": "stale-reclaim"},
            )

    try:
        yield sessionmaker, tenant_id, project_id
    finally:
        # CASCADE removes the projects and runs seeded above, so the module is
        # rerunnable and leaves no claimable rows behind for the next test.
        try:
            async with sessionmaker() as session:
                async with session.begin():
                    await session.execute(sa.text("SET search_path TO tribunal"))
                    await session.execute(
                        sa.text("DELETE FROM org WHERE id = :id"),
                        {"id": str(tenant_id)},
                    )
        finally:
            # _heartbeat_loop uses the CACHED engine (get_sessionmaker() with no
            # argument), so dispose that one too or its asyncpg pool outlives this
            # event loop (13-REVIEW WR-06).
            try:
                await base_mod.get_engine().dispose()
            except Exception:  # noqa: BLE001
                pass
            base_mod.get_engine.cache_clear()
            await engine.dispose()


# ---------------------------------------------------------------------------
# Seeding + reading helpers
# ---------------------------------------------------------------------------

_INSERT_RUN = """
    INSERT INTO run (id, tenant_id, project_id, engine, brief, status,
                     idempotency_key, worker_id, created_at, started_at,
                     heartbeat_at, reclaim_count)
    VALUES (:id, :t, :p, 'sdk', :brief, :status, :ik, :wid,
            NOW() - make_interval(mins => :created_min_ago),
            NOW() - make_interval(mins => :started_min_ago),
            NOW() - make_interval(mins => :hb_min_ago),
            :reclaim_count)
"""


async def _seed_run(
    sessionmaker,
    tenant_id,
    project_id,
    *,
    status: str,
    created_min_ago: int = 600,
    started_min_ago: int | None = None,
    hb_min_ago: int | None = None,
    reclaim_count: int = 0,
    worker_id: str | None = None,
    brief: str = "d-e seed",
):
    """Insert one `run` with an exact liveness shape and return its id.

    A `None` offset becomes SQL NULL: `make_interval(mins => NULL)` is NULL and
    `NOW() - NULL` is NULL, so a queued run gets NULL started_at / heartbeat_at
    exactly as production writes it.
    """
    sa = pytest.importorskip("sqlalchemy")
    run_id = uuid.uuid4()
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            await session.execute(
                sa.text(_INSERT_RUN),
                {
                    "id": str(run_id),
                    "t": str(tenant_id),
                    "p": str(project_id),
                    "brief": brief,
                    "status": status,
                    "ik": str(uuid.uuid4()),
                    "wid": worker_id,
                    "created_min_ago": created_min_ago,
                    "started_min_ago": started_min_ago,
                    "hb_min_ago": hb_min_ago,
                    "reclaim_count": reclaim_count,
                },
            )
    return run_id


async def _read_run(sessionmaker, run_id) -> dict:
    sa = pytest.importorskip("sqlalchemy")
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            row = (
                await session.execute(
                    sa.text(
                        "SELECT id, status, worker_id, started_at, heartbeat_at, "
                        "reclaim_count, error_message, completed_at "
                        "FROM run WHERE id = :id"
                    ),
                    {"id": str(run_id)},
                )
            ).first()
    assert row is not None, f"seeded run {run_id} disappeared"
    return dict(row._mapping)


async def _claim(sessionmaker, *, wid: str, stale: int, max_reclaims: int):
    """Run the PRODUCTION CLAIM_SQL. Returns the claimed mapping, or None."""
    sa = pytest.importorskip("sqlalchemy")
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            row = (
                await session.execute(
                    worker.CLAIM_SQL,
                    {"wid": wid, "stale": stale, "max_reclaims": max_reclaims},
                )
            ).first()
    return dict(row._mapping) if row is not None else None


async def _reap(sessionmaker, *, stale: int, max_reclaims: int) -> list[str]:
    """Run the PRODUCTION REAP_SQL. Returns the ids it failed."""
    sa = pytest.importorskip("sqlalchemy")
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            result = await session.execute(
                worker.REAP_SQL,
                {
                    "msg": worker._reap_message(),
                    "stale": stale,
                    "max_reclaims": max_reclaims,
                },
            )
            return [str(r[0]) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# Test 1 — the headline: a LIVE long-poll is never re-run
# ---------------------------------------------------------------------------

async def test_fresh_heartbeat_is_never_reclaimed(worker_db):
    """A `running` row whose heartbeat is NOW() is NOT claimable, however old
    `started_at` is.

    This is the exact shape of the defect: a deep-research long-poll can take ~35
    minutes and the stale threshold is 60, so under the OLD rule a run that
    outlived the threshold while perfectly healthy was re-claimed and re-executed
    at full cost. `started_at` here is FIVE HOURS old — far past any threshold —
    and the run must still be untouchable, because its worker is alive and saying
    so (T-15.2-200).
    """
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="running",
        started_min_ago=300,   # five hours: absurdly past the threshold
        hb_min_ago=0,          # ...but the process is alive and heartbeating
        worker_id="worker-alive",
    )

    await _claim(sessionmaker, wid="worker-thief", stale=60, max_reclaims=2)

    # Assert on OUR row, not on the claim's return value: CLAIM_SQL selects from
    # the whole table, so "it returned None" would be the weaker statement.
    row = await _read_run(sessionmaker, run_id)
    assert row["worker_id"] == "worker-alive", (
        "a live, heartbeating run was STOLEN by another worker — this is the "
        "D-E money defect: it would have been re-executed at full cost"
    )
    assert row["reclaim_count"] == 0, (
        "a live run must not accrue crash recoveries; got "
        f"reclaim_count={row['reclaim_count']}"
    )
    assert row["status"] == "running"


# ---------------------------------------------------------------------------
# Test 2 — a DEAD worker is still recovered, and only reclaims are counted
# ---------------------------------------------------------------------------

async def test_dead_heartbeat_is_reclaimed_and_counted(worker_db):
    """A `running` row whose heartbeat stopped IS claimable, and the claim
    increments `reclaim_count` by exactly 1 — while a fresh `queued` claim leaves
    it at 0.

    The recovery path survives the D-E fix; it is not deleted. Both halves matter:
    if the reclaim did not count, the ceiling in Test 3 could never be reached; if
    a queued claim counted, ordinary work would burn the run's recovery budget
    before it ever crashed.
    """
    sessionmaker, tenant_id, project_id = worker_db
    # Older created_at, so CLAIM_SQL's `ORDER BY created_at` takes it first.
    dead_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="running",
        created_min_ago=900,
        started_min_ago=300,
        hb_min_ago=180,        # three hours of silence: the process is gone
        worker_id="worker-dead",
    )
    queued_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="queued",
        created_min_ago=800,
        started_min_ago=None,
        hb_min_ago=None,
    )

    first = await _claim(sessionmaker, wid="worker-new", stale=60, max_reclaims=2)
    assert first is not None and first["id"] == dead_id, (
        "a run whose worker stopped heartbeating MUST still be recovered — the "
        "crash-recovery path is not deleted by the D-E fix"
    )
    assert first["reclaim_count"] == 1, (
        "reclaiming an already-'running' row must count as exactly one crash "
        f"recovery; got {first['reclaim_count']}"
    )

    second = await _claim(sessionmaker, wid="worker-new", stale=60, max_reclaims=2)
    assert second is not None and second["id"] == queued_id
    assert second["reclaim_count"] == 0, (
        "a fresh claim of a QUEUED run is ordinary work, not a crash recovery; "
        f"got reclaim_count={second['reclaim_count']}"
    )

    # And the reclaim stamped a fresh heartbeat, so the recovered run is not
    # instantly stale again for the next poller.
    row = await _read_run(sessionmaker, dead_id)
    assert row["heartbeat_at"] is not None
    assert row["worker_id"] == "worker-new"


# ---------------------------------------------------------------------------
# Test 3 — the ceiling closes the unattended re-bill loop
# ---------------------------------------------------------------------------

async def test_reclaim_ceiling_stops_the_loop(worker_db):
    """A stale `running` row already at `reclaim_count >= :max_reclaims` is NOT
    claimable.

    This is the clause that makes "a permanently stalling run re-bills every 60
    minutes forever" structurally unreachable (T-15.2-200). Without it, liveness
    alone would only slow the loop down — a run that genuinely keeps dying would
    still be restarted without end.
    """
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="running",
        started_min_ago=300,
        hb_min_ago=180,        # silent: it WOULD be claimable but for the ceiling
        reclaim_count=2,
        worker_id="worker-exhausted",
    )

    await _claim(sessionmaker, wid="worker-new", stale=60, max_reclaims=2)

    row = await _read_run(sessionmaker, run_id)
    assert row["worker_id"] == "worker-exhausted", (
        "a run at the reclaim ceiling was started AGAIN — the unattended "
        "re-execute loop is still open, which is the whole cost risk of D-E"
    )
    assert row["reclaim_count"] == 2


# ---------------------------------------------------------------------------
# Test 4 — the reap: failed WITH WORDS, and nothing else touched
# ---------------------------------------------------------------------------

async def test_reap_fails_over_ceiling_runs_with_a_sentence(worker_db):
    """`REAP_SQL` flips exactly the over-ceiling stale `running` rows to
    `failed` with a non-empty `error_message`, and matches zero queued /
    fresh-heartbeat / terminal rows.

    A run that hits the ceiling must not simply stop being claimable and sit in
    `running` forever: the intake's retry gate excludes `running`, so the run
    would be unresolvable and invisible (T-15.2-203). It is failed here, and the
    message is a sentence a person reads — never a code.
    """
    sessionmaker, tenant_id, project_id = worker_db
    doomed = await _seed_run(
        sessionmaker, tenant_id, project_id, status="running",
        started_min_ago=300, hb_min_ago=180, reclaim_count=2,
        worker_id="worker-exhausted",
    )
    queued = await _seed_run(
        sessionmaker, tenant_id, project_id, status="queued",
        started_min_ago=None, hb_min_ago=None, reclaim_count=2,
    )
    alive = await _seed_run(
        sessionmaker, tenant_id, project_id, status="running",
        started_min_ago=300, hb_min_ago=0, reclaim_count=9,
        worker_id="worker-alive",
    )
    done = await _seed_run(
        sessionmaker, tenant_id, project_id, status="completed",
        started_min_ago=300, hb_min_ago=180, reclaim_count=9,
    )

    reaped = await _reap(sessionmaker, stale=60, max_reclaims=2)

    assert str(doomed) in reaped, "the over-ceiling stale run must be reaped"
    for other, why in (
        (queued, "a queued run has no worker to have lost"),
        (alive, "a heartbeating run is alive, whatever its reclaim_count"),
        (done, "a terminal run is already resolved"),
    ):
        assert str(other) not in reaped, f"REAP_SQL must not touch it: {why}"

    row = await _read_run(sessionmaker, doomed)
    assert row["status"] == "failed", (
        "the reaped run must end in a terminal state — leaving it 'running' is "
        "what makes the intake unretryable"
    )
    assert row["completed_at"] is not None
    assert row["error_message"] and row["error_message"].strip(), (
        "the reap must say IN WORDS why the run was failed rather than restarted"
    )

    assert (await _read_run(sessionmaker, queued))["status"] == "queued"
    assert (await _read_run(sessionmaker, alive))["status"] == "running"
    assert (await _read_run(sessionmaker, done))["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 5 — the liveness writer works, and does not outlive its run
# ---------------------------------------------------------------------------

async def test_heartbeat_loop_writes_then_stops_on_cancel(worker_db, monkeypatch):
    """`_heartbeat_loop` advances `heartbeat_at` for the run it is given, and
    stops advancing it once cancelled.

    Asserted on the ROW, never on a sleep: the first half proves the signal Test 1
    depends on is actually written, the second proves the task cannot outlive its
    run and keep a dead run looking alive — which would be the D-E defect with the
    sign flipped (T-15.2-202).

    The interval is patched on the MODULE ATTRIBUTE rather than the environment:
    `NESTOR_WORKER_HEARTBEAT_S` is parsed once at import, and the loop reads the
    global on every iteration precisely so this is drivable.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="running",
        started_min_ago=10,
        hb_min_ago=60,
        worker_id="worker-under-test",
    )
    seeded = (await _read_run(sessionmaker, run_id))["heartbeat_at"]

    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    task = asyncio.create_task(worker._heartbeat_loop(run_id))
    try:
        await asyncio.sleep(0.6)
        beating = (await _read_run(sessionmaker, run_id))["heartbeat_at"]
        assert beating > seeded, (
            "_heartbeat_loop did not advance heartbeat_at — without this write "
            "CLAIM_SQL cannot tell a live long-poll from a dead process"
        )
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    stopped_at = (await _read_run(sessionmaker, run_id))["heartbeat_at"]
    await asyncio.sleep(0.6)
    after = (await _read_run(sessionmaker, run_id))["heartbeat_at"]
    assert after == stopped_at, (
        "heartbeat_at kept advancing after the task was cancelled — a heartbeat "
        "that outlives its run would keep a dead run looking alive forever"
    )
