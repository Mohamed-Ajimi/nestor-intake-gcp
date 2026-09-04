"""D-23.1-06 — a worker that LOST its run must not be able to write to that run.

Phase 23.1, plan 05. `23.1-CONTEXT.md` § 4 verified that a fencing token already
exists and that an external audit was WRONG to say there was none:
`runs/execute.py:88` `_CONSUME_CLAIM_SQL` gates on
`worker_id = :wid AND started_at = :token` under a per-run advisory lock, so any
one claim can be DISPATCHED at most once. What escaped that fence is the
BOOKKEEPING the worker writes afterwards. Every one of those statements gated on
`status = 'running'` alone, which says "this run is unfinished" and says nothing
at all about WHO is allowed to finish it.

The defect, concretely
----------------------
After a stale reclaim (`CLAIM_SQL`, 120 consecutive missed heartbeats at the
shipped `STALE_RUN_MINUTES=60` / 30s cadence) the `run` row's `worker_id` becomes
the NEW owner's. The OLD worker may still be alive — displaced, not dead — and
still holding its own `claimed` dict. Before this fix that displaced process
could:

  1. keep bumping `heartbeat_at`, which suppresses the very stale reclaim that
     exists to rescue the run (the mitigation defeating its own mitigation), and
  2. stamp a terminal status, a `cost_usd_total`, an `error_message`, a report
     `Output` body and a rejected-claims `Output` ledger onto a run the new
     owner is still executing, and
  3. PARK the run — flipping it off `running` to `needs_input` /
     `needs_report_spec` / `parked`, which silently disarms the new owner's own
     `status='running'` guard and strands the run carrying clarifying questions
     from an execution nobody asked for.

The fix is one extra predicate — `AND worker_id = :wid` — on the heartbeat, on
both terminal writes, and on all three park writes. The `status = 'running'`
clause is KEPT everywhere alongside it (D-23.1-06 says both, not one): that
clause is what makes a user cancel win over a late write, and dropping it while
adding the fence would trade one defect for another.

THE BIND IS THE MODULE `WORKER_ID`, NOT `claimed["worker_id"]`
--------------------------------------------------------------
At claim time those two are EQUAL, so a happy-path test cannot tell them apart.
They diverge exactly where it matters: after a reclaim the ROW carries the new
owner's id while `claimed["worker_id"]` is a stale copy this process is still
carrying in memory. Fencing against the stale copy fences against nothing.
`test_the_wid_bind_is_this_process_not_the_claimed_copy` is the one test that
discriminates, and it is the reason this file exists rather than a grep.

`REAP_SQL` IS DELIBERATELY NOT FENCED
-------------------------------------
`test_reap_sql_must_never_be_fenced_by_worker_id` asserts the ABSENCE of the
predicate there, and that is not a style rule. `REAP_SQL` exists to fail a run
whose worker has gone silent AND has exhausted `MAX_RECLAIMS`. Adding
`worker_id = :wid` would mean the reaper could only ever fire on runs it already
owns — i.e. never on the abandoned runs it was built for — converting a safety
net into a permanent leak of rows stuck in `running` forever. That is precisely
the failure `REAP_SQL`'s own comment says it prevents. A future "consistency"
cleanup that adds the clause there must go red.

What each test proves
---------------------
| # | Test | Proves | Threat |
|---|------|--------|--------|
| 1 | heartbeat_sql_carries_both_guards | the fence AND the cancel guard are both on the heartbeat | T-23.1-16 / T-23.1-19 |
| 2 | terminal_success_update_carries_both_guards | ...on the success write, in BOTH `_has_summary` branches | T-23.1-17 / T-23.1-19 |
| 3 | terminal_failure_update_carries_both_guards | ...on the failure write | T-23.1-17 / T-23.1-19 |
| 4 | park_updates_carry_both_guards | ...on all three park writes | T-23.1-17 |
| 5 | the_wid_bind_is_this_process_not_the_claimed_copy | the fence is bound to THIS PROCESS, not to a stale copy | T-23.1-16 |
| 6 | reap_sql_must_never_be_fenced_by_worker_id | the reaper stays able to reap abandoned runs | — |
| 7 | owner_heartbeat_advances_heartbeat_at | LIVE: the real owner is unaffected | T-23.1-16 |
| 8 | displaced_worker_heartbeat_matches_zero_rows | LIVE: the displaced worker cannot assert liveness | T-23.1-16 |
| 9 | cancelled_run_heartbeat_matches_zero_rows | LIVE: the pre-existing cancel guard still bites | T-23.1-19 |
| 10 | owner_completes_the_run_and_writes_the_report_output | LIVE: the real owner still finalizes and still writes its report | T-23.1-17 |
| 11 | displaced_worker_writes_neither_status_nor_output | LIVE: no status, no `Output` row of either format | T-23.1-17 / T-23.1-18 |
| 12 | displaced_worker_failure_path_leaves_error_message_null | LIVE: the failure twin is fenced too | T-23.1-17 |
| 13 | cancelled_run_gets_no_terminal_write_and_no_output | LIVE: cancel still wins over a late terminal write | T-23.1-19 |
| 14 | owner_can_still_park_a_run | LIVE: the park path works for the legitimate owner | — |
| 15 | displaced_worker_cannot_park_a_run | LIVE: a displaced park cannot disarm the new owner's guard | T-23.1-17 |
| 16 | reap_still_fires_on_a_run_whose_worker_is_gone | LIVE: test 6's absence is real behaviour, not just text | — |

Scope note (T-23.1-20, TRANSFERRED — `23.1-CONTEXT.md` § 10)
------------------------------------------------------------
Nothing in this file — and nothing in this phase — re-checks the fence DURING
execution. A reclaimed run can still be EXECUTED twice at full paid cost; what
this file proves is that the second execution cannot WRITE. No assertion here
should be read as closing that.

Harness
-------
Tests 1–6 are offline (no DB, no engine, no provider) and MUST NEVER SKIP.
Tests 7–16 need `DATABASE_URL` (a `postgresql+asyncpg://` DSN) pointing at a
MIGRATED, DISPOSABLE tribunal schema, exactly like `test_stale_reclaim.py`, whose
harness this clones. **A SKIP IS NOT A PASS**, and today no COMMITTED gate config
hands this file a DSN: `cloudbuild.test.yaml` runs the whole directory but sets
no `DATABASE_URL`, and `cloudbuild.test-critical.yaml` (which does) names four
files explicitly and this is not one of them — the same standing gap
`test_stale_reclaim.py` already carries. If you are reading a build log, read the
`-rs` skip summary, not the exit status.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.integration

_SDK_ROOT = Path(__file__).resolve().parents[1]

# The identity a DISPLACED worker's row carries: anything that is not this
# process. Written as a constant so no test can accidentally seed the row with
# the module WORKER_ID and pass vacuously.
_OTHER_WORKER = "some-other-worker-that-reclaimed-this-run"


# ===========================================================================
# PART A — OFFLINE PROOFS (no database, no engine, no provider). NEVER SKIP.
# ===========================================================================

def _capture_execute_run(runner_result=None, runner_exc=None, claimed_overrides=None):
    """Drive the REAL `execute_run` against a fake session and return every
    (sql, params) pair it issued.

    No database and no provider: `dispatch_runner` is patched to a stub whose
    `run()` returns `runner_result` (or raises `runner_exc`), and the sessionmaker
    is a fake that records statements instead of executing them. This is the same
    idiom `test_gate_replay.py` uses to assert on the completion UPDATE, and it
    lets these assertions read the string the worker ACTUALLY assembles at runtime
    rather than a grep over the source.
    """
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")

    executed: list[tuple[str, Any]] = []

    class _FakeBeginCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def begin(self):
            return _FakeBeginCtx()

        async def execute(self, stmt, params=None):
            executed.append((str(stmt), params))
            return MagicMock()

    class _FakeSessionmakerCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            pass

    def fake_get_sessionmaker():
        return lambda: _FakeSessionmakerCtx()

    async def fake_set_tenant_context(session, tenant_id):
        return None

    runner = MagicMock()
    if runner_exc is not None:
        runner.run = AsyncMock(side_effect=runner_exc)
    else:
        runner.run = AsyncMock(return_value=runner_result)

    claimed = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "engine": "sdk",
        "brief": "ownership fence",
    }
    if claimed_overrides:
        claimed.update(claimed_overrides)

    async def _drive():
        with patch(
            "nestor_pulse_sdk.runs.worker.set_tenant_context",
            side_effect=fake_set_tenant_context,
        ):
            with patch(
                "nestor_pulse_sdk.runs.worker.get_sessionmaker", fake_get_sessionmaker
            ):
                with patch(
                    "nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=runner
                ):
                    await worker_mod.execute_run(claimed)

    asyncio.run(_drive())
    return executed


def _only(executed, needle: str):
    """The single captured statement containing `needle`, or a clear failure."""
    hits = [(sql, params) for sql, params in executed if needle in sql]
    assert len(hits) == 1, (
        f"expected exactly one statement containing {needle!r}, got {len(hits)}: "
        f"{[sql for sql, _ in executed]}"
    )
    return hits[0]


def _assert_both_guards(sql: str, what: str) -> None:
    """BOTH clauses, asserted SEPARATELY.

    Two assertions, never one compound: a single `A and B` assertion that fails
    does not say WHICH half went, and the half that silently disappears is the
    one nobody notices. D-23.1-06 is explicit that this is both, not one.
    """
    assert "worker_id = :wid" in sql, (
        f"{what} lost its D-23.1-06 ownership fence. Without it a "
        "displaced-but-alive worker can write to a run the new owner holds."
    )
    assert "status='running'" in sql or "status = 'running'" in sql, (
        f"{what} lost its cancel guard. That clause is what makes a user cancel "
        "win over a late write; D-23.1-06 keeps BOTH predicates, not one."
    )


def test_heartbeat_sql_carries_both_guards():
    """T-23.1-16 + T-23.1-19 — the liveness write is fenced AND still cancel-guarded."""
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    _assert_both_guards(worker_mod._HEARTBEAT_SQL.text, "_HEARTBEAT_SQL")


@pytest.mark.parametrize(
    "runner_result,branch",
    [
        ({"output_text": "body"}, "no-verification-summary"),
        (
            {
                "output_text": "body",
                "verification_summary": {"bucket1": 1, "bucket2": 2, "bucket3": 0},
            },
            "with-verification-summary",
        ),
    ],
    ids=["has_summary=False", "has_summary=True"],
)
def test_terminal_success_update_carries_both_guards(runner_result, branch):
    """T-23.1-17 + T-23.1-19 — BOTH assemblies of the success write are fenced.

    The success statement is built by concatenation around a conditionally
    spliced `verification_summary = ...` fragment, so there are two runtime
    strings, not one. A predicate that landed inside the splice would be present
    in one branch and absent in the other; parametrising over `_has_summary`
    is what makes that unrepresentable.
    """
    executed = _capture_execute_run(runner_result=runner_result)
    sql, params = _only(executed, "status=:final_status")
    _assert_both_guards(sql, f"the success terminal UPDATE ({branch})")
    assert params.get("wid"), "the success UPDATE must bind :wid"


def test_terminal_failure_update_carries_both_guards():
    """T-23.1-17 + T-23.1-19 — the failure twin is fenced too."""
    executed = _capture_execute_run(runner_exc=RuntimeError("runner crashed"))
    sql, params = _only(executed, "status='failed'")
    _assert_both_guards(sql, "the failure terminal UPDATE")
    assert params.get("wid"), "the failure UPDATE must bind :wid"


@pytest.mark.parametrize(
    "runner_result,needle,what",
    [
        (
            {"needs_clarification": True, "clarifying_questions": ["q?"]},
            "status='needs_input'",
            "the needs_input park write",
        ),
        (
            {"needs_report_spec": True},
            "status='needs_report_spec'",
            "the needs_report_spec park write",
        ),
        (
            {
                "parked": True,
                "park": {"reason": "every provider walled", "stage": "research"},
                "terminal_inputs": {"streams_lost": 4, "streams_total": 4},
            },
            "status=:park_status",
            "the R4 park write",
        ),
    ],
    ids=["needs_input", "needs_report_spec", "parked"],
)
def test_park_updates_carry_both_guards(runner_result, needle, what):
    """Plan-05 extension beyond the literal wording of D-23.1-06, argued in the
    SUMMARY: a park is a write that moves the row OFF `running`.

    A displaced worker that parks a run therefore DISARMS the new owner's own
    `status='running'` guard — the fence added to the terminal writes would be
    reachable around, through a door that is also user-visible ("this run needs
    you") and that invites a human to answer clarifying questions belonging to a
    discarded execution. Same threat class as T-23.1-17, so the same predicate.
    """
    executed = _capture_execute_run(runner_result=runner_result)
    sql, params = _only(executed, needle)
    _assert_both_guards(sql, what)
    assert params.get("wid"), f"{what} must bind :wid"


def test_the_wid_bind_is_this_process_not_the_claimed_copy():
    """T-23.1-16 — the fence is bound to the module `WORKER_ID`, not to the row
    copy the worker is carrying.

    THIS IS THE ONLY TEST IN THE FILE THAT DISCRIMINATES BETWEEN THE TWO. At
    claim time `claimed["worker_id"] == WORKER_ID`, so every happy-path assertion
    passes under either binding. They diverge after a reclaim: the ROW then holds
    the new owner's id and `claimed["worker_id"]` is a stale in-memory copy, so a
    fence bound to the copy would match the copy and fence NOTHING. The claimed
    dict below deliberately carries a foreign worker_id to force the difference.
    """
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")

    executed = _capture_execute_run(
        runner_result={"output_text": "body"},
        claimed_overrides={"worker_id": _OTHER_WORKER},
    )
    _, params = _only(executed, "status=:final_status")
    assert params["wid"] == worker_mod.WORKER_ID, (
        "the ownership fence bound something other than this process's WORKER_ID"
    )
    assert params["wid"] != _OTHER_WORKER, (
        "the fence was bound to claimed['worker_id'] — a stale copy that, after a "
        "reclaim, is exactly the identity that no longer owns the row. Binding it "
        "makes the predicate always true for the displaced worker and fences nothing."
    )


def test_reap_sql_must_never_be_fenced_by_worker_id():
    """`REAP_SQL` has NO `worker_id` clause, and must never gain one.

    Not a style rule. The reaper exists to fail a run whose worker has gone
    SILENT and has already exhausted `MAX_RECLAIMS`. Fencing it on
    `worker_id = :wid` would let it fire only on runs the reaping process already
    owns — i.e. never on the abandoned runs it was built for. Those rows would
    then sit in `running` forever, unretryable (the intake's retry gate excludes
    `running`), which is the exact failure `REAP_SQL`'s own comment says it
    prevents. If a later "make it consistent" pass adds the clause, this goes red.
    """
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    assert "worker_id" not in worker_mod.REAP_SQL.text, (
        "REAP_SQL gained a worker_id clause. That converts the safety net into a "
        "permanent leak: a run abandoned by a dead worker could never be reaped "
        "by any live one, and would sit in 'running' forever."
    )
    # And the guards it DOES need are still there.
    assert "status = 'running'" in worker_mod.REAP_SQL.text
    assert "reclaim_count >= :max_reclaims" in worker_mod.REAP_SQL.text


# ===========================================================================
# PART B — LIVE PROOFS against a real, migrated Postgres.
#
# A SKIP HERE IS NOT A PASS. See the module docstring: no committed gate config
# currently hands this file a DATABASE_URL.
# ===========================================================================

def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql+asyncpg://"):
        pytest.skip(
            "DATABASE_URL is unset (or is not a postgresql+asyncpg:// DSN), so the "
            "D-23.1-06 ownership-fence proofs did NOT run. THIS IS NOT A PASS: the "
            "displaced-worker writes these tests cover are unproven in this build. "
            "Run this file with a DSN pointing at a migrated, disposable tribunal "
            "schema (the shape tribunal/cloudbuild.test-critical.yaml provisions)."
        )
    return url


@pytest.fixture
async def worker_db():
    """(sessionmaker, tenant_id, project_id) against a migrated tribunal schema.

    Cloned from `test_stale_reclaim.py::worker_db`, including its role guard: in
    production the claim, the heartbeat and the terminal writes are all issued by
    the RLS-exempt `worker_user` role (policy `run_worker_all`, migration 0008).
    Under an ordinary `app_user` DSN the `run` row is invisible without
    `app.tenant_id`, so every statement here would match zero rows and every
    "displaced worker matched zero rows" assertion would pass VACUOUSLY — green
    while proving nothing. Skip loudly instead.
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

    # 13-REVIEW WR-06: get_engine() is lru_cached, and BOTH _heartbeat_loop and
    # execute_run use the CACHED sessionmaker, so the cache must be primed
    # against this DSN and cleared afterwards or a later test on a new event loop
    # reuses asyncpg connections belonging to a closed one.
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
            "RLS hides the seeded `run` rows and every statement under test would "
            "match zero rows for the OWNER as well as the displaced worker. THIS "
            "IS NOT A PASS — it is a vacuous green refused."
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
                    "n": f"ownership-fence-{tenant_id}",
                    "s": f"ownership-fence-{tenant_id.hex[:12]}",
                },
            )
            await session.execute(
                sa.text("INSERT INTO project (id, tenant_id, name) VALUES (:id, :t, :n)"),
                {"id": str(project_id), "t": str(tenant_id), "n": "ownership-fence"},
            )

    try:
        yield sessionmaker, tenant_id, project_id
    finally:
        try:
            async with sessionmaker() as session:
                async with session.begin():
                    await session.execute(sa.text("SET search_path TO tribunal"))
                    await session.execute(
                        sa.text("DELETE FROM org WHERE id = :id"), {"id": str(tenant_id)}
                    )
        finally:
            try:
                await base_mod.get_engine().dispose()
            except Exception:  # noqa: BLE001
                pass
            base_mod.get_engine.cache_clear()
            await engine.dispose()


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
    status: str = "running",
    worker_id: str | None = None,
    created_min_ago: int = 60,
    started_min_ago: int | None = 10,
    hb_min_ago: int | None = 5,
    reclaim_count: int = 0,
    brief: str = "ownership fence seed",
):
    """Insert one `run` with an exact ownership + liveness shape."""
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
                        "reclaim_count, error_message, completed_at, cost_usd_total, "
                        "clarifying_questions "
                        "FROM run WHERE id = :id"
                    ),
                    {"id": str(run_id)},
                )
            ).first()
    assert row is not None, f"seeded run {run_id} disappeared"
    return dict(row._mapping)


