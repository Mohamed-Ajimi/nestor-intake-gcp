"""23.3-01 — the RUN-LEVEL TIMEOUT BACKSTOP around `runner.run()`.

WHY this file exists
--------------------
`d6bb3aae` executed for **1472 minutes** (24.5 hours) in production on 2026-07-27.
`execute_run` awaits `runner.run()` with no wall-clock bound of any kind, and the
liveness heartbeat is a SEPARATE `asyncio.Task` that keeps writing `run.heartbeat_at`
every 30s for as long as that await is pending. So while a run is hung:

  * the row never goes stale, therefore `CLAIM_SQL`'s reclaim branch never matches it;
  * `REAP_SQL` never touches it (it needs the same staleness);
  * and the poll loop stays blocked on the `await`, forever, claiming nothing else.

A hang and a legitimately-silent 35-minute deep-research long-poll are, by design,
indistinguishable to the reclaim machinery. That design is correct — it is what stopped
the 2026-07-27 re-execute loop — and its cost is that ONLY a wall-clock ceiling inside
`execute_run` itself can end a hang.

⛔ THIS IS A BACKSTOP, NOT A CURE. `asyncio` cancellation only takes effect at an
`await` point: a hang inside a synchronous call or a C extension is NOT interrupted and
the worker stays blocked (23.3-CONTEXT.md § 6, trap 8). Nothing in this file claims
otherwise, and no assertion here should ever be read as proving a hang is impossible.

WHAT IS PINNED, AND WHY EACH ASSERTION EXISTS
---------------------------------------------
Layer A — PURE (no database, no network, no key; runs in every harness):

  * `test_ceiling_is_at_least_the_longest_real_run` — the COMMITTED default of
    `RUN_TIMEOUT_MINUTES` is >= 64.2. That is the wall clock of `7dcf51d5`, the longest
    run that legitimately COMPLETED (23.3-CONTEXT.md § 1). A ceiling below it kills real
    runs *and* burns the ~$25-45 they have already spent (trap 7) — the ceiling exists to
    bound a pathology, not to ration legitimate work.
    ANTI-VACUITY: it asserts on the NUMBER, read from a module attribute, never on a grep
    of the file — a comment mentioning "120" would satisfy a grep and prove nothing. It is
    read from a FRESHLY LOADED copy of `worker.py` with
    `NESTOR_WORKER_RUN_TIMEOUT_MINUTES` deleted from the environment, so the gate measures
    the value in the repository rather than whatever the harness happens to export.

Layer B — REAL POSTGRES (skips LOUDLY without `DATABASE_URL`; A SKIP IS NOT A PASS):

  * `test_a_hung_run_is_bounded_and_failed` — the defect. A stub runner that awaits
    `asyncio.sleep(3600)` is dispatched through `execute_run` with the ceiling collapsed
    sub-minute. `execute_run` must RETURN within seconds and the row must read `failed`.
  * `test_the_timed_out_run_carries_a_worded_reason` — the assertion a naive fix FAILS.
    In Python 3.11+ `asyncio.TimeoutError` IS the builtin `TimeoutError`, which derives
    from `OSError` and so from `Exception`. Without its own `except TimeoutError` branch
    the existing generic handler catches it and writes `error_message = str(exc)`, which
    for a bare `TimeoutError` is the EMPTY STRING. The operator would open a `failed` run
    carrying no reason at all. The hang test alone passes on that broken fix; this one
    does not.
  * `test_the_queue_keeps_moving_after_a_timeout` — the ceiling must RELEASE the instance,
    not merely relabel a row. A second claimed run, dispatched after the first has timed
    out, reaches a terminal non-`failed` status.
  * `test_a_run_inside_the_ceiling_is_untouched` — COMPARABILITY GUARD, expected green
    both before and after this plan. It is NOT proof of the fix; it is proof the fix costs
    nothing. Phase 23.3 changes SCHEDULING only and no plan may alter what a run produces.

HOW THE STUB RUNNER IS INJECTED — read this before changing the test
--------------------------------------------------------------------
`execute_run` imports `dispatch_runner` LAZILY, inside the function body. Patching a name
bound in `worker` would therefore patch nothing. The patch target is the attribute on
`nestor_pulse_sdk.runs.adapter`, which the lazy import re-reads on every call.

Every DB-backed test wraps its `execute_run` call in the test's OWN
`asyncio.wait_for(..., 10)`. That is deliberate: at HEAD, where no ceiling exists, an
unbounded `execute_run` would HANG THE WHOLE SUITE rather than fail. The wrapper converts
"not bounded" into a loud, readable failure. If you ever see that failure, the ceiling is
not wired — do not raise the 10s.

Fixture helpers are COPIED from `test_run_state_cas.py` rather than imported. That
duplication is this suite's deliberate house style (`test_rls_isolation.py` does the
same): cross-module fixture imports and a shared conftest are what make these files
order-dependent, and this suite already carries one reproducible cross-file pollution
defect (DEF-23.2-14).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest


# The wall clock of `7dcf51d5` (2026-07-28, 415 audit blobs), the longest run in
# 23.3-CONTEXT.md § 1 that legitimately COMPLETED. Anything at or below this kills
# real, paid work.
LONGEST_LEGITIMATE_RUN_MINUTES = 64.2

# How long a DB-backed test is willing to wait for `execute_run` to come back. The
# ceiling under test is collapsed to ~1.2s, so 10s is ~8x headroom and any breach
# means the run was not bounded at all.
_OUTER_DEADLINE_SECONDS = 10.0

# The collapsed ceiling used by the DB-backed tests: 0.02 min = 1.2 s.
_TEST_CEILING_MINUTES = 0.02


# ===========================================================================
# LAYER A — PURE. No DB, no network, no key. Runs in every harness, including
# the DB-less ones, so the ceiling cannot be silently lowered by an edit that
# happens to keep the DB-backed tests skipping.
# ===========================================================================


def _load_worker_with_committed_defaults(monkeypatch):
    """A FRESH module object built from `worker.py`, with the ceiling's env
    override removed, so its constants are the ones in the REPOSITORY.

    It is loaded under a throwaway name and never inserted into `sys.modules`,
    so the live `nestor_pulse_sdk.runs.worker` — whose `WORKER_ID` other tests in
    this process hold and seed rows against — is not disturbed.
    """
    from nestor_pulse_sdk.runs import worker as live

    monkeypatch.delenv("NESTOR_WORKER_RUN_TIMEOUT_MINUTES", raising=False)
    spec = importlib.util.spec_from_file_location(
        "_worker_committed_default_probe", live.__file__
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ceiling_is_at_least_the_longest_real_run(monkeypatch):
    """The committed default must not be able to kill a run that would finish.

    ANTI-VACUITY: this reads the module ATTRIBUTE and compares NUMBERS. A grep for
    "120" would be satisfied by this docstring.
    """
    probe = _load_worker_with_committed_defaults(monkeypatch)

    ceiling = getattr(probe, "RUN_TIMEOUT_MINUTES", None)
    assert ceiling is not None, (
        "worker.py must define RUN_TIMEOUT_MINUTES — without a run-level ceiling a "
        "hung engine blocks its instance forever (run d6bb3aae, 1472 minutes)"
    )
    assert isinstance(ceiling, float), (
        "RUN_TIMEOUT_MINUTES must be read as a float (like POLL_INTERVAL_SECONDS, "
        "unlike STALE_RUN_MINUTES) so a test can collapse it sub-minute without a "
        "code change"
    )
    assert ceiling >= LONGEST_LEGITIMATE_RUN_MINUTES, (
        f"RUN_TIMEOUT_MINUTES is {ceiling}, at or below {LONGEST_LEGITIMATE_RUN_MINUTES} "
        "minutes — the measured wall clock of run 7dcf51d5, which COMPLETED "
        "legitimately (23.3-CONTEXT.md § 1). A ceiling here does not merely kill that "
        "run, it destroys the ~$25-45 it had already spent. If you are lowering this, "
        "you need a new duration measurement, not a preference."
    )


# ===========================================================================
# LAYER B — REAL POSTGRES.
#
# These need a migrated database. `DATABASE_URL` unset == a LOUD SKIP, and a
# skip is NOT a pass: the backstop is then asserted only as a number, and the
# behaviour it exists for — a bounded hang, a worded failure, a queue that keeps
# moving — is UNPROVEN.
# ===========================================================================


def _require_database_url() -> str:
    """The DSN, or a clean skip. Same contract as test_run_state_cas.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set — these drive the real `execute_run` against a "
            "real `run` row, because the thing under test is a terminal DB write "
            "under an ownership fence. A skip here is NOT a pass: without them the "
            "ceiling is asserted only as a number, never as a bounded hang."
        )
    return url


