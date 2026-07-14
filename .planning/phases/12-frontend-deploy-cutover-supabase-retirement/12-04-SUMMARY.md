---
phase: 12-frontend-deploy-cutover-supabase-retirement
plan: 04
subsystem: infra
tags: [terraform, cloud-run, gcp, deploy-runbook, iac-drift, cors, firebase, nitro]

# Dependency graph
requires:
  - phase: 09-gcs-storage
    provides: uploads-bucket CORS pattern (Step 9.1b) + google_storage_bucket.uploads
  - phase: 10-notifications
    provides: backend catch-up steps 10.1-10.5 (Resend secret, mail envs, jinja2 image rebuild)
  - phase: 11-internationalization
    provides: alembic 0010 + full backend suite (11-UAT #6) folded into the catch-up
provides:
  - "google_cloud_run_v2_service.frontend TF block by construction (scale-to-zero, PORT=8080, allUsers invoker) — inert, never applied (D-07)"
  - "frontend_service_name / frontend_image_tag + VITE_* build-arg variables"
  - "frontend_service_url output feeding the second-pass URL wiring"
  - "DEPLOY-RUNBOOK.md Phase 12 section: backend catch-up (12.1) + NDA asset (12.2) + two-pass frontend deploy (12.3/12.4) + parity gate (12.5)"
affects: [12-05, cutover, frontend-deploy, iac-reconcile]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IaC-by-construction drift note (# IaC-DRIFT: inert until deployed out-of-band)"
    - "Two-pass URL wiring: deploy -> capture Service URL -> wire CORS/APP_BASE_URL/bucket-CORS/Firebase (never a guessed run.app URL)"
    - "Image REBUILD mandatory (never config-only deploy) for the backend catch-up"

key-files:
  created: []
  modified:
    - infra/main.tf
    - infra/variables.tf
    - infra/outputs.tf
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "Frontend Cloud Run service drops the API's 900s timeout + cpu_idle=false (no SSE / no background LLM work on the SSR tier — Cloud Run defaults are correct)"
  - "Frontend gets an UNCONDITIONAL allUsers run.invoker (public web app, A6/T-12-12); no allow_unauthenticated toggle — it does not proxy the API, the browser calls nestor-api directly"
  - "Frontend image reuses the existing `nestor` Artifact Registry repo (path .../nestor/frontend:<tag>) — no new repo resource"
  - "VITE_* build-arg vars documented in variables.tf (inert) but never emitted as runtime Cloud Run envs — they inline at image-build time"

patterns-established:
  - "Frontend TF service mirrors google_cloud_run_v2_service.api with frontend deltas (no timeout, no cpu_idle, PORT env, allUsers invoker)"
  - "Runbook Phase 12 enforces backend-catch-up-first ordering then two-pass URL wiring off the captured Service URL"

requirements-completed: [INFRA-05, QA-05]

# Metrics
duration: 6min
completed: 2026-07-14
---

# Phase 12 Plan 04: Frontend IaC true-up + DEPLOY-RUNBOOK Phase 12 section Summary

**A by-construction `google_cloud_run_v2_service.frontend` block (scale-to-zero, PORT=8080, allUsers invoker, IaC-DRIFT note) plus a complete Phase-12 deploy runbook that orders backend catch-up first, then a two-pass frontend deploy that wires CORS/APP_BASE_URL/bucket-CORS/Firebase off the captured run.app URL.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-14T15:05:34Z
- **Completed:** 2026-07-14T15:11:35Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added the frontend Cloud Run service to `infra/*.tf` by construction (D-07): a `frontend_image` local (reusing the `nestor` repo), a `google_cloud_run_v2_service.frontend` block mirroring the API service with the correct frontend deltas (no 900s timeout, no `cpu_idle=false`, `PORT=8080` env), an unconditional `allUsers` invoker, the `IaC-DRIFT` note, new `frontend_service_name`/`frontend_image_tag`/`vite_*` variables, and a `frontend_service_url` output.
- Wrote the DEPLOY-RUNBOOK `## Phase 12` section (5 numbered steps) enforcing: backend catch-up FIRST (jinja2/httpx image rebuild + alembic 0010 Job + Resend secret + mail envs + full suite, cross-referencing Steps 10.1-10.4), then the NDA asset drop, then the two-pass frontend deploy/URL-wiring — off the CAPTURED Service URL, never a guessed run.app URL.
- Added an explicit D-08 guard (no Supabase-side actions; independence proven code-side) and updated the Summary checklist with 6 Phase-12 items.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the frontend Cloud Run service to infra/*.tf by construction (D-07)** - `d6e6d50` (feat)
2. **Task 2: Write the DEPLOY-RUNBOOK Phase 12 section** - `3af6e78` (docs)

**Plan metadata:** committed separately (this SUMMARY.md) — see final commit.

## Files Created/Modified
- `infra/main.tf` - Added `local.frontend_image`, `google_cloud_run_v2_service.frontend` (scale-to-zero, PORT=8080, no timeout/cpu_idle, IaC-DRIFT note), and `google_cloud_run_v2_service_iam_member.frontend_invoker` (unconditional allUsers).
- `infra/variables.tf` - Added `frontend_service_name` (default `nestor-frontend`), `frontend_image_tag` (no default), and 4 `vite_*` build-arg vars (all public, IaC-drift-inert).
- `infra/outputs.tf` - Added `frontend_service_url = google_cloud_run_v2_service.frontend.uri`.
- `infra/DEPLOY-RUNBOOK.md` - Added the `## Phase 12` section (Steps 12.1-12.5) + 6 Summary-checklist items.

## Decisions Made
- **Frontend deltas vs the API block:** dropped `timeout = "900s"` and `resources.cpu_idle = false` — the SSR tier has no long-lived SSE and no 90-120s background LLM/Whisper work, so the Cloud Run defaults (300s timeout, CPU throttled between requests) are correct. Kept `min_instance_count = 0` (D-02 scale-to-zero) and `container_port = 8080` + explicit `PORT=8080` env (Nitro node-server reads `$PORT`).
- **Unconditional allUsers invoker for the frontend** (unlike the API's `var.allow_unauthenticated` toggle): a public web app must be publicly reachable; app-level Firebase auth gates data. Documented in both the tf comment and the runbook (A6/T-12-12).
- **No new Artifact Registry repo:** the frontend image shares the `nestor` repo (`.../nestor/frontend:<tag>`), matching the plan's `<interfaces>` guidance.

## Deviations from Plan

None - plan executed exactly as written. Both verification blocks passed on the first run; no bugs, missing functionality, or blocking issues encountered.

## Issues Encountered
- The `12-RESEARCH.md` / `12-PATTERNS.md` / `12-CONTEXT.md` reference files were not present in the worktree (the `.planning/` directory is gitignored and only the PLAN files were force-added). Resolved by reading them from the main checkout (`C:\Users\ajimimo\Desktop\MOELD\nestor-intake-gcp\.planning\...`) — read-only, no edits there. The plan's own `<interfaces>` section had already captured the verified analog line numbers, so this was a convenience rather than a blocker.
- First Edit attempt targeted the shared-checkout path and was rejected by the worktree isolation guard; re-issued against the worktree copy. No content impact.

## Notes on Deferred Validation (dev-box constraints)
- Terraform is **not applied** — this is IaC-by-construction (D-07). `terraform init/plan/apply` cannot run on the dev box (provider downloads blocked), and no state was ever adopted, so the new frontend service block + invoker are the intended end-state only, inert until the Phase-12 gcloud steps run out-of-band. This matches the established Phase 5/7/8/9/10 drift pattern. HCL was authored by construction, mirroring the verified `google_cloud_run_v2_service.api` block; `terraform validate` was not run locally (no provider binaries).
- The runbook itself is documentation; its gcloud/Cloud Build/Console steps execute live in plan 12-05.

## Next Phase Readiness
- The IaC now honestly describes the new frontend service, and the runbook is a complete, correctly-ordered operational manual for the user-run Phase 12 deploy (plan 12-05).
- `frontend_service_url` output is ready to feed the second-pass wiring once the frontend is deployed.
- Blockers/concerns: none introduced by this plan. The pre-existing IaC-drift reconcile item (reconcile via `terraform import` or keep manual before cutover) now extends to the frontend service + invoker — logged in the runbook Summary checklist.

## Self-Check: PASSED

- All modified files present: `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/DEPLOY-RUNBOOK.md`, `12-04-SUMMARY.md`.
- All task commits present in git history: `d6e6d50` (Task 1), `3af6e78` (Task 2), `97f183d` (SUMMARY).
- Both plan verification blocks passed; working tree clean.

---
*Phase: 12-frontend-deploy-cutover-supabase-retirement*
*Completed: 2026-07-14*