async def _output_formats(sessionmaker, run_id) -> list[str]:
    """Every `output.format` written for this run, in insertion order."""
    sa = pytest.importorskip("sqlalchemy")
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            rows = (
                await session.execute(
                    sa.text(
                        "SELECT format FROM output WHERE run_id = :id ORDER BY created_at"
                    ),
                    {"id": str(run_id)},
                )
            ).fetchall()
    return [r[0] for r in rows]


async def _heartbeat_once(sessionmaker, run_id) -> int:
    """Run the PRODUCTION `_HEARTBEAT_SQL` exactly as `_heartbeat_loop` binds it.

    The loop's parameter dict is mirrored here rather than the loop being driven,
    so the assertion is on ROWCOUNT — "matched zero rows" is the property under
    test and a timing-based observation could not distinguish it from a slow write.
    """
    sa = pytest.importorskip("sqlalchemy")
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            result = await session.execute(
                worker._HEARTBEAT_SQL, {"id": str(run_id), "wid": worker.WORKER_ID}
            )
    return result.rowcount


async def _run_execute_run(sessionmaker, claimed, *, runner_result=None, runner_exc=None):
    """Drive the REAL `execute_run` against the REAL database with a stub runner.

    ZERO provider spend: `dispatch_runner` is patched, so no engine, no LLM and no
    network call happens. Everything else — `set_tenant_context`, the terminal
    UPDATE, the two `Output` INSERTs — is the production path against real rows.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    runner = MagicMock()
    if runner_exc is not None:
        runner.run = AsyncMock(side_effect=runner_exc)
    else:
        runner.run = AsyncMock(return_value=runner_result)
    with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=runner):
        await worker.execute_run(claimed)


def _claimed(run_id, tenant_id, project_id, *, worker_id):
    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "engine": "sdk",
        "brief": "ownership fence",
        "worker_id": worker_id,
        "started_at": None,
    }


# ---------------------------------------------------------------------------
# Tests 7–9 — the heartbeat, LIVE
# ---------------------------------------------------------------------------

async def test_owner_heartbeat_advances_heartbeat_at(worker_db):
    """T-23.1-16, the half that must NOT change: the real owner still heartbeats.

    Asserted on the ROW's timestamp moving, not on the statement having run — a
    fence that silently blocked the legitimate owner would look identical to a
    working one if all we checked was that no exception was raised.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=worker.WORKER_ID
    )
    before = (await _read_run(sessionmaker, run_id))["heartbeat_at"]

    assert await _heartbeat_once(sessionmaker, run_id) == 1, (
        "the OWNER's heartbeat matched zero rows — the fence is blocking the very "
        "worker it is supposed to admit, which would make every long run look dead"
    )
    after = (await _read_run(sessionmaker, run_id))["heartbeat_at"]
    assert after > before