@pytest.fixture
async def live_engine():
    """Async engine bound to a real, migrated Postgres."""
    url = _require_database_url()
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")
    engine = sa.create_async_engine(
        url,
        echo=False,
        future=True,
        connect_args={"server_settings": {"search_path": "tribunal,public"}},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def one_org(live_engine):
    """One ephemeral org, CASCADE-cleaned at teardown so the suite reruns."""
    from sqlalchemy import text as sql

    tenant = uuid.uuid4()
    async with live_engine.begin() as conn:
        await conn.execute(
            sql(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            {
                "id": tenant,
                "name": "Tenant (timeout backstop test)",
                "slug": f"tmo-{tenant.hex[:8]}",
            },
        )
    yield tenant
    async with live_engine.begin() as conn:
        await conn.execute(sql("DELETE FROM org WHERE id = :a"), {"a": tenant})


def _sessionmaker(live_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_running_run(live_engine, tenant_id):
    """A project + a run already in 'running', OWNED BY THIS PROCESS.

    `worker_id` is the live module `WORKER_ID` because every terminal write in
    `execute_run` carries the D-23.1-06 ownership fence `AND worker_id = :wid`.
    A row seeded with any other worker id would make every one of these writes a
    silent no-op, and the tests would read the seeded status back and call it a
    pass. `started_at` is stamped because it is the CR-01 fencing token and a
    'running' row without one is not a shape production ever produces.
    """
    from nestor_pulse_sdk.db.models import Project, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs import worker

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            session.add(Project(
                id=project_id, tenant_id=tenant_id, name="Timeout backstop project",
            ))
            session.add(Run(
                id=run_id, tenant_id=tenant_id, project_id=project_id,
                engine="tribunal", brief="brief", status="running",
                idempotency_key=uuid.uuid4(), worker_id=worker.WORKER_ID,
                started_at=_now_utc(),
            ))
    return run_id, project_id


def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def _read_run(live_engine, tenant_id, run_id):
    """(status, error_message, completed_at) read back under the tenant's context."""
    from sqlalchemy import text as sql

    from nestor_pulse_sdk.db.rls import set_tenant_context

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            return (await session.execute(
                sql(
                    "SELECT status, error_message, completed_at "
                    "FROM run WHERE id = :r"
                ),
                {"r": str(run_id)},
            )).first()


class _HangingRunner:
    """A runner that never returns inside any sane deadline.

    It hangs on `asyncio.sleep`, i.e. at an `await` point, which is precisely the
    class of hang a run-level `asyncio.timeout` CAN interrupt. A synchronous or
    C-extension hang is NOT interruptible and is accepted, undefended, in the
    threat register (T-23.3-04). This stub must not be read as covering that case.
    """

    def __init__(self):
        self.entered = False

    async def run(self, *, brief, run_id, tenant_id):  # noqa: ARG002
        self.entered = True
        await asyncio.sleep(3600)
        raise AssertionError("unreachable: the stub runner must never complete")


class _ImmediateRunner:
    """A runner that returns a normal, complete result at once."""

    def __init__(self, text_body="a report body"):
        self._text = text_body
        self.entered = False

    async def run(self, *, brief, run_id, tenant_id):  # noqa: ARG002
        self.entered = True
        return {"output_text": self._text}


def _bind_worker_to(live_engine, monkeypatch):
    """Make `execute_run` use THIS test's engine.

    NOT a convenience — without it this file is order-dependent and lies.
    `db.base.get_engine()` is `lru_cache`d PER PROCESS, while pytest-asyncio gives
    every test its OWN event loop. So the first test to open a connection caches an
    engine whose pooled asyncpg connections belong to a loop that is closed by the
    time the next test runs; `pool_pre_ping` then fails with "Event loop is closed"
    and `execute_run`'s generic `except Exception` writes 'failed'. That is a
    HARNESS artifact wearing the exact costume of a real regression: it made the
    comparability guard below report a completed run as 'failed'.

    `worker` binds `get_sessionmaker` at module import, so the patch target is the
    name in `worker`, not in `db.base`. `_heartbeat_loop` reads the same module
    global and is therefore bound too. Nothing under test is bypassed: the branch,
    the fenced SQL and the tenant context all still execute against a real Postgres.
    """
    from nestor_pulse_sdk.runs import worker

    monkeypatch.setattr(worker, "get_sessionmaker", lambda: _sessionmaker(live_engine))


def _install_runner(monkeypatch, runner):
    """Patch the LAZY import target.

    `execute_run` does `from nestor_pulse_sdk.runs.adapter import dispatch_runner`
    INSIDE the function, so the attribute on the adapter module is re-read on every
    call and patching a name in `worker` would patch nothing.
    """
    import nestor_pulse_sdk.runs.adapter as adapter

    monkeypatch.setattr(adapter, "dispatch_runner", lambda engine: runner)


def _claimed(run_id, tenant_id):
    from nestor_pulse_sdk.runs import worker

    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "engine": "tribunal",
        "brief": "brief",
        "worker_id": worker.WORKER_ID,
    }


async def _execute_bounded(claimed, *, ceiling_existed_before_patch=None):
    """Drive `execute_run` under the TEST's own deadline.

    At HEAD there is no ceiling at all, so the inner call would never return. The
    `wait_for` turns that into a readable failure instead of a suite that hangs.

    `ceiling_existed_before_patch` must be sampled BEFORE the monkeypatch, because
    the patch is applied with `raising=False` and therefore CREATES the attribute:
    a `hasattr` read taken here would report `True` at HEAD and send the next reader
    looking in the wrong place.
    """
    from nestor_pulse_sdk.runs import worker

    try:
        await asyncio.wait_for(
            worker.execute_run(claimed), timeout=_OUTER_DEADLINE_SECONDS
        )
    except (asyncio.TimeoutError, TimeoutError):
        pytest.fail(
            f"execute_run did not return within {_OUTER_DEADLINE_SECONDS}s while the "
            f"run-level ceiling was set to {_TEST_CEILING_MINUTES} minutes "
            f"(~{_TEST_CEILING_MINUTES * 60:.1f}s). The engine await is NOT BOUNDED — "
            "this is run d6bb3aae's 1472-minute hang, reproduced. "
            "worker.py defined RUN_TIMEOUT_MINUTES before this test patched it: "
            f"{ceiling_existed_before_patch}. "
            "Do not raise this deadline; wire the ceiling."
        )


async def _run_until_timeout(live_engine, tenant_id, monkeypatch):
    """Seed a running run, hang it, and let the ceiling fail it. Returns the row."""
    from nestor_pulse_sdk.runs import worker

    run_id, _ = await _seed_running_run(live_engine, tenant_id)
    runner = _HangingRunner()
    _install_runner(monkeypatch, runner)
    _bind_worker_to(live_engine, monkeypatch)
    existed = hasattr(worker, "RUN_TIMEOUT_MINUTES")
    monkeypatch.setattr(
        worker, "RUN_TIMEOUT_MINUTES", _TEST_CEILING_MINUTES, raising=False
    )
    # Keep the heartbeat quiet: at 30s it would never fire inside a 1.2s ceiling
    # anyway, but pinning it makes the test independent of the ambient env var.
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_SECONDS", 30.0, raising=False)

    await _execute_bounded(
        _claimed(run_id, tenant_id), ceiling_existed_before_patch=existed
    )

    assert runner.entered, (
        "the stub runner was never entered — the test patched the wrong dispatch "
        "target and is proving nothing"
    )
    return run_id, await _read_run(live_engine, tenant_id, run_id)


async def test_a_hung_run_is_bounded_and_failed(live_engine, one_org, monkeypatch):
    """THE DEFECT. A run hung at an await is cancelled at the ceiling and failed."""
    run_id, row = await _run_until_timeout(live_engine, one_org, monkeypatch)

    assert row is not None, f"run {run_id} vanished"
    status, _error_message, completed_at = row
    assert status == "failed", (
        f"a run stopped by the ceiling must be finalized 'failed', got {status!r}. "
        "Leaving it in 'running' would be worse than the hang: the intake's retry "
        "gate excludes 'running', so nothing could ever move it."
    )
    assert completed_at is not None, (
        "a timed-out run must carry completed_at — the row is terminal"
    )


async def test_the_timed_out_run_carries_a_worded_reason(
    live_engine, one_org, monkeypatch
):
    """The assertion a `except Exception` fallthrough FAILS.

    `asyncio.TimeoutError` IS the builtin `TimeoutError` in 3.11+, and it derives
    from `Exception`. Caught by the generic handler, `str(exc)` for a bare
    `TimeoutError` is `""` — a `failed` run with NO reason at all. The hang test
    above passes on that fix. This one does not.
    """
    from nestor_pulse_sdk.runs import worker

    _run_id, row = await _run_until_timeout(live_engine, one_org, monkeypatch)
    _status, error_message, _completed_at = row

    assert error_message, (
        "error_message is empty — a bare TimeoutError fell through to the generic "
        "`except Exception` handler, which writes str(exc), and str(TimeoutError()) "
        "is the EMPTY STRING. The run is failed with no reason a human can read."
    )
    assert len(error_message) > 40, (
        f"error_message is {len(error_message)} characters ({error_message!r}) — the "
        "register here is a plain sentence a person reads, like _reap_message(), "
        "never a code"
    )
    assert f"{worker.RUN_TIMEOUT_MINUTES:g}" in error_message, (
        f"error_message must name the ceiling that stopped the run "
        f"({worker.RUN_TIMEOUT_MINUTES:g} minutes) so whoever opens it can tell a "
        f"ceiling from a crash. Got: {error_message!r}"
    )
    assert "TimeoutError" not in error_message, (
        "an exception repr is not a reason. Got: " + repr(error_message)
    )


async def test_the_queue_keeps_moving_after_a_timeout(
    live_engine, one_org, monkeypatch
):
    """The ceiling must RELEASE the instance, not merely relabel a row.

    23.3-CONTEXT.md § 12 point 2: proven by a second run completing after the first
    was stuck, not by the first eventually being marked failed.
    """
    from nestor_pulse_sdk.runs import worker

    _first_id, first_row = await _run_until_timeout(live_engine, one_org, monkeypatch)
    assert first_row[0] == "failed", "precondition: the first run must have timed out"

    second_id, _ = await _seed_running_run(live_engine, one_org)
    second_runner = _ImmediateRunner()
    _install_runner(monkeypatch, second_runner)
    _bind_worker_to(live_engine, monkeypatch)
    # The ceiling stays collapsed: a run that finishes at once must be unaffected
    # by it, and leaving it collapsed proves the ceiling is not simply inert now.
    existed = hasattr(worker, "RUN_TIMEOUT_MINUTES")
    monkeypatch.setattr(
        worker, "RUN_TIMEOUT_MINUTES", _TEST_CEILING_MINUTES, raising=False
    )

    await _execute_bounded(
        _claimed(second_id, one_org), ceiling_existed_before_patch=existed
    )

    assert second_runner.entered, "the second run never reached its runner"
    status, _error_message, _completed_at = await _read_run(
        live_engine, one_org, second_id
    )
    assert status != "failed", (
        f"the run AFTER a timed-out one came back {status!r} — the ceiling did not "
        "release the instance, it poisoned it"
    )
    assert status == "completed", (
        f"expected the second run to reach 'completed', got {status!r}"
    )


async def test_a_run_inside_the_ceiling_is_untouched(live_engine, one_org, monkeypatch):
    """COMPARABILITY GUARD — expected green BEFORE and AFTER this plan.

    This is NOT proof of the fix. It is proof the fix costs nothing: phase 23.3
    changes SCHEDULING only and no plan may alter what a run produces
    (23.3-CONTEXT.md § 9). A run that finishes inside the ceiling must reach the
    same terminal status, and still write its report body, exactly as at HEAD.
    """
    from sqlalchemy import text as sql

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs import worker

    run_id, _ = await _seed_running_run(live_engine, one_org)
    runner = _ImmediateRunner("the report body")
    _install_runner(monkeypatch, runner)
    _bind_worker_to(live_engine, monkeypatch)
    # A generous ceiling: 120 minutes is the committed default and this run
    # returns instantly, so the ceiling must be entirely invisible to it.
    existed = hasattr(worker, "RUN_TIMEOUT_MINUTES")
    monkeypatch.setattr(worker, "RUN_TIMEOUT_MINUTES", 120.0, raising=False)

    await _execute_bounded(
        _claimed(run_id, one_org), ceiling_existed_before_patch=existed
    )

    status, error_message, completed_at = await _read_run(live_engine, one_org, run_id)
    assert status == "completed", (
        f"a run that finished well inside the ceiling came back {status!r}"
    )
    assert not error_message, (
        f"a completed run must carry no error_message, got {error_message!r}"
    )
    assert completed_at is not None

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, one_org)
            body = (await session.execute(
                sql(
                    "SELECT body FROM output "
                    "WHERE run_id = :r AND format = 'markdown'"
                ),
                {"r": str(run_id)},
            )).scalar_one()
    assert body == "the report body", (
        "the report body must still be persisted — the ceiling wraps ONLY the "
        "engine await, never the terminal writes that follow it"
    )
