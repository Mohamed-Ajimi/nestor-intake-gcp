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

⚠ **Numbering resolution (23.3-06, the phase's last plan — 2026-09-07).** The planner's set is
now merged in, and this is how, so nobody has to reconstruct it:

- **`DEF-23.3-00`** was reserved for the spend exposure by 23.3-06's own plan and was still
  free. It is written below and is the entry the operator checkpoint points at.
- The planner's `-01` (untraced `AsyncOpenAI()`), `-04` (no Cloud Scheduler trigger), `-05`
  (`serpapi._BREAKER`) and `-06` (K=4 from a single-run memory reading) were re-homed as
  **`-09` .. `-12`** — their planner numbers were already taken by unrelated wave-1 items.
- The planner's `-02` (the sweep's superadmin identity) and `-03` (a NULL `tribunal_run_id`
  row skipped, never finalized) are **NOT duplicated**: 23.3-05 already registered exactly
  those two findings as **`DEF-23.3-07`** and **`DEF-23.3-08`**. Cross-referenced below rather
  than re-entered, because two ids for one finding is how a register stops being usable.
- `-13` and `-14` are new findings from 23.3-06 itself.

⚠ **A note on 23.3-06's own verification step**, since it is a live example of the trap this
file keeps recording: that plan's `<verify>` greps this file for `DEF-23.3-00 .. -06`. Every
one of those ids DOES exist here — but `-01`..`-06` hold *entirely different* findings from
the ones the plan intended to check. **The grep is vacuous and passes regardless.** The real
assertion is `-00` and `-09`..`-14`, which is what 23.3-06's SUMMARY records.

---

## DEF-23.3-00 — NO concurrency or spend cap was added. ~8x simultaneous uncapped spend. **DEFERRED BY OPERATOR RULING, 2026-09-07.**

**This is the entry the phase-23.3 operator checkpoint exists for. It is recorded, not fixed,
and the decision stays OPEN.**

**What the phase changed.** Simultaneous research execution goes from **1 run** to
**M x K = 2 x 4 = 8** runs:

- **K = `NESTOR_WORKER_RUN_CONCURRENCY` = 4** — runs executing concurrently inside ONE worker
  instance (23.3-02 / 23.3-03, D-23.3-02). A **memory** bound derived from measured container
  utilization. **Not a spend ceiling.**
- **M = `MIN_INSTANCES` = 2** — worker instances (23.3-03, D-23.3-03). An **availability**
  choice. `--max-instances=5` is **INERT** on this service (no HTTP traffic -> no autoscale ->
  effective count is `minScale`), so throughput is exactly `M x K`.

**The arithmetic, plainly.** `tribunal-worker` runs with **`NESTOR_TRIBUNAL_UNCAPPED=1`**, live
and unchanged by this phase.

| | before 23.3 | after 23.3 |
|---|---|---|
| simultaneous runs | 1 | **8** |
| at the $24.78 measured on run `fb9484dd` | ~$25 | **~$198** |
| at the top of the measured $25-45 per-run range | ~$45 | **~$360** |

So worst-case simultaneous exposure moves from roughly **$25-45** to roughly **$200-360**.

**What was NOT added:** no global concurrency cap, no per-tenant limit, no queue-depth
ceiling, no spend governor change. The pre-existing $25 governor is unchanged — and note it
**has never fired**, so it is not evidence of a working ceiling.

**Why it is deferred rather than fixed:** **operator ruling of 2026-09-07** (23.3-CONTEXT.md
§ 9). The operator explicitly deferred *sizing* a ceiling until there is data from real
concurrent execution to size it against, and explicitly required that concurrency **not be
quietly lowered as a proxy for a cap** — doing so would overturn the ruling while appearing to
comply with it. K and M were therefore left at their derived values.

**Compensating controls that DO exist** (none of them a cap):

- **Rollback with no code change:** `NESTOR_WORKER_RUN_CONCURRENCY=1` restores serial
  behaviour; `NESTOR_RECONCILE_INTERVAL_S=0` disables the new sweep.
- **The deploy ordering gate** in `infra/DEPLOY-RUNBOOK.md` § Phase 23.3 puts "confirm the
  Tribunal queue is EMPTY" FIRST, because a worker deploy boots the container and the loop
  claims first — and post-23.3 a booting instance claims up to 4 runs at once, not 1.
- **The blocking operator checkpoint** in plan 23.3-06 puts this arithmetic in front of a
  person BEFORE the change becomes deployable, rather than on an invoice afterwards.

**Action to close:** after the first genuinely concurrent runs, take a real spend + memory
high-water mark and size a ceiling against it (see also DEF-23.3-12 — K itself was derived
with only one run ever in flight).

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

