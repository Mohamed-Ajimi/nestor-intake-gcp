"""
Tribunal run-API idempotency proofs -- 23.1-CONTEXT.md sections 4 and 5,
decisions D-23.1-07 and D-23.1-08 (owning plan: 23.1-06).

CONTEXT section 4 verified two non-idempotent paid paths on the Tribunal run API:

  * `GET /api/runs/{run_id}/report-proposal` (`runs/api.py`) -- a BILLABLE,
    SIDE-EFFECTING GET. On a cache miss it builds an audited LLM client, calls
    `build_report_proposal(...)` and INSERTs an `Output`. Two concurrent reads
    of the same uncached run therefore made TWO paid generations and wrote two
    rows. D-23.1-07 keeps the URL, the method and the on-demand generation --
    the interactive shaping panel depends on all three -- and fixes the double
    spend with the SAME per-run advisory lock `runs/execute.py` already owns,
    re-reading the cache UNDER the lock.

  * `POST /api/runs/{run_id}/answer` (`runs/api.py`) -- a read-then-write race.
    It read the run, refused 409 when `status != 'needs_input'`, and only THEN
    wrote. Two concurrent callers both passed the check and both queued a
    replacement run: a double spend AND a forked audit hash-chain (the chain
    the EU AI Act Art. 12 trail rests on). D-23.1-08 makes the retire a
    conditional UPDATE -- `WHERE status='needs_input' RETURNING id` -- so the
    cancel is the admission ticket and the child run is what the ticket buys.
    Note `idempotency_key=uuid.uuid4()` on that path is a fresh random value
    per row and protects NOTHING; the CAS is the protection.

CONTEXT section 5 additionally leaves `brief` with a `min_length` floor and NO
ceiling on both request models, so an arbitrarily large body could ride into a
provider prompt. This file pins the 1 MB bound.

Why the generation stub sleeps
------------------------------
The two-caller proposal tests would pass WITHOUT any lock if the stubbed
generation returned instantly -- the first caller could finish and commit
before the second ever looked. Every stub here therefore awaits a real sleep,
so the two coroutines genuinely overlap and the lock is the only thing that can
make the call count 1. Proven non-vacuous: with the lock line commented out
these tests fail with TWO recorded generation calls (recorded in
23.1-06-SUMMARY.md).

Why READ COMMITTED is load-bearing
----------------------------------
`pg_advisory_xact_lock` is transaction-scoped, and `auth/deps.py::get_db_session`
yields INSIDE `session.begin()` -- so a handler runs in ONE transaction and
holds the lock until its response commits. The second caller blocks at the
lock; when it proceeds, Postgres' default READ COMMITTED isolation gives its
next statement a FRESH snapshot, so the first caller's committed INSERT is
visible and the second returns the cache instead of paying again. Under
REPEATABLE READ the re-read would still see the pre-lock snapshot and pay
twice. The same property is what makes the answer CAS work: a blocked UPDATE
re-evaluates its WHERE against the newly committed row version.

ZERO PROVIDER SPEND: `build_report_proposal` and `build_audited_client` are
stubbed in every test in this file. Nothing here can reach a provider.

Tests
-----
  1.  test_advisory_lock_sql_is_public_and_shared_by_identity (static)
  2.  test_report_proposal_route_is_get_not_post (static)
  3.  test_concurrent_proposal_reads_generate_exactly_once (LIVE)
  4.  test_warm_cache_proposal_never_generates (LIVE)
  5.  test_distinct_runs_proposals_do_not_serialize (LIVE)
  6.  test_proposal_without_cached_bundle_is_409 (LIVE)
  7.  test_answer_single_run_happy_path (LIVE)
  8.  test_answer_single_run_not_needs_input_is_409 (LIVE)
  9.  test_concurrent_answers_queue_exactly_one_run (LIVE)
  10. test_answer_comparison_only_answered_engines_get_children (LIVE)
  11. test_concurrent_comparison_answers_replace_each_sibling_once (LIVE)
  12. test_answer_unknown_run_is_404 (LIVE)
  13. test_brief_accepts_exactly_one_million_chars (static)
  14. test_brief_rejects_one_char_over_the_bound (static)
  15. test_brief_still_rejects_empty (static)
  16. test_brief_accepts_the_analytic_worst_case (static)

WHERE THESE PROOFS ACTUALLY RUN -- read this before trusting a green build
-------------------------------------------------------------------------
`tribunal/cloudbuild.test.yaml` runs this whole directory, so it COLLECTS this
file, but its own header records a measured limitation: the testcontainers
fixture does NOT start there ("host" network_mode is incompatible with
port_bindings), so `postgres_container` skips and every test depending on it
skips with it. In that gate only the six STATIC tests below execute; the ten
LIVE ones skip. `cloudbuild.test-critical.yaml` names four files and this is
not one of them.

So: as committed, the concurrency proofs in this file run in NO CI gate. They
were executed locally against a real testcontainers Postgres (16 passed) and
observed RED against the unfixed code -- that evidence is real, but it is not
continuous. The `run_api_engine` fixture therefore ALSO accepts an explicit
`DATABASE_URL`, which is the pattern `cloudbuild.test-critical.yaml` and
`cloudbuild.test-rls.yaml` use (`docker run --network=host postgres:15` plus a
DSN), so a gate that names this file can execute these proofs rather than skip
them. Wiring that gate belongs to plan 23.1-14, not here.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SDK_ROOT = Path(__file__).resolve().parents[1]
_EXECUTE_PY = _SDK_ROOT / "runs" / "execute.py"
_API_PY = _SDK_ROOT / "runs" / "api.py"

# Long enough that two coroutines genuinely overlap; short enough to keep the
# suite quick. A stub that returned instantly would let these tests pass with
# no lock at all.
_GEN_SLEEP = 0.4


# ---------------------------------------------------------------------------
# Static assertions (no live DB) -- these encode the D-23.1-07 contract.
# ---------------------------------------------------------------------------

def test_advisory_lock_sql_is_public_and_shared_by_identity() -> None:
    """`runs/api.py` must take the SAME per-run lock object `runs/execute.py`
    uses -- asserted by IDENTITY, not by string equality, so a copy-paste
    divergence of the key expression is impossible (threat T-23.1-25).

    The key must stay the 64-bit `('x' || md5(:run_id))::bit(64)::bigint` form:
    `hashtext` is int4 and collides ~50% at ~65k runs, which would spuriously
    serialize two DISTINCT runs (T-13-07).
    """
    execute_mod = pytest.importorskip("nestor_pulse_sdk.runs.execute")
    api_mod = pytest.importorskip("nestor_pulse_sdk.runs.api")

    assert hasattr(execute_mod, "ADVISORY_LOCK_SQL"), (
        "execute.py must export ADVISORY_LOCK_SQL publicly so runs/api.py can "
        "reuse the identical lock (D-23.1-07)"
    )
    assert hasattr(api_mod, "ADVISORY_LOCK_SQL"), (
        "runs/api.py must import ADVISORY_LOCK_SQL from runs/execute.py"
    )
    assert api_mod.ADVISORY_LOCK_SQL is execute_mod.ADVISORY_LOCK_SQL, (
        "api.py and execute.py must share ONE lock object; two objects can "
        "drift apart in their key expression (T-23.1-25)"
    )

    key_sql = str(execute_mod.ADVISORY_LOCK_SQL)
    assert "pg_advisory_xact_lock" in key_sql
    assert "bit(64)::bigint" in key_sql, (
        "the lock key must remain the 64-bit md5 form (T-13-07)"
    )
    assert "hashtext" not in key_sql, "hashtext is int4 -- never use it here"

    # The handler must actually take the lock in the code path that spends.
    api_src = _API_PY.read_text(encoding="utf-8")
    assert "ADVISORY_LOCK_SQL" in api_src


def test_report_proposal_route_is_get_not_post() -> None:
    """D-23.1-07: the URL, the method and the on-demand generation are
    UNCHANGED. Moving the verb to a POST was the explicitly rejected
    alternative -- it is a breaking change for a live UI and buys nothing the
    lock does not."""
    api_mod = pytest.importorskip("nestor_pulse_sdk.runs.api")
    matching = [
        r for r in api_mod.router.routes
        if getattr(r, "path", "").endswith("/{run_id}/report-proposal")
    ]
    assert matching, "the report-proposal route must still exist"
    methods: set[str] = set()
    for r in matching:
        methods |= set(getattr(r, "methods", set()) or set())
    assert "GET" in methods, "report-proposal must remain a GET (D-23.1-07)"
    assert "POST" not in methods, (
        "report-proposal must NOT become a POST -- the shaping panel calls the "
        "GET (D-23.1-07 rejected the method change)"
    )


# ---------------------------------------------------------------------------
# LIVE harness
# ---------------------------------------------------------------------------

@pytest.fixture
async def run_api_engine(request):
    """Async engine for the LIVE proofs: an explicit `DATABASE_URL` when one is
    provided, otherwise conftest's testcontainers Postgres.

    The DATABASE_URL branch is not decoration. `cloudbuild.test.yaml` collects
    this file but cannot start testcontainers (see the module docstring), so
    every LIVE proof here skips in that gate. A gate that hands pytest a DSN --
    the `cloudbuild.test-critical.yaml` / `cloudbuild.test-rls.yaml` pattern --
    can actually execute them. `test_advisory_lock_exactly_once.py` reads
    DATABASE_URL the same way and with the same scheme guard.

    The container fixture is resolved LAZILY so the DSN path never starts a
    container it does not need, and so the skip (Docker unreachable) still comes
    from conftest rather than from an error here.
    """
    sa_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")

    url = os.environ.get("DATABASE_URL") or ""
    if not url.startswith("postgresql+asyncpg://"):
        container = request.getfixturevalue("postgres_container")
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

    engine = sa_asyncio.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


def _claims(tenant_id, user_id=None):
    from nestor_pulse_sdk.auth.provider import AuthClaims

    user_id = user_id or uuid.uuid4()
    return AuthClaims(
        app_user_id=str(user_id),
        tenant_id=str(tenant_id),
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        raw_provider_user_id=f"fb-{uuid.uuid4().hex[:8]}",
    )


async def _make_sessionmaker(engine):
    """Create the model schema on the ephemeral DB and return a sessionmaker.

    `Base.metadata.create_all` (not alembic) is deliberate: migration 0008
    GRANTs to a `worker_user` role that does not exist in an ephemeral
    testcontainer, which is exactly why the alembic-based live tests in
    `test_advisory_lock_exactly_once.py` fail on this machine. The models are
    all these tests need.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.base import Base
    # Importing the models is what REGISTERS them on Base.metadata. Without this
    # line create_all silently creates NOTHING when this file's first executed
    # test has not already imported them -- an order-dependent green.
    import nestor_pulse_sdk.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_run(Session, set_tenant, status="completed", comparison_id=None,
                    brief="base brief", engine="tribunal", tenant_id=None,
                    project_id=None):
    """Insert org (+ project) and one run in `status`. Returns
    (tenant_id, project_id, run_id)."""
    from nestor_pulse_sdk.db.models import Org, Project, Run

    run_id = uuid.uuid4()
    async with Session() as session:
        if tenant_id is None:
            tenant_id = uuid.uuid4()
            async with session.begin():
                session.add(Org(
                    id=tenant_id, name="Acme",
                    slug=f"acme-{tenant_id.hex[:8]}",
                ))
        if project_id is None:
            project_id = uuid.uuid4()
            async with session.begin():
                await set_tenant(session, tenant_id)
                session.add(Project(
                    id=project_id, tenant_id=tenant_id, name="P",
                ))
        async with session.begin():
            await set_tenant(session, tenant_id)
            session.add(Run(
                id=run_id, tenant_id=tenant_id, project_id=project_id,
                engine=engine, brief=brief, status=status,
                idempotency_key=uuid.uuid4(), comparison_id=comparison_id,
            ))
    return tenant_id, project_id, run_id


