---
phase: 09-gcs-storage
plan: 01
subsystem: storage
tags: [gcs, keyless-signing, signed-url, object-keys, tdd-red, ci-guard]
requires:
  - phase: 07-ai-function-ports
    provides: "app/ai/clients.py factory-seam convention + fake_openai/fake_anthropic fixture shape + intake_sources table (0009)"
  - phase: 04-tenant-isolation
    provides: "cross-tenant denial-suite template (test_intake_cross_tenant.py) + engine-factory patch harness"
provides:
  - "app.storage.gcs — 4-function external-client seam (upload_object / signed_download_url / delete_object / download_bytes), ADC-only keyless V4 signing, TTL clamped to 900s"
  - "app.storage.keys — build_object_key ({space}/{intake}/{category}/{uuid}-{name}) + sanitize_filename + CATEGORIES + 16-ext ALLOWED_EXT"
  - "Settings.storage_bucket (env STORAGE_BUCKET, non-secret)"
  - "scripts/ci_no_sa_json_key.sh — criterion-1 SA-JSON-key grep-guard (exit-code gated)"
  - "fake_gcs conftest fixture + 4 Wave-0 RED test scaffolds that 09-02's storage router turns GREEN"
affects: [09-02, 09-03, 09-04]
tech-stack:
  added:
    - "google-cloud-storage>=3,<4 (official googleapis client — human-verified on PyPI at the blocking checkpoint)"
    - "python-multipart>=0.0.9 (Kludex distribution — NOT the deprecated bare `multipart`)"
  patterns:
    - "GCS seam mirrors app/ai/clients.py: call-time config read, module = monkeypatch target, HTTP-transport-only (no DB engines/sessions)"
    - "fake_gcs patches BOTH app.storage.gcs module attrs AND app.storage package re-exports (raising=False)"
key-files:
  created:
    - backend/app/storage/__init__.py
    - backend/app/storage/keys.py
    - backend/app/storage/gcs.py
    - backend/scripts/ci_no_sa_json_key.sh
    - backend/tests/test_storage_upload.py
    - backend/tests/test_storage_signed_url.py
    - backend/tests/test_storage_delete.py
    - backend/tests/test_storage_cross_tenant.py
  modified:
    - backend/pyproject.toml
    - backend/app/core/config.py
    - backend/tests/conftest.py
decisions:
  - "Keyless V4 signing via IAM signBlob (service_account_email + access_token kwargs) — no SA JSON key anywhere; Assumption A1 (exact kwargs) to be confirmed against the installed wheel in the Cloud Build run"
  - "TTL clamp is a pure helper (gcs._clamp_ttl) so D-10 is unit-testable without auth/network; route layer additionally advertises the clamped expires_in (09-02)"
  - "delete_object treats NotFound as success (idempotent, Pitfall 6)"
  - "All four storage test files carry pytest.mark.integration (they drive live-DB harnesses); the pure clamp test rides along in the signed-url file"
metrics:
  duration: "~15 min (post-checkpoint execution; checkpoint wait excluded)"
  completed: "2026-07-13"
---

# Phase 9 Plan 01: GCS Storage Foundation Summary

**One-liner:** Keyless-ADC GCS seam (`app.storage.gcs`, 4 monkeypatch targets) + server-authored object keys (`{space}/{intake}/{category}/{uuid}-{sanitized}`) + SA-JSON-key CI guard + fake_gcs fixture and four Wave-0 RED suites that pin the 09-02 storage-router contract.

## What Was Built

- **Task 1 (checkpoint-gated deps):** `google-cloud-storage>=3,<4` and `python-multipart>=0.0.9` pinned in `backend/pyproject.toml` after the human verified both distributions on PyPI (T-09-SC). No bare `multipart` entry; `google-auth` deliberately not pinned (transitive). **The live Cloud Run image does NOT contain these until the 09-04 runbook rebuild (Pitfall 7).**
- **Task 2 (the seam):**
  - `backend/app/storage/gcs.py` — `upload_object` / `signed_download_url` / `delete_object` / `download_bytes`. Bucket name read via `get_settings().storage_bucket` inside function bodies (never module top-level). Signing is keyless: `google.auth.default()` → refresh → `generate_signed_url(version="v4", service_account_email=..., access_token=..., response_disposition='attachment; ...')`. `_MAX_TTL_S = 900` (D-10), `_DEFAULT_TTL_S = 300`, `_clamp_ttl` pure helper. `delete_object` swallows `NotFound` (idempotent).
  - `backend/app/storage/keys.py` — `CATEGORIES` (attachments/audio/artifacts/reports), `ALLOWED_EXT` (16 D-04 extensions), `sanitize_filename` (1:1 port of `FinalReportBlock.tsx:sanitizeFilenameForStorage` + max_len cap + `"file"` fallback), `build_object_key` (ValueError on unknown category).
  - `backend/app/storage/__init__.py` — package re-exports of the 4 seam functions (transcribe-seam import path, mirrors `app/ai/skills/__init__.py`).
  - `backend/app/core/config.py` — `storage_bucket: str | None = None` (env `STORAGE_BUCKET`, non-secret; zero Secret Manager resources).
  - `backend/scripts/ci_no_sa_json_key.sh` — exit-code-gated guard banning `from_service_account_file` / `service_account.json` / `GOOGLE_APPLICATION_CREDENTIALS=.*json` under `backend/app/`, comment lines stripped; executable (100755); **negative test executed locally: a planted offender correctly fails the guard, clean tree exits 0.**