async def test_displaced_worker_heartbeat_matches_zero_rows(worker_db):
    """T-23.1-16 — the headline. A worker that lost the run cannot claim it is alive.

    Without the fence this UPDATE succeeds, `heartbeat_at` keeps moving, and
    `CLAIM_SQL`'s staleness test therefore never fires — the displaced worker
    suppresses the stale reclaim that exists to rescue the run from it.
    """
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=_OTHER_WORKER
    )
    before = (await _read_run(sessionmaker, run_id))["heartbeat_at"]

    assert await _heartbeat_once(sessionmaker, run_id) == 0, (
        "a displaced worker's heartbeat still matched the row: it can keep a run "
        "it no longer owns looking alive, suppressing the stale reclaim"
    )
    after = (await _read_run(sessionmaker, run_id))["heartbeat_at"]
    assert after == before, "heartbeat_at moved despite the fence"


async def test_cancelled_run_heartbeat_matches_zero_rows(worker_db):
    """T-23.1-19 — the regression this plan must NOT cause.

    Adding `worker_id` while dropping `status='running'` would be a silent trade:
    the run below is owned by THIS process, so only the status clause can stop
    the write. If it were removed, a cancelled run would keep looking alive.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="cancelled",
        worker_id=worker.WORKER_ID,
    )
    before = (await _read_run(sessionmaker, run_id))["heartbeat_at"]

    assert await _heartbeat_once(sessionmaker, run_id) == 0, (
        "a cancelled run still heartbeats — the status='running' guard was lost "
        "while the ownership fence was added"
    )
    assert (await _read_run(sessionmaker, run_id))["heartbeat_at"] == before


# ---------------------------------------------------------------------------
# Tests 10–13 — the terminal writes, LIVE
# ---------------------------------------------------------------------------

async def test_owner_completes_the_run_and_writes_the_report_output(worker_db):
    """T-23.1-17, the half that must NOT change: the new owner still finalizes.

    This is the control for tests 11–13. If it ever goes red the fence has locked
    out the legitimate worker, and every run would hang in `running` until reaped.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=worker.WORKER_ID
    )

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_result={
            "output_text": "the report body",
            "rejected_claims": [{"claim": "dropped", "why": "unsupported"}],
        },
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "completed", (
        f"the OWNER did not complete its own run (status={row['status']!r}) — the "
        "fence is refusing the worker it must admit"
    )
    assert row["completed_at"] is not None
    assert row["cost_usd_total"] is not None, "cost_usd_total must be rolled up"
    assert sorted(await _output_formats(sessionmaker, run_id)) == [
        "markdown",
        "rejected_claims",
    ], "the owner must still write both Output rows"