async def _seed_synthesis_cache(Session, set_tenant, tenant_id, run_id):
    """Give the run a cached research bundle so the proposal GET can generate."""
    from nestor_pulse_sdk.db.models import Output

    body = json.dumps({
        "mission_brief": {"goal": "assess the market"},
        "cleaned_reports": [["gemini", "a cleaned report"]],
    })
    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            session.add(Output(
                tenant_id=tenant_id, run_id=run_id,
                format="synthesis_cache", body=body,
            ))


def _patch_generation(recorder, sleep=_GEN_SLEEP):
    """Patch the REAL targets. `get_report_proposal` imports both names
    function-locally at CALL time, so the interception point is the SOURCE
    module attribute -- patching `runs.api` would miss the call entirely
    (the 13-REVIEW WR-02 lesson).

    This is also the ZERO-SPEND guarantee: `build_audited_client` never
    constructs a real client and `build_report_proposal` never reaches a
    provider.
    """
    planner = pytest.importorskip(
        "nestor_pulse_sdk.pipeline.tribunal.report_planner"
    )
    audit = pytest.importorskip("nestor_pulse_sdk.audit.audited_llm_client")

    async def _fake_build_report_proposal(**kwargs):
        started = time.monotonic()
        await asyncio.sleep(sleep)
        recorder.append({
            "run_id": kwargs.get("run_id"),
            "started": started,
            "ended": time.monotonic(),
        })
        return {
            "focus_areas": ["market", "risk"],
            "length": "standard",
            "tables": [],
        }

    return (
        patch.object(planner, "build_report_proposal", _fake_build_report_proposal),
        patch.object(audit, "build_audited_client", MagicMock(return_value=object())),
    )


