---
phase: 17-raw-output-audit-chain-guard
plan: 04
subsystem: deploy
tags: [runbook, cloud-build, cloud-run, alembic, human-uat, checkpoint, deploy-gap]

# Dependency graph
requires:
  - phase: 17-raw-output-audit-chain-guard
    plan: 01
    provides: migration 0012 (chain/lock/bundle columns), tribunal GET /research-bundle endpoint, verify_chain + get_research_bundle seam
  - phase: 17-raw-output-audit-chain-guard
    plan: 02
    provides: completion-path verify_chain gate + bundle materialization (bundle.py, run_task.py)
  - phase: 17-raw-output-audit-chain-guard
    plan: 03
    provides: superadmin-only download + re-verify routes, denial suite, frontend RawOutputControls
  - phase: 16-research-trigger-progress-bridge
    provides: § Phase 16 runbook section (16.a REBUILD idiom + nestor-migrate Job pattern), the parked live run the download proof rides on
provides:
  - "infra/DEPLOY-RUNBOOK.md § Phase 17: ordered dual-image REBUILD (tribunal-api FIRST, then nestor-api) + migration 0012 Job + frontend deploy + no-new-env/secret confirm"
  - "17-HUMAN-UAT.md operator checklist: zip-contents (D-01/D-03), completion-path verify_chain gate + locked/Re-verify (D-06), client isolation (REPORT-02)"
  - "Summary-checklist rows 17.a–17.f"
