---
phase: 09-gcs-storage
plan: 04
subsystem: infra
tags: [gcs, iam, signblob, keyless, terraform, gcloud-runbook, iac-drift, uat]
requires:
  - phase: 09-gcs-storage
    plan: 01
    provides: "app.storage.gcs seam (keyless ADC V4 signing, TTL clamp 900s), Settings.storage_bucket (env STORAGE_BUCKET), ci_no_sa_json_key.sh guard, google-cloud-storage + python-multipart pins (NOT in the live v12 image)"
provides:
  - "infra/main.tf: google_storage_bucket.uploads (private, uniform BLA + public-access-prevention enforced, no versioning/lifecycle, force_destroy=false)"
  - "infra/main.tf: google_storage_bucket_iam_member.runtime_object_admin (bucket-scoped storage.objectAdmin)"
  - "infra/main.tf: google_service_account_iam_member.runtime_token_creator_self (serviceAccountTokenCreator self-binding — keyless signBlob)"
  - "infra/main.tf: STORAGE_BUCKET env on the Cloud Run service (non-secret)"
  - "infra/DEPLOY-RUNBOOK.md: Phase-9 gcloud runbook (Steps 9.1-9.5) + combined 7+8+9 UAT (D-13) + checklist rows"
affects: []
tech-stack:
  added: []
  patterns:
    - "Dual-authoring (D-11): the same provisioning is expressed in BOTH main.tf (intended end-state, inert) AND the gcloud runbook (the applied path), because Terraform state was never adopted"
    - "Keyless signBlob = TWO distinct grants (Pitfall 2): bucket-scoped storage.objectAdmin for object access + serviceAccountTokenCreator self-binding for URL signing"
key-files:
  created:
    - .planning/phases/09-gcs-storage/09-04-SUMMARY.md
  modified:
    - infra/main.tf
    - infra/DEPLOY-RUNBOOK.md
decisions:
  - "storage.objectAdmin scoped to THIS bucket only (google_storage_bucket_iam_member), never a project-wide roles/storage.* grant (T-09-15 least privilege)"
  - "public_access_prevention = enforced + uniform_bucket_level_access = true (D-07a): zero public objects, IAM-only access surface (T-09-14)"
  - "NO versioning block and NO lifecycle rules on the bucket (D-12): out of scope this phase"
  - "STORAGE_BUCKET is a plain non-secret env (D-09), mirrors INSTANCE_CONNECTION_NAME — no Secret Manager reference"
  - "Both IAM bindings added to the service depends_on so they exist before boot (implicit edge only covers the STORAGE_BUCKET env → bucket, not the two grants)"
  - "The Step-9.4 image rebuild MUST also ship the Phase-8 stream route — live Cloud Run is still v12, so 8+9 land in one image/one deploy (D-13)"
metrics:
  duration: "~12 min"
  completed: "2026-07-13"
---

# Phase 9 Plan 04: GCS bucket + keyless-signBlob IAM provisioning (infra) Summary

**One-liner:** Dual-authored (D-11) the private hardened GCS uploads bucket, its bucket-scoped `storage.objectAdmin` binding, the `serviceAccountTokenCreator` self-binding that makes keyless signBlob possible (criterion 1), and the `STORAGE_BUCKET` env — in BOTH `infra/main.tf` (inert end-state) and the `infra/DEPLOY-RUNBOOK.md` Phase-9 gcloud steps (the applied path) — plus the combined 7+8+9 live UAT (D-13). The live apply + UAT is a human-action checkpoint (Task 3).

## What Was Built

- **Task 1 — `infra/main.tf` (inert, drift-noted):**
  - `google_storage_bucket.uploads` — name `"${var.project}-nestor-uploads"`, location `var.region`, `uniform_bucket_level_access = true`, `public_access_prevention = "enforced"` (D-07a), NO versioning block, NO lifecycle rules (D-12), `force_destroy = false`.
  - `google_storage_bucket_iam_member.runtime_object_admin` — `roles/storage.objectAdmin`, bucket-scoped to the uploads bucket only (T-09-15 least privilege), member = the runtime SA.
  - `google_service_account_iam_member.runtime_token_creator_self` — `roles/iam.serviceAccountTokenCreator` on the runtime SA, member = the SA itself: the keyless-signBlob grant (criterion 1 / T-09-13), a SEPARATE grant from object access (Pitfall 2).
  - A `STORAGE_BUCKET` env on the Cloud Run service `containers.env`, value = `google_storage_bucket.uploads.name`, placed with the other non-secret connector config (mirrors `INSTANCE_CONNECTION_NAME`).
  - Both IAM bindings added to the service `depends_on` (the STORAGE_BUCKET env only creates an implicit edge to the bucket, not to the grants).
  - A drift-note comment marking every one of these resources INERT-until-applied per the STATE.md IaC-drift blocker (D-11).
