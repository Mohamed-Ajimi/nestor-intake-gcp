"""
ENGINE-08 -- Per-run advisory lock exactly-once proof (owning plan: 13-02).

The audit hash-chain is per-run and legally load-bearing (EU AI Act Art. 12).
It is safe ONLY under a single writer per run: two executors that both dispatch
the engine for the SAME run_id fork the chain and double-spend the provider
budget (13-RESEARCH.md Pitfall 3; threat T-13-06). Before Phase 13 the old
deploy was capped at `max-instances=1` precisely because this lock was missing
(01-19 objective).

Plan 13-02 Task 2 extracts ONLY the keystone from Tribunal's unexecuted plan
01-19 -- a transaction-scoped 64-bit `pg_advisory_xact_lock(run_id)` plus a
claimable-set re-check -- into `runs/execute.py` (`execute_run_locked`), wired
into `worker_loop`. It does NOT port 01-19's Pub/Sub / Eventarc / Cloud Run
Jobs / reaper / concurrency-cap machinery (out of scope per REQUIREMENTS.md).

Key correctness points asserted here:
  * The lock key is the 64-bit form `('x'||md5(:run_id))::bit(64)::bigint`,
    NOT `hashtext()` (int4, 32-bit -> ~50% birthday collision at ~65k runs,
    which would spuriously serialize two DISTINCT runs -- threat T-13-07).
  * After acquiring the lock, execute_run_locked re-checks OWNERSHIP (13-REVIEW
    CR-01 fix): still 'running', still OUR worker_id, claim still fresh. The
    claimable set (status='queued' OR stale-'running') belongs to CLAIM_SQL in
    worker.py — re-testing it post-claim refused the worker's own fresh claim.
    The paused/terminal states needs_input, needs_report_spec, cancelled,
    completed, failed and stolen claims (worker_id mismatch) cause an early
    return (no second engine dispatch) -- exactly-once.

Tests:
  1. test_lock_sql_is_64bit_not_hashtext (static): the lock SQL in execute.py
     uses `bit(64)::bigint` and never `hashtext` (T-13-07).
  2. test_claimable_guard_names_paused_and_terminal_states (static): execute.py
     names needs_input / needs_report_spec / cancelled / completed / failed as
     NOT claimable (H-3).
  3. test_worker_delegates_to_locked_path (static): worker_loop imports and
     calls execute_run_locked from runs.execute.
  4. test_no_out_of_scope_1_19_machinery (static): execute.py adds no Pub/Sub /
     Eventarc / reaper / concurrency-cap code (scope guard).
  5. test_worker_claimed_run_dispatches (LIVE): CR-01 regression — a freshly
     self-claimed run passes the ownership re-check and dispatches.
  6. test_same_run_executes_exactly_once (LIVE): two coroutines handed the same
     claimed run dispatch the engine exactly once.
  7. test_stolen_claim_does_not_double_dispatch (LIVE): after a stale reclaim,
     only the new owner dispatches.
  8. test_distinct_runs_do_not_serialize (LIVE): two distinct claimed runs
     acquire independent 64-bit locks without blocking each other.

The live tests are authored-by-construction (dev machine has no Python/Docker)
and executed in Plan 04's Cloud Build suite.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SDK_ROOT = Path(__file__).resolve().parents[1]
_EXECUTE_PY = _SDK_ROOT / "runs" / "execute.py"
_WORKER_PY = _SDK_ROOT / "runs" / "worker.py"


# ---------------------------------------------------------------------------
# Static assertions (no live DB) -- these encode the ENGINE-08 contract.
# ---------------------------------------------------------------------------

def test_lock_sql_is_64bit_not_hashtext() -> None:
    """The advisory lock must use the 64-bit md5 key, never hashtext (int4)."""
    src = _EXECUTE_PY.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in src, (
        "execute.py must acquire a per-run pg_advisory_xact_lock"
    )
    assert "bit(64)::bigint" in src, (
        "the lock key must be ('x'||md5(:run_id))::bit(64)::bigint (64-bit) -- "
        "hashtext is int4 and collides ~50% at ~65k runs (T-13-07)"
    )
    assert "hashtext" not in src, (
        "execute.py must NOT use hashtext (int4 birthday-collision pitfall)"
    )
    assert "md5" in src, "the 64-bit key is derived from md5(:run_id)"


def test_claimable_guard_names_paused_and_terminal_states() -> None:
    """After the lock, the run must be re-checked; paused/terminal states are
    NOT claimable and must not trigger a second engine dispatch (H-3)."""
    src = _EXECUTE_PY.read_text(encoding="utf-8")
    for state in (
        "needs_input",
        "needs_report_spec",
        "cancelled",
        "completed",
        "failed",
    ):
        assert state in src, (
            f"execute.py claimable re-check must name the {state!r} state as "
            "not-claimable (exactly-once, H-3)"
        )
    # The claimable set itself: queued OR stale-running.
    assert "queued" in src and "running" in src, (
        "claimable = status='queued' OR (status='running' AND started_at stale)"
    )


def test_worker_delegates_to_locked_path() -> None:
    """worker_loop must call the lock-wrapped entrypoint from runs.execute."""
    src = _WORKER_PY.read_text(encoding="utf-8")
    assert "from nestor_pulse_sdk.runs.execute import" in src or (
        "runs.execute import" in src
    ), "worker.py must import from nestor_pulse_sdk.runs.execute"
    assert "execute_run_locked" in src, (
        "worker_loop must call execute_run_locked (the lock-wrapped path)"
    )


def test_no_out_of_scope_1_19_machinery() -> None:
    """Only the advisory-lock keystone is extracted; the rest of 01-19
    (Pub/Sub / Eventarc / Cloud Run Jobs / reaper / concurrency caps) is NOT
    ported (scope guard -- REQUIREMENTS.md Out-of-Scope)."""
    src = _EXECUTE_PY.read_text(encoding="utf-8").lower()
    for forbidden in ("pubsub", "pub/sub", "eventarc", "reaper", "publish_run"):
        assert forbidden not in src, (
            f"execute.py must NOT add out-of-scope 01-19 machinery: {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# Live assertions (skip-guarded) -- run in Plan 04's Cloud Build suite.
# ---------------------------------------------------------------------------

def _live_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql+asyncpg://"):
        return url
    return None


async def _make_live_sessionmaker():
    """Return (sessionmaker, cleanup) against a fresh migrated tribunal schema,
    or skip cleanly when no live DB is reachable."""
    sa_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")

    url = _live_database_url()
    container = None
    if url is None:
        try:
            from testcontainers.postgres import PostgresContainer  # type: ignore
        except ImportError:
            pytest.skip("no live DB: DATABASE_URL unset and testcontainers absent")
        try:
            container = PostgresContainer("postgres:15")
            container.start()
        except Exception as exc:  # noqa: BLE001 -- DockerException family
            pytest.skip(f"no live DB: Docker unavailable ({exc})")
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

    os.environ["DATABASE_URL"] = url
    from alembic import command  # type: ignore
    from alembic.config import Config  # type: ignore

    alembic_ini = _SDK_ROOT / "alembic.ini"
    cfg = Config(str(alembic_ini)) if alembic_ini.exists() else Config()
    cfg.set_main_option("script_location", str(_SDK_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = sa_asyncio.create_async_engine(url, future=True)
    from nestor_pulse_sdk.db import base as base_mod

    # 13-REVIEW WR-06: get_engine() is lru_cached, so a second test on a NEW
    # pytest-asyncio event loop would reuse an engine whose asyncpg connections
    # belong to the PREVIOUS (closed) loop -> "attached to a different loop".
    # execute_run_locked calls get_sessionmaker() (cached engine) internally,
    # so reset the cache at every live-test setup and dispose at cleanup.
    base_mod.get_engine.cache_clear()

    sessionmaker = base_mod.get_sessionmaker(engine)

    async def _cleanup() -> None:
        try:
            cached = base_mod.get_engine()
            await cached.dispose()
        except Exception:  # noqa: BLE001
            pass
        base_mod.get_engine.cache_clear()
        await engine.dispose()
        if container is not None:
            try:
                container.stop()
            except Exception:  # noqa: BLE001
                pass

    return sessionmaker, _cleanup


def _patch_dispatch(side_effect):
    """Patch the REAL dispatch target. execute_run_locked lazily does
    `from nestor_pulse_sdk.runs.worker import execute_run` at call time, so the
    interception point is the WORKER module attribute — patching runs.execute
    would miss the call entirely (13-REVIEW WR-02)."""
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    return patch.object(
        worker_mod, "execute_run", new=AsyncMock(side_effect=side_effect)
    )


async def _claim(sessionmaker, wid: str, stale_minutes: int = 60) -> dict | None:
    """Model the production claim: run worker.py's CLAIM_SQL as worker `wid`."""
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    async with sessionmaker() as session:
        async with session.begin():
            sa = pytest.importorskip("sqlalchemy")
            await session.execute(sa.text("SET search_path TO tribunal"))
            result = await session.execute(
                worker_mod.CLAIM_SQL,
                {
                    "wid": wid,
                    "stale": stale_minutes,
                    # D-E (plan 15.2-20) added the reclaim ceiling bind. The
                    # production default is used so this helper keeps modelling
                    # the production claim exactly.
                    "max_reclaims": worker_mod.MAX_RECLAIMS,
                },
            )
            row = result.first()
    return dict(row._mapping) if row is not None else None