> ⚠ **Second numbering collision (orchestrator, wave-2 merge).** Plans 23.3-03 and 23.3-05 ran
> in parallel worktrees and BOTH claimed `DEF-23.3-05`, for unrelated findings. 23.3-03's item
> (the `DATABASE_URL` leak) keeps `-05` because it merged first; 23.3-05's three are renumbered
> **`-06`, `-07`, `-08`**. No item dropped, no body text changed. This is the SECOND collision on
> this file in one phase: an append-only shared register is a structural conflict point for
> parallel waves, and telling each executor "continue from the taken ids" cannot work when they
> cannot see each other. A future phase should give each plan its OWN deferral file and have the
> orchestrator concatenate them.

- **23.3-03 addendum (different environment, same conclusion):** in the venv used by 23.3-03
  `structlog` IS installed, so that collection error does not occur; instead
  `test_report_planner.py` fails collection with `ModuleNotFoundError: No module named 'google'`
  (`pipeline/tribunal/report_planner.py:25` imports `google.genai`), and the DSN-less baseline at
  `fe43c62` is `204 failed, 2260 passed, 31 skipped, 3 xfailed, 28 errors`. **The absolute numbers
  are environment-specific and are not comparable across sessions** — only the before/after DELTA
  inside ONE environment means anything. Nobody should quote "182/39" or "204/28" as the number.

## DEF-23.3-05 — `test_advisory_lock_exactly_once.py` LEAKS `DATABASE_URL` into the whole process

- **Found during:** 23.3-03, DSN-less regression baselining.
- **What:** `test_advisory_lock_exactly_once.py:162` does a bare
  `os.environ["DATABASE_URL"] = url` after starting a `testcontainers` `postgres:15` and running
  migrations against it, and **never removes it**. It is not a `monkeypatch.setenv`, so nothing
  undoes it. `test_schema_isolation.py:159` does the same.
- **Consequence, measured:** run `nestor_pulse_sdk/tests` with NO `DATABASE_URL` in the
  environment and `test_worker_in_instance_concurrency.py` does **not** skip its six DB-backed
  tests — it finds the leaked DSN (alphabetically `test_advisory_lock_*` collects and runs first)
  and executes them against the throwaway container. Targeted run: `1 passed, 6 skipped`.
  Full-suite run, same environment: all 7 passed. Same code, same environment, different outcome
  purely from module ordering.
- **Why it matters beyond tidiness:** the leaked DSN's role is the container's `test` SUPERUSER,
  which bypasses RLS. Any test meaning to prove something about a *role* — the `run_worker_all`
  policy of migration 0008, tenant isolation, an RLS fence — is silently handed a role that can
  see everything. A file can therefore report green on an assertion its own preflight was written
  to skip. Same family as DEF-23.2-14 (process-wide state leaking between test modules), but the
  mechanism is an env var rather than `caplog`.
- **Not fixed here:** the file is untouched by 23.3-03, whose scope is the poll loop and the
  deploy script. Changing a fixture in an advisory-lock test file under a concurrency plan is the
  scope creep the phase fences forbid.
- **Action:** convert both assignments to `monkeypatch.setenv` (or restore the previous value in
  the fixture teardown). Until then, **DB-role claims must be measured with a targeted run**, not
  read off a full-suite line.

---

## DEF-23.3-06 — the reconciler's NON-terminal mirror is not compare-and-swapped

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

## DEF-23.3-07 — the sweep replays a SUPERADMIN identity, not a space-scoped one

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

## DEF-23.3-08 — a claimed run with a NULL `tribunal_run_id` is skipped, never finalized

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
- **23.3-06 addendum:** plan 06 did NOT decide it. Its scope was the sweep's trigger, the runbook
  and this register; writing a terminal state on a possibly-spending ~$45 run was out of scope for
  a plan that adds a timer. The entry stands OPEN with its consequence (a held in-flight slot)
  unchanged.

---

# Added by 23.3-06 (the planner's re-homed set, plus two new findings)

## DEF-23.3-09 — the bare `AsyncOpenAI()` fallback at `audit/audited_llm_client.py:992` carries no explicit timeout

- **Found during:** phase-23.3 planning; re-homed here by 23.3-06 (the planner filed it as
  `-01`, which was already taken).
- **What:** the client constructed at `:992` gets no `timeout=`, so it takes the SDK default.
  `:1728`'s client is explicit (`timeout=3600`) and the Anthropic client was bounded at
  `timeout=600.0` by 23.3-02 — this one path is the remaining unbounded constructor.