- **Task 2 — `infra/DEPLOY-RUNBOOK.md` Phase-9 section:**
  - Env preamble (`GOOGLE_PROJECT`, `REGION`, `RUNTIME_SA=nestor-run@…`, `BUCKET=${GOOGLE_PROJECT}-nestor-uploads`).
  - **Step 9.1** `gcloud storage buckets create` (uniform BLA + public-access-prevention; D-12/D-07a).
  - **Step 9.2** `gcloud storage buckets add-iam-policy-binding` for `roles/storage.objectAdmin` (bucket-scoped).
  - **Step 9.3** `gcloud iam service-accounts add-iam-policy-binding` for `roles/iam.serviceAccountTokenCreator` (keyless signBlob; the separate grant, Pitfall 2).
  - **Step 9.4** Cloud Build image rebuild (new deps `google-cloud-storage` + `python-multipart` AND the Phase-8 stream route — Pitfall 7; live is still v12) + `gcloud run services update … --image … --update-env-vars=STORAGE_BUCKET=…`.
  - **Step 9.5** the COMBINED 7+8+9 live UAT (D-13): one deploy/one session — upload attachment + audio → transcribe → structure-answers/extract-insights → apply-intake-skill over SSE → signed-URL artifact download — closing the deferred Phase-7 UAT and the Phase-8 UAT together, with failure triage (signBlob 403 → Pitfall 2, upload 422 → Pitfall 3, 500 ModuleNotFoundError → Pitfall 7).
  - Summary-checklist rows 9.1–9.5 + the IaC-drift preamble/note extended to cover the storage resources (D-11).

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | Bucket + 2 IAM bindings + STORAGE_BUCKET env in main.tf (inert) | c9053e7 | feat |
| 2 | Phase-9 runbook section + combined-UAT + checklist rows | d71def6 | docs |
| 3 | Live apply + combined 7+8+9 UAT | — | checkpoint:human-action (returned, not executed) |

## Deviations from Plan

None — the plan executed exactly as written for the two authoring tasks. The `read_first` RESEARCH/CONTEXT docs (`09-RESEARCH.md`, `09-CONTEXT.md`) are not present at this worktree's base commit, but the PLAN's `<interfaces>` block specified the exact resource shapes, bucket name, IAM roles, member shape, and gcloud command forms — so the authoring proceeded by construction against `main.tf`/`variables.tf` (both present and read), with no guesswork. `var.project` and `var.region` confirmed in `variables.tf`.

### Minor Additions (documented, not plan-contradicting)

- **Both IAM bindings added to the Cloud Run service `depends_on`.** The plan specified the four resources + env; the ordering edge for the two grants is not implied by the `STORAGE_BUCKET` env reference (which only edges to the bucket). Declaring them explicitly mirrors the existing secret-grant `depends_on` pattern (main.tf:356-361) and prevents a first-request 403 on a cold service boot.

## Known Stubs

None. Both files are complete authored end-state. The `infra/main.tf` resources are consciously **inert until applied out-of-band** (IaC-drift D-11) — this is the documented, intended state (the runbook is the applied path), not a stub.

## Threat Flags

None new. The plan's `<threat_model>` (T-09-13 keyless signBlob, T-09-14 public exposure, T-09-15 over-broad role, T-09-16 IaC drift) covers the entire surface this plan introduces; all four dispositions are honored by construction (self-binding as the only signing grant, enforced public-access-prevention, bucket-scoped objectAdmin, and the consciously-accepted drift documented in the runbook + this SUMMARY).

## Verification

- `grep 'google_storage_bucket" "uploads"' infra/main.tf` ✓; `roles/storage.objectAdmin` ✓; `roles/iam.serviceAccountTokenCreator` ✓; `public_access_prevention.*enforced` ✓; `STORAGE_BUCKET` ✓ (Task-1 automated verify passed).
- `grep 'Phase 9' infra/DEPLOY-RUNBOOK.md` ✓; `gcloud storage buckets create` ✓; `roles/iam.serviceAccountTokenCreator` ✓; `STORAGE_BUCKET` ✓; `combined` ✓ (Task-2 automated verify passed).
- Terraform NOT run (CLI unavailable + downloads blocked on the dev box); the `.tf` is authored by construction and is inert until the runbook gcloud apply — validated by grep, not `terraform validate`.
- Task 3 (live apply + combined 7+8+9 UAT) is a human-action checkpoint — deferred to the operator with GCP credentials.

## Follow-ups for Later Plans

- **Task 3 / operator:** run runbook Steps 9.1–9.4 live (bucket, both bindings, image rebuild with the two new deps AND the Phase-8 stream route, STORAGE_BUCKET env), then the combined 7+8+9 UAT (Step 9.5). Report the round-trip result (upload/transcribe/SSE/signed-URL TTL+disposition, no SA JSON key).
- **Phase 12 cutover:** reconcile the IaC drift (`terraform import`) for these storage resources — the runbook + SUMMARY both flag this as a Phase-12 gate.

## Self-Check: PASSED

- Created file present: `.planning/phases/09-gcs-storage/09-04-SUMMARY.md` (this file).
- Modified files present + committed: `infra/main.tf` (c9053e7), `infra/DEPLOY-RUNBOOK.md` (d71def6).
- Both task commits verified in git log; working tree clean except this SUMMARY (committed next).