async def test_displaced_worker_writes_neither_status_nor_output(worker_db):
    """T-23.1-17 + T-23.1-18 — the assertion that matters most.

    A displaced worker must not stamp a terminal status, and — because the two
    `Output` INSERTs are gated on `completed.rowcount` — must not write a report
    body or a rejected-claims ledger either. Two `Output` rows of the same format
    for one run would give the audit chain two report bodies for one run and no
    way to say which the human read.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=_OTHER_WORKER
    )
    before_formats = await _output_formats(sessionmaker, run_id)

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_result={
            "output_text": "a report the new owner did not ask for",
            "rejected_claims": [{"claim": "dropped", "why": "unsupported"}],
        },
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "running", (
        "a displaced worker stamped a terminal status over a run the new owner is "
        f"still executing (status={row['status']!r})"
    )
    assert row["worker_id"] == _OTHER_WORKER, "ownership must be untouched"
    assert row["completed_at"] is None
    assert await _output_formats(sessionmaker, run_id) == before_formats, (
        "a displaced worker wrote an Output row. The audit chain now holds a "
        "report body from an execution nobody asked for (T-23.1-18)."
    )


async def test_displaced_worker_failure_path_leaves_error_message_null(worker_db):
    """T-23.1-17 — the failure twin is fenced too.

    Symmetry matters here: an unfenced failure write is arguably worse than an
    unfenced success one, because it moves the run to `failed` and so disarms the
    real owner's own `status='running'` guard on the way past.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=_OTHER_WORKER
    )

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_exc=RuntimeError("the displaced worker's engine crashed"),
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "running", (
        f"a displaced worker failed a run it does not own (status={row['status']!r})"
    )
    assert row["error_message"] is None, (
        "a displaced worker wrote its own crash onto the new owner's run"
    )


