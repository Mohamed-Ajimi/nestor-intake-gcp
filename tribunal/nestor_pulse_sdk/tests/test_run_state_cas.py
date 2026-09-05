"""D-23.2-13 — the two Tribunal status flips must be COMPARE-AND-SWAP, not read-then-write.

WHY this file exists
--------------------
`submit_report_spec` and `resume_run` (`runs/api.py`) both did:

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:  -> 404
    if run.status != <expected>:  -> 409
    run.status = "queued"; run.worker_id = None
    await session.flush()

That is a plain read-then-write under READ COMMITTED. Two concurrent callers both read
the expected status and both re-queue the SAME run: the worker re-claims it and re-drives
a pipeline whose stages are paid, on the path that runs with NESTOR_TRIBUNAL_UNCAPPED=1.
For `submit_report_spec` it also writes TWO `report_spec` Outputs, leaving the pipeline's
resume branch an ambiguous spec to read.

Worse, `resume_run`'s docstring asserted the opposite in so many words — "two concurrent
clicks cannot both succeed: the first commits `queued` and the second sees it and 409s".
A comment claiming a guarantee the code does not provide is worse than no comment: it is
what stops the next reader from looking. That sentence is gated out below.

WHAT IS PINNED, AND WHY EACH ASSERTION EXISTS
---------------------------------------------
Layer A — SOURCE GATES (pure; no database, no network, no key):
  * both handlers keep `scalar_one_or_none` + `HTTPException(404` — the read is kept ONLY
    to classify the refusal. Collapsing the pair into one bare UPDATE would turn a
    cross-tenant 404 into a 409, which is an existence oracle (T-23.2-05-03).
  * neither handler mentions the forbidden status code — restated from
    test_checkpoint_resume.py's gate so a regression is caught here too.
  * both handlers contain `rowcount` — the CAS is present, not just intended.
  * `resume_run.__doc__` no longer contains "cannot both succeed", and still documents
    the `parked` allow-list.
  * ANTI-VACUITY: each handler gate iterates a list and asserts it checked exactly 2.

Layer B — REAL POSTGRES (skips loudly without DATABASE_URL; A SKIP IS NOT A PASS):
  * two genuinely concurrent resumes -> EXACTLY one success and EXACTLY one 409.
  * two genuinely concurrent report-spec submissions -> exactly one success, one 409, and
    EXACTLY ONE `report_spec` Output row for the run. That last count is the criterion a
    rollback-only fix would satisfy and an insert-before-CAS-without-rollback would not.
  * the winner's RETURN VALUE reports `queued`, not the pre-flip status. A bulk UPDATE
    leaves the already-loaded ORM instance STALE unless it is synchronised or re-read; a
    CAS that returns the stale instance passes the concurrency test and fails this one,
    and the operator would see `parked` after a successful resume and click again.
  * the refusals are unchanged: a non-`parked` run is still 409 and mutates nothing, a
    run that does not exist is still 404, a cross-tenant run is still 404. Restated here
    so this file is self-contained.

HOW "CONCURRENT" IS MADE DETERMINISTIC — read this before changing the test
--------------------------------------------------------------------------
The defect needs a specific interleaving: BOTH callers must have completed their READ
before EITHER has committed. A test that lets caller A finish entirely before B starts
proves nothing — B's read would already see `queued` and even the OLD read-then-write code
would 409.

So a third connection takes `SELECT ... FOR UPDATE` on the run row FIRST. Readers do not
block in Postgres, so both handlers' SELECTs complete and both see the expected status;
their UPDATEs then block on that row lock. Only once BOTH are observed waiting (polled
through `pg_stat_activity`) is the barrier released. A wins the row lock and commits; B's
UPDATE unblocks, re-evaluates its WHERE against the winner's newly committed row version
under READ COMMITTED, matches zero rows, and 409s. That last step is the ONLY thing
standing between two operators and a duplicated paid run — and it exists solely because
the predicate is in the UPDATE.

The barrier asserts it actually locked a row: under FORCE RLS an unset tenant context
would return zero rows and take NO lock, which would silently degrade this file into the
useless "A finishes, then B starts" shape.

Fixture helpers are COPIED from test_checkpoint_resume.py rather than imported. That
duplication is this suite's house style (test_rls_isolation.py does the same) and is
deliberate: cross-module fixture imports and a shared conftest are what make these files
order-dependent, and this suite already has one reproducible cross-file pollution defect.

`require_non_superuser` is deliberately NOT used. These are concurrency tests, not RLS
tests; row locks and READ COMMITTED behave identically for a superuser, so requiring a
non-superuser DSN would make them skip in a harness where they would run faithfully.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest


# ===========================================================================
# LAYER A — SOURCE GATES. Pure: no DB, no network, no key. These run in every
# harness, including the DB-less ones, so the CAS cannot be silently reverted
# by an edit that happens to keep the DB-backed tests skipping.
# ===========================================================================

def test_both_status_flips_are_compare_and_swap():
    """The flip is decided by the DATABASE, not by a preceding read.

    ANTI-VACUITY: the loop counts what it checked and asserts it saw both
    handlers. A gate that silently iterates an empty list is a green that
    proves nothing.
    """
    import inspect

    from nestor_pulse_sdk.runs.api import resume_run, submit_report_spec

    checked = 0
    for handler in (resume_run, submit_report_spec):
        src = inspect.getsource(handler)
        name = handler.__name__
        assert "rowcount" in src, (
            f"{name} must gate its status flip on the matched-row count of a "
            "conditional UPDATE — a read that gates a write in a different "
            "statement is the race D-23.2-13 removes"
        )
        assert "409" in src, (
            f"{name} must map a lost race to the SAME conflict its read-check "
            "raises — two distinct refusals would let a caller tell 'you lost "
            "the race' from 'it was never in that state'"
        )
        checked += 1

    assert checked == 2, (
        "both handlers must be gated; a shorter list here is a vacuous green"
    )


def test_neither_handler_can_answer_forbidden():
    """A cross-tenant run_id is INVISIBLE, not forbidden.

    Restated from test_checkpoint_resume.py::test_resume_handler_is_404_not_403
    _by_construction so that a regression introduced by the CAS edit is caught
    by this file too, and extended to `submit_report_spec`, which has the same
    RLS-resolved read and the same obligation.
    """
    import inspect

    from nestor_pulse_sdk.runs.api import resume_run, submit_report_spec

    checked = 0
    for handler in (resume_run, submit_report_spec):
        src = inspect.getsource(handler)
        name = handler.__name__
        assert "scalar_one_or_none" in src, (
            f"{name} must resolve the row through RLS, so a foreign run reads "
            "as absent rather than as denied"
        )
        assert "HTTPException(404" in src, f"{name} must answer 404 for an unresolved run"
        assert "403" not in src, (
            f"{name} must not contain the forbidden status code — anywhere, "
            "including in a comment or inside a longer number. Answering it "
            "would confirm that another tenant's run exists"
        )
        checked += 1

    assert checked == 2


def test_resume_run_docstring_no_longer_claims_a_guarantee_it_lacked():
    """The false sentence is gone.

    Before D-23.2-13 the docstring said the read-check made it so that "two
    concurrent clicks cannot both succeed". It did not. The handler may say
    something TRUE about concurrency — it may not say that.
    """
    from nestor_pulse_sdk.runs.api import resume_run

    doc = resume_run.__doc__ or ""
    assert "cannot both succeed" not in doc, (
        "the docstring claimed the read-then-write serialized two clicks. It "
        "did not, and a comment asserting a guarantee the code does not "
        "provide is worse than no comment — it stops the next reader looking"
    )
    assert "parked" in doc, (
        "the status allow-list must still be documented where the handler is "
        "read (also asserted by test_checkpoint_resume.py)"
    )


def test_report_spec_insert_cannot_precede_its_admission_ticket():
    """The Output row is what the ticket BUYS, never what precedes it.

    Order matters independently of the rollback behaviour of get_db_session:
    relying on an HTTPException unwinding a dependency's `session.begin()` is
    an implicit dependency on another module's internals. The explicit order —
    CAS, then insert — is correct without that argument.
    """
    import inspect

    from nestor_pulse_sdk.runs.api import submit_report_spec

    src = inspect.getsource(submit_report_spec)
    cas_at = src.find("rowcount")
    insert_at = src.find('format="report_spec"')
    assert cas_at != -1, "no compare-and-swap in submit_report_spec"
    assert insert_at != -1, "the report_spec Output insert has moved or been renamed"
    assert cas_at < insert_at, (
        "the CAS must run BEFORE the Output insert: the loser of the race must "
        "not have written a second report_spec row at all, rather than relying "
        "on a caller's rollback to remove it"
    )


# ===========================================================================
# LAYER B — REAL POSTGRES.
#
# These need a migrated database. `DATABASE_URL` unset == a LOUD SKIP, and a
# skip is NOT a pass: the concurrency claim is then UNPROVEN and the source
# gates above say nothing about it. `tribunal/cloudbuild.test-cas.yaml` runs
# this file against a real, migrated, non-superuser Postgres and fails on any
# skip for exactly that reason.
# ===========================================================================


def _require_database_url() -> str:
    """The DSN, or a clean skip. Same contract as test_checkpoint_resume.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set — these are real-Postgres concurrency tests. "
            "They need row locks and READ COMMITTED, which no in-memory double "
            "provides. See tribunal/cloudbuild.test-cas.yaml. A skip here is "
            "NOT a pass: without them the CAS is asserted only as source text."
        )
    return url