@pytest.mark.asyncio
async def test_worker_claimed_run_dispatches() -> None:
    """CR-01 regression: a run freshly claimed by THIS worker (status='running',
    fresh started_at, our worker_id) MUST pass the post-lock re-check and
    dispatch. The original re-check re-tested the pre-claim claimable set
    (queued-or-stale) and refused its own claim — starving the queue forever."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        await _seed_queued_run(sessionmaker)
        claimed = await _claim(sessionmaker, wid="worker-A")
        assert claimed is not None, "CLAIM_SQL must claim the seeded queued run"
        assert claimed["worker_id"] == "worker-A"

        dispatch_calls: list[uuid.UUID] = []

        async def _fake_execute_run(c: dict) -> None:
            dispatch_calls.append(c["id"])
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        with _patch_dispatch(_fake_execute_run):
            await execute_mod.execute_run_locked(dict(claimed))

        assert dispatch_calls == [claimed["id"]], (
            "a freshly self-claimed run must dispatch exactly once "
            "(CR-01: the old queued-or-stale re-check refused its own claim)"
        )
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_same_run_executes_exactly_once() -> None:
    """Two concurrent execute_run_locked calls on the SAME claimed run dispatch
    the engine EXACTLY ONCE; the lock serializes them and the loser sees the
    run no longer claimable (completed) and returns."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        await _seed_queued_run(sessionmaker)
        claimed = await _claim(sessionmaker, wid="worker-A")
        assert claimed is not None

        dispatch_calls: list[uuid.UUID] = []

        async def _fake_execute_run(c: dict) -> None:
            dispatch_calls.append(c["id"])
            # Mark terminal so the second lock-holder sees it not-claimable.
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        with _patch_dispatch(_fake_execute_run):
            await asyncio.gather(
                execute_mod.execute_run_locked(dict(claimed)),
                execute_mod.execute_run_locked(dict(claimed)),
            )

        assert len(dispatch_calls) == 1, (
            f"expected exactly one engine dispatch, got {len(dispatch_calls)}"
        )
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_stolen_claim_does_not_double_dispatch() -> None:
    """Stale-reclaim race: worker A claims, goes stale, worker B re-claims.
    A's later dispatch attempt must be REFUSED (worker_id no longer A's) while
    B's dispatch proceeds — exactly one engine dispatch total (T-13-06)."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sa = pytest.importorskip("sqlalchemy")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        await _seed_queued_run(sessionmaker)
        claimed_a = await _claim(sessionmaker, wid="worker-A")
        assert claimed_a is not None

        # Force A's claim stale, then B re-claims it (crash-recovery path).
        # D-E (plan 15.2-20): the staleness clock is now
        # COALESCE(heartbeat_at, started_at), and the claim stamps a FRESH
        # heartbeat_at. Backdating started_at alone therefore no longer makes a
        # run stale — both must move, which is precisely the point of the fix:
        # a claim whose worker is still heartbeating is never stolen.
        async with sessionmaker() as session:
            async with session.begin():
                await session.execute(sa.text("SET search_path TO tribunal"))
                await session.execute(
                    sa.text(
                        "UPDATE run SET started_at = NOW() - INTERVAL '1 day', "
                        "heartbeat_at = NOW() - INTERVAL '1 day' "
                        "WHERE id = :id"
                    ),
                    {"id": str(claimed_a["id"])},
                )
        claimed_b = await _claim(sessionmaker, wid="worker-B")
        assert claimed_b is not None and claimed_b["id"] == claimed_a["id"]
        assert claimed_b["worker_id"] == "worker-B"

        dispatch_calls: list[str] = []

        async def _fake_execute_run(c: dict) -> None:
            dispatch_calls.append(str(c.get("worker_id")))
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        with _patch_dispatch(_fake_execute_run):
            # A tries to dispatch its stolen claim; B dispatches its fresh one.
            await execute_mod.execute_run_locked(dict(claimed_a))
            await execute_mod.execute_run_locked(dict(claimed_b))

        assert dispatch_calls == ["worker-B"], (
            "only the current owner (worker-B) may dispatch; the stolen claim "
            f"must be refused — got dispatches from {dispatch_calls}"
        )
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_distinct_runs_do_not_serialize() -> None:
    """Two DISTINCT claimed runs acquire independent 64-bit advisory locks and
    both dispatch -- the 64-bit key space keeps them from serializing (T-13-07)."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        await _seed_queued_run(sessionmaker)
        await _seed_queued_run(sessionmaker)
        claimed_a = await _claim(sessionmaker, wid="worker-A")
        claimed_b = await _claim(sessionmaker, wid="worker-A")
        assert claimed_a is not None and claimed_b is not None
        assert claimed_a["id"] != claimed_b["id"]

        dispatched: set[uuid.UUID] = set()

        async def _fake_execute_run(c: dict) -> None:
            dispatched.add(c["id"])
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        with _patch_dispatch(_fake_execute_run):
            await asyncio.gather(
                execute_mod.execute_run_locked(dict(claimed_a)),
                execute_mod.execute_run_locked(dict(claimed_b)),
            )

        assert dispatched == {claimed_a["id"], claimed_b["id"]}, (
            "both distinct runs must dispatch; neither serializes on the other"
        )
    finally:
        await cleanup()


