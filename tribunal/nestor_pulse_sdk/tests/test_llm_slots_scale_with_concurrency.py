"""Phase 23.3 plan 02 -- the process-wide LLM budget must scale with K.

WHAT THIS FILE PINS, and why each assertion is here rather than a grep:

`audit/audited_llm_client.py` owns ONE module-level `_SEMAPHORE` shared by every
coroutine in the worker process (five `async with _SEMAPHORE:` sites). Today the
worker runs one run at a time, so that single run gets the whole budget. The
skeptic stage -- ~79% of a run's cost -- is sized by `_SKEPTIC_CONCURRENCY = 8`
to saturate exactly that budget. If K runs share the process against a fixed
`Semaphore(8)`, each run gets 8/K slots, every run's wall clock stretches by
roughly K, and the run-level ceiling plan 01 adds starts killing LEGITIMATE runs.

So the property that matters is not "the semaphore is bigger". It is
"ONE RUN'S BUDGET IS INVARIANT IN K" -- test 3. Tests 1 and 2 are two points on
that curve, kept separate because they carry different meanings:

  * test 1 (K unset -> 8) is the COMPARABILITY GUARD. It is expected GREEN at
    HEAD and proves nothing about the fix; it proves merging the fix changes
    nothing until plan 03 raises K.
  * test 2 (K=4 -> 32) is the DEFECT GATE. At HEAD the semaphore is the literal
    `8` regardless of the environment, so it cannot pass at HEAD.

Assertions are on NUMBERS, never on source text, except test 5 where the thing
under test genuinely is a construction-site keyword. A `grep "8 *"` would match
the comment prose the implementation adds and read green on unchanged code.

No database, no network, no provider key: this file runs in the DSN-less harness.
The teardown reloads the client module one final time with the variable deleted,
so a 32-slot semaphore cannot leak into whatever test file runs next (this suite
has a documented cross-file pollution defect, DEF-23.2-14, and a module-level
semaphore is exactly the shape that causes one).
"""

from __future__ import annotations

import importlib
import inspect
import re

import pytest

_CLIENT_MOD = "nestor_pulse_sdk.audit.audited_llm_client"
_ENV = "NESTOR_WORKER_RUN_CONCURRENCY"


def _reload_client(monkeypatch, k: str | None):
    """Set (or delete) K, then rebuild the module so `_SEMAPHORE` is re-derived.

    `_SEMAPHORE` is built ONCE at import, so the env var must be in place
    before the reload. That is deliberate in the implementation: the value is
    deployment configuration, not a runtime dial.
    """
    if k is None:
        monkeypatch.delenv(_ENV, raising=False)
    else:
        monkeypatch.setenv(_ENV, k)
    mod = importlib.import_module(_CLIENT_MOD)
    return importlib.reload(mod)


@pytest.fixture(autouse=True)
def _restore_k1_semaphore():
    """Leave the process holding a K=1 semaphore no matter how a test exits."""
    yield
    import os

    os.environ.pop(_ENV, None)
    mod = importlib.import_module(_CLIENT_MOD)
    importlib.reload(mod)


def test_1_no_op_at_k1_comparability_guard(monkeypatch):
    """COMPARABILITY GUARD -- expected GREEN at HEAD. Not a defect gate.

    With no `NESTOR_WORKER_RUN_CONCURRENCY` in the environment the worker must
    behave EXACTLY as it does today: 8 in-flight LLM calls process-wide.
    """
    mod = _reload_client(monkeypatch, None)
    assert mod._SEMAPHORE._value == 8


def test_2_scales_with_k_defect_gate(monkeypatch):
    """DEFECT GATE -- cannot pass at HEAD, where the semaphore is a literal 8."""
    mod = _reload_client(monkeypatch, "4")
    assert mod._SEMAPHORE._value == 32


@pytest.mark.parametrize("k", [1, 2, 4, 8])
def test_3_per_run_budget_is_invariant_in_k(monkeypatch, k):
    """THE PROPERTY THE PHASE DEPENDS ON: each concurrent run still gets 8 slots."""
    mod = _reload_client(monkeypatch, str(k))
    from nestor_pulse_sdk.concurrency import LLM_SLOTS_PER_RUN, run_concurrency

    assert run_concurrency() == k
    assert mod._SEMAPHORE._value == LLM_SLOTS_PER_RUN * k
    assert mod._SEMAPHORE._value // run_concurrency() == 8


def test_4_engine_knobs_did_not_move():
    """A SCHEDULING plan must not move an ENGINE parameter.

    Anti-vacuity: the checked constants are counted and the count is asserted,
    so deleting a row from the table cannot make this test quietly weaker.
    """
    from nestor_pulse_sdk.pipeline.deep_researchers import degraded_parallel
    from nestor_pulse_sdk.pipeline.tribunal import gates, pipeline, research_division

    checked: dict[str, int] = {
        "pipeline._SKEPTIC_CONCURRENCY": pipeline._SKEPTIC_CONCURRENCY,
        "pipeline._SKEPTIC_TIMEOUT_S": pipeline._SKEPTIC_TIMEOUT_S,
        "gates._GATE_CONCURRENCY": gates._GATE_CONCURRENCY,
        "research_division._ANGLE_CONCURRENCY": research_division._ANGLE_CONCURRENCY,
        "degraded_parallel.PROVIDER_TIMEOUT_S": degraded_parallel.PROVIDER_TIMEOUT_S,
    }
    expected = {
        "pipeline._SKEPTIC_CONCURRENCY": 8,
        "pipeline._SKEPTIC_TIMEOUT_S": 300,
        "gates._GATE_CONCURRENCY": 4,
        "research_division._ANGLE_CONCURRENCY": 4,
        "degraded_parallel.PROVIDER_TIMEOUT_S": 2100,
    }
    assert len(checked) == 5, "expected to check exactly five engine constants"
    assert checked == expected


def test_5_anthropic_timeout_bound_is_ours():
    """The single permitted `AsyncAnthropic(...)` site must carry our own bound.

    An unpinned client inherits whichever default the SDK ships next. The value
    must sit ABOVE the longest single Anthropic call the pipeline permits itself
    (`_SKEPTIC_TIMEOUT_S = 300`), or our own bound would truncate a legal call.
    """
    mod = importlib.import_module(_CLIENT_MOD)
    src = inspect.getsource(mod.build_audited_client)

    m = re.search(r"AsyncAnthropic\(\s*timeout\s*=\s*([0-9]+(?:\.[0-9]+)?)", src)
    assert m is not None, "AsyncAnthropic is not constructed with an explicit timeout="
    assert float(m.group(1)) >= 300.0