@pytest.fixture
async def live_engine():
    """Async engine bound to a real, migrated Postgres."""
    url = _require_database_url()
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")
    engine = sa.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def two_orgs(live_engine):
    """Two ephemeral orgs, CASCADE-cleaned at teardown so the suite reruns."""
    from sqlalchemy import text as sql

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    async with live_engine.begin() as conn:
        await conn.execute(
            sql(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            [
                {"id": tenant_a, "name": "Tenant A (CAS test)",
                 "slug": f"cas-a-{tenant_a.hex[:8]}"},
                {"id": tenant_b, "name": "Tenant B (CAS test)",
                 "slug": f"cas-b-{tenant_b.hex[:8]}"},
            ],
        )
    yield tenant_a, tenant_b
    async with live_engine.begin() as conn:
        await conn.execute(
            sql("DELETE FROM org WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )


def _sessionmaker(live_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_run(live_engine, tenant_id, *, status):
    """A project + a run in `status`, both written under the tenant's RLS context."""
    from nestor_pulse_sdk.db.models import Project, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            session.add(Project(
                id=project_id, tenant_id=tenant_id, name="CAS test project",
            ))
            session.add(Run(
                id=run_id, tenant_id=tenant_id, project_id=project_id,
                engine="tribunal", brief="brief", status=status,
                idempotency_key=uuid.uuid4(), worker_id="worker-1",
                error_message="[park#1] parked earlier",
            ))
    return run_id


async def _read_run(live_engine, tenant_id, run_id):
    """(status, worker_id, error_message) read back under the tenant's context."""
    from sqlalchemy import text as sql

    from nestor_pulse_sdk.db.rls import set_tenant_context

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            return (await session.execute(
                sql("SELECT status, worker_id, error_message FROM run WHERE id = :r"),
                {"r": str(run_id)},
            )).first()


async def _count_outputs(live_engine, tenant_id, run_id, fmt):
    """How many Output rows of `fmt` exist for this run, under the tenant's context."""
    from sqlalchemy import text as sql

    from nestor_pulse_sdk.db.rls import set_tenant_context

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            return (await session.execute(
                sql("SELECT count(*) FROM output WHERE run_id = :r AND format = :f"),
                {"r": str(run_id), "f": fmt},
            )).scalar_one()


def _claims(tenant_id):
    from nestor_pulse_sdk.auth.provider import AuthClaims

    return AuthClaims(
        app_user_id=str(uuid.uuid4()),
        tenant_id=str(tenant_id),
        email="cas-test@example.invalid",
        raw_provider_user_id="cas-test-uid",
    )


class _RowBarrier:
    """Holds `SELECT ... FOR UPDATE` on one run row so both callers READ before
    either WRITES — the exact interleaving the defect needs.

    Asserts it actually locked a row. Under FORCE RLS a missing tenant context
    returns zero rows and takes NO lock, which would silently turn this whole
    file into the "A finishes, then B starts" shape that proves nothing.
    """

    def __init__(self, live_engine, tenant_id, run_id):
        self._engine = live_engine
        self._tenant_id = tenant_id
        self._run_id = run_id
        self._conn = None
        self._txn = None

    async def acquire(self):
        from sqlalchemy import text as sql

        self._conn = await self._engine.connect()
        self._txn = await self._conn.begin()
        await self._conn.execute(
            sql("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(self._tenant_id)},
        )
        locked = (await self._conn.execute(
            sql("SELECT id FROM run WHERE id = :r FOR UPDATE"),
            {"r": str(self._run_id)},
        )).first()
        assert locked is not None, (
            "the barrier locked NOTHING — the run row was invisible to it, so "
            "the two callers would not have been held at their UPDATE and this "
            "test would prove nothing about concurrency"
        )
        return self

    async def release(self):
        if self._txn is not None:
            await self._txn.rollback()
            self._txn = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def wait_until_blocked(self, n, timeout=15.0):
        """Poll until `n` backends are WAITING on a lock inside an UPDATE of `run`."""
        from sqlalchemy import text as sql

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        seen = -1
        while loop.time() < deadline:
            async with self._engine.connect() as probe:
                seen = (await probe.execute(sql(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND state = 'active' AND wait_event_type = 'Lock' "
                    "AND query ILIKE '%%UPDATE run %%' "
                    "AND query NOT ILIKE '%%pg_stat_activity%%'"
                ))).scalar_one()
            if seen >= n:
                return
            await asyncio.sleep(0.05)
        pytest.fail(
            f"only {seen} of {n} callers reached a blocked UPDATE within "
            f"{timeout}s. The interleaving this test depends on was not "
            "established, so its result would be meaningless — this is a setup "
            "failure, not a pass and not a CAS finding."
        )


async def _resume_attempt(live_engine, tenant_id, run_id):
    """One caller: its own session, its own transaction, committed on success."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    try:
        async with _sessionmaker(live_engine)() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                response = await resume_run(run_id, session=session)
        return ("ok", response)
    except HTTPException as exc:
        return ("http", exc.status_code)


async def _report_spec_attempt(live_engine, tenant_id, run_id, instructions):
    """One caller of submit_report_spec: own session, own transaction."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import submit_report_spec
    from nestor_pulse_sdk.runs.schemas import ReportSpecRequest

    payload = ReportSpecRequest(instructions=instructions)
    try:
        async with _sessionmaker(live_engine)() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                result = await submit_report_spec(
                    run_id, payload, user=_claims(tenant_id), session=session,
                )
        return ("ok", result)
    except HTTPException as exc:
        return ("http", exc.status_code)


async def test_two_concurrent_resumes_leave_exactly_one_winner(live_engine, two_orgs):
    """THE PROOF OF D-23.2-13 for `resume_run`.

    Both callers read `parked` before either writes (see the barrier). Exactly
    one may re-queue the run; the other must be told 409. Before the CAS both
    succeeded, and the worker re-claimed and re-drove a paid pipeline.
    """
    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="parked")

    barrier = _RowBarrier(live_engine, tenant_a, run_id)
    await barrier.acquire()
    try:
        task_a = asyncio.create_task(_resume_attempt(live_engine, tenant_a, run_id))
        task_b = asyncio.create_task(_resume_attempt(live_engine, tenant_a, run_id))
        await barrier.wait_until_blocked(2)
    finally:
        await barrier.release()

    outcomes = await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=30)

    successes = [o for kind, o in outcomes if kind == "ok"]
    conflicts = [o for kind, o in outcomes if kind == "http" and o == 409]
    assert len(successes) == 1, (
        f"EXACTLY one concurrent resume may win; got {len(successes)} "
        f"(outcomes={outcomes!r}). Two winners means the same parked run is "
        "re-queued twice and the paid pipeline is re-driven"
    )
    assert len(conflicts) == 1, (
        f"the loser must be refused with 409, not silently succeed or fail "
        f"differently (outcomes={outcomes!r})"
    )
    assert successes[0].status == "queued"

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "queued", "the winner's flip must have landed"
    assert row[1] is None, "worker_id must be cleared so the worker can re-claim it"
    assert row[2] is None, "the stale park reason must not survive the resume"


async def test_the_winning_resume_returns_a_fresh_status_not_a_stale_one(
    live_engine, two_orgs
):
    """THE SYNCHRONIZE_SESSION TRAP.

    A bulk UPDATE does not, by default, refresh the ORM instance that was
    already loaded by the handler's read. A CAS that returns that stale
    instance passes every concurrency assertion above and still tells the
    operator the run is `parked` right after a SUCCESSFUL resume — so they
    click again. The returned view must be post-flip.
    """
    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="parked")

    kind, response = await _resume_attempt(live_engine, tenant_a, run_id)

    assert kind == "ok", f"a lone resume of a parked run must succeed, got {response!r}"
    assert response.status == "queued", (
        "the handler returned the PRE-flip status — the ORM instance loaded by "
        "the read was not synchronised with the bulk UPDATE"
    )
    assert response.id == run_id, "the SAME run must be re-queued, never a new one"


async def test_two_concurrent_report_specs_write_exactly_one_output(
    live_engine, two_orgs
):
    """THE PROOF OF D-23.2-13 for `submit_report_spec`.

    The Output count is the load-bearing assertion: a fix that only relies on
    the caller's transaction rolling back would still satisfy "one success, one
    409", while an insert-before-CAS whose rollback assumption broke would
    leave the pipeline's resume branch two conflicting `report_spec` rows to
    choose between.
    """
    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="needs_report_spec")

    barrier = _RowBarrier(live_engine, tenant_a, run_id)
    await barrier.acquire()
    try:
        task_a = asyncio.create_task(
            _report_spec_attempt(live_engine, tenant_a, run_id, "spec-A")
        )
        task_b = asyncio.create_task(
            _report_spec_attempt(live_engine, tenant_a, run_id, "spec-B")
        )
        await barrier.wait_until_blocked(2)
    finally:
        await barrier.release()

    outcomes = await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=30)

    successes = [o for kind, o in outcomes if kind == "ok"]
    conflicts = [o for kind, o in outcomes if kind == "http" and o == 409]
    assert len(successes) == 1, (
        f"EXACTLY one concurrent report-spec submission may win; got "
        f"{len(successes)} (outcomes={outcomes!r})"
    )
    assert len(conflicts) == 1, (
        f"the loser must be refused with 409 (outcomes={outcomes!r})"
    )
    assert successes[0]["status"] == "queued", (
        "the winner's response must report the POST-flip status"
    )

    assert await _count_outputs(live_engine, tenant_a, run_id, "report_spec") == 1, (
        "the loser's report_spec Output must not persist — a second spec row "
        "leaves the pipeline's resume branch an ambiguous choice"
    )

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "queued"
    assert row[1] is None, "worker_id must be cleared so the worker can re-claim it"


