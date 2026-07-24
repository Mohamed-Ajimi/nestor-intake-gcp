---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 15-07
subsystem: infra
tags: [deploy, runbook, uat, cloud-run, cloud-build, alembic]
requires: [15-01, 15-02, 15-03, 15-04, 15-05, 15-06]
provides:
  - DEPLOY-RUNBOOK § Phase 15 (Steps 15.a–15.f)
  - 15-UAT.md recorded-run walkthrough + V-02 checklist
  - Phase 15 deployed live (all five deployables + migration 0011)
  - All Phase-15 Cloud Build gates green (intake, tribunal full, verify_chain critical)
affects: []
key-files:
  created:
    - .planning/phases/15-engine-enhancements-plan-critique-draft-tournament-deferred-/15-UAT.md
    - tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/recorded/ (fix cycle)
  modified:
    - infra/DEPLOY-RUNBOOK.md
    - tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/loader.py (fix cycle)
    - tribunal/nestor_pulse_sdk/tests/test_hash_chain_replay.py (fix cycle)
    - tribunal/nestor_pulse_sdk/tests/test_graceful_degradation.py (fix cycle)
duration: ~2h (authoring by executor + deploy/gates by orchestrator)
status: complete-with-deferral
---

# Plan 15-07 Summary — Runbook + Deploy + UAT (checkpoint resolved by operator decision)

## Tasks

| # | Task | Status |
|---|------|--------|
| 1 | DEPLOY-RUNBOOK § Phase 15 section (Steps 15.a–15.f, +274 lines) | ✅ commit `15ef921` |
| 2 | 15-UAT.md recorded-run walkthrough + V-02 checklist (226 lines) | ✅ commit `7d1977b` |
| 3 | Operator deploy + UAT checkpoint | ✅ deploy executed 2026-07-24; browser walkthrough + V-02 sign-off DEFERRED to end-of-15.2 combined UAT (operator decision 2026-07-24) |

## Deploy record (2026-07-24, all green)

- tribunal-worker + tribunal-api rebuilt at one SHA `20260724-214354`, deployed (worker first); tribunal-api URL unchanged.
- `tribunal-migrate` repinned to the new image then executed — log shows `Running upgrade 0010 -> 0011` (image-pin lesson applied; no silent no-op).
- nestor-api rebuilt + deployed (`nestor-api-00040-8mw`) — live rev predated the 15-04 proxy routes, so Step 15.e was required.
- frontend rebuilt with the Phase-12 substitutions + deployed (`nestor-frontend-00024-lwq`).
- Gates: intake suite SUCCESS; tribunal FULL suite SUCCESS (345 passed / 35 skipped — first-ever full-suite green); verify_chain critical SUCCESS (SC5 automated half); `TRIBUNAL_SERVICE_URL` seam env confirmed untouched.

## Post-merge fix cycle (3 commits, test-only — no production code)

1. `c9f192a` — recorded run-report committed in-package (`fixtures/run_4cbb5311/recorded/`, 4.1M) + loader prefers it: `gcloud builds submit tribunal` ships only the tribunal/ subtree, so the repo-root `docs/` extracts were absent in Cloud Build (9 fixture failures).
2. fake-writer kwarg — 15-01's `_ConstraintEnforcingFakeWriter.write_full_row()` now accepts 15-02's additive `cache_creation_tokens` (cross-wave integration miss; exactly the post-merge-gate blind spot).
3. CRLF-agnostic D-01 guard — legacy-tools hash on LF-normalized bytes; normalized hash `fa03ab505f5b` matches the snapshot exactly (carried file proven untouched). Never-carried gemini/openai researchers now produce an explicit skip, not a phantom violation.

## Deferred

- 15-UAT.md walkthrough steps 1–5 + V-02 operator sign-off → combined end-of-15.2 UAT session (recorded in 15-UAT.md § Deploy Record + Deferral). Client-blindness meanwhile proven automatically by the 15-04 denial trios.

## Self-Check: PASSED

- Runbook section + UAT walkthrough authored and committed (force-added).
- Deploy executed per runbook order; migration upgrade line confirmed in logs.
- All three Cloud Build gates green; no production-code changes in the fix cycle.
