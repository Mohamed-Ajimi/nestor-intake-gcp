"""Tribunal budget governor — Plan 01-14 Task 3.

Reads real audit_log.cost_usd (via SQLAlchemy sessionmaker) to bound the
multi-agent verification cost tax against a configurable max_budget_usd ceiling.

Task-1 confirmed defaults (overridable via env):
  NESTOR_TRIBUNAL_MAX_BUDGET_USD       = 5.00
  NESTOR_TRIBUNAL_BUDGET_BEHAVIOUR     = flag-budget-capped  (NOT silent-degrade)
  NESTOR_TRIBUNAL_SURVIVAL_RULE        = majority-independent

Governor behaviour (Task-1 decision = flag-budget-capped):
  When over budget: surfaces "budget-capped" marker in the verification_report.
  This is NOT silent truncation — callers see the cap was hit.

Uncapped posture (Plan 01-17, D-15):
  NESTOR_TRIBUNAL_UNCAPPED=1 makes over_budget() always return False so the
  governor never blocks any run. current_cost still executes the SELECT
  sum(cost_usd) query so audit_log recording is unaffected (D-15: uncap,
  do NOT stop recording cost). This is a dev-round-only posture — reversible
  by unsetting the flag. NO aggregate/daily ceiling and NO global kill-switch
  are added (explicitly declined in D-15).

Design note (T-14-02 / T-16-01 — hash-chain concurrency):
  The budget governor reads audit_log.cost_usd via a SELECT sum(...) query.
  Seq+hash assignment in AuditedLLMClient is serialized per-run via
  AuditedLLMClient._run_lock (completion-order assignment), so concurrent
  providers and skeptics within the same Tribunal run no longer collide on
  uq_audit_tenant_run_seq. _SEMAPHORE(8) bounds total in-flight LLM calls
  but does NOT serialize seq assignment (it was wrong to assume otherwise).
  Multi-worker seq safety is deferred to Phase 2 (DB-level advisory lock).
"""

from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from nestor_pulse_sdk.db.rls import set_tenant_context

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task-1 confirmed defaults (ADR-006 open questions resolved)
# ---------------------------------------------------------------------------

#: Default max cost in USD before the governor halts/degrades verification.
#: Raised 5.00 -> 25.00 (decision 2026-06-11): the $5 default was calibrated for
#: the old truncated distiller (~30 claims). With full-coverage chunked
#: distillation (every report fully extracted -> typically 150-400+ claims on a
#: multi-question brief, x2-3 skeptics each), $5 would cap verification after
#: the first batches and wave the rest through — silently undoing the coverage
#: fix. The governor still hard-stops at the ceiling and flags the run.
DEFAULT_MAX_BUDGET_USD: float = float(
    os.environ.get("NESTOR_TRIBUNAL_MAX_BUDGET_USD", "25.00")
)

#: Survival rule — majority + independent-source-required-to-refute.
#: Encoded here as a module constant for Plan 01-15 adjudication.
SURVIVAL_RULE: str = os.environ.get(
    "NESTOR_TRIBUNAL_SURVIVAL_RULE", "majority-independent"
)

#: Governor behaviour: "flag-budget-capped" or "silent-degrade".
BUDGET_BEHAVIOUR: str = os.environ.get(
    "NESTOR_TRIBUNAL_BUDGET_BEHAVIOUR", "flag-budget-capped"
)

#: D-15 uncapped flag (Plan 01-17).
#: When NESTOR_TRIBUNAL_UNCAPPED=1, over_budget() always returns False so
#: the governor never blocks. current_cost still SELECTs sum(cost_usd) for
#: audit recording. Reversible by unsetting. NO kill-switch / daily ceiling.
TRIBUNAL_UNCAPPED: bool = os.environ.get("NESTOR_TRIBUNAL_UNCAPPED", "") == "1"

#: The marker string written into verification_report when the governor trips.
_BUDGET_CAPPED_MARKER = "budget-capped"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def current_cost(run_id: uuid.UUID, tenant_id: uuid.UUID, sessionmaker: Any) -> Decimal:
    """Return the current total LLM cost (USD) for a run from audit_log.

    audit_log is FORCE-RLS; the tenant context must be set before any read.
    set_tenant_context() issues SELECT set_config('app.tenant_id', :tid, true)
    which is transaction-local (Pitfall 1 in rls.py).

    Args:
        run_id:       UUID of the current run.
        tenant_id:    UUID of the current tenant (required for RLS).
        sessionmaker: SQLAlchemy async sessionmaker (or synchronous
                      callable returning a context-manager session).

    Returns:
        Decimal sum of cost_usd for the run. Returns Decimal("0") if
        audit_log has no rows yet (SUM returns NULL).
    """
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                text("SELECT sum(cost_usd) FROM audit_log WHERE run_id = :r"),
                {"r": str(run_id)},
            )
            total = result.scalar_one_or_none()
            if total is None:
                return Decimal("0")
            return Decimal(str(total))


async def over_budget(
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    max_budget_usd: float,
    sessionmaker: Any,
) -> bool:
    """Return True when the run's accumulated cost >= max_budget_usd.

    When NESTOR_TRIBUNAL_UNCAPPED=1 (D-15), always returns False (the
    governor ceiling is effectively unbounded). current_cost is still
    called so audit_log.cost_usd continues to be observed — the uncapped
    posture removes the ceiling, not the recording.

    Args:
        run_id:          UUID of the current run.
        tenant_id:       UUID of the current tenant (required for RLS).
        max_budget_usd:  Cost ceiling in USD.
        sessionmaker:    SQLAlchemy async sessionmaker.

    Returns:
        True if sum(cost_usd) >= max_budget_usd AND not uncapped;
        False otherwise (including when NESTOR_TRIBUNAL_UNCAPPED=1).
    """
    # Always read current cost — audit recording must not be skipped (D-15).
    total = await current_cost(run_id, tenant_id, sessionmaker)

    # D-15 uncapped posture: ceiling is effectively unbounded.
    # Module-level TRIBUNAL_UNCAPPED reflects the env at import time; tests
    # that reload the module after setting the env see the updated value.
    if TRIBUNAL_UNCAPPED:
        log.debug(
            "budget governor: UNCAPPED (D-15) — run %s cost so far: %s USD",
            run_id,
            total,
        )
        return False

    ceiling = Decimal(str(max_budget_usd))
    is_over = total >= ceiling
    if is_over:
        log.warning(
            "budget governor: run %s exceeded %.2f USD (current: %s)",
            run_id,
            max_budget_usd,
            total,
        )
    return is_over


def budget_marker(over: bool, behaviour: str) -> str:
    """Return the budget-capped marker string when applicable.

    Args:
        over:       True when the run is over budget.
        behaviour:  "flag-budget-capped" or "silent-degrade".

    Returns:
        "budget-capped" if over and behaviour is flag-budget-capped.
        Empty string in all other cases.
    """
    if over and behaviour == "flag-budget-capped":
        return _BUDGET_CAPPED_MARKER
    return ""