async def _call_proposal(Session, set_tenant, tenant_id, user, run_id):
    """Model ONE HTTP request: a dedicated session, one transaction opened
    before the handler and committed after it -- exactly the contract
    `auth/deps.py::get_db_session` gives a route (it yields INSIDE
    `session.begin()`)."""
    from nestor_pulse_sdk.runs.api import get_report_proposal

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            return await get_report_proposal(run_id, user=user, session=session)


async def _count_outputs(Session, set_tenant, tenant_id, run_id, fmt):
    from sqlalchemy import func, select

    from nestor_pulse_sdk.db.models import Output

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            return (await session.execute(
                select(func.count()).select_from(Output).where(
                    Output.run_id == run_id, Output.format == fmt,
                )
            )).scalar_one()


# ---------------------------------------------------------------------------
# LIVE: the D-23.1-07 double-spend proof
# ---------------------------------------------------------------------------

async def test_concurrent_proposal_reads_generate_exactly_once(
    run_api_engine, set_tenant
) -> None:
    """TWO concurrent GETs on the SAME uncached run must produce EXACTLY ONE
    paid generation and EXACTLY ONE cached Output row, and both callers must
    get the same proposal back.

    Without the advisory lock this fails with TWO recorded generation calls --
    the double spend CONTEXT section 4 found.
    """
    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _project_id, run_id = await _seed_run(Session, set_tenant)
    await _seed_synthesis_cache(Session, set_tenant, tenant_id, run_id)
    user = _claims(tenant_id)

    recorded: list[dict] = []
    p_planner, p_audit = _patch_generation(recorded)
    with p_planner, p_audit:
        first, second = await asyncio.gather(
            _call_proposal(Session, set_tenant, tenant_id, user, run_id),
            _call_proposal(Session, set_tenant, tenant_id, user, run_id),
        )

    assert len(recorded) == 1, (
        "expected EXACTLY ONE paid generation for two concurrent reads of the "
        f"same uncached run, got {len(recorded)} -- the per-run advisory lock "
        "and the cache re-read UNDER it are what prevent the double spend "
        "(D-23.1-07)"
    )
    rows = await _count_outputs(
        Session, set_tenant, tenant_id, run_id, "report_proposal"
    )
    assert rows == 1, f"expected exactly one cached proposal row, got {rows}"
    assert first["proposal"] == second["proposal"], (
        "both callers must receive the same proposal payload"
    )
    assert first["run_id"] == str(run_id) and second["run_id"] == str(run_id)


