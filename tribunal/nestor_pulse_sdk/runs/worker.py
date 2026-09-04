"""
Async worker poll loop with SKIP LOCKED claim + engine dispatch (D-09).

References:
- 01-RESEARCH.md § Pattern 3 SKIP LOCKED + worker_loop lines 461-511
- 01-RESEARCH.md Anti-pattern line 583: SET LOCAL AFTER claim, NOT before
- 01-CONTEXT.md D-09: single worker, poll, status transitions
- 01-CONTEXT.md D-02: engine field routes to ADK or SDK pipeline

CRITICAL ORDERING (T-06-02):
  1. CLAIM step: claim_one() uses elevated worker role (BYPASSRLS user).
     This is a 1-statement surgical bypass -- the CLAIM_SQL itself runs
     without tenant filtering.
  2. IMMEDIATELY AFTER claim: execute_run() calls set_tenant_context(session, run.tenant_id)
     BEFORE any further tenant-scoped DB access.
  DO NOT call set_tenant_context BEFORE the claim step.

Crash recovery (T-06-04, B2 fix, REWRITTEN by the D-E fix):
  A run is reclaimable ONLY when the worker executing it has STOPPED WRITING
  HEARTBEATS, and only a BOUNDED number of times.

  The old rule was `status = 'running' AND started_at < NOW() - <stale>`. That
  was wrong, and it fired for real on 2026-07-27: `started_at` is stamped once
  at claim time and never moves again, so a live process holding a 35-minute
  deep-research long-poll was INDISTINGUISHABLE from a process that died 35
  minutes ago. Killing a stuck worker therefore started a fresh one that was
  seconds from re-executing the same run at full cost, unattended, on a 60-minute
  loop. It was held back only by a temporary NESTOR_WORKER_STALE_MINUTES=525600
  on the deployed service -- which is worse in the other direction, because with
  it set a genuinely crashed worker is NEVER recovered.

  The rule now has two parts:
    1. LIVENESS. `run.heartbeat_at` (migration 0014) is bumped on a timer by the
       executing worker while `runner.run()` is awaited, so a live process has a
       fresh heartbeat even during a silent long-poll and a dead one stops
       writing within one HEARTBEAT_INTERVAL_SECONDS. Staleness is measured as
       `COALESCE(heartbeat_at, started_at)`, so a pre-0014 row behaves exactly as
       it did before.
    2. A CEILING. `run.reclaim_count` is incremented by the claim ONLY when it
       re-claims a row that was already 'running'. Past MAX_RECLAIMS the run is
       no longer claimable at all, and REAP_SQL FAILS it with a worded
       error_message instead of starting it again. "A permanently stalling run
       re-bills every 60 minutes forever" is therefore structurally unreachable.

  `started_at` is NOT the heartbeat and must never become one: it is the CR-01
  FENCING TOKEN that `runs/execute.py::_CONSUME_CLAIM_SQL` matches to guarantee a
  claim dispatches at most once (ENGINE-08, legally load-bearing for the audit
  chain). Bumping it on a timer would make every heartbeat invalidate the run's
  own claim token.

  IMPORTANT (unchanged): must use make_interval(mins => :stale), NOT
  INTERVAL ':stale minutes' (the literal-bind variant fails at runtime with
  bound params -- B2 fix).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.db.base import get_sessionmaker
from nestor_pulse_sdk.db.rls import set_tenant_context
from nestor_pulse_sdk.pipeline.tribunal.reliability import terminal_state

log = structlog.get_logger(__name__)
# Unique per PROCESS: Cloud Run instances can share hostname ('localhost') and
# pid (1), so hostname-pid alone collides across instances — the advisory-lock
# ownership re-check (runs/execute.py) keys on worker_id, which must therefore
# be globally unique (13-REVIEW CR-01/IN-01).
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
POLL_INTERVAL_SECONDS = float(os.environ.get("NESTOR_WORKER_POLL_INTERVAL", "2.0"))
STALE_RUN_MINUTES = int(os.environ.get("NESTOR_WORKER_STALE_MINUTES", "60"))
# Liveness cadence (D-E): how often the EXECUTING worker bumps run.heartbeat_at
# while runner.run() is awaited. Read as float (like POLL_INTERVAL_SECONDS, not
# like STALE_RUN_MINUTES) so a test can drive it sub-second without a code change.
#
# MUST stay well under STALE_RUN_MINUTES * 60. At the defaults that is 30s
# against 3600s -- a ratio of 120, i.e. a run is only considered abandoned after
# 120 consecutive heartbeats have failed to land. If you ever raise this, raise
# STALE_RUN_MINUTES with it or you will start reclaiming live runs again.
HEARTBEAT_INTERVAL_SECONDS = float(os.environ.get("NESTOR_WORKER_HEARTBEAT_S", "30"))
# The number of CRASH RECOVERIES a single run is granted -- NOT the number of
# attempts. A run that keeps dying gets at most this many re-claims; past it,
# REAP_SQL FAILS it with a sentence rather than starting it again, because an
# unattended re-execute loop is a repeating spend (D-E: the worst case was a
# permanently stalling run re-billing every 60 minutes, forever).
MAX_RECLAIMS = int(os.environ.get("NESTOR_WORKER_MAX_RECLAIMS", "2"))

# ---------------------------------------------------------------------------
# CLAIM SQL -- SELECT FOR UPDATE SKIP LOCKED
# ---------------------------------------------------------------------------
# Two reclaimable conditions:
#   1. status = 'queued'  (normal work queue)
#   2. status = 'running'
#        AND COALESCE(heartbeat_at, started_at) < NOW() - make_interval(mins => :stale)
#        AND reclaim_count < :max_reclaims
#      (crash recovery: the worker STOPPED WRITING HEARTBEATS, and this run has
#       not already used up its bounded recoveries)
#
# THE STALENESS CLOCK IS THE HEARTBEAT, NOT started_at (D-E, 2026-07-27).
# started_at is stamped once at claim time and never moves, so measuring
# staleness by it makes a live 35-minute deep-research long-poll look exactly
# like a process that died 35 minutes ago -- and the designed response to a dead
# process is to re-run, at full cost, unattended. COALESCE(heartbeat_at,
# started_at) keeps pre-0014 rows behaving exactly as they do today while giving
# every new run a real liveness signal. See the module docstring.
#
# B2 fix: use make_interval(mins => :stale) NOT INTERVAL ':stale minutes'
# The literal-string INTERVAL form cannot accept a bind parameter in SQLAlchemy
# text(); make_interval() is the correct parameterized form in Postgres.
#
# Note on worker_pg_role / BYPASSRLS:
#   Phase 1 simplification: the worker connects using a DB user with BYPASSRLS=ON
#   (worker_user created by `gcloud sql users create worker_user ...`).
#   This lets the CLAIM_SQL see ALL queued runs regardless of tenant_id, which
#   is required because the worker polls for any tenant's work.
#   IMMEDIATELY after claim, execute_run() calls set_tenant_context(session, run.tenant_id)
#   to restore RLS scope for all subsequent queries.
#   Phase 4 hardening: swap to SET LOCAL ROLE worker_pg_role for the claim
#   statement only, then RESET ROLE (or use a per-statement role flip).
#
# THE reclaim_count ARITHMETIC IS THE NON-OBVIOUS PART. In a Postgres UPDATE
# every expression on the right-hand side of SET reads the OLD row, so the
# `CASE WHEN status = 'running'` below tests the status the row had BEFORE this
# statement -- even though the same SET list is also assigning status='running'.
# That is exactly what we want: a reclaim of an already-'running' row counts,
# a fresh claim of a 'queued' row does not, so reclaim_count is a count of CRASH
# RECOVERIES and never of ordinary work.
CLAIM_SQL = text("""
    UPDATE run
       SET status = 'running',
           started_at = NOW(),
           worker_id = :wid,
           heartbeat_at = NOW(),
           reclaim_count = reclaim_count
                           + CASE WHEN status = 'running' THEN 1 ELSE 0 END
     WHERE id = (
       SELECT id FROM run
        WHERE status = 'queued'
           OR (status = 'running'
               AND COALESCE(heartbeat_at, started_at)
                   < NOW() - make_interval(mins => :stale)
               AND reclaim_count < :max_reclaims)
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
     )
   RETURNING id, tenant_id, project_id, engine, brief, worker_id, started_at,
             reclaim_count
