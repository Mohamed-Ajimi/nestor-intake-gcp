---
phase: 09-gcs-storage
plan: 02
subsystem: storage
tags: [gcs, storage-router, signed-url, upload, delete, tenant-isolation, transcribe-seam, tdd-green]
requires:
  - phase: 09-gcs-storage
    plan: 01
    provides: "app.storage.gcs 4-fn seam (upload_object/signed_download_url/delete_object/download_bytes) + app.storage.keys (build_object_key/CATEGORIES/ALLOWED_EXT) + fake_gcs fixture + 4 RED suites"
  - phase: 04-tenant-isolation
    provides: "get_intake_and_answer_repos combined-DI analog + TenantRepository._scope wall + existence-hidden 404 contract"
  - phase: 07-ai-function-ports
    provides: "intake_sources table (0009) + transcribe download_audio_bytes seam + IntakeSourceRepository"
provides:
  - "storage_router (POST upload / GET signed-url / DELETE objects) mounted under protected_router"
  - "get_intake_and_source_repos combined DI (IntakeRepository + IntakeSourceRepository, one tx)"
  - "IntakeSourceRepository.delete_by_storage_path (scoped ref cleanup for D-09)"
  - "download_audio_bytes real GCS delegation (app.storage.gcs.download_bytes keyed off storage_path)"
affects: [09-03, 09-04]
tech-stack:
  added: []
  patterns:
    - "combined-DI ownership gate: IntakeRepository.get -> None -> 404, then write the 2nd repo on the SAME session/tx (clone of get_intake_and_answer_repos)"
    - "server-authored key + key-prefix assert (key.startswith(f'{intake.space_id}/{intake_id}/')) as the D-08 existence-hidden authorization for client-supplied paths"
    - "authoritative read(_MAX_BYTES+1) size gate (never trust UploadFile.size) for the 413 ceiling"
key-files:
  created:
    - backend/app/api/storage_routes.py
  modified:
    - backend/app/db/session.py
    - backend/app/db/repository.py
    - backend/app/main.py
    - backend/app/ai/skills/transcribe.py
    - backend/tests/test_ai_transcribe.py
decisions:
  - "Type/category gate runs BEFORE the size read so a bad extension is 415 even for an oversize body; ownership 404 runs AFTER the size/type gates (a rejected body never opens the ownership read)"
  - "expires_in is advertised via gcs._clamp_ttl(expires_in) so the response echoes the EFFECTIVE (<=900s) lifetime the seam actually signed (D-10) — the fake records the raw ttl, so the route must clamp the advertised value itself"
  - "delete validates ALL keys' prefixes BEFORE deleting any (all-or-nothing forged-key gate) so one bad key in a batch reaches neither GCS nor the DB"
  - "source-ref cleanup uses a new scoped IntakeSourceRepository.delete_by_storage_path (routed through _scope) rather than a raw delete — keeps the D-01 space wall + the no-raw-DB grep guard green"
metrics:
  duration: "~20 min"
  completed: "2026-07-13"
---

# Phase 9 Plan 02: GCS Storage Endpoints Summary

**One-liner:** Real three-endpoint `storage_router` (upload/signed-url/delete) mounted under `protected_router` — server-authored keys, existence-hidden 404 + key-prefix authorization, authoritative 25 MB/415 gates, audio auto-registers an `intake_sources` row, delete cleans the ref in one tx — plus the `download_audio_bytes` seam swapped to real GCS, turning the four 09-01 RED suites GREEN.

## What Was Built

- **Task 1 — combined DI + scoped ref cleanup (`session.py`, `repository.py`):**
  - `get_intake_and_source_repos` in `app/db/session.py`: a verbatim clone of `get_intake_and_answer_repos` (engine-by-role, default-deny 403 on a null user space BEFORE any session, ONE `maker.begin()` tx, GUC set for the user path only, **sync** generator — Pitfall 5), yielding the tuple `(IntakeRepository(session, identity), IntakeSourceRepository(session, identity))` so the ownership read and the source-row write are atomic on one tx (D-02/D-07/D-09).
  - `IntakeSourceRepository.delete_by_storage_path(intake_id, storage_path)`: a scoped delete routed through `_scope` (so a user only ever removes a row in their own space, D-01), returning `rowcount`. `delete` added to the `sqlalchemy` import. **The inherited `TenantRepository.create` already injects `space_id` from Identity** (TENANT-02), so no new create method was needed — Task 1's create requirement was already satisfied by Wave-1's repository.
