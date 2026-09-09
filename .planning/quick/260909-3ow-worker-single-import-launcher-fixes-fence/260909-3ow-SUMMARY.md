---
quick_id: 260909-3ow
status: complete
base_commit: 1180fc9
commits:
  - 919fdef  test(260909-3ow) — RED, test-only
  - c98faa9  fix(260909-3ow) — launcher + alias + Dockerfile
deployed: false
---

# 260909-3ow SUMMARY — the worker now runs under ONE module identity

**Defect:** DEF-23.3-01 (root cause; supersedes the heartbeat-only framing of `260909-168`).

## Base commit

Worked from **`1180fc9`** ("plan(260909-3ow): run the worker under ONE module identity"),
verified with `git merge-base --is-ancestor 1180fc9 HEAD` BEFORE any edit — it was HEAD of the
worktree branch `worktree-agent-ac1092db876828ead`. No stale base; no fetch/reset was needed.

## RED evidence — recorded verbatim, observed BEFORE any source change

`test_dash_m_worker_does_not_double_import` was written and run against unmodified `worker.py`.
It runs the module as `__main__` (`runpy.run_module(..., run_name="__main__", alter_sys=True)`,
`main()` neutralised at `asyncio.run`), then performs the exact import `execute.py` performs at
dispatch time, and compares the two `WORKER_ID`s. Output, Python 3.12.6, no database:

```
nestor_pulse_sdk/tests/test_worker_single_module_identity.py::test_dash_m_worker_does_not_double_import FAILED
E   AssertionError: worker.py evaluated WORKER_ID TWICE in one process -- the `__main__` copy
E   claims the run, the canonical copy owns every fenced write, and `WHERE worker_id = :wid`
E   matches zero rows (DEF-23.3-01).
E       __main__  copy WORKER_ID = '7HD4N44-60500-1f22a40c'
E       canonical copy WORKER_ID = '7HD4N44-60500-3d2aebf6'
E   assert '7HD4N44-60500-1f22a40c' == '7HD4N44-60500-3d2aebf6'
```

**The two observed pre-fix values are `7HD4N44-60500-1f22a40c` and `7HD4N44-60500-3d2aebf6`.**
Same hostname (`7HD4N44`), same pid (`60500`), two different `uuid4()` draws — structurally the
identical shape to the live pair on `tribunal-worker-20260908-233038-013724` for run `9b79e10f`
(`worker_started worker_id=localhost-1-d35c5630` vs `run_heartbeat rowcount=0
wid=localhost-1-cbcd49a4`). The reproduction is the root cause, not an analogy: the mismatch is
produced by the same two mechanisms (a `-m` module run plus `execute.py`'s lazy canonical import).

All three tests were RED on `1180fc9`:

| Test | Pre-fix result |
|---|---|
| `test_dash_m_worker_does_not_double_import` | FAILED — the two IDs above |
| `test_launcher_loads_worker_exactly_once` | FAILED — `ImportError: No module named nestor_pulse_sdk.runs.worker_main` |
| `test_worker_dockerfile_cmd_points_at_the_launcher` | FAILED — CMD was `['python','-m','nestor_pulse_sdk.runs.worker']` |

## Post-fix identity assertion

Same test, after Task 1, asserts more than equality — it asserts **object identity**:

```python
assert main_worker_id == canonical_worker_id   # the message above
assert main_worker_id is canonical_worker_id   # same str object => same module object
```

and the launcher test asserts there is exactly **one** module object in `sys.modules` whose
`__file__` resolves to `runs/worker.py`, and that `sys.modules["nestor_pulse_sdk.runs.worker"]`
**is** that object. Green:

```
test_dash_m_worker_does_not_double_import PASSED [ 33%]
test_launcher_loads_worker_exactly_once   PASSED [ 66%]
test_worker_dockerfile_cmd_points_at_the_launcher PASSED [100%]
3 passed in 1.42s
```

## What changed (4 files, exactly the fenced set)

```
 tribunal/infrastructure/cloud-run/worker/Dockerfile              |   9 +-
 tribunal/nestor_pulse_sdk/runs/worker.py                         |  19 ++-
 tribunal/nestor_pulse_sdk/runs/worker_main.py                    |  10 ++   (new)
 tribunal/nestor_pulse_sdk/tests/test_worker_single_module_identity.py | 176 +++   (new)
 4 files changed, 211 insertions(+), 3 deletions(-)
```

* **NEW `runs/worker_main.py`** — launcher; imports `main` from the canonical `runs.worker` and
  calls it under `__main__`. `worker.py` is therefore never `__main__` in the container.
* **Dockerfile** — `CMD ["python","-m","nestor_pulse_sdk.runs.worker_main"]`, header comment at
  line 5 updated, and the reason recorded inline so a future edit cannot revert it innocently.
* **`worker.py`** — `main()` docstring now names the launcher and states why; the
  `if __name__ == "__main__":` block calls
  `sys.modules.setdefault("nestor_pulse_sdk.runs.worker", sys.modules[__name__])` **before**
  `main()`, so the legacy local `-m runs.worker` invocation cannot double-import either.
* `execute.py:135`'s lazy import was deliberately **not** touched — the cycle is real; the
  launcher makes it harmless. Import-graph restructuring stays out of scope.

Verified the fix is actually reachable in production: neither
`tribunal/infrastructure/cloud-run/deploy-worker.sh` nor the `google_cloud_run_v2_service`
`tribunal_worker` block in `infra/main.tf` (lines 1046-1094) sets `--command`/`--args` or
`command`/`args`, so the image's `CMD` **is** the effective entrypoint. (The `command`/`args`
overrides at `infra/main.tf:574,628,1338` belong to the migration and seed Jobs, not the worker.)