""")


async def claim_one(session: AsyncSession) -> Optional[dict]:
    """
    CLAIM step: claims one queued (or stale-running) run via SKIP LOCKED.

    This runs WITHOUT tenant filtering -- the worker sees ALL tenants' queued
    work (required: we don't know the tenant until we read the row).

    Per RESEARCH Anti-pattern line 583: caller MUST call
    set_tenant_context(session, run.tenant_id) BEFORE any subsequent
    tenant-scoped query. execute_run() does this immediately after claim_one().

    Returns:
        dict with run fields if a row was claimed, None if queue is empty.
        `reclaim_count` in that dict is 0 for a fresh claim and >0 when this was
        a crash recovery (D-E).
    """
    result = await session.execute(
        CLAIM_SQL,
        {
            "wid": WORKER_ID,
            "stale": STALE_RUN_MINUTES,
            "max_reclaims": MAX_RECLAIMS,
        },
    )
    row = result.first()
    if row is None:
        return None
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# LIVENESS HEARTBEAT (D-E)
# ---------------------------------------------------------------------------
# The `AND status = 'running'` guard is what ends the heartbeat by itself: the
# instant a cancel or a terminal write moves the row off 'running', this UPDATE
# matches zero rows and the run's liveness stops being asserted -- so a heartbeat
# task that somehow outlives its run cannot keep a finished run looking alive.
#
# The `AND worker_id = :wid` guard is the D-23.1-06 OWNERSHIP FENCE, and it is a
# SECOND predicate, never a replacement: without the status clause a cancel would
# stop winning, and without the ownership clause a displaced-but-alive worker
# keeps asserting liveness on a run it has already LOST to a stale reclaim --
# which suppresses the very reclaim that exists to rescue that run, the mitigation
# defeating itself.
#
# :wid IS BOUND TO THE MODULE `WORKER_ID` -- THIS PROCESS -- AND NEVER TO
# `claimed["worker_id"]`. At claim time the two are equal, so no happy-path test
# can tell them apart. They diverge exactly where it matters: after a reclaim the
# ROW carries the new owner's id while `claimed["worker_id"]` is a stale copy this
# process is still holding in memory, so fencing against that copy fences against
# nothing at all.
_HEARTBEAT_SQL = text(
    "UPDATE run SET heartbeat_at = NOW() "
    "WHERE id = :id AND status = 'running' AND worker_id = :wid"
)


async def _heartbeat_loop(run_id) -> None:
    """Bump `run.heartbeat_at` on a timer for as long as this task is alive.

    This is the ONLY thing that tells the stale reclaim "the process executing
    this run is still here". Without it a silent 35-minute deep-research
    long-poll is indistinguishable from a dead worker (D-E).

    Exception-safe, verbatim per `stages.set_stage`'s contract: any failure is
    logged at WARNING and swallowed. A liveness write must never break the run it
    is reporting on -- a transient DB blip should cost one heartbeat, not the run.
    `asyncio.CancelledError` derives from BaseException, so `except Exception`
    does NOT swallow the cancellation that ends this task.

    It deliberately does NOT call `set_tenant_context`: like the claim, it is a
    primary-key UPDATE issued by the RLS-exempt `worker_user` role and it reads
    and writes no tenant data (T-15.2-205, accepted).

    The interval is read from the module global on every iteration so it can be
    driven sub-second by a test (the env var is parsed once at import).

    `wid` binds the module `WORKER_ID` (this process), which is what makes the
    D-23.1-06 fence above bite: once a stale reclaim has handed the row to another
    worker, this loop's UPDATE matches zero rows and quietly stops asserting a
    liveness it is no longer entitled to assert.
    """
    sessionmaker = get_sessionmaker()
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            async with sessionmaker() as session:
                async with session.begin():
                    await session.execute(
                        _HEARTBEAT_SQL,
                        {"id": str(run_id), "wid": WORKER_ID},
                    )
        except Exception:  # noqa: BLE001
            log.warning("run_heartbeat_failed", run_id=str(run_id), exc_info=True)


# ---------------------------------------------------------------------------
# THE REAP (D-E) -- the ceiling's terminal write
# ---------------------------------------------------------------------------
# A run that has used up its recoveries and whose worker has gone silent again
# must NOT sit in 'running' forever (nothing can retry it: the intake's retry
# gate excludes 'running') and must NOT be started again (that is the repeating
# spend). It is FAILED here, with one sentence a human reads.
REAP_SQL = text("""
    UPDATE run
       SET status = 'failed', completed_at = NOW(), error_message = :msg
     WHERE status = 'running'
       AND COALESCE(heartbeat_at, started_at) < NOW() - make_interval(mins => :stale)
       AND reclaim_count >= :max_reclaims
    RETURNING id
""")


def _reap_message() -> str:
    """One plain sentence, in the register of `verification/report.py` -- never a
    code. It has to be readable by whoever opens the run and asks what happened.
    """
    return (
        "This run was stopped because the worker executing it stopped responding, "
        f"and it had already been recovered and restarted {MAX_RECLAIMS} times. "
        "Rather than start it again -- which would keep spending money on a run "
        "that never finishes -- it was failed here so that a person can look at it."
    )


async def execute_run(claimed: dict) -> None:
    """
    Dispatch + execute a claimed run.

    CRITICAL: SET LOCAL app.tenant_id = claimed['tenant_id'] BEFORE any
    tenant-scoped query (RESEARCH Anti-pattern line 583, T-06-02).

    Ordering:
      1. dispatch_runner(engine) -- pure Python, no DB
      2. runner.run(...) -- may take minutes for deep research
      3. Post-completion: set_tenant_context + UPDATE run SET the terminal status
         computed by terminal_state() -- completed, or completed_degraded when a
         reason was named (D-12)
      4. On exception: set_tenant_context + UPDATE run SET status='failed'
    """
    from nestor_pulse_sdk.runs.adapter import dispatch_runner
    from nestor_pulse_sdk.runs.stages import RunCancelled

    sessionmaker = get_sessionmaker()
    runner = dispatch_runner(claimed["engine"])

    # LIVENESS (D-E). Declared BEFORE the try so the finally can always reach it,
    # even if create_task itself raises.
    _hb: Optional[asyncio.Task] = None
    try:
        # Start asserting liveness immediately before the long await. runner.run()
        # can be silent for ~35 minutes (deep research long-polls); without this
        # task the stale reclaim cannot tell that silence from a dead process.
        _hb = asyncio.create_task(_heartbeat_loop(claimed["id"]))
        result = await runner.run(
            brief=claimed["brief"],
            run_id=claimed["id"],
            tenant_id=claimed["tenant_id"],
        )
        # CLARIFICATION (0005): a vague brief -> the engine asked questions instead
        # of researching. Park the run as 'needs_input' carrying the questions; do
        # NOT mark it completed or write a report. The user answers via
        # POST /api/runs/{id}/answer, which re-queues a NEW run with the answers
        # folded into the brief.
        if isinstance(result, dict) and result.get("needs_clarification"):
            import json as _json
            questions = result.get("clarifying_questions") or []
            log.info(
                "run_needs_input", run_id=str(claimed["id"]), n_questions=len(questions)
            )
            async with sessionmaker() as session:
                async with session.begin():
                    await set_tenant_context(session, claimed["tenant_id"])
                    await session.execute(
                        text(
                            "UPDATE run SET status='needs_input', completed_at=NOW(), "
                            "clarifying_questions = CAST(:q AS JSONB), "
                            "cost_usd_total = COALESCE("
                            "(SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id), 0) "
                            # Guard: a user cancel (status='cancelled') must win.
                            # Fence: and only the OWNER may park (D-23.1-06). A park
                            # moves the row OFF 'running', which disarms the new
                            # owner's own status guard -- so an unfenced park is a
                            # way around the fence on the terminal writes, and a
                            # user-visible one: the run would sit asking a human to
                            # answer questions from an abandoned execution.
                            "WHERE id=:id AND status='running' AND worker_id = :wid"
                        ),
                        {
                            "q": _json.dumps(questions),
                            "id": claimed["id"],
                            "wid": WORKER_ID,
                        },
                    )
            return

        # REPORT-SPEC PAUSE (interactive report shaping): the Tribunal engine
        # finished research + verification + scrub and cached the bundle, then
        # paused for the user to shape the report. Park as 'needs_report_spec';
        # the user submits a spec (POST /report-spec) which re-queues this run and
        # the pipeline resumes from cache. No report is written yet.
        if isinstance(result, dict) and result.get("needs_report_spec"):
            log.info("run_needs_report_spec", run_id=str(claimed["id"]))
            async with sessionmaker() as session:
                async with session.begin():
                    await set_tenant_context(session, claimed["tenant_id"])
                    await session.execute(
                        text(
                            "UPDATE run SET status='needs_report_spec', "
                            "cost_usd_total = COALESCE("
                            "(SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id), 0) "
                            # Cancel guard + D-23.1-06 ownership fence; see the
                            # needs_input park above for why a park needs both.
                            "WHERE id=:id AND status='running' AND worker_id = :wid"
                        ),
                        {"id": claimed["id"], "wid": WORKER_ID},
                    )
            return

        # PARK (R4/D-17, plan 15.2-16). The engine could not produce an honest
        # deliverable — every research stream was lost, or a provider refused at
        # the account level (the monthly cap / exhausted credits / a 402 billing
        # block). The paid work is on disk as ckpt_* rows, so this is NOT a
        # failure: the run keeps its cost, carries its reason in words, and
        # POST /api/runs/{id}/resume re-queues this same run to continue from
        # those checkpoints.
        if isinstance(result, dict) and result.get("parked"):
            import json as _pjson
            _park = result.get("park") if isinstance(result.get("park"), dict) else {}
            _ti = (
                result.get("terminal_inputs")
                if isinstance(result.get("terminal_inputs"), dict) else {}
            )
            # DEC-6: terminal_state() is the SINGLE decision function. The
            # pipeline reported facts; we compute and write whatever the rule
            # returns. Same defensive read shape the verification_summary block
            # below uses.
            _park_status = terminal_state(
                streams_lost=int(_ti.get("streams_lost") or 0),
                streams_total=int(_ti.get("streams_total") or 1),
                verify_ran=bool(_ti.get("verify_ran", False)),
                synthesis_ran=bool(_ti.get("synthesis_ran", False)),
                hard_wall=bool(_ti.get("hard_wall", False)),
                degradation_reasons=[
                    str(r) for r in (_ti.get("degradation_reasons") or [])
                    if isinstance(r, str) and r.strip()
                ],
            )
            if _park_status != "parked":
                # A genuine contract violation: the pipeline took its park branch
                # but the facts it reported do not add up to a park. Say so, by
                # name -- and then WRITE THE COMPUTED VALUE ANYWAY. Overriding it
                # here would create the second park rule this phase exists to
                # remove.
                log.error(
                    "park_state_inconsistent",
                    run_id=str(claimed["id"]),
                    computed=_park_status,
                    terminal_inputs=_ti,
                )
            # `park` is a SIBLING key on the persisted summary, added on the
            # WRITE side only: build_verification_summary() and
            # RECORDED_FUNNEL_COUNTS are NOT touched (Pitfall 3 -- the recorded
            # funnel is compared by full dict equality in two tests). Copy, never
            # mutate the pipeline's dict. With no funnel at all the row carries
            # `park` alone, and report.py's accounting helper still returns None
            # on a missing funnel, so an honest "no gate data" is preserved.
            _psummary = result.get("verification_summary")
            _psummary = {**_psummary} if isinstance(_psummary, dict) and _psummary else {}
            _psummary["park"] = _park
            _preason = str(_park.get("reason") or "This run was parked.")[:1000]
            log.warning(
                "run_parked",
                run_id=str(claimed["id"]),
                stage=_park.get("stage"),
                seq=_park.get("seq"),
                reason=_preason,
            )
            async with sessionmaker() as session:
                async with session.begin():
                    await set_tenant_context(session, claimed["tenant_id"])
                    # completed_at is DELIBERATELY NOT SET. A parked run is not
                    # complete, and stamping a completion time would make the
                    # intake card render a duration for a run that has not
                    # finished (15.2-19 reads exactly that).
                    await session.execute(
                        text(
                            "UPDATE run SET status=:park_status, error_message=:e, "
                            "verification_summary = CAST(:vsummary AS JSONB), "
                            "cost_usd_total = COALESCE("
                            "(SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id), 0) "
                            # Guard: a user cancel (status='cancelled') must win.
                            # Fence: and only the OWNER may park (D-23.1-06); see
                            # the needs_input park above for the full reasoning.
                            "WHERE id=:id AND status='running' AND worker_id = :wid"
                        ),
                        {
                            "park_status": _park_status,
                            "e": _preason,
                            "vsummary": _pjson.dumps(_psummary, ensure_ascii=False),
                            "id": claimed["id"],
                            "wid": WORKER_ID,
                        },
                    )
            return

        # The runner returns the synthesized report text. Accept either key
        # ('output_text' from SDK/ADK, 'text' from the Tribunal synthesis step).
        output_text = ""
        if isinstance(result, dict):
            output_text = result.get("output_text") or result.get("text") or ""

        # The 15.1 verification funnel (plan 15.1-08). Read with the same defensive
        # shape as output_text / rejected_claims above: an engine that does not
        # fact-check (ADK) and any pipeline that returned no funnel simply omits it.
        import json as _json
        _summary = result.get("verification_summary") if isinstance(result, dict) else None
        _has_summary = isinstance(_summary, dict) and bool(_summary)
        if _has_summary and _summary.get("should_have_been_checked"):
            # The operator's SERVER-SIDE trace that a completed run was degraded --
            # independent of the UI, so a feed nobody was watching cannot lose it.
            log.warning(
                "run_verification_degraded",
                run_id=str(claimed["id"]),
                should_have_been_checked=_summary.get("should_have_been_checked"),
                selected_verify=_summary.get("selected_verify"),
                checked=_summary.get("checked"),
            )

        # --- D-12 REASON LIST + terminal status -----------------------------
        # The region between the BEGIN/END markers below is read as TEXT and pinned
        # by tests/test_status_gates.py (the D-12 "these two never degrade" test).
        # Keep that test's own name OUT of the region: it contains the very token
        # the test forbids, so mentioning it inside would fail the gate.
        # BEGIN reason-building region
        #
        # The TOP-LEVEL result key `degradation_reasons` is the contract, and its
        # producer is TribunalPipeline.run() in plan 15.2-07 (wave 4): plan 07
        # declares the run's ONE accumulator plus a `_note_degradation(reason)`
        # closure at the top of run() and publishes it here; plans 15.2-11 / 12 /
        # 14 / 16 are the stages that append reasons through that closure. Plan
        # 15.2-08 (wave 5) normalises the SAME list onto the funnel as
        # verification_summary["degradation_reasons"] -- that nested copy is the
        # READ-side surfacing and is NOT what this line reads.
        #
        # This plan is wave 2 and plan 07 is wave 4, so at the moment this lands
        # NOTHING writes the key yet and `_reasons` starts empty, leaving today's
        # behaviour unchanged. THAT IS INTENTIONAL AND CORRECT, not a bug -- do
        # not "fix" a read that has no writer yet. Until 07 lands, the only reason
        # this branch can add is the bucket-3 sentence below, computed here from
        # the verification funnel.
        _raw_reasons = result.get("degradation_reasons") if isinstance(result, dict) else None
        _reasons: list[str] = [
            str(r) for r in (_raw_reasons or []) if isinstance(r, str) and r.strip()
        ]
        if _has_summary and _summary.get("should_have_been_checked"):
            # A worded reason a human reads, following the register at
            # verification/report.py:184-190 -- never a code.
            _reasons.append(
                f"VERIFICATION DEGRADED -- "
                f"{int(_summary.get('should_have_been_checked') or 0)} claims were "
                "selected for fact-checking but were not checked; they ship "
                "unexamined."
            )
        # END reason-building region. Nothing about a RECOVERED retry and nothing
        # about a pending Gemini grounding fee may ever enter this list (D-12):
        # both are designed paths, not shortfalls, and demoting them would drain
        # completed_degraded of its meaning.

        # THE PINS ARE GONE (plan 15.2-16). 15.2-09 pinned synthesis_ran=True /
        # hard_wall=False here because nothing produced those facts yet and a
        # missing fact must never turn a run WITH a deliverable into a park.
        # 15.2-16 supplies them: the pipeline publishes `terminal_inputs` and the
        # park path is a SEPARATE branch above, so this branch now reads the
        # facts when they are present and falls back to exactly the old literals
        # when they are not (an ADK run, or any engine that does not report them).
        _ti_success = result.get("terminal_inputs") if isinstance(result, dict) else None
        _ti_success = _ti_success if isinstance(_ti_success, dict) else {}
        _final_status = terminal_state(
            streams_lost=int(
                _ti_success.get(
                    "streams_lost",
                    (result.get("streams_lost") or 0) if isinstance(result, dict) else 0,
                ) or 0
            ),
            streams_total=int(
                _ti_success.get(
                    "streams_total",
                    (result.get("streams_total") or 1) if isinstance(result, dict) else 1,
                ) or 1
            ),
            verify_ran=bool(
                _ti_success.get(
                    "verify_ran",
                    result.get("verify_ran", True) if isinstance(result, dict) else True,
                )
            ),
            synthesis_ran=bool(_ti_success.get("synthesis_ran", True)),
            hard_wall=bool(_ti_success.get("hard_wall", False)),
            degradation_reasons=_reasons,
        )

        if _reasons:
            # Persist the reasons as a SIBLING key on the funnel, WRITE SIDE ONLY:
            # build_verification_summary() and RECORDED_FUNNEL_COUNTS are NOT
            # touched (Pitfall 3 -- loader.py compares the funnel by full dict
            # equality). Copy, never mutate the pipeline's dict in place. When
            # there is no funnel at all the row carries degradation_reasons alone:
            # report.py's _accounting() returns None on missing funnel keys, so the
            # report still honestly says "no gate data" while naming the degradation.
            _summary = {**_summary} if _has_summary else {}
            _summary["degradation_reasons"] = _reasons
            _has_summary = True

        # SUCCESS: update status to the computed terminal state
        async with sessionmaker() as session:
            async with session.begin():
                # SET LOCAL app.tenant_id BEFORE any tenant-scoped query (T-06-02)
                await set_tenant_context(session, claimed["tenant_id"])
                # Close the status AND roll the per-call audited cost up into
                # run.cost_usd_total so the A/B Compare screen + Report show a real
                # cost (was always NULL otherwise -- review finding). RLS-scoped:
                # set_tenant_context above limits the SUM to this tenant's rows.
                #
                # The verification funnel is set in the SAME STATEMENT as the status
                # (G-10, T-15.1-36): a run must never be able to say 'completed'
                # while its degradation marker is missing, and two statements -- or
                # two transactions -- is exactly how that split happens. When there
                # is no funnel the column is left NULL rather than zeroed: report.py
                # renders NULL as "this run has no gate data", while a zeroed funnel
                # would certify a clean bucket 3 that nobody ever measured
                # (T-15.1-38). 15.2's R6 promoted the marker into a real terminal
                # state: the status below is terminal_state()-computed, and its
                # reason list rides in this SAME statement (T-15.2-23 -- a run must
                # never be able to say 'completed' while its marker is missing).
                _set_summary = (
                    "verification_summary = CAST(:vsummary AS JSONB), " if _has_summary else ""
                )
                _params = {
                    "id": claimed["id"],
                    "final_status": _final_status,
                    "wid": WORKER_ID,
                }
                if _has_summary:
                    _params["vsummary"] = _json.dumps(_summary, ensure_ascii=False)
                completed = await session.execute(
                    text(
                        "UPDATE run SET status=:final_status, completed_at=NOW(), "
                        + _set_summary +
                        "cost_usd_total = COALESCE("
                        "(SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id), 0) "
                        # Guard: only a still-running run completes. A user cancel
                        # (status='cancelled') makes this a no-op, so the cancelled
                        # state — and the cancel verdict — sticks.
                        #
                        # OWNERSHIP FENCE (D-23.1-06). The second predicate is
                        # ADDITIVE: without the status clause a cancel stops
                        # winning, without the ownership clause a worker displaced
                        # by a stale reclaim can stamp a terminal status over a run
                        # the NEW owner is still executing. `:wid` is the module
                        # WORKER_ID -- this process -- and never claimed['worker_id'],
                        # which after a reclaim is a stale in-memory copy that would
                        # make the predicate trivially true for the displaced worker.
                        #
                        # Narrowing this UPDATE deliberately narrows the two Output
                        # INSERTs below, because they are gated on
                        # `completed.rowcount`: a displaced worker must write neither
                        # a report body nor a rejected-claims ledger onto a run it
                        # lost. Two Output rows for one run would leave the audit
                        # chain with two report bodies and no way to say which one a
                        # human actually read.
                        #
                        # The predicate is appended AFTER the status clause on
                        # purpose. test_status_gates.py and test_gate_replay.py both
                        # assert the whole WHERE prefix up to and including the
                        # status clause as an exact substring, so reordering the two
                        # predicates would break those cancel-guard regression tests
                        # without touching the guard they exist to protect. (The
                        # literal is deliberately not repeated here: it is also
                        # COUNTED by test_checkpoint_resume.py, and a comment that
                        # inflates a counted grep is the vacuous gate this
                        # repository keeps getting bitten by.)
                        "WHERE id=:id AND status='running' AND worker_id = :wid"
                    ),
                    _params,
                )
                # Persist the synthesized report body so GET /api/runs/{id}/report
                # can serve it (the Output table was never written before -- the
                # report viewer had no real-mode data source). Skip if the run was
                # cancelled (completed update changed no row) — no report for a
                # cancelled run.
                if output_text and completed.rowcount:
                    await session.execute(
                        text(
                            "INSERT INTO output (id, tenant_id, run_id, format, body, created_at) "
                            "VALUES (:oid, :tid, :rid, 'markdown', :body, NOW())"
                        ),
                        {
                            "oid": str(uuid.uuid4()),
                            "tid": str(claimed["tenant_id"]),
                            "rid": str(claimed["id"]),
                            "body": output_text,
                        },
                    )
                # Persist the rejected-claims ledger (Tribunal verification drops) so
                # the Deep Content Compare cross-check can show what this engine threw
                # out. Best-effort; engines that don't verify (ADK) emit nothing.
                # (_json is imported above, alongside the verification funnel read.)
                _rejected = result.get("rejected_claims") if isinstance(result, dict) else None
                if _rejected and completed.rowcount:
                    await session.execute(
                        text(
                            "INSERT INTO output (id, tenant_id, run_id, format, body, created_at) "
                            "VALUES (:oid, :tid, :rid, 'rejected_claims', :body, NOW())"
                        ),
                        {
                            "oid": str(uuid.uuid4()),
                            "tid": str(claimed["tenant_id"]),
                            "rid": str(claimed["id"]),
                            "body": _json.dumps(_rejected, ensure_ascii=False),
                        },
                    )
    except RunCancelled:
        # User cancelled mid-run; the cancel endpoint already set 'cancelled'.
        # Stop the wasted work; do NOT mark it failed.
        log.info("run_cancelled", run_id=str(claimed["id"]))
        return
    except Exception as exc:
        log.exception("run_failed", run_id=str(claimed["id"]))
        # FAILURE: update status to failed -- but only if the run is still running
        # AND this process still owns it. If the user cancelled (and the failure is
        # the cancel tearing down an in-flight provider call), the 'cancelled'
        # verdict must win; if a stale reclaim moved the run to another worker, the
        # displaced process must not write its own crash onto the new owner's run
        # (D-23.1-06). An unfenced failure write is if anything worse than an
        # unfenced success one: it moves the row off 'running' and so disarms the
        # real owner's own status guard on the way past.
        async with sessionmaker() as session:
            async with session.begin():
                # SET LOCAL app.tenant_id BEFORE any tenant-scoped query (T-06-02)
                await set_tenant_context(session, claimed["tenant_id"])
                await session.execute(
                    text(
                        "UPDATE run SET status='failed', completed_at=NOW(), error_message=:e "
                        "WHERE id=:id AND status='running' AND worker_id = :wid"
                    ),
                    {"e": str(exc)[:1000], "id": claimed["id"], "wid": WORKER_ID},
                )
    finally:
        # Stop asserting liveness on EVERY exit path -- success, RunCancelled and
        # the exception path alike (T-15.2-202: a heartbeat task that outlived its
        # run would keep a dead run looking alive forever, which is the D-E defect
        # with the sign flipped). `return` inside an except still runs this block.
        if _hb is not None:
            _hb.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _hb


async def worker_loop() -> None:
    """
    Main poll loop. Claims one run at a time via SKIP LOCKED, dispatches it
    through the per-run advisory lock (execute_run_locked), then polls again.
    Sleeps between polls when the queue is empty.

    D-09 single-worker simplification: one Cloud Run instance with min-instances=1
    and always-on CPU. The advisory lock (ENGINE-08) makes >1 poller/instance
    safe, so this loop can now run at max-instances > 1 without forking the audit
    chain (D-08: size for 5+ concurrent).
    """
    # Imported here (not at module top) to keep the import graph acyclic:
    # runs.execute lazily imports execute_run from THIS module.
    from nestor_pulse_sdk.runs.execute import execute_run_locked
    sessionmaker = get_sessionmaker()
    log.info("worker_started", worker_id=WORKER_ID, poll_s=POLL_INTERVAL_SECONDS)
    while True:
        # CLAIM step: runs WITHOUT tenant context (worker sees all tenants' work)
        async with sessionmaker() as session:
            async with session.begin():
                claimed = await claim_one(session)
        if claimed is None:
            # REAP (D-E) on the EMPTY-QUEUE tick only: one statement per idle
            # poll, never competing with real work. Runs that have gone silent
            # again after using up their recoveries are failed with a sentence
            # instead of being started a further time.
            try:
                async with sessionmaker() as session:
                    async with session.begin():
                        reaped = await session.execute(
                            REAP_SQL,
                            {
                                "msg": _reap_message(),
                                "stale": STALE_RUN_MINUTES,
                                "max_reclaims": MAX_RECLAIMS,
                            },
                        )
                        reaped_ids = [str(r[0]) for r in reaped.fetchall()]
                if reaped_ids:
                    # Fail LOUD and in words, naming the runs (phase rule 7).
                    log.warning(
                        "stale_runs_reaped_to_failed",
                        n=len(reaped_ids),
                        run_ids=reaped_ids,
                        max_reclaims=MAX_RECLAIMS,
                        stale_minutes=STALE_RUN_MINUTES,
                        cause=(
                            "worker stopped heartbeating and the run had already "
                            "used its bounded crash recoveries"
                        ),
                    )
            except Exception:  # noqa: BLE001
                # Same defensive posture as the dispatch guard below: the reap is
                # housekeeping and must never stall the queue.
                log.warning("stale_reap_failed", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        if claimed.get("reclaim_count"):
            # A crash recovery actually happened. Say so by name, with the count,
            # so a run that keeps dying is visible BEFORE it hits the ceiling.
            log.warning(
                "run_reclaimed_from_dead_worker",
                run_id=str(claimed["id"]),
                reclaim_count=claimed["reclaim_count"],
                max_reclaims=MAX_RECLAIMS,
            )
        log.info("run_claimed", run_id=str(claimed["id"]), engine=claimed["engine"])
        # EXECUTE step: the per-run 64-bit advisory lock WRAPS the dispatch so
        # >1 poller/instance is safe for the audit chain (ENGINE-08, T-13-06).
        # execute_run_locked re-checks claimability under the lock, then delegates
        # to execute_run() (runner.run() + set_tenant_context, T-06-02 preserved).
        # Defensive guard: a single run (or even a logging error inside its own
        # failure path) must NEVER kill the worker -- it would stall the queue and,
        # in an A/B fan-out, the sibling arm. Swallow + keep polling.
        try:
            await execute_run_locked(claimed)
        except Exception:  # noqa: BLE001
            try:
                log.exception("execute_run_crashed", run_id=str(claimed["id"]))
            except Exception:
                pass


async def _health_server(port: int) -> None:
    """Minimal HTTP server for Cloud Run startup/liveness probes.

    Cloud Run requires every revision to bind on PORT and respond to HTTP
    within the startup timeout -- even background workers with no real HTTP
    traffic. This server fulfills that contract using only stdlib asyncio:
      GET /healthz -> 200 {"status":"ok"}
      GET /         -> 200 {"status":"ok"}
    It runs concurrently with the main worker_loop() via asyncio.gather.
    """
    _RESPONSE = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 15\r\n"
        b"Connection: close\r\n"
        b"\r\n"
        b'{"status":"ok"}'
    )

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read(1024)  # consume request (we don't inspect it)
            writer.write(_RESPONSE)
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    log.info("worker_health_server_started", port=port)
    async with server:
        await server.serve_forever()


def main() -> None:
    """Entrypoint: `python -m nestor_pulse_sdk.runs.worker`."""
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent.parent / "nestor_pulse" / ".env")

    # LOCAL_DEV_AUTH: skip Secret Manager -- it overrides DATABASE_URL with the
    # Cloud SQL unix-socket URL ("Secret Manager values always win"), which is
    # unusable on Windows and is not the local clean-room DB. The provider API
    # keys the engines need come from nestor_pulse/.env (load_dotenv above).
    if os.environ.get("LOCAL_DEV_AUTH") != "1":
        # The worker MUST connect as worker_user: deploy-worker.sh mounts
        # DATABASE_URL from the DATABASE_URL_WORKER secret so the cross-tenant
        # SKIP LOCKED claim matches the permissive *_worker_all RLS policies
        # (migration 0008). But the bootstrap re-pulls the app_user `DATABASE_URL`
        # secret and "Secret Manager values always win" (nestor_pulse/secrets.py),
        # which would stomp the mounted worker_user URL back to app_user. The
        # engine is built lazily (get_engine is lru_cached, first called inside
        # the poll loop -- AFTER this bootstrap), so it would bind to app_user;
        # then the claim SELECT runs RLS-scoped with no app.tenant_id set and
        # matches ZERO queued runs -> the worker silently never claims. Preserve
        # the mounted worker URL across the bootstrap. (The API has no conflict:
        # it WANTS app_user, so this guard lives only in the worker.)
        _worker_db_url = os.environ.get("DATABASE_URL")
        try:
            from nestor_pulse_sdk.secrets_bootstrap import load_sdk_secrets_into_env
            load_sdk_secrets_into_env()
        except Exception:
            pass
        if _worker_db_url:
            os.environ["DATABASE_URL"] = _worker_db_url

    port = int(os.environ.get("PORT", "8080"))

    async def _run() -> None:
        await asyncio.gather(
            worker_loop(),
            _health_server(port),
        )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