async def test_warm_cache_proposal_never_generates(run_api_engine, set_tenant) -> None:
    """A run that already has a cached proposal must be served from cache with
    ZERO generation calls -- the lock must not turn a free read into a paid
    one."""
    from nestor_pulse_sdk.db.models import Output

    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _project_id, run_id = await _seed_run(Session, set_tenant)
    await _seed_synthesis_cache(Session, set_tenant, tenant_id, run_id)
    cached = {"focus_areas": ["already"], "length": "short", "tables": []}
    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            session.add(Output(
                tenant_id=tenant_id, run_id=run_id, format="report_proposal",
                body=json.dumps(cached),
            ))

    user = _claims(tenant_id)
    recorded: list[dict] = []
    p_planner, p_audit = _patch_generation(recorded)
    with p_planner, p_audit:
        result = await _call_proposal(
            Session, set_tenant, tenant_id, user, run_id
        )

    assert recorded == [], (
        "a warm cache must not generate anything -- recorded calls: "
        f"{len(recorded)}"
    )
    assert result["proposal"] == cached


async def test_distinct_runs_proposals_do_not_serialize(
    run_api_engine, set_tenant
) -> None:
    """The lock is PER RUN, not global: two callers for two DIFFERENT uncached
    runs must both generate, and their generations must genuinely OVERLAP in
    time (asserted on recorded intervals, not on a flaky wall-clock threshold).
    """
    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, project_id, run_a = await _seed_run(Session, set_tenant)
    _t, _p, run_b = await _seed_run(
        Session, set_tenant, tenant_id=tenant_id, project_id=project_id
    )
    await _seed_synthesis_cache(Session, set_tenant, tenant_id, run_a)
    await _seed_synthesis_cache(Session, set_tenant, tenant_id, run_b)
    user = _claims(tenant_id)

    recorded: list[dict] = []
    p_planner, p_audit = _patch_generation(recorded)
    with p_planner, p_audit:
        await asyncio.gather(
            _call_proposal(Session, set_tenant, tenant_id, user, run_a),
            _call_proposal(Session, set_tenant, tenant_id, user, run_b),
        )

    assert {r["run_id"] for r in recorded} == {run_a, run_b}, (
        "both distinct runs must generate their own proposal"
    )
    assert len(recorded) == 2
    latest_start = max(r["started"] for r in recorded)
    earliest_end = min(r["ended"] for r in recorded)
    assert latest_start < earliest_end, (
        "the two generations must overlap -- if they serialize, the lock key "
        "is not per-run (T-23.1-24 accepts a per-run hold, never a global one)"
    )


