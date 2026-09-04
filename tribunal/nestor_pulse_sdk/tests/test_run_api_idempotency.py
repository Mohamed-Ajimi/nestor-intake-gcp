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

The LIVE tests use the session-scoped testcontainers Postgres from
`conftest.py`, which SKIPS cleanly (never errors) when Docker is unreachable --
so this file is safe in `tribunal/cloudbuild.test.yaml`, which sets no
DATABASE_URL and has no Docker-in-Docker.
"""

from __future__ import annotations

import asyncio
import json
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
# LIVE harness -- testcontainers Postgres via conftest's `async_engine`.
# ---------------------------------------------------------------------------

def _claims(tenant_id, user_id=None):
    from nestor_pulse_sdk.auth.provider import AuthClaims

    user_id = user_id or uuid.uuid4()
    return AuthClaims(
        app_user_id=str(user_id),
        tenant_id=str(tenant_id),
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        raw_provider_user_id=f"fb-{uuid.uuid4().hex[:8]}",
    )


async def _make_sessionmaker(async_engine):
    """Create the model schema on the ephemeral DB and return a sessionmaker.

    `Base.metadata.create_all` (not alembic) is deliberate: migration 0008
    GRANTs to a `worker_user` role that does not exist in an ephemeral
    testcontainer, which is exactly why the alembic-based live tests in
    `test_advisory_lock_exactly_once.py` fail on this machine. The models are
    all these tests need.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.base import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
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
    async_engine, set_tenant
) -> None:
    """TWO concurrent GETs on the SAME uncached run must produce EXACTLY ONE
    paid generation and EXACTLY ONE cached Output row, and both callers must
    get the same proposal back.

    Without the advisory lock this fails with TWO recorded generation calls --
    the double spend CONTEXT section 4 found.
    """
    Session = await _make_sessionmaker(async_engine)
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


async def test_warm_cache_proposal_never_generates(async_engine, set_tenant) -> None:
    """A run that already has a cached proposal must be served from cache with
    ZERO generation calls -- the lock must not turn a free read into a paid
    one."""
    from nestor_pulse_sdk.db.models import Output

    Session = await _make_sessionmaker(async_engine)
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
    async_engine, set_tenant
) -> None:
    """The lock is PER RUN, not global: two callers for two DIFFERENT uncached
    runs must both generate, and their generations must genuinely OVERLAP in
    time (asserted on recorded intervals, not on a flaky wall-clock threshold).
    """
    Session = await _make_sessionmaker(async_engine)
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
    async_engine, set_tenant
) -> None:
    """No cached research bundle -> still 409 with the existing message, no
    generation, and the lock released with the transaction (a later caller for
    the same run is not blocked)."""
    from fastapi import HTTPException

    Session = await _make_sessionmaker(async_engine)
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
