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

Crash recovery (T-06-04, B2 fix):
  CLAIM_SQL includes `status = 'running' AND started_at < NOW() - make_interval(mins => :stale)`
  as a reclaimable condition. This handles workers that died mid-execute.
  IMPORTANT: must use make_interval(mins => :stale), NOT INTERVAL ':stale minutes'
  (the literal-bind variant fails at runtime with bound params -- B2 fix).
"""

from __future__ import annotations

import asyncio
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

# ---------------------------------------------------------------------------
# CLAIM SQL -- SELECT FOR UPDATE SKIP LOCKED
# ---------------------------------------------------------------------------
# Two reclaimable conditions:
#   1. status = 'queued'  (normal work queue)
#   2. status = 'running' AND started_at < NOW() - make_interval(mins => :stale)
#      (crash recovery: worker died without completing)
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
CLAIM_SQL = text("""
    UPDATE run
       SET status = 'running', started_at = NOW(), worker_id = :wid
     WHERE id = (
       SELECT id FROM run
        WHERE status = 'queued'
           OR (status = 'running' AND started_at < NOW() - make_interval(mins => :stale))
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
     )
   RETURNING id, tenant_id, project_id, engine, brief, worker_id, started_at
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
    """
    result = await session.execute(CLAIM_SQL, {"wid": WORKER_ID, "stale": STALE_RUN_MINUTES})
    row = result.first()
    if row is None:
        return None
    return dict(row._mapping)


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

    try:
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
                            "WHERE id=:id AND status='running'"
                        ),
                        {"q": _json.dumps(questions), "id": claimed["id"]},
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
                            "WHERE id=:id AND status='running'"
                        ),
                        {"id": claimed["id"]},
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

        # synthesis_ran / hard_wall are PINNED on this branch because this IS the
        # success branch -- a report is in hand. The park path (F6's
        # InsufficientProvidersError catch and the hard-wall park) is 15.2-16's
        # work; pinning them here keeps terminal_state() from returning 'parked'
        # down a path that already has a deliverable.
        _final_status = terminal_state(
            streams_lost=int(result.get("streams_lost") or 0) if isinstance(result, dict) else 0,
            streams_total=int(result.get("streams_total") or 1) if isinstance(result, dict) else 1,
            verify_ran=bool(result.get("verify_ran", True)) if isinstance(result, dict) else True,
            synthesis_ran=True,
            hard_wall=False,
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
                _params = {"id": claimed["id"], "final_status": _final_status}
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
                        "WHERE id=:id AND status='running'"
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
        # FAILURE: update status to failed -- but only if the run is still running.
        # If the user cancelled (and the failure is the cancel tearing down an
        # in-flight provider call), the 'cancelled' verdict must win.
        async with sessionmaker() as session:
            async with session.begin():
                # SET LOCAL app.tenant_id BEFORE any tenant-scoped query (T-06-02)
                await set_tenant_context(session, claimed["tenant_id"])
                await session.execute(
                    text(
                        "UPDATE run SET status='failed', completed_at=NOW(), error_message=:e "
                        "WHERE id=:id AND status='running'"
                    ),
                    {"e": str(exc)[:1000], "id": claimed["id"]},
                )


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
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
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