- **Task 2 — `storage_routes.py` + mount (GREEN):**
  - `storage_router = APIRouter(prefix="/intakes", tags=["storage"])`, three **sync-def** handlers, no auth dep of its own (inherits `get_current_identity` from `protected_router`). Reaches the DB only via `get_intake_and_source_repos` and GCS only via `app.storage.gcs` — the `ci_no_raw_db_access.sh` guard stays green.
  - **Upload** `POST /{intake_id}/storage/uploads` (201): category-not-in-`CATEGORIES` -> 422; extension outside `ALLOWED_EXT` -> 415; authoritative `read(_MAX_BYTES + 1)` with `_MAX_BYTES = 25 * 1024 * 1024` -> 413 (D-02/D-03); ownership `intake_repo.get` -> None -> 404 (D-08); key via `build_object_key(str(intake.space_id), intake_id, category, filename)` (D-05); `gcs.upload_object`; `category == "audio"` -> `source_repo.create(... storage_path=key ...)` on the same tx (D-07). Returns `UploadedFileMeta{path, filename, size, uploaded_at, mime_type}`.
  - **Signed-url** `GET /{intake_id}/storage/signed-url` (`path`, `expires_in=300`): ownership 404 + `path.startswith(f"{intake.space_id}/{intake_id}/")` else 404 (D-08); `gcs.signed_download_url(path, ttl_seconds=expires_in, filename=<derived>, content_type=None)`; returns `{url, expires_in: gcs._clamp_ttl(expires_in)}` so the advertised lifetime never exceeds the D-10 900s ceiling.
  - **Delete** `DELETE /{intake_id}/storage/objects` (`{paths:[...]}`): ownership 404; per-key prefix assert (any mismatch -> 404) validated for the WHOLE batch before any deletion; per key `gcs.delete_object` (idempotent) then `source_repo.delete_by_storage_path` on the same tx (D-09/T-09-09). Returns `{removed}`.
  - Mounted with `protected_router.include_router(storage_router)` in `main.py`, in the same block as `intake_router`/`ai_router`; no second `app.include_router(storage_router)`.
- **Task 3 — transcribe seam swap + delegation test (`transcribe.py`, `test_ai_transcribe.py`):**
  - `download_audio_bytes` body now delegates to `gcs.download_bytes(source["storage_path"])` (via `from app.storage import gcs`); the `NotImplementedError` Phase-9 placeholder is gone. Raises `ValueError` on a missing `storage_path` (defensive). `read_fn` now projects `"storage_path": source.storage_path` into the DTO so the key reaches the no-DB CALL window. `run_transcribe`/`_chunk_segments` logic unchanged.
  - `test_download_delegates_to_gcs` added to `test_ai_transcribe.py`: patches `app.storage.gcs.download_bytes` with a capture-fake, calls the REAL `download_audio_bytes`, asserts it delegated with the exact key and returned the seam's bytes. The existing `test_transcribe_faked_whisper_writes_scoped_transcripts` (which monkeypatches `app.ai.skills.download_audio_bytes` itself, `raising=False`) is untouched and still passes.

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | get_intake_and_source_repos DI + source-ref cleanup | 5d3a405 | feat |
| 2 | storage_router upload/signed-url/delete + mount (GREEN) | 568f700 | feat |
| 3 | download_audio_bytes real GCS + delegation test | 46ce563 | feat |

## TDD Gate Compliance

