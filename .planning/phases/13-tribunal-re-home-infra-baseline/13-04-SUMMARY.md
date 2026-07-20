---
phase: 13-tribunal-re-home-infra-baseline
plan: "04"
subsystem: infra
tags: [tribunal, cloud-run, alembic, audit-chain, concurrency, live-session]
requires: [13-01, 13-02, 13-03]
provides:
  - Live tribunal-api + tribunal-worker on Cloud Run (tag 20260720-161029-fix1)
  - tribunal schema migrated (tribunal_alembic_version=0010, zero public leak)
  - verify_chain green on re-homed deployment (ENGINE-04 legal gate)
  - ENGINE-02 duration/cost baseline (1020s pipeline, ~$1.5-2.1 per run)
  - ENGINE-08 concurrency proof (2 simultaneous runs, distinct tenants, both chains OK)
affects: [phase-16-stale-calibration, phase-14-seam, teardown-chore]
key-files:
  created:
    - .planning/phases/13-tribunal-re-home-infra-baseline/13-PROOF-RESULTS.md
  modified:
    - tribunal/nestor_pulse_sdk/db/base.py
    - tribunal/nestor_pulse_sdk/alembic/env.py
    - tribunal/cloudbuild.test.yaml
key-decisions:
  - "Single-project reality: project-cb01b861-cb4a-438d-b9a IS Nestor Pulse and hosts both old and new builds; teardown is resource-level only, never project deletion"
  - "Provider secrets already existed in-project (Nestor_*); no reseeding needed (D-06 trivially satisfied)"
  - "Operator deferred the D-02 teardown (Not now) — carried as a chore; phase criteria do not depend on it"
duration: ~3h live session (operator-delegated to agent)
completed: 2026-07-20
---

# Plan 13-04 Summary — Live deploy + proof runs

**All three operator gates green; teardown deferred by operator choice.** The user
delegated the live session ("u do it"); every step ran under explicit confirmation for
IAM/destructive actions.

## Task 1 — Deploy (GREEN)

Secrets bound/seeded (6), audit bucket created (7y Unlocked per-object retention),
`app_user`/`worker_user` created on `nestor-pg`, both images built via Cloud Build
(first-build legitimacy gate clean), `tribunal-migrate` job green, both services live:
`tribunal-api-20260720-161029-fix1-164103`, `tribunal-worker-20260720-161029-fix1-163954`.
`/health` + `/readyz` 200; worker polling, zero warnings.

## Task 2 — Suite + E2E proof (GREEN)

- Critical-subset Cloud Build gate green: 24 tests (schema isolation incl. live
  upgrade-head, advisory-lock exactly-once under racing executors, hash-chain replay
  10/10, RLS isolation).
- LUKOIL benchmark run `1315ea6a`: 115 claims / 112 grounded / 97.4% recall / $1.9696 /
  **verify_chain OK** / 1020s pipeline. Quality + coverage gates PASS.

## Task 3 — Concurrency proof (GREEN); teardown DEFERRED

Two fully-overlapped runs from distinct self-provisioned tenants (`5b0b574f…`,
`260563e6…`), both `chain=OK`, no interference. Teardown of the old build offered
post-proof and declined ("Not now") — recorded as carried chore in 13-PROOF-RESULTS.md.

## Deviations (live-session fixes, all committed)

1. `fix(13-02)` db/base.py — runtime engine `search_path=tribunal,public` (runtime was
   schema-blind; would have 404'd every table lookup at boot).
2. `fix(13-02)` env.py — commit the autobegun preamble transaction (first migration run
   logged 0001→0010 then silently rolled back on connection close).
3. `fix(13-02)` env.py — loop-aware alembic runner (programmatic invocation from async
   tests).
4. `fix(13-03)` cloudbuild.test.yaml — host-network docker step (Cloud Build reserves the
   socket volume path; sibling-container published ports unreachable from plain steps).
5. Migrate job invocation: jobs need `--set-cloudsql-instances` and
   `sh -c "cd /app/nestor_pulse_sdk && alembic upgrade head"` (cwd-relative
   script_location).

## Known deferrals

- Full Tribunal suite triage (key-dependent tests fail in keyless build env; config
  mechanism fixed, timeout 3600s).
- D-02 teardown of old-build resources (+ decision on `nestor-pulse-pdf-extractor`).
- Engine-quality warnings observed in proof runs (group-skeptic parse errors, malformed
  FOCUS_AREA retry) — candidates for Phase 15 while the pipeline is being enhanced.

## Self-Check: PASSED

- Both services live and healthy (checked via gcloud + curl this session)
- verify_chain OK on 3 real runs (1 solo + 2 concurrent)
- Duration + cost recorded for Phase 16 calibration
- All working-tree changes committed
