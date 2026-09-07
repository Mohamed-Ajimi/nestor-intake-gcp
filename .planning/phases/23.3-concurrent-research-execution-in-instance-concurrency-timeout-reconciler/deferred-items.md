# Phase 23.3 — deferred items

Out-of-scope discoveries logged during execution. NOT fixed in the plan that found them.

## DEF-23.3-02-a — stale `_SEMAPHORE(8)` docstring in `pipeline/tribunal/budget.py:28`

- **Found during:** 23.3-02, Task 2.
- **What:** `budget.py:28` still reads *"`_SEMAPHORE(8)` bounds total in-flight LLM calls"*.
  As of 23.3-02 the semaphore is `LLM_SLOTS_PER_RUN * run_concurrency()`, so that line is stale.
  A docstring asserting the opposite of the code is this repository's most-repeated defect shape,
  so it is recorded rather than left silent.
- **Why not fixed here:** it lives under `tribunal/nestor_pulse_sdk/pipeline/`, and 23.3-02's
  verification requires `git diff -- tribunal/nestor_pulse_sdk/pipeline/` to be exactly 0 lines
  (the phase's "no engine behaviour change / output comparability" fence, 23.3-CONTEXT.md § 9).
  A one-line comment edit would have broken that gate for no functional gain.
- **Action:** a later plan already touching `pipeline/` should correct the one line.
  Documentation only — no behavioural effect.

## DEF-23.3-02-b — DSN-less tribunal suite has 182 pre-existing failures + 39 errors

- **Found during:** 23.3-02, regression baselining.
- **What:** `python -m pytest nestor_pulse_sdk/tests -q --continue-on-collection-errors` with no
  `DATABASE_URL` gives `182 failed, 2230 passed, 67 skipped, 11 xfailed, 39 errors` at base commit
  `999c985`. Separately, `structlog` is not installed in this dev environment, which breaks
  collection of `test_clarification_cap_per_engine.py` (`ModuleNotFoundError: No module named
  'structlog'`) via `nestor_pulse_sdk/runs/adapter.py:37`.
- **Why not fixed here:** entirely pre-existing and unrelated to the current task's changes
  (scope-boundary rule). Confirmed by running the suite with the base client restored and with the
  new client: identical `182 failed / 39 errors` both ways.
- **Action:** whoever sets up the tribunal CI harness should either install `structlog` in the dev
  extra or provide a DSN, so the DSN-less signal is usable as a gate. Today it is not.