## Verification — actual output

**1. New test file (no DB needed):** `3 passed in 1.42s` — pasted above.

**2. Launcher imports cleanly**, run from `tribunal/`:

```
$ python -c "import nestor_pulse_sdk.runs.worker_main; print(...)"
launcher imports OK: nestor_pulse_sdk.runs.worker
```

(`main.__module__` is the *canonical* name — the launcher does not create a `__main__` copy.)

**3. The four existing worker test files:** `18 passed, 21 skipped in 1.51s`

| File | passed | skipped |
|---|---|---|
| `test_async_worker.py` | 6 | 0 |
| `test_worker_in_instance_concurrency.py` | 1 | 6 |
| `test_run_timeout_backstop.py` | 1 | 4 |
| `test_run_ownership_fence.py` | 10 | 11 |

**The 21 skips are NOT passes.** Every one is DB-gated on this machine (no DSN set). Their own
skip messages say so explicitly, e.g.:

> `DATABASE_URL is unset (or is not a postgresql+asyncpg:// DSN), so the D-23.1-06
> ownership-fence proofs did NOT run. THIS IS NOT A PASS: the displaced-worker writes these tests
> cover are unproven in this build.`

> `neither DATABASE_URL_WORKER nor DATABASE_URL is set -- ... A skip here is NOT a pass: with them
> skipped, in-instance concurrency is asserted only as source text and never as behaviour.`

Notably `test_heartbeat_loop_logs_rowcount_1_for_the_owner_live` — the test that would have
caught this defect behaviourally — is one of the skipped ones. The fenced-write behaviour remains
unproven locally; only the module-identity precondition is now proven.

**4. Combined run, new file first, to prove no `sys.modules` leakage** (the new tests mutate
`sys.modules`/`sys.argv` via `runpy`; both are snapshot/restored per test):

```
$ pytest test_worker_single_module_identity.py test_async_worker.py \
         test_worker_in_instance_concurrency.py test_run_timeout_backstop.py \
         test_run_ownership_fence.py -q
..........ssssss.ssss..........sssssssssss  [100%]
21 passed, 21 skipped in 3.27s
```

18 + 3 = 21 passed, skip count unchanged — the canonical worker module is intact for the rest of
the suite.

