"""
Per-run advisory lock -- the exactly-once keystone (ENGINE-08, plan 13-02).

This module extracts ONLY the keystone from Tribunal's unexecuted plan 01-19: a
transaction-scoped 64-bit Postgres advisory lock keyed on `run_id`, plus an
explicit claimable-set re-check. It WRAPS the existing SKIP-LOCKED claim in
`runs/worker.py` (it does NOT replace it) and delegates the actual engine
dispatch to `worker.execute_run` UNCHANGED, so the copied engine behavior and
the frozen audit hash-chain are preserved byte-for-byte.

Why the lock exists (13-RESEARCH.md Pitfall 3 / threat T-13-06):
  The audit hash-chain is per-run and legally load-bearing (EU AI Act Art. 12).
  It is safe only under a SINGLE writer per run. Two executors that both dispatch
  the engine for the same run_id fork the chain and double-spend the provider
  budget. Before Phase 13 the deploy was capped at max-instances=1 precisely
  because this lock was missing (01-19 objective). With the lock in place, >1
  poller / instance is safe (D-08: size for 5+ concurrent).

64-bit key (13-RESEARCH.md / threat T-13-07):
  A 32-bit int4 digest would collide ~50% at ~65k runs, which would spuriously
  serialize two DISTINCT runs and defeat parallelism. Use the 64-bit form
  `('x' || md5(:run_id))::bit(64)::bigint` (verbatim from 01-19). Do NOT use the
  int4 string-hash builtin.

Claimable set (explicit -- "not terminal" is the WRONG test):
  claimable = status='queued' OR (status='running' AND started_at is stale).
  EXPLICITLY NOT claimable: needs_input, needs_report_spec (paused for the user),
  cancelled, completed, failed. If the run is not claimable after acquiring the
  lock, another executor already handled it -> return without a second dispatch
  (exactly-once).

SCOPE GUARD (13-RESEARCH.md Anti-Patterns): this file carries ONLY the lock
keystone. It deliberately does NOT add the message-bus trigger, the event-driven
Cloud Run Job launcher, the stale-run re-publisher, or concurrency caps (01-19
Tasks 2-6 -- out of scope per REQUIREMENTS.md). Only the existing SKIP-LOCKED
poll worker calls this path.

T-06-02 ordering is preserved: `worker.execute_run` still calls
set_tenant_context AFTER the claim, before any tenant-scoped write. The advisory
lock here is acquired on a SEPARATE short transaction BEFORE dispatch; it does
not itself touch tenant-scoped rows beyond the (RLS-exempt in the worker_user
role) `run` status re-check that the SKIP-LOCKED claim already performed.
"""

from __future__ import annotations

import os

import structlog
from sqlalchemy import text

from nestor_pulse_sdk.db.base import get_sessionmaker

log = structlog.get_logger(__name__)

# Stale-running threshold: a run left 'running' longer than this (worker died
# mid-execute) is reclaimable. Mirrors worker.py's CLAIM_SQL crash-recovery
# window (NESTOR_WORKER_STALE_MINUTES) so the two agree.
STALE_RUN_MINUTES = int(os.environ.get("NESTOR_WORKER_STALE_MINUTES", "60"))

# 64-bit per-run advisory lock (transaction-scoped, auto-releases on
# commit/rollback/crash). 64-bit md5 key, NOT the int4 string-hash builtin --
# see module docstring (T-13-07).
_ADVISORY_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(('x' || md5(:run_id))::bit(64)::bigint)"
)

# Post-lock claimable re-check: queued, OR running-but-stale. The paused
# (needs_input, needs_report_spec) and terminal (cancelled, completed, failed)
# states are NOT selected -> not claimable -> no second dispatch (H-3).
_CLAIMABLE_SQL = text(
    """
    SELECT status FROM run
     WHERE id = :run_id
       AND (
             status = 'queued'
          OR (status = 'running' AND started_at < NOW() - make_interval(mins => :stale))
       )
    """
)


async def execute_run_locked(claimed: dict) -> None:
    """Lock-wrapped execution entrypoint (ENGINE-08).

    Acquires the per-run 64-bit advisory lock, re-checks that the claimed run is
    still claimable, and only then delegates to `worker.execute_run(claimed)`
    (the unchanged dispatch + finalize path). If the run is not claimable after
    the lock is held, another executor already finished it -> return (no second
    engine dispatch, no forked audit chain).

    The lock is held for the SHORT re-check transaction only; it is released the
    instant that transaction commits. The subsequent `execute_run` opens its own
    transactions (with set_tenant_context) exactly as before. This is sufficient
    for exactly-once because the claimable re-check runs UNDER the lock: any
    concurrent executor for the same run_id either (a) has not yet claimed it
    (SKIP-LOCKED gave the row to only one of them), or (b) blocks on the advisory
    lock and, once it acquires it, observes the run no longer claimable (this
    executor moved it to 'running'/terminal) and returns.
    """
    run_id = claimed["id"]

    # Import lazily to avoid a circular import: worker.py imports this module.
    from nestor_pulse_sdk.runs.worker import execute_run

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            # Acquire the transaction-scoped 64-bit advisory lock for this run.
            await session.execute(_ADVISORY_LOCK_SQL, {"run_id": str(run_id)})
            # Re-check claimability WHILE holding the lock.
            result = await session.execute(
                _CLAIMABLE_SQL, {"run_id": str(run_id), "stale": STALE_RUN_MINUTES}
            )
            still_claimable = result.first() is not None

    if not still_claimable:
        # needs_input / needs_report_spec / cancelled / completed / failed, or a
        # fresh 'running' owned by another executor -> exactly-once: do not
        # re-dispatch the engine.
        log.info("run_not_claimable_after_lock", run_id=str(run_id))
        return

    # Still claimable -> delegate to the unchanged dispatch + finalize path.
    # execute_run sets status='running'/terminal and calls set_tenant_context
    # AFTER the claim, before any tenant-scoped write (T-06-02, preserved).
    await execute_run(claimed)
