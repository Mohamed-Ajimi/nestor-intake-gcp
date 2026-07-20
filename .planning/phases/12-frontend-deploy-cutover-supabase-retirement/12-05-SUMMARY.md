---
phase: 12-frontend-deploy-cutover-supabase-retirement
plan: 05
subsystem: infra
tags: [cloud-run, cloud-build, firebase, cors, uat, cutover]

# Dependency graph
requires:
  - phase: 12-frontend-deploy-cutover-supabase-retirement (plans 01-04)
    provides: frontend container (Dockerfile + cloudbuild.yaml + D-11 bundle guard), sources-read/transcribe gap closure, IaC frontend service, Phase-12 DEPLOY-RUNBOOK
provides:
  - Live cutover executed — nestor-frontend on Cloud Run wired to nestor-api (CORS, APP_BASE_URL, bucket CORS, Firebase authorized domains)
  - Parity UAT executed across 4 operator rounds (2026-07-16); 8 defects found and fixed same-day
  - Operator parity decision recorded — PARITY ACCEPTED WITH DEFERRALS (2026-07-20); remaining items deferred to post-Tribunal
affects: [milestone-close, tribunal-milestone, deferred-uat]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - .planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md

key-decisions:
  - "Operator decision 2026-07-20: partial UAT accepted as sufficient — remaining unchecked 12-UAT items DEFERRED until after the Tribunal milestone; gate marked PARITY ACCEPTED WITH DEFERRALS, explicitly NOT full PARITY GREEN"
  - "Supabase retirement = independence-only (D-08): no Supabase-side action taken; legacy project untouched"

patterns-established: []

requirements-completed: [INFRA-05, QA-05]

# Metrics
duration: multi-session (2026-07-14 cutover → 2026-07-20 close)
completed: 2026-07-20
---

# Phase 12 Plan 05: Live Cutover + Parity Gate Summary

**Live cutover executed and iterated to frontend rev 00010-ndr / backend rev 00024-67b; parity gate closed by operator decision as ACCEPTED WITH DEFERRALS — remaining UAT items carried to post-Tribunal.**

## Performance

- **Duration:** multi-session (both tasks were human checkpoints run live by the operator)
- **Started:** 2026-07-14 (cutover deploy)
- **Completed:** 2026-07-20 (parity decision + close-out)
- **Tasks:** 2/2 (both human-gate checkpoints resolved)
- **Files modified:** 1 planning artifact (12-UAT.md, iteratively) + live GCP deploys (no repo code in this plan)

## Accomplishments

- **Task 1 — Live cutover (2026-07-14, plus follow-up revisions):** backend catch-up deployed (jinja2/httpx image, alembic 0010, RESEND_API_KEY seeded rev 00023, APP_BASE_URL + NESTOR_ADMIN_EMAIL set); frontend deployed as a Cloud Run container with the D-11 bundle guard green; FRONTEND_URL wired into backend CORS_ALLOWED_ORIGINS + APP_BASE_URL, uploads-bucket CORS, and Firebase authorized domains; SSR HTML confirmed at the run.app URL. No Supabase-side action taken (D-08); legacy deploy untouched (D-10).
- **Task 2 — Parity UAT (2026-07-15 → 2026-07-20):** pre-UAT UI consistency pass (canvas rounds fts+j7f), then operator UAT rounds 1-3 on 2026-07-16 surfaced 8 defects — all fixed and deployed same-day (frontend revs 00004→00009, backend rev 00024). Final pending fix `a710e8e` (client validation diff) deployed 2026-07-20 as frontend rev **00010-ndr** (image `frontend:20260716→20260720-102153`, Cloud Build 69381baa, smoke 200, no Supabase signature). Operator ran a further partial pass and recorded the closing decision.
- **Gate outcome:** `12-UAT.md` gate line reads **PARITY ACCEPTED WITH DEFERRALS (2026-07-20)** — 21 inherited items remain unchecked and are explicitly deferred until after the Tribunal milestone; they do not gate phase-12 closure. The scope ceiling held throughout: all runs stopped at `decomposed`; run-research/Tribunal was never reachable.

## Task Commits

Both tasks were human-action checkpoints; repo commits are the docs trail recording live outcomes:

1. **Task 1: cutover + wiring** — `fa50172`..`b3477cc` (docs(12-05): cutover gaps, mail gap resolved rev 00023)
2. **Task 2: UAT rounds + fixes + decision** — `2685d15`..`81347cf` (per-revision records), `c83fdaf` (session handoff), `7731421` (docs(12-05): rev 00010-ndr deploy + operator UAT-deferral decision)

Defect fixes themselves were committed via quick tasks / fast tasks tracked in STATE.md (260716-e59, 260716-i0j, 260716-ji9, 1d7732a, d2f335b, 4eb1c6e, acf1ba4, a710e8e).

## Files Created/Modified

- `.planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md` — live-environment record (revs 00001→00010 frontend, →00024 backend), session logs, gate decision block

## Decisions Made

- **PARITY ACCEPTED WITH DEFERRALS (operator, 2026-07-20):** partial UAT coverage accepted; every remaining unchecked item deferred to post-Tribunal. Rationale: all defects found in 3 UAT rounds were fixed and verified live; the deep-research (Tribunal) milestone will re-exercise most deferred surfaces anyway.
- Open product decisions logged (not blockers): Templates page visibility, Intake-info link-row trimming, "Verzonden mails" history block.

## Deviations from Plan

### 1. Parity gate closed by operator decision instead of full PARITY GREEN

- **Found during:** Task 2
- **Issue:** The plan's must_have "12-UAT fully green for BOTH roles" was not literally met — 21 items (AI enrichment verification, storage click-throughs, invite flow, i18n items, cross-space SSE 404, two-role E2E, Cloud Build suite rerun) remain unchecked.
- **Resolution:** Operator explicitly accepted current coverage and deferred the remainder to post-Tribunal (recorded in 12-UAT.md gate block + STATE.md). This is an authorized human-gate override, not silent scope reduction; the deferred list is preserved verbatim so nothing is lost.
- **Committed in:** `7731421`

**Total deviations:** 1 (operator gate override)
**Impact on plan:** Phase closes with a deferred-UAT ledger instead of a green gate; deferral tracked for the Tribunal milestone.

## Issues Encountered

- 8 live defects found during UAT rounds (space-switch staleness, nav i18n, decomposed filter, phase-machine enrichment-run bug, stuck SSE poll timer, silent review dead-end, validation-diff invisibility, mail UX) — all fixed and deployed same-day; details in 12-UAT.md rev block.
- Known gaps carried in 12-UAT.md: NDA PDF never dropped into the image (download 404s), backend suite not rerun after the ji9 backend change, Resend key rotation pending (post-UAT chore).

## User Setup Required

None beyond existing chores: rotate the Resend API key (add as version 2 of `nestor-resend-api-key`) and remove legacy `VITE_SUPABASE_*` from `frontend/.env`.

## Next Steps

- Milestone close; Tribunal (deep research) as the next milestone via `/gsd-new-milestone` — includes lifting the `decomposed` scope ceiling and revisiting the deferred UAT ledger.