async def test_proposal_without_cached_bundle_is_409(
    run_api_engine, set_tenant
) -> None:
    """No cached research bundle -> still 409 with the existing message, no
    generation, and the lock released with the transaction (a later caller for
    the same run is not blocked)."""
    from fastapi import HTTPException

    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _project_id, run_id = await _seed_run(Session, set_tenant)
    user = _claims(tenant_id)

    recorded: list[dict] = []
    p_planner, p_audit = _patch_generation(recorded)
    with p_planner, p_audit:
        with pytest.raises(HTTPException) as ei:
            await _call_proposal(Session, set_tenant, tenant_id, user, run_id)
    assert ei.value.status_code == 409
    assert "no cached research" in str(ei.value.detail)
    assert recorded == [], "a 409 must never generate anything"

    # The lock was transaction-scoped, so a later caller is not blocked by it.
    await _seed_synthesis_cache(Session, set_tenant, tenant_id, run_id)
    recorded2: list[dict] = []
    p_planner2, p_audit2 = _patch_generation(recorded2, sleep=0.0)
    with p_planner2, p_audit2:
        result = await asyncio.wait_for(
            _call_proposal(Session, set_tenant, tenant_id, user, run_id),
            timeout=20,
        )
    assert len(recorded2) == 1
    assert result["proposal"]["focus_areas"] == ["market", "risk"]


# ---------------------------------------------------------------------------
# LIVE: the D-23.1-08 answer compare-and-swap
# ---------------------------------------------------------------------------