async def test_cancelled_run_gets_no_terminal_write_and_no_output(worker_db):
    """T-23.1-19 — cancel still wins, proved on a run this process DOES own.

    The only clause that can stop this write is `status='running'`. If a later
    edit "simplifies" the WHERE down to the ownership fence alone, this goes red.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="cancelled",
        worker_id=worker.WORKER_ID,
    )

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_result={"output_text": "a report for a cancelled run"},
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "cancelled", (
        "the cancel verdict was overwritten by a late terminal write"
    )
    assert await _output_formats(sessionmaker, run_id) == [], (
        "a cancelled run got a report body"
    )


# ---------------------------------------------------------------------------
# Tests 14–15 — the park writes, LIVE (plan-05 extension)
# ---------------------------------------------------------------------------

async def test_owner_can_still_park_a_run(worker_db):
    """The park path still works for the LEGITIMATE owner.

    Required before fencing the park writes could be defensible: the extension is
    only safe if the owner's park is untouched. Asserted on the row's status AND
    on the questions it carries, because a park that lost its payload would be a
    park the user cannot act on.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=worker.WORKER_ID
    )

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_result={
            "needs_clarification": True,
            "clarifying_questions": ["which market?"],
        },
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "needs_input", (
        f"the OWNER could not park its own run (status={row['status']!r}) — the "
        "park fence is refusing the worker it must admit"
    )
    assert row["clarifying_questions"], "the park must carry its questions"


