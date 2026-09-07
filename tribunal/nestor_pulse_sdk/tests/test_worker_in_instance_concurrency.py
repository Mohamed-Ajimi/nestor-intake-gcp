"""23.3-03 -- IN-INSTANCE CONCURRENCY in `worker_loop`, and the tenant isolation
that concurrency is only safe with.

WHY this file exists
--------------------
`worker_loop` claims one run and then awaits the ENTIRE run before claiming
again (23.3-CONTEXT.md section 3). Concurrency is therefore exactly one run per
instance by construction, and raising `--max-instances` does not help: the
worker takes no HTTP traffic, Cloud Run autoscales a service on request
concurrency, so `maxScale` is INERT and effective instance count equals
`minScale`. Runs are I/O-bound -- 35+ minutes long-polling providers -- so the
high-leverage change is a semaphore of K inside one instance.

⭐ THE TRAP THIS FILE IS BUILT AROUND (23.3-CONTEXT.md trap 6)
--------------------------------------------------------------
**A concurrency test that awaits two runs one after the other PASSES ON THE
SERIAL CODE and proves nothing.** "A finished, then B finished" is exactly what
the defect produces. So every behavioural assertion here proves genuine
INTERLEAVING:

  * `test_two_runs_are_inside_the_engine_at_the_same_moment` puts an
    `asyncio.Barrier(2)` INSIDE the runner stub. The barrier can only trip if
    both runs are inside `runner.run()` at the same instant. On serial code the
    first run parks on the barrier forever and the test times out saying so.
  * `test_the_two_runs_overlap_in_wall_clock_time` uses no barrier at all -- two
    sleeping stubs and `time.monotonic()` on entry and exit -- and asserts the
    two intervals genuinely overlap. It is a second, independent proof with a
    different failure mode, because a barrier proves structure and timestamps
    prove time (23.3-CONTEXT.md section 12 item 1 asks for the timestamps by
    name).

⭐ THE HIGHEST-SEVERITY RISK IN THE PHASE (23.3-CONTEXT.md trap 3)
------------------------------------------------------------------
The claim runs WITHOUT tenant context -- the worker must see every tenant's
queued work -- and `execute_run` calls `set_tenant_context` immediately after.
That ordering is a documented anti-pattern boundary. Under concurrency it
acquires a second requirement: **each concurrent run needs its OWN database
session.** `set_config('app.tenant_id', ..., true)` is TRANSACTION-local, so a
session shared between two concurrent runs would carry one tenant's context into
the other's transaction. That is a cross-tenant defect, not a performance bug.
`test_no_session_is_ever_used_with_two_different_tenants` spies on
`set_tenant_context` and asserts no session object is ever seen with two tenant
ids -- with an ANTI-VACUITY half asserting the spy actually observed BOTH
tenants, because a spy that recorded nothing would otherwise "pass".

WHAT IS PINNED
--------------
Layer A -- PURE (no database; runs in every harness):

  * `test_worker_loop_dispatches_instead_of_awaiting_the_run` -- a source
    tripwire. `worker_loop` must dispatch through `asyncio.create_task` and must
    no longer contain the serial engine await; `_dispatch_one` must release its
    semaphore slot inside a `finally`. This is a TRIPWIRE, not the proof: it
    would be satisfied by code that never actually runs. Tests 1-4 are the proof.

Layer B -- REAL POSTGRES (skips LOUDLY without a DSN; A SKIP IS NOT A PASS):

  * two runs inside the engine simultaneously (barrier),
  * their wall-clock intervals overlapping (timestamps),
  * no session carrying two tenants (the trap-3 gate),
  * a hung run not blocking the queue -- the second run's TERMINAL WRITE LANDS
    FIRST, which is the only form of that claim a serial worker cannot satisfy,
  * `test_at_k_one_the_loop_is_still_serial`, the ROLLBACK GUARANTEE:
    with `NESTOR_WORKER_RUN_CONCURRENCY` unset the barrier must NOT trip.
    ⚠ THIS ONE IS EXPECTED GREEN AT HEAD. It is a comparability guard, not a
    defect gate, and it must never be counted as evidence that the fix works.
  * `test_a_crashing_dispatch_gives_its_slot_back`, the LEAKED-SLOT gate
    (T-23.3-13). ⚠ ALSO EXPECTED GREEN AT HEAD, and for the same reason: a
    serial loop has no slot to leak. It exists because a `sem.release()` that
    only runs on the happy path is invisible to every other test here, and the
    resulting K-1 worker is close to undiagnosable in production.

TWO OF THE SEVEN TESTS ARE GREEN AT HEAD BY DESIGN. Neither is evidence for
this change. The four that are RED at HEAD -- barrier, overlap, isolation,
hang-ordering -- are the whole of the evidence.

WHY THE WORKER ROLE IS REQUIRED
-------------------------------
`CLAIM_SQL` is a cross-tenant UPDATE issued with NO `app.tenant_id` set. Under
FORCE ROW LEVEL SECURITY that matches ZERO rows for `app_user`; only a role that
satisfies the `run_worker_all` policy of migration 0008 (`current_user =
'worker_user'`) can claim. That is exactly how production works -- the worker
service mounts `DATABASE_URL_WORKER`. So these tests read `DATABASE_URL_WORKER`
first and fall back to `DATABASE_URL`, and a fixture PROVES the chosen role can
see the seeded rows without tenant context before any assertion is made. If it
cannot, the file skips loudly rather than reporting a green run that never
claimed anything.

WHY THE QUARANTINE FIXTURE EXISTS
---------------------------------
`worker_loop` claims the OLDEST claimable run in the WHOLE database, not the
oldest one this test seeded. A developer database with pre-existing `queued`
rows would therefore have the loop under test claim, execute and finalize
somebody else's rows. `queued_runs_quarantined` holds `SELECT ... FOR UPDATE` on
every pre-existing claimable row for the duration of the test: `CLAIM_SQL`'s own
`FOR UPDATE SKIP LOCKED` then skips them, non-destructively, and the lock is
released by a rollback at teardown. It PROVES it worked (a second connection
must find nothing claimable) rather than assuming it. The stale-'running' claim
branch is neutralised separately, by parking `STALE_RUN_MINUTES` a year out --
which also stops `REAP_SQL` from failing a stranger's row on an idle tick.

HOW THE STUB RUNNER IS INJECTED
-------------------------------
`execute_run` imports `dispatch_runner` LAZILY, inside the function body, so
patching a name bound in `worker` would patch nothing. The patch target is the
attribute on `nestor_pulse_sdk.runs.adapter`.

Fixture helpers are COPIED from `test_run_state_cas.py` / the 23.3-01 timeout
file rather than imported. That duplication is this suite's deliberate house
style: cross-module fixture imports are what make these files order-dependent,
and this suite already carries one reproducible cross-file pollution defect
(DEF-23.2-14).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest


# How long a DB-backed test waits for the scenario it set up to complete. The
# stubs finish in well under a second, so a breach means the scenario never
# happened -- do NOT raise this to make a test pass.
_OUTER_DEADLINE_SECONDS = 20.0

# How long the K=1 rollback guard watches for a barrier that must NOT trip.
_SERIAL_OBSERVATION_SECONDS = 5.0

# Park staleness a year out for the duration of every test here, so neither the
# stale-reclaim branch of CLAIM_SQL nor REAP_SQL can touch a row this test did
# not create. See "WHY THE QUARANTINE FIXTURE EXISTS" above.
_STALENESS_PARKED_MINUTES = 525600

# The collapsed run-level ceiling used by the hang test: 0.06 min = 3.6 s.
_TEST_CEILING_MINUTES = 0.06


# ===========================================================================
# LAYER A -- PURE. No DB, no network, no key.
# ===========================================================================


def _fn_ast(fn):
    """The `ast.FunctionDef`/`AsyncFunctionDef` node for a live function object.

    ⛔ WHY AST AND NOT A SUBSTRING SEARCH. The first version of this gate asked
    `"finally" in inspect.getsource(_dispatch_one)` and `sem.release()` after it.
    Both are satisfied BY THE DOCSTRING -- `_dispatch_one`'s docstring contains
    the sentence "THE SLOT IS RELEASED IN THE `finally`". A counterfactual build
    with the release moved OUT of the `finally` and onto the happy path only was
    measured passing that gate. A grep-shaped gate over a file whose comments
    describe the very construct being greppped for is decoration, and this
    repository has been bitten by that exact shape before. The tree cannot be
    fooled by prose.
    """
    import ast
    import textwrap

    module = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = module.body[0]
    assert isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)), (
        f"could not parse {fn!r} back to a function definition -- this gate would "
        "be vacuous"
    )
    return node


def _calls_named(node, name):
    """Every `ast.Call` in `node` whose callee is `name` or `x.name`."""
    import ast

    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == name:
            out.append(sub)
        elif isinstance(func, ast.Attribute) and func.attr == name:
            out.append(sub)
    return out


def test_worker_loop_dispatches_instead_of_awaiting_the_run():
    """SOURCE TRIPWIRE -- not the proof, and not to be read as one.

    Green source text says nothing about whether two runs ever actually overlap;
    the DB-backed tests below are the evidence. What this catches is a later edit
    that quietly restores the serial await or drops the slot release, in a
    harness with no database where the real gates only skip.

    Every assertion here is made against the PARSED SYNTAX TREE, never a
    substring of the source, because both functions under test carry long
    comments that name the very constructs being checked -- see `_fn_ast`.
    """
    import ast

    from nestor_pulse_sdk.runs import worker

    loop = _fn_ast(worker.worker_loop)
    assert loop.body, "worker_loop parsed to an empty body -- this gate is vacuous"

    dispatch_fn = getattr(worker, "_dispatch_one", None)
    assert dispatch_fn is not None, (
        "worker.py must define `_dispatch_one` -- the per-run dispatch coroutine "
        "that owns the semaphore slot. Without it there is nowhere for the slot to "
        "be released on the failure paths."
    )
    dispatch = _fn_ast(dispatch_fn)
    assert dispatch.body, "_dispatch_one parsed to an empty body"

    assert _calls_named(loop, "create_task"), (
        "worker_loop must dispatch each claimed run with asyncio.create_task. "
        "Without it the loop cannot claim a second run until the first has "
        "finished, which is the whole defect (23.3-CONTEXT.md section 3)."
    )
    serial_awaits = [
        n
        for n in ast.walk(loop)
        if isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "execute_run_locked"
    ]
    assert not serial_awaits, (
        "worker_loop still awaits execute_run_locked directly. That single "
        "expression IS the one-run-per-instance defect: the entire run is awaited "
        "before the next claim. It belongs in _dispatch_one now."
    )
    assert _calls_named(loop, "run_concurrency"), (
        "worker_loop must size its semaphore from concurrency.run_concurrency(), "
        "the ONE reader of NESTOR_WORKER_RUN_CONCURRENCY (plan 23.3-02). A second "
        "reader is how K and the process LLM budget silently disagree."
    )

    tries = [n for n in ast.walk(dispatch) if isinstance(n, ast.Try)]
    assert tries, (
        "_dispatch_one contains no try/finally at all, so there is no path on "
        "which the slot is guaranteed to come back"
    )
    released_in_finally = [
        call
        for t in tries
        for stmt in t.finalbody
        for call in _calls_named(stmt, "release")
    ]
    assert released_in_finally, (
        "no `release()` call appears in any `finally` body of _dispatch_one. The "
        "slot must come back on EVERY path -- success, RunCancelled, exception, "
        "and plan 23.3-01's TimeoutError branch. A slot leaked on a failure path "
        "shrinks the worker to K-1 for the life of the process, and the symptom "
        "(throughput quietly halving some time after an unrelated failure) is "
        "close to undiagnosable. NOTE: a docstring or comment saying the release "
        "is in a finally does NOT satisfy this assertion, which is the point."
    )


# ===========================================================================
# LAYER B -- REAL POSTGRES.
# ===========================================================================


def _require_worker_database_url() -> str:
    """The worker-role DSN, or a LOUD skip.

    `DATABASE_URL_WORKER` first: CLAIM_SQL is a cross-tenant statement run with
    no `app.tenant_id`, and under FORCE RLS only the `run_worker_all` role
    (migration 0008) matches any row. `DATABASE_URL` is accepted as a fallback
    because a CI harness may already point it at that role; the
    `two_queued_runs` fixture proves the role can actually see the rows before
    any assertion is made.
    """
    url = os.environ.get("DATABASE_URL_WORKER") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "neither DATABASE_URL_WORKER nor DATABASE_URL is set -- these tests "
            "drive the REAL worker_loop against a REAL claim, because the thing "
            "under test is whether two claims can be in flight at once. A skip "
            "here is NOT a pass: with them skipped, in-instance concurrency is "
            "asserted only as source text and never as behaviour."
        )
    return url


@pytest.fixture
async def worker_engine():
    """Async engine on the worker role -- the same role production mounts."""
    url = _require_worker_database_url()
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


def _sessionmaker(engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def two_tenants(worker_engine):
    """TWO ephemeral orgs. Two, not one, because the isolation gate is the point:
    a session leaking `app.tenant_id` between two runs of the SAME tenant is
    invisible."""
    from sqlalchemy import text as sql

    a, b = uuid.uuid4(), uuid.uuid4()
    async with worker_engine.begin() as conn:
        for tenant, label in ((a, "A"), (b, "B")):
            await conn.execute(
                sql(
                    "INSERT INTO org (id, name, slug, retention_days) "
                    "VALUES (:id, :name, :slug, 180)"
                ),
                {
                    "id": tenant,
                    "name": f"Tenant {label} (in-instance concurrency test)",
                    "slug": f"cc{label.lower()}-{tenant.hex[:8]}",
                },
            )
    yield a, b
    async with worker_engine.begin() as conn:
        await conn.execute(sql("DELETE FROM org WHERE id IN (:a, :b)"), {"a": a, "b": b})


@pytest.fixture
async def queued_runs_quarantined(worker_engine):
    """Hold `SELECT ... FOR UPDATE` on every PRE-EXISTING claimable run.

    `CLAIM_SQL` picks the oldest claimable row in the whole database. On a
    developer database with a backlog, the loop under test would claim, execute
    and finalize rows belonging to somebody else's work. Locking them makes
    `CLAIM_SQL`'s own `FOR UPDATE SKIP LOCKED` skip them -- no writes, no
    deletes, and the lock disappears on the teardown rollback.

    It PROVES the quarantine holds instead of assuming it: a second connection
    must find nothing claimable afterwards. If that check ever fails, every test
    in this file could be silently measuring a stranger's run.

    Only the `status='queued'` branch is locked here. The stale-'running' branch
    is neutralised by `_bind_worker`, which parks STALE_RUN_MINUTES a year out --
    that also stops REAP_SQL from failing a stranger's row on an idle tick.
    """
    from sqlalchemy import text as sql

    conn = await worker_engine.connect()
    txn = await conn.begin()
    try:
        locked = (
            await conn.execute(sql("SELECT id FROM run WHERE status = 'queued' FOR UPDATE"))
        ).all()
        async with worker_engine.connect() as probe:
            leftover = (
                await probe.execute(
                    sql(
                        "SELECT id FROM run WHERE status = 'queued' "
                        "FOR UPDATE SKIP LOCKED"
                    )
                )
            ).first()
            await probe.rollback()
        assert leftover is None, (
            f"quarantine FAILED: run {leftover[0]} is still claimable by another "
            "session. The worker_loop under test would claim a row this test did "
            "not create, execute a stub against it and finalize it. This is a "
            "setup failure, not a pass."
        )
        yield len(locked)
    finally:
        await txn.rollback()
        await conn.close()


def _now_utc():
    return datetime.now(timezone.utc)


async def _seed_queued_run(engine, tenant_id, *, created_at, label):
    """A project + a `queued` run, ready for the REAL CLAIM_SQL to claim.

    `queued`, not `running`: the point of this file is the claim-and-dispatch
    loop, so the run must go through `claim_one` -> `execute_run_locked` (the
    64-bit advisory lock and the CR-01 fencing-token consume) -> `execute_run`
    exactly as production does. Nothing on that path is stubbed except the
    engine itself.
    """
    from nestor_pulse_sdk.db.models import Project, Run

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with _sessionmaker(engine)() as session:
        async with session.begin():
            session.add(
                Project(
                    id=project_id,
                    tenant_id=tenant_id,
                    name=f"Concurrency project {label}",
                )
            )
            session.add(
                Run(
                    id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    engine="tribunal",
                    brief=f"brief {label}",
                    status="queued",
                    idempotency_key=uuid.uuid4(),
                    created_at=created_at,
                )
            )
    return run_id


@pytest.fixture
async def two_queued_runs(worker_engine, two_tenants, queued_runs_quarantined):
    """One queued run per tenant, A strictly older than B so A is claimed first.

    Also the PREFLIGHT for the whole file: it asserts the connected role can see
    both rows with NO tenant context set. That is precisely what `CLAIM_SQL`
    does, and a role that cannot would make every test here claim nothing and
    time out for a reason that has nothing to do with concurrency.
    """
    from sqlalchemy import text as sql

    tenant_a, tenant_b = two_tenants
    base = _now_utc() - timedelta(days=3650)
    run_a = await _seed_queued_run(worker_engine, tenant_a, created_at=base, label="A")
    run_b = await _seed_queued_run(
        worker_engine, tenant_b, created_at=base + timedelta(seconds=1), label="B"
    )

    async with worker_engine.connect() as conn:
        who = (await conn.execute(sql("SELECT current_user"))).scalar_one()
        visible = (
            await conn.execute(
                sql("SELECT count(*) FROM run WHERE id IN (:a, :b)"),
                {"a": run_a, "b": run_b},
            )
        ).scalar_one()
    if visible != 2:
        pytest.skip(
            f"the connected role {who!r} sees {visible} of the 2 seeded runs with no "
            "app.tenant_id set, so it cannot perform the cross-tenant CLAIM_SQL that "
            "these tests exist to exercise. Point DATABASE_URL_WORKER at the role "
            "that satisfies the run_worker_all policy of migration 0008 (production "
            "mounts DATABASE_URL_WORKER for exactly this reason). A skip here is NOT "
            "a pass."
        )
    return run_a, run_b, tenant_a, tenant_b


# ---------------------------------------------------------------------------
# Runner stubs. NOTHING here touches a provider: no key is read, no network call
# is made, and no run costs anything.
# ---------------------------------------------------------------------------


class _RoutingRunner:
    """One runner object serving both runs, routing on `run_id`.

    `dispatch_runner(engine)` is handed the ENGINE STRING, not the run, so a
    single object has to serve every concurrent run -- which is also exactly how
    production behaves.

    A run this test did not seed raises `RunCancelled`, which `execute_run`
    treats as "user cancelled": it returns WITHOUT any terminal write. That is
    the least destructive response to a claim that should have been impossible,
    and `foreign` records it so the test can fail loudly instead of silently
    measuring a stranger's run.
    """

    def __init__(self, behaviours):
        self._behaviours = behaviours
        self.entered: list[str] = []
        self.foreign: list[str] = []
        self.marks: dict[str, dict[str, float]] = {}

    async def run(self, *, brief, run_id, tenant_id):  # noqa: ARG002
        key = str(run_id)
        behaviour = self._behaviours.get(key)
        if behaviour is None:
            from nestor_pulse_sdk.runs.stages import RunCancelled

            self.foreign.append(key)
            raise RunCancelled(f"run {key} was not seeded by this test")
        self.entered.append(key)
        self.marks.setdefault(key, {})["start"] = time.monotonic()
        result = await behaviour()
        self.marks.setdefault(key, {})["end"] = time.monotonic()
        return result


def _barrier_behaviours(run_a, run_b, barrier, tripped):
    """Both runs park on ONE `asyncio.Barrier(2)`.

    ⭐ This is the entire test, not decoration. The barrier can only release if
    BOTH coroutines are inside `runner.run()` at the same instant. On the serial
    loop the first run waits there forever and the second is never claimed.
    """

    async def _wait():
        await barrier.wait()
        tripped.append(time.monotonic())
        return {"output_text": "a report body"}

    return {str(run_a): _wait, str(run_b): _wait}


def _sleeping_behaviours(run_a, run_b, seconds):
    """No barrier at all -- just two runs that take time.

    Deliberately a DIFFERENT mechanism from the barrier test so the two proofs
    fail independently: this one is about wall-clock overlap, which is what
    23.3-CONTEXT.md section 12 item 1 asks for in its own words.
    """

    async def _slow():
        await asyncio.sleep(seconds)
        return {"output_text": "a report body"}

    return {str(run_a): _slow, str(run_b): _slow}


def _install_runner(monkeypatch, runner):
    """Patch the LAZY import target.

    `execute_run` does `from nestor_pulse_sdk.runs.adapter import dispatch_runner`
    INSIDE the function body, so the attribute on the adapter module is re-read on
    every call and patching a name in `worker` would patch nothing.
    """
    import nestor_pulse_sdk.runs.adapter as adapter

    monkeypatch.setattr(adapter, "dispatch_runner", lambda engine: runner)


def _bind_worker(monkeypatch, engine):
    """Point every DB path the loop uses at THIS test's engine, and park the
    clocks that would otherwise reach rows this test did not create.

    `db.base.get_engine()` is `lru_cache`d PER PROCESS while pytest-asyncio gives
    every test its own event loop, so a cached engine's pooled connections belong
    to a closed loop by the next test and `pool_pre_ping` fails with "Event loop
    is closed" -- a harness artifact that wears the exact costume of a real
    regression (23.3-01 deviation 1).

    THREE bindings are needed, not one. `worker` binds `get_sessionmaker` at
    import; `runs.execute` binds its OWN copy at import (it takes the advisory
    lock and consumes the fencing token on a session of its own); and
    `_heartbeat_loop` reads the `worker` module global. Missing the `runs.execute`
    one leaves the advisory lock talking to a different engine, which is not a
    test failure so much as a test that quietly proves less than it says.
    """
    import nestor_pulse_sdk.runs.execute as execute_mod
    from nestor_pulse_sdk.runs import worker

    maker = _sessionmaker(engine)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(execute_mod, "get_sessionmaker", lambda: maker)
    # Poll fast: an idle tick must not dominate a 20 s deadline.
    monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.05, raising=False)
    # 30 s heartbeat: never fires inside these tests, and pinning it makes the
    # file independent of the ambient NESTOR_WORKER_HEARTBEAT_S.
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_SECONDS", 30.0, raising=False)
    # Park staleness: no pre-existing 'running' row can be reclaimed or reaped.
    monkeypatch.setattr(
        worker, "STALE_RUN_MINUTES", _STALENESS_PARKED_MINUTES, raising=False
    )


def _set_concurrency(monkeypatch, k):
    """K for this test. `None` == the variable UNSET, i.e. today's serial worker.

    `run_concurrency()` is read by `worker_loop` when the loop starts, so setting
    the variable before the task is created is what takes effect.
    """
    if k is None:
        monkeypatch.delenv("NESTOR_WORKER_RUN_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("NESTOR_WORKER_RUN_CONCURRENCY", str(k))


@pytest.fixture(autouse=True)
def _no_concurrency_leak(monkeypatch):
    """Never let this file leave a K>1 or a collapsed ceiling behind it.

    A module-level env var set by one test file and read at import by another is
    the documented DEF-23.2-14 shape. `monkeypatch` undoes the sets, and these
    deletes cover an ambient value inherited from the shell.
    """
    monkeypatch.delenv("NESTOR_WORKER_RUN_CONCURRENCY", raising=False)
    monkeypatch.delenv("NESTOR_WORKER_RUN_TIMEOUT_MINUTES", raising=False)
    yield


async def _cancel_stragglers():
    """Cancel any dispatch/heartbeat task still alive after the loop is stopped.

    Cancelling `worker_loop` does NOT cancel the tasks it created -- that is the
    point of `create_task`. A stub parked on a barrier that will never trip would
    otherwise outlive its test, hold a DB connection, and be reported by asyncio
    as "Task was destroyed but it is pending".
    """
    me = asyncio.current_task()
    victims = [
        t
        for t in asyncio.all_tasks()
        if t is not me
        and not t.done()
        and getattr(t.get_coro(), "__name__", "")
        in ("_dispatch_one", "execute_run", "execute_run_locked", "_heartbeat_loop")
    ]
    for t in victims:
        t.cancel()
    if victims:
        await asyncio.gather(*victims, return_exceptions=True)


async def _read_runs(engine, run_ids):
    """{run_id: (status, error_message, completed_at)} read with the worker role."""
    from sqlalchemy import text as sql

    async with _sessionmaker(engine)() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    sql(
                        "SELECT id, status, error_message, completed_at FROM run "
                        "WHERE id = ANY(:ids)"
                    ),
                    {"ids": [str(r) for r in run_ids]},
                )
            ).all()
    return {str(r[0]): (r[1], r[2], r[3]) for r in rows}


_TERMINAL = {"completed", "completed_degraded", "failed", "cancelled", "parked"}


async def _wait_for_all_terminal(engine, run_ids):
    while True:
        rows = await _read_runs(engine, run_ids)
        if len(rows) == len(run_ids) and all(v[0] in _TERMINAL for v in rows.values()):
            return rows
        await asyncio.sleep(0.05)


async def _drive_worker_loop(waiter_factory, *, deadline):
    """Run the REAL `worker_loop` as a task until `waiter_factory()` completes.

    Returns "done", "timeout", or re-raises if `worker_loop` itself died -- a
    loop that crashed would otherwise look identical to a loop that was simply
    too slow, and the two need completely different fixes.
    """
    from nestor_pulse_sdk.runs import worker

    loop_task = asyncio.create_task(worker.worker_loop())
    waiter = asyncio.create_task(waiter_factory())
    try:
        done, _pending = await asyncio.wait(
            {loop_task, waiter},
            timeout=deadline,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if loop_task in done:
            exc = loop_task.exception()
            raise AssertionError(
                "worker_loop returned or crashed instead of polling: "
                f"{exc!r}. Every assertion below would be meaningless."
            )
        return "done" if waiter in done else "timeout"
    finally:
        waiter.cancel()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
        await _cancel_stragglers()


# ---------------------------------------------------------------------------
# 1 -- GENUINE INTERLEAVING (the phase's headline claim)
# ---------------------------------------------------------------------------


async def test_two_runs_are_inside_the_engine_at_the_same_moment(
    worker_engine, two_queued_runs, monkeypatch
):
    """⭐ THE HEADLINE. Two runs, two tenants, both inside `runner.run()` at once.

    The `asyncio.Barrier(2)` is the whole test. It releases only when both
    coroutines have reached it, so it cannot be satisfied by "A finished, then B
    started" -- the shape a serial loop produces and the shape 23.3-CONTEXT.md
    trap 6 warns is the usual way a concurrency test lies.
    """
    run_a, run_b, _tenant_a, _tenant_b = two_queued_runs
    barrier = asyncio.Barrier(2)
    tripped: list[float] = []
    runner = _RoutingRunner(_barrier_behaviours(run_a, run_b, barrier, tripped))
    _install_runner(monkeypatch, runner)
    _bind_worker(monkeypatch, worker_engine)
    _set_concurrency(monkeypatch, 2)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_a, run_b]),
        deadline=_OUTER_DEADLINE_SECONDS,
    )

    assert not runner.foreign, (
        f"the loop claimed runs this test did not seed: {runner.foreign}. The "
        "quarantine fixture did not hold and this result means nothing."
    )
    assert outcome == "done", (
        f"the two seeded runs did not both reach a terminal status within "
        f"{_OUTER_DEADLINE_SECONDS}s. The barrier the runner stub waits on needs "
        "BOTH runs inside runner.run() at the same instant to release, so this is "
        "the serial loop: the second run was never dispatched while the first was "
        "still executing. Runs that entered the engine: "
        f"{len(runner.entered)} of 2. Do not raise this deadline."
    )
    assert len(tripped) == 2, (
        f"the barrier released {len(tripped)} times instead of 2 -- it did not "
        "actually synchronise two concurrent runs"
    )
    assert sorted(runner.entered) == sorted([str(run_a), str(run_b)]), (
        f"expected exactly the two seeded runs to enter the engine, got "
        f"{runner.entered}"
    )


# ---------------------------------------------------------------------------
# 2 -- OVERLAPPING WALL CLOCK (section 12 item 1, in its own terms)
# ---------------------------------------------------------------------------


async def test_the_two_runs_overlap_in_wall_clock_time(
    worker_engine, two_queued_runs, monkeypatch
):
    """No barrier -- two sleeping runs and two intervals that must overlap.

    An independent proof with an independent failure mode: the barrier test
    proves STRUCTURE (both coroutines suspended in the engine together), this one
    proves TIME. On the serial loop A's interval closes before B's opens and the
    failure message prints both intervals, so a reviewer sees the numbers rather
    than a bare assertion.
    """
    run_a, run_b, _tenant_a, _tenant_b = two_queued_runs
    runner = _RoutingRunner(_sleeping_behaviours(run_a, run_b, 0.4))
    _install_runner(monkeypatch, runner)
    _bind_worker(monkeypatch, worker_engine)
    _set_concurrency(monkeypatch, 2)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_a, run_b]),
        deadline=_OUTER_DEADLINE_SECONDS,
    )
    assert not runner.foreign, f"foreign runs claimed: {runner.foreign}"
    assert outcome == "done", (
        f"both runs did not finish within {_OUTER_DEADLINE_SECONDS}s "
        f"(entered: {runner.entered})"
    )

    a, b = runner.marks.get(str(run_a)), runner.marks.get(str(run_b))
    assert a and b and "end" in a and "end" in b, (
        f"both runs must have entered and left the engine; got {runner.marks!r}"
    )
    origin = min(a["start"], b["start"])
    a_iv = (round(a["start"] - origin, 3), round(a["end"] - origin, 3))
    b_iv = (round(b["start"] - origin, 3), round(b["end"] - origin, 3))
    assert a["start"] < b["end"] and b["start"] < a["end"], (
        f"the two runs did NOT overlap: A occupied {a_iv} and B occupied {b_iv} "
        "(seconds from the first entry). Disjoint intervals are exactly what the "
        "serial loop produces -- one run is awaited to completion before the next "
        "is claimed. 23.3-CONTEXT.md section 12 item 1 asks for overlapping "
        "timestamps, not for both runs eventually completing."
    )


# ---------------------------------------------------------------------------
# 3 -- TRAP 3: no session carries two tenants
# ---------------------------------------------------------------------------


async def test_no_session_is_ever_used_with_two_different_tenants(
    worker_engine, two_queued_runs, monkeypatch
):
    """⭐ THE HIGHEST-SEVERITY GATE IN THE PHASE.

    `set_config('app.tenant_id', ..., true)` is TRANSACTION-local. Two concurrent
    runs sharing one session would therefore carry one tenant's context into the
    other's transaction -- a cross-tenant defect, not a performance bug. The
    design that prevents it is that the claim session is CLOSED before dispatch
    and every run reaches the database only through its own per-block sessions.
    This spy is what holds that design in place.

    ANTI-VACUITY, both halves: the spy must have observed at least two calls AND
    both tenant ids. A spy that recorded nothing would satisfy "no session saw
    two tenants" trivially.

    The observed sessions are kept ALIVE in `seen_sessions` on purpose: `id()` is
    a memory address and CPython reuses the address of a freed object, so without
    a strong reference two sequential sessions could report the same id and this
    test would fail on an artifact rather than on a leak.
    """
    from nestor_pulse_sdk.runs import worker

    run_a, run_b, tenant_a, tenant_b = two_queued_runs
    barrier = asyncio.Barrier(2)
    tripped: list[float] = []
    runner = _RoutingRunner(_barrier_behaviours(run_a, run_b, barrier, tripped))
    _install_runner(monkeypatch, runner)
    _bind_worker(monkeypatch, worker_engine)
    _set_concurrency(monkeypatch, 2)

    real_set_tenant_context = worker.set_tenant_context
    records: list[tuple[int, str]] = []
    seen_sessions: list[object] = []

    async def _spy(session, tenant_id):
        records.append((id(session), str(tenant_id)))
        seen_sessions.append(session)
        return await real_set_tenant_context(session, tenant_id)

    monkeypatch.setattr(worker, "set_tenant_context", _spy)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_a, run_b]),
        deadline=_OUTER_DEADLINE_SECONDS,
    )
    assert not runner.foreign, f"foreign runs claimed: {runner.foreign}"
    assert outcome == "done", (
        f"the two runs were never executed concurrently within "
        f"{_OUTER_DEADLINE_SECONDS}s, so this file's isolation gate had nothing "
        "to observe. The barrier did not trip -- the loop is still serial."
    )

    assert len(records) >= 2, (
        f"the spy recorded {len(records)} calls to set_tenant_context. It must see "
        "at least one per run, or it is asserting nothing at all."
    )
    tenants_seen = {t for _sid, t in records}
    assert {str(tenant_a), str(tenant_b)} <= tenants_seen, (
        f"the spy saw tenants {tenants_seen} but the two runs belong to "
        f"{str(tenant_a)} and {str(tenant_b)}. A gate that never observed both "
        "tenants cannot prove they stayed apart."
    )

    per_session: dict[int, set[str]] = {}
    for session_id, tenant in records:
        per_session.setdefault(session_id, set()).add(tenant)
    leaking = {sid: ts for sid, ts in per_session.items() if len(ts) > 1}
    assert not leaking, (
        f"the SAME database session was given more than one tenant id: {leaking}. "
        "app.tenant_id is transaction-local, so a session shared across two "
        "concurrent runs carries one tenant's context into the other's "
        "transaction. This is a cross-tenant defect (23.3-CONTEXT.md trap 3), not "
        "a performance bug: the claim session must be closed before dispatch and "
        "each run must reach the database only through its own sessions."
    )


# ---------------------------------------------------------------------------
# 4 -- A HANG NO LONGER BLOCKS THE QUEUE (section 12 item 2)
# ---------------------------------------------------------------------------


async def test_a_hung_run_does_not_block_the_second_run(
    worker_engine, two_queued_runs, monkeypatch
):
    """The second run's TERMINAL WRITE must land FIRST, while the first is stuck.

    The ordering is the entire assertion. "Both runs eventually reached a
    terminal status" is satisfied by the serial worker too -- plan 23.3-01's
    ceiling already guarantees a hung run is eventually failed and the queue then
    moves on. What a serial worker CANNOT do is finish the second run while the
    first is still hanging, and that is what `completed_at(B) < completed_at(A)`
    measures.

    The ceiling is collapsed so the hung run is cleaned up inside the test rather
    than left running; the hang is at an `await`, which is the only class of hang
    an asyncio ceiling can interrupt (T-23.3-04 is accepted, undefended).
    """
    from nestor_pulse_sdk.runs import worker

    run_a, run_b, _tenant_a, _tenant_b = two_queued_runs

    async def _hang():
        await asyncio.sleep(3600)
        raise AssertionError("unreachable: the hung stub must never complete")

    async def _immediate():
        return {"output_text": "a report body"}

    runner = _RoutingRunner({str(run_a): _hang, str(run_b): _immediate})
    _install_runner(monkeypatch, runner)
    _bind_worker(monkeypatch, worker_engine)
    monkeypatch.setattr(
        worker, "RUN_TIMEOUT_MINUTES", _TEST_CEILING_MINUTES, raising=False
    )
    _set_concurrency(monkeypatch, 2)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_a, run_b]),
        deadline=_OUTER_DEADLINE_SECONDS,
    )
    assert not runner.foreign, f"foreign runs claimed: {runner.foreign}"
    assert outcome == "done", (
        f"both runs did not reach a terminal status within "
        f"{_OUTER_DEADLINE_SECONDS}s (entered: {runner.entered})"
    )

    rows = await _read_runs(worker_engine, [run_a, run_b])
    a_status, _a_err, a_completed = rows[str(run_a)]
    b_status, _b_err, b_completed = rows[str(run_b)]

    assert a_status == "failed", (
        f"the hung run should have been stopped by the run-level ceiling and "
        f"finalized 'failed', got {a_status!r}"
    )
    assert b_status == "completed", (
        f"the second run should have completed normally, got {b_status!r}"
    )
    assert a_completed is not None and b_completed is not None
    assert b_completed < a_completed, (
        f"the second run finalized at {b_completed.isoformat()}, AFTER the hung "
        f"run's {a_completed.isoformat()}. That is the serial worker: run B was "
        "not claimed until run A's ceiling released the instance. A hang must not "
        "hold the queue for the length of the ceiling -- proven by B finishing "
        "WHILE A is stuck, not by both eventually reaching a terminal status "
        "(23.3-CONTEXT.md section 12 item 2)."
    )


# ---------------------------------------------------------------------------
# 5 -- THE ROLLBACK GUARANTEE. ⚠ EXPECTED GREEN AT HEAD.
# ---------------------------------------------------------------------------


async def test_at_k_one_the_loop_is_still_serial(
    worker_engine, two_queued_runs, monkeypatch
):
    """⚠ COMPARABILITY GUARD -- expected green BEFORE and AFTER this plan.

    This is NOT a defect gate and must never be counted as evidence that
    concurrency works. It is the rollback guarantee: with
    `NESTOR_WORKER_RUN_CONCURRENCY` unset the worker behaves exactly as it does
    today, so the deploy can be reverted with one environment variable rather
    than a code change.

    Same barrier as test 1. At K=1 the single slot is held by the first run for
    as long as it is in the engine, so the second run is never claimed and the
    barrier cannot trip.
    """
    run_a, run_b, _tenant_a, _tenant_b = two_queued_runs
    barrier = asyncio.Barrier(2)
    tripped: list[float] = []
    runner = _RoutingRunner(_barrier_behaviours(run_a, run_b, barrier, tripped))
    _install_runner(monkeypatch, runner)
    _bind_worker(monkeypatch, worker_engine)
    _set_concurrency(monkeypatch, None)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_a, run_b]),
        deadline=_SERIAL_OBSERVATION_SECONDS,
    )

    assert not runner.foreign, f"foreign runs claimed: {runner.foreign}"
    assert outcome == "timeout", (
        "with NESTOR_WORKER_RUN_CONCURRENCY unset the barrier TRIPPED, i.e. two "
        "runs were in the engine at once. K=1 must reproduce today's strictly "
        "serial worker exactly -- that is what makes this change revertible by "
        "one environment variable instead of a rollback."
    )
    assert not tripped, f"the barrier released at K=1: {tripped}"
    assert len(runner.entered) == 1, (
        f"exactly one run may be in flight at K=1, but {len(runner.entered)} "
        f"entered the engine: {runner.entered}"
    )


# ---------------------------------------------------------------------------
# 7 -- THE LEAKED SLOT (T-23.3-13). ⚠ EXPECTED GREEN AT HEAD.
# ---------------------------------------------------------------------------


async def test_a_crashing_dispatch_gives_its_slot_back(
    worker_engine, two_queued_runs, monkeypatch
):
    """⚠ NOT a defect gate for the serial loop -- green at HEAD, by construction.

    It exists because nothing else in this file can tell a `finally: sem.release()`
    apart from a `sem.release()` that only runs on the happy path, and a slot
    leaked on a failure path is the quietest failure in this plan's threat
    register: the worker keeps working, just permanently at K-1, and the symptom
    surfaces as "throughput halved some time last week" (T-23.3-13). The source
    tripwire checks the TEXT of the `finally`; this checks the BEHAVIOUR.

    Shape: K=2, three runs. The first two dispatches raise BEFORE any terminal
    write -- `dispatch_runner` itself raises, and that call sits OUTSIDE
    `execute_run`'s try, so the exception travels all the way out to
    `_dispatch_one`'s own handler. That is the hardest path on which to get the
    release right. With both slots consumed and never returned the third run can
    never be claimed and this test times out; with the release in the `finally`
    it completes at once.
    """
    run_a, _run_b, tenant_a, _tenant_b = two_queued_runs
    assert run_a  # the two fixture runs are the two that must crash
    run_c = await _seed_queued_run(
        worker_engine,
        tenant_a,
        created_at=_now_utc() - timedelta(days=3650) + timedelta(seconds=2),
        label="C",
    )

    async def _immediate():
        return {"output_text": "a report body"}

    survivor = _RoutingRunner({str(run_c): _immediate})
    calls: list[str] = []

    def _exploding_dispatch(engine):
        calls.append(engine)
        if len(calls) <= 2:
            raise RuntimeError("dispatch_runner blew up before the run started")
        return survivor

    import nestor_pulse_sdk.runs.adapter as adapter

    monkeypatch.setattr(adapter, "dispatch_runner", _exploding_dispatch)
    _bind_worker(monkeypatch, worker_engine)
    _set_concurrency(monkeypatch, 2)

    outcome = await _drive_worker_loop(
        lambda: _wait_for_all_terminal(worker_engine, [run_c]),
        deadline=_OUTER_DEADLINE_SECONDS,
    )
    assert not survivor.foreign, f"foreign runs claimed: {survivor.foreign}"
    assert len(calls) >= 3, (
        f"only {len(calls)} runs were ever dispatched. The two crashing dispatches "
        "consumed their concurrency slots and never gave them back, so the loop is "
        "parked on an empty semaphore and the third run can never be claimed. The "
        "slot must be released in a `finally`, on EVERY path -- success, "
        "RunCancelled, exception, and plan 23.3-01's TimeoutError branch."
    )
    assert outcome == "done", (
        f"the third run never reached a terminal status within "
        f"{_OUTER_DEADLINE_SECONDS}s after two crashing dispatches; "
        f"dispatch_runner was called {len(calls)} times."
    )
    rows = await _read_runs(worker_engine, [run_c])
    assert rows[str(run_c)][0] == "completed", (
        f"the run after two crashed dispatches came back {rows[str(run_c)][0]!r} "
        "-- a crashed dispatch must not poison the runs that follow it"
    )
    # The two crashed runs are deliberately NOT asserted on. `dispatch_runner`
    # raises before `execute_run` reaches any write, so they stay 'running' with
    # this worker's id and are recovered later by the ordinary stale-reclaim path
    # (23.3-CONTEXT.md section 7). Asserting a terminal status for them here would
    # be asserting a behaviour this plan neither has nor claims.