async def _call_answer(Session, set_tenant, tenant_id, user, run_id, hold=0.0,
                       **answer_kw):
    """Model ONE POST /api/runs/{id}/answer request -- its own session, one
    transaction opened before the handler and COMMITTED after it, exactly the
    contract `auth/deps.py::get_db_session` gives a route.

    `hold` keeps the transaction OPEN for that many seconds after the handler
    returns and before the commit. That is what makes the concurrency proofs
    below bite rather than pass by luck: without it the two coroutines finish
    one after the other and the second simply reads the first's committed
    result, so a broken read-then-write would never be caught (measured: the
    two-caller test passed 1-success/1-409 against the UNFIXED code). With a
    hold on one caller, the rival's read lands while the first transaction is
    still open -- it sees the last COMMITTED row version, `needs_input`, which
    is precisely the window the D-23.1-08 race lives in.
    """
    from nestor_pulse_sdk.runs.api import answer_run
    from nestor_pulse_sdk.runs.schemas import AnswerRequest

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            result = await answer_run(
                run_id, AnswerRequest(**answer_kw), user=user, session=session,
            )
            if hold:
                await asyncio.sleep(hold)
            return result


async def _runs_by_status(Session, set_tenant, tenant_id):
    """Return {status: [run rows]} for the tenant -- the DB truth, which is what
    the concurrency assertions count. Inferring from the responses alone would
    miss a second child that was written but not returned."""
    from sqlalchemy import select

    from nestor_pulse_sdk.db.models import Run

    out: dict[str, list] = {}
    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            rows = (await session.execute(
                select(Run).where(Run.tenant_id == tenant_id)
            )).scalars().all()
    for r in rows:
        out.setdefault(r.status, []).append(r)
    return out


_HOLD = 0.6  # seconds the first caller keeps its transaction open