async def test_displaced_worker_cannot_park_a_run(worker_db):
    """The plan-05 extension, proved.

    A park moves the row OFF `running`, which disarms the new owner's own
    `status='running'` guard — so an unfenced park is a way around the fence
    added to the terminal writes, and a user-visible one at that: the run would
    sit in `needs_input` asking a human to answer questions produced by an
    execution that was already abandoned.
    """
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker, tenant_id, project_id, worker_id=_OTHER_WORKER
    )

    await _run_execute_run(
        sessionmaker,
        _claimed(run_id, tenant_id, project_id, worker_id=worker.WORKER_ID),
        runner_result={
            "needs_clarification": True,
            "clarifying_questions": ["a question from an abandoned execution"],
        },
    )

    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "running", (
        f"a displaced worker parked a run it does not own (status={row['status']!r}); "
        "the new owner's terminal write is now disarmed and the user is being asked "
        "to answer questions from an execution nobody is running"
    )
    assert row["clarifying_questions"] is None


# ---------------------------------------------------------------------------
# Test 16 — the reaper still reaps, LIVE
# ---------------------------------------------------------------------------

async def test_reap_still_fires_on_a_run_whose_worker_is_gone(worker_db):
    """`REAP_SQL`'s missing fence is real BEHAVIOUR, not just missing text.

    Test 6 asserts the clause is absent from the string; this proves what that
    absence buys. The row below is owned by a worker that is not this process and
    has exhausted `MAX_RECLAIMS` — exactly the abandoned run the reaper exists
    for. Had the fence been added "for consistency", this would match zero rows
    and the run would sit in `running` forever.
    """
    sa = pytest.importorskip("sqlalchemy")
    worker = pytest.importorskip("nestor_pulse_sdk.runs.worker")
    sessionmaker, tenant_id, project_id = worker_db
    run_id = await _seed_run(
        sessionmaker,
        tenant_id,
        project_id,
        status="running",
        worker_id=_OTHER_WORKER,
        created_min_ago=600,
        started_min_ago=300,
        hb_min_ago=180,
        reclaim_count=2,
    )

    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(sa.text("SET search_path TO tribunal"))
            reaped = [
                str(r[0])
                for r in (
                    await session.execute(
                        worker.REAP_SQL,
                        {
                            "msg": worker._reap_message(),
                            "stale": 60,
                            "max_reclaims": 2,
                        },
                    )
                ).fetchall()
            ]

    assert str(run_id) in reaped, (
        "REAP_SQL did not reap an abandoned over-ceiling run. If a worker_id "
        "fence was added there, the reaper can now only reap runs it already "
        "owns — never the abandoned ones it was built for."
    )
    row = await _read_run(sessionmaker, run_id)
    assert row["status"] == "failed"
    assert row["error_message"] and row["error_message"].strip()
