# Phase 23.3 — deferred items

Out-of-scope discoveries logged during execution. NOT fixed by the plan that found them.

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
