---
phase: 10-notifications
plan: 02
subsystem: infra
tags: [terraform, secret-manager, cloud-run, resend, iac-drift, jinja2]

# Dependency graph
requires:
  - phase: 07-ai-seam
    provides: "anthropic_api_key secret/version/iam + secret_key_ref env pattern that this plan copies verbatim for RESEND_API_KEY"
  - phase: 09-gcs-storage
    provides: "STORAGE_BUCKET plain non-secret env pattern + the IaC-drift-honest runbook convention this plan extends"
provides:
  - "RESEND_API_KEY Secret Manager secret + count-guarded version + resource-scoped secretAccessor grant to the runtime SA (Terraform)"
  - "RESEND_API_KEY Cloud Run secret_key_ref env (version latest)"
  - "NESTOR_ADMIN_EMAIL + APP_BASE_URL plain non-secret Cloud Run env vars"
  - "DEPLOY-RUNBOOK Phase-10 section: secret version, env vars, jinja2 image rebuild, five-mail UAT gate"
affects: [10-01-mail-module, 10-03-endpoints, 10-04, 12-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verbatim block-copy of the anthropic_api_key secret trio for a new provider credential (RESEND_API_KEY)"
    - "IaC-drift-honest secret: resource + scoped grant in Terraform, VALUE seeded out-of-band per runbook (count-0 default)"

key-files:
  created: []
  modified:
    - infra/main.tf
    - infra/variables.tf
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "RESEND_API_KEY seeded out-of-band (count-0 default version) — the key never enters committed IaC/state (T-10-04)"
  - "secretAccessor grant is resource-scoped to the single resend secret for the runtime SA only (T-10-05 accept — mirrors anthropic)"
  - "NESTOR_ADMIN_EMAIL + APP_BASE_URL are plain non-secret Cloud Run env vars (D-08/D-15), default \"\", IaC-drift-inert until the runbook --update-env-vars step"

patterns-established:
  - "New provider secret = verbatim structural copy of the anthropic_api_key secret/version/iam trio + a depends_on edge on the grant"
  - "jinja2 (like anthropic/openai/google-cloud-storage before it) is only present after a Cloud Build image rebuild — documented as the recurring deploy-gap (Pitfall 2)"

requirements-completed: [NOTIF-02]

# Metrics
duration: 12min
completed: 2026-07-13
---

# Phase 10 Plan 02: Resend Mail Infra + Deploy Runbook Summary

**Declared the RESEND_API_KEY Secret Manager secret + resource-scoped secretAccessor + Cloud Run secret_key_ref env in Terraform (mirroring the anthropic_api_key pattern), plus the NESTOR_ADMIN_EMAIL / APP_BASE_URL non-secret env vars, and a drift-honest DEPLOY-RUNBOOK Phase-10 section covering the out-of-band secret version, the two env vars, the jinja2 image rebuild, and the five-mail UAT gate.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-13T23:11Z (approx)
- **Completed:** 2026-07-13
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

### Task 1 — RESEND_API_KEY secret + IAM + env, and the two non-secret env vars (commit 4042099)

- `infra/main.tf`: added `google_secret_manager_secret.resend_api_key` (auto replication), a count-guarded `google_secret_manager_secret_version.resend_api_key` (`count = var.resend_api_key == "" ? 0 : 1`, drift-honest default 0), and `google_secret_manager_secret_iam_member.runtime_resend_secret_accessor` scoped to the runtime SA — a verbatim structural copy of the anthropic_api_key trio.
- Cloud Run container env: added `RESEND_API_KEY` via `value_source.secret_key_ref` (version `"latest"`), and two PLAIN env vars beside `STORAGE_BUCKET` — `NESTOR_ADMIN_EMAIL` (from `var.nestor_admin_email`) and `APP_BASE_URL` (from `var.app_base_url`), each with a STORAGE_BUCKET-style drift comment.
- Added `runtime_resend_secret_accessor` to the service `depends_on` so the grant exists before boot (mirrors the anthropic/openai edges).
- `infra/variables.tf`: declared `resend_api_key_secret_id` (default `"nestor-resend-api-key"`), `resend_api_key` (sensitive, default `""`), `nestor_admin_email` (default `""`), and `app_base_url` (default `""`).

### Task 2 — DEPLOY-RUNBOOK Phase-10 deploy step (commit e4a6701)

- Added a Phase-10 section (`infra/DEPLOY-RUNBOOK.md`) with Steps 10.1–10.5: (10.1) create the `nestor-resend-api-key` secret + resource-scoped secretAccessor + add the key VALUE out-of-band via `gcloud secrets versions add … --data-file=-`; (10.2) set `NESTOR_ADMIN_EMAIL` + `APP_BASE_URL` via `--update-env-vars`; (10.3) map `RESEND_API_KEY=nestor-resend-api-key:latest` via `--update-secrets`; (10.4) REBUILD the backend image via Cloud Build so `jinja2` reaches the container (calls out RESEARCH Pitfall 2 — green CI but a 500 `ModuleNotFoundError: jinja2` in UAT if skipped); (10.5) five-mail UAT gate (invite, validation, results, reminder, admin_validated).
- Added five Phase-10 items + updated the drift-reconcile line in the Summary checklist.

## Deviations from Plan

None — plan executed exactly as written. The plan's referenced context files (10-CONTEXT.md, 10-PATTERNS.md) do not exist on disk, but the plan's inline `<interfaces>` block and the actual anthropic_api_key blocks in `infra/main.tf` / `infra/variables.tf` provided the exact block-copy source needed, so no functionality was affected.

## Verification

Task 1 automated grep (all pass):
- `google_secret_manager_secret[."]resend_api_key`, `runtime_resend_secret_accessor`, `RESEND_API_KEY`, `NESTOR_ADMIN_EMAIL`, `APP_BASE_URL` present in `infra/main.tf`
- `resend_api_key` present in `infra/variables.tf`
- No plaintext Resend key (`re_[A-Za-z0-9]{8,}`) anywhere in `infra/`

Task 2 automated grep (all pass):
- `RESEND_API_KEY`, `NESTOR_ADMIN_EMAIL`, `APP_BASE_URL`, `jinja2` present in `infra/DEPLOY-RUNBOOK.md`
- No plaintext key committed

Full `terraform validate` intentionally deferred to the deploy runbook / CI — no local Terraform on the dev machine (Terraform downloads blocked; environment note).

## Known Stubs

None. This is IaC authoring + runbook only; no application code stubs introduced. The count-0 secret version default is intentional and drift-honest (real value added out-of-band per the runbook, T-10-04), documented in both Terraform and the runbook — not a stub.

## Threat Flags

None. The only new surface (Secret Manager → Cloud Run RESEND_API_KEY injection) is already covered by the plan's threat_model (T-10-04 mitigate via out-of-band seed; T-10-05 accept via resource-scoped grant), and both dispositions are implemented as specified.

## Notes for Downstream Plans

- Plan 01 (mail module) and Plan 03 (endpoints) are inert **live** until Steps 10.1–10.4 run against the deployed service; the infra is authored but IaC-drift-inert (Phase 8 D-07), reconciled at Phase 12.
- The mail module must read `RESEND_API_KEY` / `NESTOR_ADMIN_EMAIL` (`Settings.nestor_admin_email`) / `APP_BASE_URL` (`Settings.app_base_url`) from process env at call time — matching the env var names declared here.

## Self-Check: PASSED

- FOUND: infra/main.tf (RESEND_API_KEY secret + iam + env)
- FOUND: infra/variables.tf (resend_api_key vars)
- FOUND: infra/DEPLOY-RUNBOOK.md (Phase-10 section)
- FOUND: .planning/phases/10-notifications/10-02-SUMMARY.md
- FOUND commit 4042099 (Task 1 — Terraform)
- FOUND commit e4a6701 (Task 2 — runbook)
