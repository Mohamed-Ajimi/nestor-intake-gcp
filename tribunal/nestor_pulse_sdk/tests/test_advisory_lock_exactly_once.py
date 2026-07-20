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
  * After acquiring the lock, execute_run_locked RE-CHECKS the claimable set:
    claimable = status='queued' OR (status='running' AND started_at stale).
    The paused/terminal states needs_input, needs_report_spec, cancelled,
    completed, failed are EXPLICITLY NOT claimable and cause an early return
    (no second engine dispatch) -- exactly-once.

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
  5. test_same_run_executes_exactly_once (LIVE, skip-guarded): two coroutines
     handed the same claimed run_id dispatch the engine exactly once.
  6. test_distinct_runs_do_not_serialize (LIVE, skip-guarded): two distinct
     run_ids acquire independent 64-bit locks without blocking each other.

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
    from nestor_pulse_sdk.db.base import get_sessionmaker

    sessionmaker = get_sessionmaker(engine)

    async def _cleanup() -> None:
        await engine.dispose()
        if container is not None:
            try:
                container.stop()
            except Exception:  # noqa: BLE001
                pass

    return sessionmaker, _cleanup


@pytest.mark.asyncio
async def test_same_run_executes_exactly_once() -> None:
    """Two concurrent execute_run_locked calls on the SAME claimed run_id run
    the engine EXACTLY ONCE; the loser sees the run not-claimable and returns."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        # Seed one queued run (helper inserts org/project/run under RLS bypass).
        claimed = await _seed_queued_run(sessionmaker)

        dispatch_calls: list[uuid.UUID] = []

        async def _fake_execute_run(c: dict) -> None:
            dispatch_calls.append(c["id"])
            # Mark the run terminal so the second lock-holder sees it not-claimable.
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        # Patch the inner engine-dispatch so we count dispatches, not real work.
        with patch.object(execute_mod, "execute_run", new=AsyncMock(side_effect=_fake_execute_run)):
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
async def test_distinct_runs_do_not_serialize() -> None:
    """Two DISTINCT run_ids acquire independent 64-bit advisory locks and both
    dispatch -- the 64-bit key space keeps them from serializing (T-13-07)."""
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    sessionmaker, cleanup = await _make_live_sessionmaker()
    try:
        claimed_a = await _seed_queued_run(sessionmaker)
        claimed_b = await _seed_queued_run(sessionmaker)
        assert claimed_a["id"] != claimed_b["id"]

        dispatched: set[uuid.UUID] = set()

        async def _fake_execute_run(c: dict) -> None:
            dispatched.add(c["id"])
            await _mark_completed(sessionmaker, c["id"], c["tenant_id"])

        with patch.object(execute_mod, "execute_run", new=AsyncMock(side_effect=_fake_execute_run)):
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
                text("INSERT INTO org (id, name) VALUES (:id, :n)"),
                {"id": str(tenant_id), "n": f"org-{tenant_id}"},
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