async def test_resume_of_a_non_parked_run_is_still_409_and_mutates_nothing(
    live_engine, two_orgs
):
    """UNCHANGED BEHAVIOUR. The CAS narrows the match; it must not widen it."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="running")

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            with pytest.raises(HTTPException) as ei:
                await resume_run(run_id, session=session)
    assert ei.value.status_code == 409

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "running", "a refused resume must mutate nothing"
    assert row[1] == "worker-1", "the refused call must not have cleared worker_id"


async def test_resume_of_an_unresolvable_run_is_still_404(live_engine, two_orgs):
    """UNCHANGED BEHAVIOUR. rowcount 0 must never be reported as a 404 — the
    404 belongs to the read, and only to the read."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, _ = two_orgs
    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            with pytest.raises(HTTPException) as ei:
                await resume_run(uuid.uuid4(), session=session)
    assert ei.value.status_code == 404


async def test_report_spec_on_a_wrong_state_run_is_still_409_and_writes_nothing(
    live_engine, two_orgs
):
    """UNCHANGED BEHAVIOUR, plus the Output consequence of the reordering: a
    refused submission must not leave a `report_spec` row behind."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import submit_report_spec
    from nestor_pulse_sdk.runs.schemas import ReportSpecRequest

    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="running")

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            with pytest.raises(HTTPException) as ei:
                await submit_report_spec(
                    run_id, ReportSpecRequest(instructions="nope"),
                    user=_claims(tenant_a), session=session,
                )
    assert ei.value.status_code == 409

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "running", "a refused submission must mutate nothing"
    assert await _count_outputs(live_engine, tenant_a, run_id, "report_spec") == 0, (
        "a refused submission must not persist a report_spec Output"
    )


async def test_report_spec_on_an_unresolvable_run_is_still_404(live_engine, two_orgs):
    """UNCHANGED BEHAVIOUR — a cross-tenant or absent run is indistinguishable."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import submit_report_spec
    from nestor_pulse_sdk.runs.schemas import ReportSpecRequest

    tenant_a, _ = two_orgs
    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            with pytest.raises(HTTPException) as ei:
                await submit_report_spec(
                    uuid.uuid4(), ReportSpecRequest(instructions="nope"),
                    user=_claims(tenant_a), session=session,
                )
    assert ei.value.status_code == 404


async def test_a_cross_tenant_resume_is_still_404_and_mutates_nothing(
    live_engine, two_orgs
):
    """T-23.2-05-03. Adding a status predicate to the UPDATE must not tempt a
    later reader to drop the read — that would turn this 404 into a 409 and
    hand the caller an existence oracle."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, tenant_b = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="parked")

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            with pytest.raises(HTTPException) as ei:
                await resume_run(run_id, session=session)
    assert ei.value.status_code == 404, (
        "a foreign run must be INVISIBLE, never forbidden and never a conflict"
    )

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "parked", "tenant A's run must be untouched by the denial"
