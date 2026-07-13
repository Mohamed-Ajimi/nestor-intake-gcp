---
phase: 08-sse-skill-run-progress
plan: 03
subsystem: infra
tags: [cloud-run, sse, timeout, iac-drift, deploy-runbook]
requires:
  - "google_cloud_run_v2_service.api (existing Cloud Run v2 service, infra/main.tf)"
provides:
  - "template.timeout = 900s on the api Cloud Run service (adopted-state source of truth for D-07)"
  - "DEPLOY-RUNBOOK Phase-8 step: image redeploy for the new stream/full-run endpoints + live gcloud --timeout=900 apply + console/live verification"
affects:
  - "The live nestor-api request-timeout window (once the documented out-of-band gcloud apply runs in the D-10 UAT)"
tech-stack:
  added: []
  patterns:
    - "Two-task IaC-drift split: (1) edit main.tf as the intended end-state, (2) document the manual gcloud apply — the .tf edit alone is inert because Terraform state was never adopted"
key-files:
  created: []
  modified:
    - "infra/main.tf — added template.timeout = \"900s\" (+ D-07 / IaC-drift comment) inside google_cloud_run_v2_service.api"
    - "infra/DEPLOY-RUNBOOK.md — added Phase-8 section (image redeploy, live 900s timeout apply, verification) + 3 checklist items"
decisions:
  - "D-07: 900s Cloud Run request timeout so SSE text/event-stream is not severed at the 300s default; paired with the app's 10-min MAX_STREAM_SECONDS cap (plan 08-01)"
  - "No live mutation in this plan — the gcloud --timeout=900 apply + image redeploy are deferred to the combined 7+8 UAT (D-10), documented not executed (dev box has no Terraform/gcloud apply path here)"
metrics:
  duration: "~2 min"
  completed: "2026-07-13"
  tasks: 2
  files: 2
---

# Phase 8 Plan 03: Cloud Run 900s Request Timeout (SSE) Summary

Raise the Cloud Run request timeout to 900s in `infra/main.tf` (D-07) and document the
out-of-band live `gcloud` apply + backend image redeploy in the deploy runbook — the infra
knob a long-lived `text/event-stream` SSE stream needs so it is not cut at the 300s Cloud Run
default, paired with the app's 10-min in-handler cap so a hung run cannot hold a connection
for the full 900s.

## What Was Built

**Task 1 — `infra/main.tf` (commit `95836d0`):** Added `timeout = "900s"` as a direct child
of the `template {` block of `google_cloud_run_v2_service.api` (sibling of `scaling`/
`service_account`, line 261), with a comment tying it to D-07 (default 300s severs the stream
at ~5 min), the pairing with the 10-min `MAX_STREAM_SECONDS` cap (plan 08-01), and the
IaC-drift caveat (edit is inert until applied by hand). No change to `scaling`,
`resources.cpu_idle`, or any env block. Brace balance unchanged (74/74).

**Task 2 — `infra/DEPLOY-RUNBOOK.md` (commit `918694c`):** Added a Phase-8 section documenting
the two manual steps that make SSE work on the LIVE `nestor-api` service, executed during the
combined 7+8 UAT (D-10), not during plan execution:
- **8.1** Rebuild the backend image via Cloud Build so the new
  `GET /intakes/{id}/skill-runs/stream` (SSE) + `GET /intakes/{id}/skill-runs/{run_id}`
  (terminal full-run) endpoints ship (reuses the Step-3 idiom).
- **8.2** Apply the request timeout live:
  `gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" --timeout=900`.
- **8.3** Verify: console **Request timeout** reads 900s AND streamed events arrive at a ~2s
  cadence (a steady trickle, not a terminal burst) and do not drop at ~300s.

The section states the IaC-drift caveat explicitly (editing `main.tf` alone does NOT change the
live service) and adds all three steps to the runbook's summary checklist.

## Verification Results

All acceptance-criteria greps passed (dev box — no Terraform, source assertions only):

| Gate | Expected | Actual |
|------|----------|--------|
| `grep -c 'timeout *= *"900s"' infra/main.tf` | == 1 | 1 |
| timeout inside the api service | within api resource (line 247) | line 261 ✓ |
| `main.tf` brace balance | unchanged | 74 open / 74 close ✓ |
| `git diff` main.tf | added lines only | 9 insertions, 0 deletions ✓ |
| `grep -c -- '--timeout=900' infra/DEPLOY-RUNBOOK.md` | >= 1 | 3 |
| `grep -c 'skill-runs/stream' infra/DEPLOY-RUNBOOK.md` | >= 1 | 2 |
| `grep -ci 'drift\|...' infra/DEPLOY-RUNBOOK.md` | >= 1 | 12 |
| `grep -ci 'phase 8\|phase-8\|sse' infra/DEPLOY-RUNBOOK.md` | >= 1 | 3 |
| `git diff` runbook | added lines only | 62 insertions, 0 deletions ✓ |

**Live (deferred to combined 7+8 UAT, D-10):** `gcloud run services describe nestor-api` should
show a 900s timeout; a live stream should deliver events at ~2s cadence and not drop at ~300s.
Not performed in this plan per the IaC-drift reality and the "leave the phase UAT-ready" rule.

## Deviations from Plan

None — plan executed exactly as written. No auto-fixes, no auth gates, no architectural
decisions required.

## Threat Model Compliance

- **T-08-12 (DoS, self-inflicted stream cut) — mitigate:** satisfied by the 900s timeout (D-07),
  paired with the app-side 10-min `MAX_STREAM_SECONDS` cap (plan 08-01).
- **T-08-13 (config drift) — mitigate:** satisfied by the runbook's out-of-band
  `--timeout=900` apply + console verification, with the drift caveat stated explicitly.
- **T-08-14 (long-lived connection pressure) — accept:** unchanged; `max_instance_count = 4`
  plus async-generator thread release (plan 08-01) keep worst-case concurrent streams bounded.

No new security-relevant surface introduced beyond the plan's threat model.

## Notes for Downstream

- The live 900s apply + image redeploy are the ONLY way this changes the running service. Until
  the D-10 UAT runbook steps run, the live `nestor-api` still severs SSE streams at 300s.
- This plan (08-03) is infra-only and independent of the backend (08-01) and frontend (08-02)
  work in the same wave; no shared files.

## Self-Check: PASSED

- FOUND: infra/main.tf (`timeout = "900s"` at line 261)
- FOUND: infra/DEPLOY-RUNBOOK.md (Phase-8 section + checklist items)
- FOUND: commit 95836d0 (feat 08-03 main.tf timeout)
- FOUND: commit 918694c (docs 08-03 runbook)
