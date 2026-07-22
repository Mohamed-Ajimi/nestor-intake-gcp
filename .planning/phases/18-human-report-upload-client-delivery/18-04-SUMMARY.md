---
phase: 18-human-report-upload-client-delivery
plan: 04
subsystem: infra
tags: [runbook, cloud-run, cloud-build, deploy, uat, report-delivery]

# Dependency graph
requires:
  - phase: 18-human-report-upload-client-delivery
    provides: 18-01 backend verbs, 18-02 admin delivery UI, 18-03 client report page (the surfaces this plan deploys)
provides:
  - "infra/DEPLOY-RUNBOOK.md § Phase 18 — nestor-api rebuild + frontend deploy, NO migrate, NO new secret"
  - "Phase 18 LIVE: nestor-api rev 00038-7jp + nestor-frontend rev 00018-m6x"
  - "18-HUMAN-UAT.md — live stage/deliver/download UAT record (REPORT-01/02/03)"

key-files:
  created:
    - .planning/phases/18-human-report-upload-client-delivery/18-HUMAN-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md
    - frontend/src/routes/intake.$id.tsx (UAT-cycle fix)
    - backend/tests/test_intake_cross_tenant.py (wave-1 gate fix)

status: complete
completed: 2026-07-22
---

# 18-04 Summary — Deploy runbook + operator live delivery UAT

## What shipped

**Task 1 (commit `7130771`):** `infra/DEPLOY-RUNBOOK.md § Phase 18` — Steps 18.a–18.e
(nestor-api Cloud Build rebuild + repoint, suite run, frontend rebuild + deploy, mail-env
confirm-only, live UAT script + failure triage). Explicit NO-migrate / NO-new-secret notes;
Tribunal images untouched.

**Task 2 (checkpoint:human-action) — resolved 2026-07-22:** The live session was executed from
the dev box (operator authorized "DO IT"; gcloud available locally, so Cloud Shell was not
needed):

- 18.a `backend:20260722-184319` → **nestor-api-00038-7jp** (build ae8d3fb4). Smoke: all three
  verbs return 401 auth-wall (not 404).
- 18.b Cloud Build suite build `b0365150`: ALL Phase-18 tests green; only the 4 known
  pre-existing mail test-harness defects fail (deferred Phase 20 CLOSE-02).
- 18.c `frontend:20260722-184435` → nestor-frontend-00017-gfr, superseded during the UAT cycle
  by `frontend:20260722-192344` → **nestor-frontend-00018-m6x** (Outlet fix below).
- 18.d mail env confirmed present (APP_BASE_URL / NESTOR_ADMIN_EMAIL / RESEND_API_KEY);
  Resend key NOT rotated (Phase-20 chore).

## Live UAT (intake e08620c5-2ccf-4006-8bce-ae45f47f8c88)

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Stage → pre-delivery invisibility (REPORT-02) | ✅ PASS | staged upload 201 @17:15:11Z, status stayed in_research; client saw nothing pre-delivery |
| 2 | Deliver + mail (REPORT-01/03) | ✅ PASS | POST /deliver 200 @17:15:19Z; operator received the delivery mail; CTA deep-links /intake/{id}/report |
| 3 | Client sees + downloads report (REPORT-02) | ✅ PASS | client GET /report 200 + signed-url 200 @17:27Z; PDF downloaded |
| 4 | Replace silent + re-notify (D-04/D-05) | ☑ ACCEPTED (operator decision) | Operator reported both paths worked in the UI; backend logs show no /report/replace call, so no server-side confirmation. Replace verb behavior IS covered green in Cloud Build (`test_report_delivery.py` replace cases). Operator chose to close ("just mark it as done"). |

## UAT-cycle fixes (2 commits during the live session)

1. `7dbc50c` — fix(18-01): `_cleanup_spaces` missing arg in the new pre-delivery-404 test
   (crashed in `finally` AFTER the REPORT-02 assertion passed). Wave-1 Cloud Build gate.
2. `285f050` — fix(18-03): `intake.$id.tsx` parent route rendered no `<Outlet/>`, so the
   child routes `/intake/$id/report` AND `/intake/$id/results` could never render (router
   silently showed the parent fill form). Found live: client "View report" showed nothing;
   API logs showed getIntake+listAnswers but never GET /report. Fixed with a
   `UserIntakeRouteShell` that renders `<Outlet/>` when a child matches. This also repairs the
   same latent bug on the pre-existing results child route. Deployed as nestor-frontend-00018-m6x.

## Deviations

- Checkpoint executed by the Claude session from the dev box instead of operator-in-Cloud-Shell
  (operator authorized; identical commands). Browser/mail checks remained operator-performed.
- UAT item 4 closed on operator acceptance without server-side log evidence (see table).

## Self-Check: PASSED

- Runbook § Phase 18 present with rebuild commands + no-migrate/no-secret notes ✅
- Both images rebuilt + deployed; smoke checks green ✅
- 18-HUMAN-UAT.md recorded ✅