- **Task 3 (RED scaffolds):**
  - `fake_gcs` fixture in `backend/tests/conftest.py` — capture-only fakes for all four seam functions, patching both `app.storage.gcs.*` module attributes and the `app.storage` package re-exports; signed-url fake returns `https://signed.example/{key}` and records ttl/filename/disposition. Lazily imports `app.storage.gcs` (importorskip) so conftest stays collectable without google-cloud-storage.
  - `test_storage_upload.py` — `test_upload_writes_scoped_key` (DOC-02/D-05), `test_upload_413_over_cap` (D-02/D-03), `test_upload_415_bad_type` (D-04), `test_audio_upload_creates_source` (D-07).
  - `test_storage_signed_url.py` — `test_ttl_clamped_and_disposition` (DOC-01/D-10/T-09-04) + `test_seam_clamps_ttl_to_900` (pure T-09-03 unit proof).
  - `test_storage_delete.py` — `test_delete_cleans_ref` (D-09/T-09-09: object delete + intake_sources ref cleanup in one request).
  - `test_storage_cross_tenant.py` — clones the `test_intake_cross_tenant.py` template: EXACT 404 for upload/signed-url/delete cross-tenant, forged-key-prefix 404 on the user's OWN intake, null-space 403; `pytestmark = pytest.mark.integration`; every denial also asserts zero seam calls.

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | Package legitimacy checkpoint + pins | 43abc0f | chore |
| 2 | app/storage seam + config + grep-guard | 8b8f8f5 | feat |
| 3 | fake_gcs + 4 RED scaffolds | da3c085 | test (TDD RED) |

## TDD Gate Compliance

Plan tasks are the Wave-0 **RED half** of the phase cycle by design: the `test(09-01)` commit (da3c085) is the RED gate; the GREEN gate (`feat` turning these suites green) belongs to 09-02's storage router, exactly as the plan headers document. No test could be executed locally (no Python/Docker on the dev box — author-by-construction per project constraint); RED state and GREEN flip are verified in the Cloud Build suite run at wave merge.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Execution worktree destroyed between checkpoint and resume**
- **Found during:** Resume after the Task-1 blocking-human checkpoint
- **Issue:** The original worktree `agent-ace47b35dd87b5fe3` and its branch had been removed after the checkpoint return; the repo's only checkout was `master` (protected — committing there is forbidden for a worktree executor)
- **Fix:** Recreated the worktree at the original path on branch `worktree-agent-ace47b35dd87b5fe3` from the pinned base commit `f892616` and executed there
- **Files modified:** none (environment only)
- **Commit:** n/a

### Minor Additions (documented, not plan-contradicting)

- **`test_seam_clamps_ttl_to_900`** added to the signed-url suite: with the seam faked, the HTTP test can only pin the *advertised* `expires_in`; this pure unit test pins the REAL seam's clamp arithmetic (`_clamp_ttl`), closing the D-10 gap between 09-01 (seam clamps) and 09-02 (route passes `expires_in` through).
- **`pytestmark = pytest.mark.integration` on all four test files** (plan required it only for cross-tenant) — upload/signed-url/delete also drive the live-DB harness, so the mark keeps them skip-clean on DB-less boxes.
- **`fake_gcs` also patches the `app.storage` package-level re-exports** (`raising=False`) so a consumer binding either import style is intercepted.

## Known Stubs

None in production code. The four storage test files are intentionally RED (they exercise routes that 09-02 creates) — each file header states "RED until 09-02"; this is the planned Wave-0 state, not a stub.

## Verification

- `bash backend/scripts/ci_no_sa_json_key.sh` → exit 0 (clean tree); planted-offender negative test → exit 1 (guard works).
- `bash backend/scripts/ci_no_raw_db_access.sh` → exit 0 (the new storage package holds no raw DB symbols).
- All plan `<verify>` greps pass (build_object_key / signed_download_url / storage_bucket / `_MAX_TTL_S = 900` / fake_gcs / all named test functions / `app.storage.gcs` references).
- Deferred to Cloud Build (no Python on dev box): import-cleanliness of `app/storage/`, RED confirmation of the four suites, and Assumption A1 (keyless `generate_signed_url` kwargs vs the installed 3.x wheel).

## Follow-ups for Later Plans

- **09-02:** turn the four RED suites GREEN (storage router + DI + transcribe seam swap).
- **09-04 runbook:** Cloud Build image rebuild so the two new deps exist in the running image (Pitfall 7); wire `ci_no_sa_json_key.sh` into the CI gate alongside the existing guards; confirm Assumption A1 against the installed wheel; live signBlob round-trip in the D-13 combined UAT.

## Self-Check: PASSED

All 9 created files present; all 4 task/doc commits (43abc0f, 8b8f8f5, da3c085, docs) verified in git log; working tree clean.