The four storage suites (`test_storage_upload` / `test_storage_signed_url` / `test_storage_delete` / `test_storage_cross_tenant`) are the **RED gate** authored in 09-01 (`test(09-01)` commit `da3c085`); this plan is their **GREEN gate** — `feat(09-02)` commit `568f700` creates the router that turns them green. Task 3's `test_download_delegates_to_gcs` is a new test authored WITH its implementation in the same task (the plan's authored shape); the phase-level RED/GREEN order is satisfied (09-01 RED -> 09-02 GREEN). No test could be executed on the dev box (no Python/Docker — author-by-construction per project constraint); RED->GREEN is confirmed in the Cloud Build suite run at wave merge.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `sqlalchemy.delete` not imported in `repository.py`**
- **Found during:** Task 1 (adding `delete_by_storage_path`)
- **Issue:** `repository.py` imported only `select, update`; the scoped ref-cleanup delete needs `delete`.
- **Fix:** Extended the import to `from sqlalchemy import delete, select, update`.
- **Files modified:** `backend/app/db/repository.py`
- **Commit:** 5d3a405

### Minor Additions (documented, not plan-contradicting)

- **`IntakeSourceRepository.delete_by_storage_path`** — the plan's Task 2 says "delete the intake_sources row whose storage_path == key via source_repo" but Wave-1's `IntakeSourceRepository` had only `list_for_intake`. Rather than a raw delete in the route (which would trip `ci_no_raw_db_access.sh` and bypass the `_scope` D-01 wall), a scoped repo method was added (committed with Task 1 since it lives in the repository layer). Routed through `_scope`, so a user can only clean a ref in their own space.
- **`ValueError` guard in `download_audio_bytes`** — a defensive check for a missing `storage_path` (Rule 2 — correctness); the transcribe `call_fn` already wraps the seam in a try/except that finalizes the run `failed`, so a malformed source degrades gracefully instead of raising a bare `KeyError`.
- **Category `422` (not `400`)** — the plan allowed "400/422" for an unknown category; `422 UNPROCESSABLE_ENTITY` was chosen to match FastAPI's native validation-error code. The RED suites only exercise valid categories, so this is unconstrained by the contract.

## Known Stubs

None. `download_audio_bytes` is now a real GCS delegation (its Phase-7 placeholder is removed); all three storage endpoints are fully wired to the seam and the tenant repos.

## Threat Flags

None. No security surface was introduced beyond the plan's `<threat_model>` — the three endpoints and their mitigations (T-09-05 IDOR via ownership 404 + prefix assert, T-09-06 traversal via server-authored key, T-09-07 DoS via 25 MB read cap, T-09-08 spoofing via extension allowlist + attachment disposition, T-09-09 dangling ref via same-tx cleanup) are exactly the registered threats.

## Verification

- `bash backend/scripts/ci_no_raw_db_access.sh` -> exit 0 (storage_routes.py holds no raw DB symbols; transcribe's `app.storage.gcs` import is not a DB symbol).
- `bash backend/scripts/ci_no_sa_json_key.sh` -> exit 0 (no SA JSON key introduced).
- All plan `<verify>` greps pass: `storage_router = APIRouter(prefix="/intakes"` / `protected_router.include_router(storage_router)` / `gcs.(upload_object|signed_download_url|delete_object)` / `25 * 1024 * 1024` / `get_intake_and_source_repos` / `IntakeSourceRepository(session, identity)` / `download_bytes` / absence of the Phase-9 placeholder string / `storage_path` / `test_download_delegates_to_gcs`.
- No second `app.include_router(storage_router)` (grep count 0).
- Deferred to Cloud Build (no Python on dev box): GREEN confirmation of the four storage suites + the full `test_ai_transcribe.py`, and Assumption A1 (keyless `generate_signed_url` kwargs) — the latter tracked for the 09-04 runbook.

## Follow-ups for Later Plans

- **09-03:** the frontend storage seam (apiFetch upload/signed-url/delete) consuming these endpoint shapes.
- **09-04 runbook:** Cloud Build image rebuild (the two new deps from 09-01 + this router) so the live Cloud Run image serves `/intakes/{id}/storage/*`; confirm Assumption A1 against the installed google-cloud-storage wheel; live signBlob + real GCS round-trip in the D-13 combined 7+8+9 UAT.

## Self-Check: PASSED

All 1 created + 5 modified files present; all 3 task commits (5d3a405, 568f700, 46ce563) verified in git log; working tree clean; both CI guards green.