- **Why not fixed:** its call path was never traced during planning. Pinning a timeout on an
  untraced path can convert a latent inefficiency into a **live truncation** of a paid run, which
  is a worse defect than the one being fixed. Under concurrency the exposure is real but bounded
  by 23.3-01's run-level backstop (`NESTOR_WORKER_RUN_TIMEOUT_MINUTES=120`).
- **Action:** trace the `:992` call path first, then set a timeout with a known blast radius.

## DEF-23.3-10 — no Cloud Scheduler HTTP trigger for the sweep

- **Found during:** 23.3-06, Task 1 (the planner filed it as `-04`).
- **What:** the sweep's only trigger is the in-process `asyncio` timer in
  `app/main.py::_reconcile_loop`. There is no external, belt-and-braces trigger.
- **Why not fixed:** the **Cloud Scheduler API is not enabled** on this project and enabling it
  is an operator/IAM action the agent cannot perform. Adding an HTTP route now would create
  request surface for an API nobody can call.
- **Deliberate design consequence:** `sweep_once` is a **plain callable** taking no FastAPI
  object, no request and no identity — so adding the Scheduler trigger later is a route, not a
  redesign.
- ⚠ **What stands between now and then:** the in-process timer depends on TWO deploy-config
  facts, and both fail SILENTLY. `minScale >= 1` (else no instance exists between requests) and
  `cpu-throttling=false` (else Cloud Run cuts an idle instance's CPU and the timer stops
  ticking with no error and no log). Both are now pinned in `infra/DEPLOY-RUNBOOK.md` Step 4
  and re-asserted in its § Phase 23.3 read-back — but a doc is not an alarm. Nothing monitors
  whether the sweep is actually ticking.
- **Action:** when the Scheduler API is enabled, add the HTTP trigger; separately, consider a
  liveness signal for the timer itself (a "last swept at" the operator surface can read).

## DEF-23.3-11 — `serpapi._BREAKER` and `_SEMAPHORE` are process-wide and now shared by concurrent runs

- **Found during:** phase-23.3 planning (the planner filed it as `-05`).
- **What:** `pipeline/tribunal/serpapi.py`'s circuit breaker and semaphore are module-level, so
  under K=4 four concurrent runs share one breaker: one run's failures could open the breaker for
  the other three, and one run's rate limit throttles all of them.
- **Why it is currently inert:** the own-researcher / SerpAPI stream was cut in Phase 15.6
  (D-W3-3) and does not execute. The live rotation is `("gemini","openai","claude")`. The sharing
  is therefore latent, not active.
- **⚠ It becomes real the moment that stream is restored** — and restoring it would look like an
  unrelated change. Whoever does it inherits this.
- **Action:** make both per-run (or key them by run id) as part of any work that revives the
  SerpAPI stream.

## DEF-23.3-12 — K=4 was derived with only ONE run ever in flight

- **Found during:** phase-23.3 planning (the planner filed it as `-06`).
- **What:** K=4 comes from a 5-minute P99 memory alignment measured on a worker that has never
  executed more than one run at a time. It is the best number available, but it is an
  extrapolation, not a high-water mark.
- **Why not fixed:** a true high-water mark under real concurrency cannot be taken before the
  first concurrent run happens.
- **Action:** take the real memory high-water mark after the first concurrent runs and re-check
  K **before** anyone raises it. Paired with DEF-23.3-00: that same measurement is what a spend
  ceiling should be sized against.

## DEF-23.3-13 — an editable install maps `app` to the MAIN repo, so verification scripts run by PATH check the wrong tree

- **Found during:** 23.3-06, while building an AST verifier for Task 1. **NEW finding.**
- **What, measured:** `site-packages/_editable_impl_nestor_intake_backend.pth` (dist-info
  `nestor_intake_backend-0.1.0`) resolves the `app` package to
  `C:/Users/ajimimo/Desktop/MOELD/nestor-intake-gcp/backend/app` — the **main repo**. From inside
  a worktree, `python -c "import app.main"` and `pytest` are SAFE (both put the cwd / rootdir
  first on `sys.path`), but `python some/script.py` is NOT: `sys.path[0]` becomes the script's own
  directory, the `.pth` wins, and the main-repo copy is imported.
- **Measured symptom:** a verifier invoked by path raised `AttributeError: module 'app.main' has
  no attribute 'RECONCILE_INTERVAL_SECONDS'` while the worktree file plainly defined it, and an
  earlier traceback pointed at `nestor-intake-gcp/backend/app/db/base.py` (main repo) during a
  run inside the worktree.
