# Phase 23.3 — deferred items

Out-of-scope discoveries logged during execution. NOT fixed by the plan that found them.

⚠ **Numbering note (orchestrator, wave-1 merge).** Plans 23.3-01 and 23.3-02 each created this
file independently and both claimed low ids, so the merge was an add/add conflict with a real
COLLISION. 23.3-01's two items keep `-01` and `-02`. 23.3-02's were written as `-02-a` / `-02-b`,
which falsely read as sub-items of 23.3-01's `caplog` deferral; they are renumbered **`-03` and
`-04`**. No item was dropped and no text was altered beyond the heading ids. Note also that the
PLANNER's report used `DEF-23.3-00`, `-01` and `-05` for a different set (the spend exposure, the
untraced `AsyncOpenAI()` client, and `serpapi._BREAKER`); those are NOT yet in this file and must
be added by a later plan WITHOUT reusing `-01`..`-04`.

---

## DEF-23.3-01 — `test_advisory_lock_exactly_once.py` errors under the `app_user` DSN

**Found during:** 23.3-01, plan verification step 2.
**Pre-existing:** YES. Reproduced at HEAD (`999c985`) with `worker.py` unmodified — identical
counts before and after the plan's change, so this plan neither caused nor worsened it.

**Symptom** — 4 of the file's tests ERROR, not skip:

```
asyncpg.exceptions.InsufficientPrivilegeError:
  new row violates row-level security policy for table "project"
```

on `test_worker_claimed_run_dispatches`, `test_same_run_executes_exactly_once`,
`test_stolen_claim_does_not_double_dispatch`, `test_distinct_runs_do_not_serialize`.

**Cause:** the file seeds its `project` row WITHOUT a tenant context. Under `app_user` (RLS
enforced, non-superuser) the INSERT is refused. It passes as `postgres` only because RLS is
bypassed there.

**Why it matters:** this is the same failure CLASS that `test_run_ownership_fence.py` and
`test_stale_reclaim.py` handle by SKIPPING themselves with an explicit "this would be a
vacuous green" message (23.2-CONTEXT). This file instead ERRORS, which reads as a broken
environment rather than as the suite defending itself. The fix is a `set_tenant_context` in
the seed helper (or the same self-skip), not a DSN change.

**Not fixed here** because it is untouched by this plan's files and 23.3-01's scope is the
timeout backstop. Fixing a seed helper in an advisory-lock test file under a timeout plan is
exactly the scope creep the phase fences forbid.

---

## DEF-23.3-02 — `test_checkpoint_resume.py` cross-file pollution, still present

**Found during:** 23.3-01, plan verification step 2. **Pre-existing:** YES, identical at HEAD.

`test_a_payload_from_another_checkpoint_version_is_discarded` and
`test_an_oversized_payload_is_refused_and_nothing_is_written` fail when run in the same
process as `test_advisory_lock_exactly_once.py`. This is DEF-23.2-14, already registered;
recorded here only so the "6 failed, 39 passed" baseline in `23.3-01-SUMMARY.md` is
attributable line by line and nobody reads it as a regression from this plan.

## DEF-23.3-03 — stale `_SEMAPHORE(8)` docstring in `pipeline/tribunal/budget.py:28`

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

## DEF-23.3-04 — DSN-less tribunal suite has 182 pre-existing failures + 39 errors

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

---

## DEF-23.3-05 — the reconciler's NON-terminal mirror is not compare-and-swapped

- **Found during:** 23.3-05, Task 2 (design), while wiring the terminal CAS.
- **What:** `reconcile_one` finalizes a terminal run behind a `patch_if` compare-and-swap on the
  claim-time status, but the NON-terminal branch reuses `run_task.mirror_tick` verbatim (as
  23.3-CONTEXT § 8 requires — *reuse, do not duplicate*), and `mirror_tick` has no conditional
  form. So in the window `[claim -> mirror write]` a live driver that finalized could have its
  terminal status overwritten by a progress mirror.
- **Why it is not fixed here:** the window is closed by `ORPHAN_CUTOFF_MINUTES = 15`, not by luck.
  For a live driver to land a terminal write inside it, that driver must have been silent for
  longer than 15 minutes and then wake up and write; the only silent path this codebase has is the
  401/403 retry budget, hard-capped at 600 s (10 min). Adding a conditional mirror would mean
  either duplicating `mirror_tick` or editing `run_task.py`, which this plan's verification step 5
  forbids (`git diff -- run_task.py` must be 0 lines).
- **Blast radius if it ever did happen:** self-healing and free. The row goes back to non-terminal,
  the next sweep reads the same terminal metrics and finalizes it properly. The one residual cost
  is a second completion mail on that next pass.
- **Action:** whoever next touches `run_task.mirror_tick` should give it an optional
  `expected_status` and have the reconciler pass the claim-time value.

## DEF-23.3-06 — the sweep replays a SUPERADMIN identity, not a space-scoped one

- **Found during:** 23.3-05, Task 2 (threat register T-23.3-23, disposition *accept, documented*).
- **What:** `reconcile._replay_identity` builds `Identity(role="superadmin", space_id=None)` from
  the row's stored `acting_user_id` / `acting_email`. That REPLAYS the identity the run's own
  driver already used (`run_task._patch_run`'s docstring records that the research write path runs
  as superadmin because the triggering actor has no own space) and the values are never request
  input — but it is wider than strictly necessary.
- **The tighter alternative:** a space-scoped `user` identity relying on the 0011
  `research_runs_space_isolation` policy to wall the write. Not taken because the `app_user` WRITE
  path on `research_runs` has never been exercised anywhere in this repository, and a background
  sweep over paid, in-flight runs is the wrong place to find out whether that policy's `WITH CHECK`
  admits it.
- **Action:** exercise the `app_user` write path on `research_runs` under test first; only then
  narrow the sweep's identity.

## DEF-23.3-07 — a claimed run with a NULL `tribunal_run_id` is skipped, never finalized

- **Found during:** 23.3-05, Task 2.
- **What:** a `queued` row whose `tribunal_run_id` is still NULL never reached the engine — the
  trigger created the row but `create_run` never returned (or the instance died between the two).
  `reconcile_one` returns `skipped_no_engine_run` with a WARNING and leaves the row alone.
- **Why not decided here:** finalizing it means asserting something about a run that may or may not
  have started spending. `failed` is probably right and would free the intake's in-flight slot, but
  "probably" is not a basis for writing a terminal state on a ~$45 path, and the plan scoped this
  out explicitly.
- **⚠ Consequence while it stands:** such a row holds that intake's single in-flight slot
  (`uq_research_runs_one_inflight_per_intake`) indefinitely, so no new research can be triggered
  for that intake until a human clears the row.
- **Action:** plan 06 (or a follow-up) should decide the terminal, ideally after asking the engine
  whether an idempotency-keyed run exists for it.