affects: [phase-18-pdf, raw-output-download, audit-chain-guard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ordered dual-image REBUILD: the image whose endpoint is CALLED by the other ships first (tribunal-api before nestor-api), so the first live completion never 404s a stale seam"
    - "Confirm-only env step: a phase that adds NO new env/secret still documents an explicit read-only confirm (STORAGE_BUCKET + TRIBUNAL_SERVICE_URL present, NO AUDIT_GCS_BUCKET) so the deploy is not mistaken for needing config"

key-files:
  created:
    - .planning/phases/17-raw-output-audit-chain-guard/17-HUMAN-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "tribunal-api rebuilds + deploys FIRST (Step 17.a): the intake finalize path calls its new /research-bundle endpoint, so a stale tribunal image would 404 the seam at the first real completion; nestor-api (Step 17.b) ships second"
  - "tribunal-worker is UNCHANGED this phase — the runbook explicitly says do NOT rebuild/redeploy the worker (only the api endpoint is new)"
  - "Both images are Cloud Build image REBUILDs, never env flips — the recurring deploy-gap is called out at the top and in both step bodies"
  - "Step 17.e is confirm-only: NO new env/secret; the bundle uses STORAGE_BUCKET (the app bucket, D-05), NOT AUDIT_GCS_BUCKET (the 7-year audit-evidence bucket)"
  - "The live proof is an operator checkpoint (blocking-human), same pattern as 16-05: it rides on the parked Phase-16 completed run, which is blocked on empty Anthropic credits (Nestor_Claude2)"

requirements-completed: []

# Metrics
duration: ~20min
completed: 2026-07-22
---

# Phase 17 Plan 04: Deploy Runbook + Operator Live-UAT Summary

**The Phase 17 deploy runbook section (ordered dual-image REBUILD — tribunal-api FIRST for the new
`/research-bundle` endpoint, then nestor-api for the completion gate + download routes — migration 0012
via the `nestor-migrate` Job, the frontend deploy, and a confirm-only no-new-env/secret step that pins
the bundle to `STORAGE_BUCKET` and explicitly excludes `AUDIT_GCS_BUCKET`, D-05) plus the operator
live-UAT checklist (raw-output zip contents D-01/D-03, completion-path `verify_chain` gate + locked
Re-verify D-06, and client isolation REPORT-02). The live session itself is a blocking-human checkpoint
returned to the operator — it rides on the parked Phase-16 completed run behind the empty-Anthropic-credits
blocker.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1 of 2 executed (Task 1 authored + committed; Task 2 is the operator checkpoint, returned not performed)
- **Files:** 2 (1 created, 1 modified)

## Accomplishments

- **`infra/DEPLOY-RUNBOOK.md` § Phase 17** appended after § Phase 16 with ordered steps 17.a–17.f:
  - **17.a — tribunal-api REBUILD + deploy FIRST** via Cloud Build (`cloudbuild.api.yaml`), the new
    `GET /api/runs/{run_id}/research-bundle` endpoint; explicitly REBUILD-not-env-flip; **tribunal-worker
    LEFT UNCHANGED** (no worker rebuild); tribunal-api URL captured read-only (unchanged from Phase 14/16).
  - **17.b — nestor-api REBUILD + deploy** via Cloud Build (`app/research/bundle.py`, extended
    `run_task.py`/`research_routes.py`, the `research_runs` chain/lock/bundle columns, migration 0012);
    REBUILD-not-env-flip; full intake suite run in Cloud Build against the fresh image.
  - **17.c — migration 0012** via the `nestor-migrate` Job (`alembic upgrade head`); the three new nullable
    columns (`chain_status`, `chain_broken_at`, `bundle_key`) named and confirmed; pure add-column, so NO
    new policy/grant/index (inherits 0011 FORCE-RLS).
  - **17.d — frontend deploy** (download button + locked/re-verify UI) per the standard § Phase 12 Step-12.3
    flow; SAME `_API_BASE_URL`/`_FB_*` substitutions (no URL re-wiring); NO `VITE_SUPABASE_*`.
  - **17.e — confirm-only** read: `STORAGE_BUCKET` (app bucket — bundle target, D-05) + `TRIBUNAL_SERVICE_URL`
    (seam audience) present; NO new env/secret; explicitly **NO `AUDIT_GCS_BUCKET`** on the download path (D-05).
  - **17.f — CHECKPOINT:** top up Anthropic credits + complete the parked § Phase 16 run FIRST (produces the
    real `completed` run), then the live download/verify_chain/isolation UAT (points to 17-HUMAN-UAT.md).
    Includes a failure-triage block (404 → skipped rebuild; 403 → role-gate regression; client reaches
    surface → REPORT-02 breach, stop).
- **Summary-checklist rows 17.a–17.f** added at the end of the runbook's checklist.
- **`17-HUMAN-UAT.md`** created (mirrors the 16-HUMAN-UAT frontmatter + Tests/Summary/Gaps format) with a
  PRECONDITION callout (empty Anthropic credits → complete the parked Phase-16 run first) and three tests:
  (1) raw-output zip download contents — `report.md` + `research/*.md` + `sources.json`, NO rejected claims
  (D-01/D-03); (2) completion-path `verify_chain` gate green + optional scratch-tenant tamper → locked card +
  working Re-verify (D-06); (3) client isolation — a client login sees NO raw-output/research surface,
  direct route → existence-hidden 404 (REPORT-02).

## Task Commits

1. **Task 1: Phase 17 runbook section + 17-HUMAN-UAT checklist** — `f557c06` (docs)
2. **Task 2: operator live session** — CHECKPOINT (blocking-human); returned to the operator, not performed
   by the executor (no deploys, no live Tribunal runs from this environment).

## Files Created/Modified

- `infra/DEPLOY-RUNBOOK.md` — appended § Phase 17 (ordered dual REBUILD + 0012 Job + frontend + confirm-only
  env + live checkpoint) and the 17.a–17.f Summary-checklist rows.
- `.planning/phases/17-raw-output-audit-chain-guard/17-HUMAN-UAT.md` — NEW operator checklist (3 tests, all
  pending; blocked on the Anthropic-credits precondition).

## Decisions Made

- **tribunal-api FIRST, worker untouched.** The runbook orders tribunal-api's rebuild before nestor-api's
  because the intake finalize path (in nestor-api) calls tribunal-api's new `/research-bundle` endpoint —
  a stale tribunal image would 404 the seam at the first real completion (`bundle_key` would stay NULL).
  The `tribunal-worker` image gained nothing this phase, so the runbook explicitly forbids a worker rebuild
  (mirrors the Phase-16 "config-only env update on the UNCHANGED worker image" discipline, inverted here to
  "no worker touch at all").
- **REBUILD, never env-flip (twice).** The recurring deploy-gap ("a config-only env flip ships a stale
  image") is called out in the section preamble and in both 17.a and 17.b bodies, with the exact failure
  symptom (404 on the new route / `ModuleNotFoundError` while CI is green).
- **Confirm-only env step, no new secret.** Phase 17 adds no env/secret; Step 17.e is a read-only confirm
  that `STORAGE_BUCKET` + `TRIBUNAL_SERVICE_URL` are present and that `AUDIT_GCS_BUCKET` is NOT on the
  download path (D-05 — the raw-output zip lives in the app bucket, never the 7-year audit-evidence bucket).
- **Live proof is a checkpoint, not executor work.** The proof rides on a real `completed` run, still
  blocked on empty Anthropic credits (`Nestor_Claude2`), so it is an operator-runbook checkpoint — the same
  pattern as 16-05. The executor authored and committed the artifacts; the operator runs the live session.

## Deviations from Plan

None — plan executed exactly as written. Task 1 authored both artifacts to the plan's acceptance criteria;
Task 2 is the blocking-human checkpoint, returned per the checkpoint protocol (no deploys / live runs from
this environment, per the phase's autonomous:false + the empty-credits blocker).

## Automated Verification

Task 1's automated verify passed:

- `grep -c "## Phase 17" infra/DEPLOY-RUNBOOK.md` ≥ 1 AND `17-HUMAN-UAT.md` exists → `runbook+uat present`.
- Steps 17.a..17.f present; tribunal-api-first callout present; the three column names present; the
  "NO AUDIT_GCS_BUCKET" note present; the UAT file contains both `download` and `verify_chain`.

The live proof (Task 2) is deferred to the operator checkpoint — a real completed run behind the
Anthropic-credits blocker, same external blocker as 16-05. No Python/Docker/deploy runs from this
environment (dev box has neither; deploys are operator-only).

## Threat Surface Scan

No NEW code surface — this plan is docs + a checklist only. It documents the mitigations already in the
plan's `<threat_model>`:

- **T-17-16** (stale-image deploy): Steps 17.a/17.b force ordered Cloud Build REBUILDs (tribunal-api first),
  with the recurring deploy-gap called out explicitly.
- **T-17-17** (client reaching the raw-output download): UAT test 3 verifies a client login shows NO
  raw-output surface + existence-hidden 404 on the route (REPORT-02), backed by the Plan-03 denial suite.
- **T-17-18** (export on an unverified chain): UAT test 2 confirms `chain_status=verified` came from the
  completion-path gate; the optional scratch-tenant tamper proves broken → locked (D-06).
- **T-17-19** (bundle to the wrong bucket): Step 17.e confirms `STORAGE_BUCKET` (app bucket), NO
  `AUDIT_GCS_BUCKET` (D-05).
- **T-17-SC** (package installs): none — no new packages; both images ship existing deps only.

## Known Stubs

None. The runbook section and UAT checklist are complete and reference live artifacts (the Plan-01/02/03
endpoints, routes, columns, migration, and UI). The three UAT tests are `[pending]` because they are the
operator's live-session outputs, not stubs — they cannot be filled until the parked Phase-16 run completes
after the Anthropic-credits top-up.

## Next Phase Readiness

- The operator has a single ordered runbook (§ Phase 17) + a 3-test checklist to run the live proof once
  credits are topped up and the parked Phase-16 run completes.
- Phase 18 (PDF report step) inherits: the deployed download surface, the `bundle_key`/`chain_status`
  contract, and the confirmed app-bucket (`STORAGE_BUCKET`) bundle location.
- Blocker carried forward: Anthropic credits (`Nestor_Claude2` empty) gate BOTH the parked Phase-16 run and
  this Phase-17 download proof — top up first.

## Self-Check: PASSED

- Both claimed files exist on disk (`infra/DEPLOY-RUNBOOK.md` modified, `17-HUMAN-UAT.md` created).
- Task 1 commit present: `f557c06` (docs).
- § Phase 17 present with Steps 17.a–17.f; the three column names, tribunal-api-first, and the
  no-AUDIT_GCS_BUCKET note all grep-confirmed.
- SUMMARY.md + HUMAN-UAT force-added (`.planning/` is gitignored).
- No STATE.md / ROADMAP.md modified (orchestrator owns those in worktree mode).

---
*Phase: 17-raw-output-audit-chain-guard*
*Completed: 2026-07-22 (Task 1 authored; Task 2 = operator checkpoint returned)*