- **Why it matters as a GATE-INTEGRITY defect, not a nuisance:** a helper script that imports
  `app` can verify the MAIN repo and report GREEN about code the worktree does not contain — or
  RED about code it does. The direction of the lie depends on which tree is ahead. This is the
  same family as the stale-base trap, but it survives a correct base.
- **Not fixed here:** the fix is environment/tooling (`pip install -e` inside each worktree, or
  `PYTHONPATH`/`sys.path` discipline in every helper), which is outside a plan whose files are
  `main.py`, one test file, the runbook and this register.
- **Action, immediate and cheap:** write verification as `pytest` tests or `python -c` from the
  repo root. Never as a script invoked by absolute path that imports `app`.

## DEF-23.3-14 — `infra/main.tf` still says `min_instance_count = 0` for `nestor-api`; live is `minScale: '1'`

- **Found during:** 23.3-06, Task 3(a). **NEW finding.**
- **What:** `infra/main.tf:381` reads `min_instance_count = 0` (D-01a, scale-to-zero) for
  `nestor-api`, while the live service is `minScale: '1'` (measured 2026-09-07, revision
  `nestor-api-00049-wgk`).
- **⚠ Consequence:** a `terraform apply` from that file would take `nestor-api` back to zero
  instances and thereby **silently disable the phase-23.3 reconcile timer between requests** —
  no error, no log, no failed probe, just orphaned paid runs that are never recovered. The
  premise the reconciler was designed around would be deleted by an IaC operation that looks
  routine.
- **Why not fixed here:** 23.3-06's file scope does not include `main.tf`, no Terraform was run
  in this phase and none is in scope, and editing IaC that is not then applied creates a THIRD
  state (file, live, and the un-applied intention) rather than removing drift.
- **Mitigation now in place:** `infra/DEPLOY-RUNBOOK.md` Step 4 carries the measured live table,
  the corrected `--min-instances=1` command, and an explicit drift warning naming this entry.
- **Action:** reconcile `main.tf` with live **before** the next `terraform apply` — and treat
  `min_instance_count` on `nestor-api` as load-bearing from now on, not a cost knob.

## DEF-23.3-15 — alembic's `fileConfig` DISABLES every app logger for the rest of the pytest process

- **Found during:** 23.3-06, Task 2, while three log assertions passed in isolation and failed
  in the full suite. **NEW finding. Pre-existing — nothing in this phase caused it.**
- **What, PROVEN not inferred:** `backend/app/db/alembic/env.py:41` calls
  `fileConfig(config.config_file_name)`. `logging.config.fileConfig` defaults to
  **`disable_existing_loggers=True`**, and `alembic.ini`'s `[loggers] keys = root,sqlalchemy,alembic`
  names none of this app's loggers. So the moment the conftest runs `alembic upgrade head`,
  `logging.getLogger("nestor.health").disabled` becomes `True` **for the remainder of the
  process**. A disabled logger drops records before they reach ANY handler — including one
  attached directly to that logger, so this defeats `caplog` and hand-rolled handlers alike.
- **Reproduction (30 seconds, no DB), run in `backend/`:** attach a handler to
  `nestor.health`, `warning(...)` -> 1 record; `fileConfig("alembic.ini")`; `warning(...)`
  again -> still 1 record, and `lg.disabled` is now `True`. Measured 2026-09-07.
- **⚠ Why this is a GATE-INTEGRITY defect and not a nuisance.** The visible direction is a
  false RED (an assertion that a warning WAS logged fails). **The dangerous direction is
  silent:** any assertion of the shape *"no ERROR/WARNING was logged"* goes **vacuously
  GREEN** after any DB-backed module has run. This repository already has a documented habit
  of diagnosing from silence (16-05 cost a full UAT day), and `run_task.py` / `reconcile.py`
  both log at WARNING *specifically* so their signal survives — none of which can be
  test-asserted once the logger is disabled.
- **Same family as** DEF-23.2-14 and DEF-23.3-05 (process-wide state leaking between test
  modules), but the mechanism is the logging config rather than `caplog` or an env var, and
  the trigger is a fixture nearly every DB-backed module uses.
- **Workaround in place (23.3-06 only, local to one file):**
  `tests/test_reconciler_lifespan.py::_capture` clears `lg.disabled` for the duration of the
  assertion and restores it afterwards. That fixes ONE file. Every other module that wants to
  assert on logs inherits the bug.
- **Action:** pass `disable_existing_loggers=False` in `env.py`'s `fileConfig` call (a
  one-line change, but it touches the migration entry point, so it belongs to a plan that owns
  that file and can prove migrations still log correctly), or stop calling `fileConfig` when
  alembic is invoked programmatically from the test harness.