**5. Scope fence — `git diff --stat 1180fc9 HEAD`** touches exactly the four files listed above.
No deletions (`git diff --diff-filter=D --name-only 1180fc9 HEAD` is empty). Working tree clean.

**6. Fenced SQL and timing constants unchanged** — this grep over the `worker.py` diff returns
NOTHING (no matching added or removed line):

```
$ git diff 1180fc9 -- .../worker.py | grep -E "^[+-].*(_HEARTBEAT_SQL|CLAIM_SQL|REAP_SQL|_CONSUME_CLAIM_SQL|NESTOR_WORKER_STALE_MINUTES|STALE_RUN_MINUTES|MAX_RECLAIMS)"
(no output)
```

They are all still present at HEAD: `CLAIM_SQL` `worker.py:180`, `_HEARTBEAT_SQL` `:255`,
`REAP_SQL` `:338`, `_CONSUME_CLAIM_SQL` `execute.py:92`, and the env line
`STALE_RUN_MINUTES = int(os.environ.get("NESTOR_WORKER_STALE_MINUTES", "60"))` at `worker.py:91`.

**NOT DEPLOYED.** No `gcloud`, no `docker` was run. A paid run is in flight on the live worker;
the orchestrator deploys.

## Deferred — `NESTOR_WORKER_STALE_MINUTES` stays at 90

The 60 -> 90 bump from `260909-168` was a stopgap taken *because* the heartbeat was not landing:
with `rowcount=0` forever, the stale window is effectively the maximum length of a healthy run,
and 60 sat below the 64.2-minute longest run that ever completed. **Do not revert it here.** It
reverts to 60 in a follow-up ONLY after the deployed launcher shows `run_heartbeat` with
`rowcount=1` in production logs.

The two 90s that must move together:

| Where | Line |
|---|---|
| `tribunal/infrastructure/cloud-run/deploy-worker.sh` | `:281` — inside `--set-env-vars="...,NESTOR_WORKER_STALE_MINUTES=90,..."` (documented at `:51` and `:216`) |
| `infra/variables.tf` | `:269` — the Terraform default + its ⚠ STOPGAP description (consumed at `infra/main.tf:1094`) |

Keep both strictly below `tribunal_worker_run_timeout` (120) so the two cannot tie.

## Found but NOT touched

1. **Five stale doc references to the old entrypoint.** Out of the 4-file fence; they now describe
   a CMD that no longer exists:
   - `docs/handbook/03-architecture.md:81`
   - `docs/handbook/09-tribunal-service.md:460`
   - `docs/handbook/13-infrastructure-and-deploy.md:301` and `:410`
   - `infra/DEPLOY-RUNBOOK.md:5222`
   `infra/DEPLOY-RUNBOOK.md:6162` also lists `nestor_pulse_sdk.runs.worker` in an import-surface
   table as **NOT DEPLOYED**, which the deploy surface for THIS change contradicts — the worker
   image must be rebuilt and deployed for the fix to take effect.
2. **The blast radius is wider than the heartbeat, and none of it is verified.** With the two
   copies, every fenced write in `execute_run` matched zero rows: the heartbeat, the `needs_input`
   park, the `needs_report_spec` park, the success finalize and the failure write. Since the fence
   shipped on the worker at `20260907-161728`, no run has been able to record a completion, and
   the report-body INSERT is gated on `completed.rowcount`, so finished reports were discarded
   silently. **How many runs that affected was not investigated here** (no DB access, no gcloud) —
   worth an operator query over `run` rows in that window.
3. **`execute.py`'s lazy import** is untouched by ruling. It remains a latent trap for any future
   entrypoint that runs a module both as `__main__` and by name.
4. **Local dev still uses `-m runs.worker`** in places (per the docstring); the self-alias covers
   it, but the launcher is the supported entrypoint and local instructions were not updated.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/runs/worker_main.py` — FOUND
- `tribunal/nestor_pulse_sdk/tests/test_worker_single_module_identity.py` — FOUND
- commit `919fdef` — FOUND
- commit `c98faa9` — FOUND
