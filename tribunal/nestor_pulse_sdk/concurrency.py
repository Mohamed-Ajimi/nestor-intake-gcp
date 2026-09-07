"""Worker concurrency configuration -- the ONE reader of NESTOR_WORKER_RUN_CONCURRENCY.

Phase 23.3 plan 02.

This module lives at the PACKAGE ROOT and imports nothing from the package (only
`os` and `logging`) on purpose. Both `runs/` (which owns the poll loop) and
`audit/` (which owns the process-wide LLM semaphore) need the same number, and
making `audit` import `runs` to get it would be a layering inversion as well as
an import cycle. A leaf module with no package imports is the only shape that
lets both depend on it.

The distinction this module exists to draw:

  * `LLM_SLOTS_PER_RUN` -- the in-flight LLM budget ONE run is entitled to.
  * `LLM_SLOTS_PER_RUN * run_concurrency()` -- the budget the PROCESS may use.

Until this module existed those two were the same literal `8`, which was correct
only because the worker ran exactly one run at a time.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_ENV_RUN_CONCURRENCY = "NESTOR_WORKER_RUN_CONCURRENCY"

#: The in-flight LLM budget ONE run is entitled to.
#:
#: 8 is NOT a new number. It is the value `audit/audited_llm_client.py`'s
#: `_SEMAPHORE` has carried since PATTERNS lines 302-304, and it is the value
#: `pipeline/tribunal/pipeline.py`'s `_SKEPTIC_CONCURRENCY` (default 8) is sized
#: to saturate -- the skeptic stage being ~79% of a run's cost. Naming it here
#: makes "one run's budget" and "the process's budget" two different things,
#: which is the entire point of plan 23.3-02.
#:
#: >>> CHANGING THIS CHANGES ENGINE BEHAVIOUR AND IS OUT OF SCOPE FOR PHASE 23.3. <<<
#: Phase 23.3 changes SCHEDULING only; no plan in it may alter what a run
#: produces (23.3-CONTEXT.md section 9). Raising or lowering this alters how many
#: provider calls a single run has in flight, which is an engine parameter.
LLM_SLOTS_PER_RUN = 8


def run_concurrency() -> int:
    """How many research runs one worker process may execute at the same time.

    Reads ``NESTOR_WORKER_RUN_CONCURRENCY``; defaults to ``1``, i.e. today's
    strictly serial worker. Plan 03 and ``deploy-worker.sh`` are what raise it,
    so at merge time this whole plan is a no-op.

    NEVER RAISES. Garbage (``""``, ``"four"``, ``"0"``, ``"-3"``, ``None``)
    degrades to 1 and logs at ``warning``. This function is called at module
    import of the LLM client, and an import-time exception there takes the whole
    worker container down -- a config typo must not be able to do that.

    It is a FUNCTION rather than a constant read at import so a test can set the
    variable and re-derive the value without an ``importlib.reload`` dance.
    But note: ``_SEMAPHORE`` calls it ONCE, at import. Changing the environment
    variable at runtime therefore does NOT resize an already-built semaphore.
    That is intended -- this is deployment configuration, not a runtime dial.
    """
    raw = os.environ.get(_ENV_RUN_CONCURRENCY)
    if raw is None:
        return 1
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        log.warning(
            "%s=%r is not an integer; falling back to 1",
            _ENV_RUN_CONCURRENCY,
            raw,
        )
        return 1
    if value < 1:
        log.warning(
            "%s=%r is below the floor of 1; falling back to 1",
            _ENV_RUN_CONCURRENCY,
            raw,
        )
        return 1
    return value