async def _gather_answers(n, Session, set_tenant, tenant_id, user, run_id, **kw):
    """Fire `n` concurrent answer calls; return (successes, exceptions).

    Only the FIRST caller holds its transaction open (`hold=_HOLD`); the rest
    run at full speed, so their reads and their writes both land inside the
    first caller's open window. That is the genuine race.
    """
    results = await asyncio.gather(
        *[
            _call_answer(
                Session, set_tenant, tenant_id, user, run_id,
                hold=(_HOLD if i == 0 else 0.0), **kw,
            )
            for i in range(n)
        ],
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    errs = [r for r in results if isinstance(r, BaseException)]
    return ok, errs


async def test_answer_single_run_happy_path(run_api_engine, set_tenant) -> None:
    """The externally visible contract is unchanged by the CAS: mode 'run', the
    paused run ends `cancelled` with `completed_at` set, and exactly ONE queued
    child carries the folded brief."""
    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _p, run_id = await _seed_run(
        Session, set_tenant, status="needs_input", brief="Base brief."
    )
    user = _claims(tenant_id)

    result = await _call_answer(
        Session, set_tenant, tenant_id, user, run_id, answers="the answer",
    )
    assert result["mode"] == "run"
    assert result["run"]["status"] == "queued"

    by_status = await _runs_by_status(Session, set_tenant, tenant_id)
    assert len(by_status.get("cancelled", [])) == 1
    retired = by_status["cancelled"][0]
    assert retired.id == run_id
    assert retired.completed_at is not None, (
        "the CAS must set completed_at, not just the status"
    )
    queued = by_status.get("queued", [])
    assert len(queued) == 1, f"expected exactly one queued child, got {len(queued)}"
    assert queued[0].id == uuid.UUID(result["run_id"])
    assert "[CLARIFICATION ANSWERS]" in queued[0].brief
    assert queued[0].brief.startswith("Base brief.")
    assert "the answer" in queued[0].brief


async def test_answer_single_run_not_needs_input_is_409(
    run_api_engine, set_tenant
) -> None:
    """A run that is not awaiting clarification still 409s with the existing
    message, and NO child run is created (counted, not inferred)."""
    from fastapi import HTTPException

    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _p, run_id = await _seed_run(Session, set_tenant, status="completed")
    user = _claims(tenant_id)

    before = await _runs_by_status(Session, set_tenant, tenant_id)
    before_total = sum(len(v) for v in before.values())

    with pytest.raises(HTTPException) as ei:
        await _call_answer(
            Session, set_tenant, tenant_id, user, run_id, answers="a",
        )
    assert ei.value.status_code == 409
    assert ei.value.detail == "run is not awaiting clarification"

    after = await _runs_by_status(Session, set_tenant, tenant_id)
    after_total = sum(len(v) for v in after.values())
    assert after_total == before_total, (
        f"a 409 must create no run: {before_total} -> {after_total}"
    )


async def test_concurrent_answers_queue_exactly_one_run(
    run_api_engine, set_tenant
) -> None:
    """TWO concurrent answers on the SAME needs_input run: exactly ONE 201 and
    one 409, and exactly ONE new queued run in the DATABASE.

    Without the CAS both callers pass the read-then-check and both queue a
    replacement -- a double spend AND a forked Art.12 audit chain (D-23.1-08).
    """
    from fastapi import HTTPException

    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _p, run_id = await _seed_run(
        Session, set_tenant, status="needs_input", brief="Base brief."
    )
    user = _claims(tenant_id)

    ok, errs = await _gather_answers(
        2, Session, set_tenant, tenant_id, user, run_id, answers="the answer",
    )

    by_status = await _runs_by_status(Session, set_tenant, tenant_id)
    queued = by_status.get("queued", [])
    assert len(queued) == 1, (
        f"expected EXACTLY ONE queued replacement run, got {len(queued)} -- "
        "the conditional UPDATE is the admission ticket (D-23.1-08)"
    )
    assert len(ok) == 1, f"expected exactly one success, got {len(ok)}"
    assert len(errs) == 1, f"expected exactly one refusal, got {len(errs)}"
    assert isinstance(errs[0], HTTPException) and errs[0].status_code == 409
    assert len(by_status.get("cancelled", [])) == 1
    assert by_status["cancelled"][0].id == run_id


async def test_answer_comparison_only_answered_engines_get_children(
    run_api_engine, set_tenant
) -> None:
    """Comparison branch contract, unchanged: only the answered engines get
    children, the unanswered sibling stays needs_input, and every child shares
    the parent's comparison_id (answering one arm never restarts the others)."""
    Session = await _make_sessionmaker(run_api_engine)
    comparison_id = uuid.uuid4()
    tenant_id, project_id, run_a = await _seed_run(
        Session, set_tenant, status="needs_input", engine="tribunal",
        comparison_id=comparison_id, brief="Arm A.",
    )
    _t, _p, run_b = await _seed_run(
        Session, set_tenant, status="needs_input", engine="adk",
        comparison_id=comparison_id, brief="Arm B.",
        tenant_id=tenant_id, project_id=project_id,
    )
    user = _claims(tenant_id)

    result = await _call_answer(
        Session, set_tenant, tenant_id, user, run_a,
        answers_by_engine={"tribunal": "only A answered"},
    )
    assert result["mode"] == "comparison"
    assert result["comparison_id"] == str(comparison_id)
    assert len(result["runs"]) == 1

    by_status = await _runs_by_status(Session, set_tenant, tenant_id)
    assert [r.id for r in by_status.get("cancelled", [])] == [run_a]
    assert [r.id for r in by_status.get("needs_input", [])] == [run_b], (
        "the unanswered arm must stay paused"
    )
    queued = by_status.get("queued", [])
    assert len(queued) == 1
    assert queued[0].engine == "tribunal"
    assert queued[0].comparison_id == comparison_id
    assert "only A answered" in queued[0].brief


async def test_concurrent_comparison_answers_replace_each_sibling_once(
    run_api_engine, set_tenant
) -> None:
    """Two concurrent callers answering BOTH arms: each paused sibling is
    replaced AT MOST ONCE. Counted per engine on the DB, not on the responses.
    """
    Session = await _make_sessionmaker(run_api_engine)
    comparison_id = uuid.uuid4()
    tenant_id, project_id, run_a = await _seed_run(
        Session, set_tenant, status="needs_input", engine="tribunal",
        comparison_id=comparison_id, brief="Arm A.",
    )
    _t, _p, run_b = await _seed_run(
        Session, set_tenant, status="needs_input", engine="adk",
        comparison_id=comparison_id, brief="Arm B.",
        tenant_id=tenant_id, project_id=project_id,
    )
    user = _claims(tenant_id)

    await _gather_answers(
        2, Session, set_tenant, tenant_id, user, run_a, answers="shared answer",
    )

    by_status = await _runs_by_status(Session, set_tenant, tenant_id)
    queued = by_status.get("queued", [])
    per_engine: dict[str, int] = {}
    for r in queued:
        per_engine[r.engine] = per_engine.get(r.engine, 0) + 1
    assert per_engine == {"tribunal": 1, "adk": 1}, (
        f"each paused arm must be replaced exactly once, got {per_engine}"
    )
    assert {r.id for r in by_status.get("cancelled", [])} == {run_a, run_b}
    assert by_status.get("needs_input", []) == []


async def test_answer_unknown_run_is_404(run_api_engine, set_tenant) -> None:
    """An unknown run id is still a 404, ahead of any CAS."""
    from fastapi import HTTPException

    Session = await _make_sessionmaker(run_api_engine)
    tenant_id, _p, _run_id = await _seed_run(Session, set_tenant)
    user = _claims(tenant_id)

    with pytest.raises(HTTPException) as ei:
        await _call_answer(
            Session, set_tenant, tenant_id, user, uuid.uuid4(), answers="a",
        )
    assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# The brief bound (CONTEXT section 5) -- a request-body DoS guard
# ---------------------------------------------------------------------------

_BRIEF_MAX = 1_000_000
# The analytic worst case for a real brief, from the producer side: the FULL
# context pack rides into the brief verbatim and untruncated
# (`backend/app/research/brief.py::assemble_brief` step 5), and that text is a
# Claude generation capped at `_CONTEXT_PACK_MAX_TOKENS = 8192`
# (`backend/app/ai/skills/context_pack.py`) -- roughly 32 KB of characters. The
# enumerated research questions and the decision/report blocks add far less.
_ANALYTIC_WORST_CASE = 60_000


def _run_request(brief: str):
    from nestor_pulse_sdk.runs.schemas import CreateRunRequest

    return CreateRunRequest(
        project_id=uuid.uuid4(), brief=brief, engine="tribunal",
        idempotency_key=uuid.uuid4(),
    )


def _compare_request(brief: str):
    from nestor_pulse_sdk.runs.schemas import CreateCompareRequest

    return CreateCompareRequest(
        project_id=uuid.uuid4(), brief=brief, engines=["tribunal", "adk"],
        comparison_id=uuid.uuid4(),
    )


def test_brief_accepts_exactly_one_million_chars() -> None:
    """The bound is inclusive: exactly 1,000,000 characters is valid on BOTH
    request models."""
    brief = "x" * _BRIEF_MAX
    assert len(_run_request(brief).brief) == _BRIEF_MAX
    assert len(_compare_request(brief).brief) == _BRIEF_MAX


def test_brief_rejects_one_char_over_the_bound() -> None:
    """1,000,001 characters is a pydantic ValidationError on BOTH models, which
    FastAPI surfaces as a 422 -- the body is refused at the schema boundary
    instead of being carried into a provider prompt (T-23.1-23)."""
    from pydantic import ValidationError

    brief = "x" * (_BRIEF_MAX + 1)
    with pytest.raises(ValidationError):
        _run_request(brief)
    with pytest.raises(ValidationError):
        _compare_request(brief)


def test_brief_still_rejects_empty() -> None:
    """The `min_length=1` floor is untouched by adding a ceiling."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _run_request("")
    with pytest.raises(ValidationError):
        _compare_request("")


def test_brief_accepts_the_analytic_worst_case() -> None:
    """A brief the size of the analytic worst case must still be accepted.

    This is the regression guard that matters: the bound is a DoS guard on the
    request body, NOT a content policy. Tightening it toward a real brief's
    size would silently 422 somebody's research. ROADMAP Phase 24 D-RR-3 also
    adds a superadmin steering note to this field with NO length cap and no
    truncation -- 1 MB is chosen to leave that feature room.
    """
    brief = "x" * _ANALYTIC_WORST_CASE
    assert len(_run_request(brief).brief) == _ANALYTIC_WORST_CASE
    assert len(_compare_request(brief).brief) == _ANALYTIC_WORST_CASE
    assert _BRIEF_MAX > _ANALYTIC_WORST_CASE * 15, (
        "the bound must keep an order of magnitude of headroom over a real "
        "brief so it never becomes a silent truncation"
    )