# ---------------------------------------------------------------------------
# Live-test seed helpers (only used by the skip-guarded live tests above).
# ---------------------------------------------------------------------------

async def _seed_queued_run(sessionmaker) -> dict:
    """Insert org + project + one queued run; return the CLAIM_SQL-shaped dict.

    Runs as the migrating superuser (RLS bypass in the ephemeral test DB), so
    no worker_user role is needed for the seed.
    """
    sa = pytest.importorskip("sqlalchemy")
    text = sa.text
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(text("SET search_path TO tribunal"))
            await session.execute(
                text("INSERT INTO org (id, name, slug) VALUES (:id, :n, :s)"),
                {
                    "id": str(tenant_id),
                    "n": f"org-{tenant_id}",
                    "s": f"org-{tenant_id}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO project (id, tenant_id, name) "
                    "VALUES (:id, :t, :n)"
                ),
                {"id": str(project_id), "t": str(tenant_id), "n": "p"},
            )
            await session.execute(
                text(
                    "INSERT INTO run (id, tenant_id, project_id, engine, brief, "
                    "status, idempotency_key) VALUES "
                    "(:id, :t, :p, 'sdk', 'b', 'queued', :ik)"
                ),
                {
                    "id": str(run_id),
                    "t": str(tenant_id),
                    "p": str(project_id),
                    "ik": str(uuid.uuid4()),
                },
            )
    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "engine": "sdk",
        "brief": "b",
    }


async def _mark_completed(sessionmaker, run_id, tenant_id) -> None:
    sa = pytest.importorskip("sqlalchemy")
    text = sa.text
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(text("SET search_path TO tribunal"))
            await session.execute(
                text("UPDATE run SET status='completed' WHERE id=:id"),
                {"id": str(run_id)},
            )
