---
phase: 09-gcs-storage
plan: 03
subsystem: storage
tags: [gcs, storage-seam, multipart, frontend, keyless, category]
requires:
  - phase: 09-gcs-storage
    provides: "app.storage seam + server-authored object keys ({space}/{intake}/{category}/{uuid}-{name}); endpoint contract POST /intakes/{id}/storage/uploads (multipart file+category), GET .../signed-url?path=&expires_in=, DELETE .../objects {paths}"
provides:
  - "frontend/src/lib/api/storage.ts — finalized storage seam: uploadFile({intakeId,file,filename,category,contentType?}), removeFile({intakeId,paths}), signedDownloadUrl({intakeId,path,expiresIn?}); no bucket, no client-authored key"
  - "frontend/src/lib/api/client.ts — apiFetch skips the JSON Content-Type default for FormData bodies so the browser authors the multipart boundary"
  - "5 intake call sites re-pointed at the finalized seam with per-site categories (attachments/audio/reports/artifacts) and no hardcoded nestor-uploads constant"
affects: [09-04]
tech-stack:
  added: []
  patterns:
    - "Browser never authors an object key or names a storage container (DOC-02/D-05) — it sends only file + category; the server owns the key"
    - "Intake-scoped storage mutations: removeFile/signedDownloadUrl carry intakeId in the path; the server enforces ownership + prefix"
    - "FormData transport guard: instanceof FormData check on init.body, mirrors the single load-bearing multipart fix (Pitfall 3)"
key-files:
  created: []
  modified:
    - frontend/src/lib/api/storage.ts
    - frontend/src/lib/api/client.ts
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/components/intake/FieldDisplay.tsx
    - frontend/src/components/intake/FinalReportBlock.tsx
    - frontend/src/components/intake/ResearchArtifacts.tsx
    - frontend/src/components/intake/ResearchResultsPanel.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/routes/intake.$id.results.tsx
decisions:
  - "Audio-category detection derives from the field's accept list (audio/* mime OR .mp*/.wav/.m4a/.aac/.ogg extensions) — no new field schema; everything else uploads as attachments"
  - "sanitizeFilenameForStorage retained in FinalReportBlock (display-side name normalization only) even though the server now authors the stored key — noUnusedLocals is false, so the dead helper is tolerated per the plan"
  - "FieldDisplay's dropped bucket null-guard is replaced by an intakeId prop threaded from both route call sites (admin: intake.id, results: route param id); FileRow now guards on intakeId presence"
requirements: [DOC-01, DOC-02]
metrics:
  duration: "~12 min"
  completed: "2026-07-13"
---

# Phase 9 Plan 03: Finalize Frontend Storage Seam Summary

**One-liner:** Reshaped the frontend storage seam to the server-authored-key contract (drop `bucket`/client `path`, add `category`, intake-scope delete/signed-url), applied the single load-bearing `apiFetch` FormData Content-Type guard, and re-pointed all 5 intake call sites with correct per-site categories — deleting the 3 hardcoded `nestor-uploads` constants and the client-side key builders.

## What Was Built

- **Task 1 (the seam + transport guard):**
  - `frontend/src/lib/api/client.ts` — the one load-bearing edit: the JSON Content-Type default now skips FormData bodies (`!headers.has("Content-Type") && !(init?.body instanceof FormData)`), so the browser sets the multipart boundary. Every existing JSON caller keeps the default. Nothing else in `apiFetch` touched.
  - `frontend/src/lib/api/storage.ts` — three functions reshaped and the header comment updated from "Phase-9 SEAM STUB / not yet implemented" to "finalized in Phase 9":
    - `uploadFile({ intakeId, file, filename, category, contentType? })` — dropped `bucket` + `path`; FormData now carries `file` (+ filename), `category`, and optional `content_type`. Still POSTs `/intakes/{intakeId}/storage/uploads`.
    - `removeFile({ intakeId, paths })` — dropped `bucket`; DELETEs `/intakes/{intakeId}/storage/objects` with body `{ paths }`.
    - `signedDownloadUrl({ intakeId, path, expiresIn? })` — dropped `bucket`; GETs `/intakes/{intakeId}/storage/signed-url` with `path` + `expires_in` query only.
    - `UploadedFileMeta` / `SignedDownloadUrl` types and the return-no-throw `ApiResult` contract left unchanged.
- **Task 2 (5 call sites re-pointed):**
  - `FieldRenderer.tsx` — deleted `const bucket = field.storage_bucket ?? "nestor-uploads"` and the client-side `prefix`/`path` builder. `uploadFile` now passes a derived `category` (`"audio"` when the field's accept list is audio, else `"attachments"`). `removeFile` (2 sites) and the `DownloadControl` `signedDownloadUrl` carry `intakeId` (threaded into `DownloadControl` as a new prop).
  - `FieldDisplay.tsx` — `FileRow` receives `intakeId` instead of `bucket`; the download null-guard is now on `intakeId`. Threaded an optional `intakeId` prop through `FieldDisplay` → `ValueRenderer` → the two `FileRow` sites and the object-list recursion.
  - `FinalReportBlock.tsx` — deleted `const BUCKET`; `uploadFile` passes `category: "reports"`; `signedDownloadUrl` carries `intakeId`. `sanitizeFilenameForStorage` retained for display only.
  - `ResearchArtifacts.tsx` — deleted `const BUCKET`; both `uploadFile` sites (PendingUploadForm + NoteModal) pass `category: "artifacts"`; `ArtifactRow` gained an `intakeId` prop (threaded from `QuestionBlock`) for its `signedDownloadUrl` + `removeFile`.
  - `ResearchResultsPanel.tsx` — deleted `const BUCKET`; the `getSignedUrl` callback passes `intake.id` (added to its dep array).
  - Route wiring: `admin.pulse.intakes.$id.tsx` passes `intakeId={intake.id}` to `FieldDisplay`; `intake.$id.results.tsx` passes `intakeId={id}` (route param).

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | Reshape storage.ts + apiFetch FormData guard | 47be9e8 | feat |
| 2 | Re-point 5 call sites to the finalized seam | 15dff7a | feat |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] FieldDisplay lost its download null-guard when `bucket` was dropped**
- **Found during:** Task 2
- **Issue:** The plan directed `FileRow` to "receive `intakeId` instead of `bucket`", but `FieldDisplay` (and its `ValueRenderer`) had no `intakeId` in scope — the value never flowed from the routes. Dropping `bucket` without threading `intakeId` would leave `FileRow.open()` unable to build a signed-url request and would not compile.
- **Fix:** Added an optional `intakeId?: string` prop to `FieldDisplay`, threaded it through `ValueRenderer` and the object-list recursion to `FileRow`, and passed `intake.id` (admin route) / `id` (results route) at the two external call sites. `FileRow` now guards on `intakeId` presence (replacing the old `bucket` guard) with the same toast.
- **Files modified:** `FieldDisplay.tsx`, `admin.pulse.intakes.$id.tsx`, `intake.$id.results.tsx`
- **Commit:** 15dff7a

### Minor Notes (documented, not plan-contradicting)

- **Audio-category derivation:** the plan said "derive from the field config already present" without pinning the exact predicate. Implemented as: field is audio when every `accept` entry is an `audio/*` mime or a common audio extension (`.mp*`/`.wav`/`.m4a`/`.aac`/`.ogg`); otherwise `attachments`. No schema change.
- **`sanitizeFilenameForStorage` now dead in FinalReportBlock:** its only use (building the client `path`) was removed. The plan explicitly says to keep it "for display purposes only"; `noUnusedLocals` is `false` in `tsconfig.json`, so the retained helper does not break the compile.
- **`field.storage_bucket` / `storage_path_prefix`** remain in the `IntakeField` type but are no longer read by any call site (tolerated; a later cleanup could prune them).

## Known Stubs

None introduced by this plan. The intake components' research/final-report data sources remain gated off behind the Phase-6 CONTEXT scope ceiling (unchanged by this plan); those pre-existing gates are documented in their own file headers and are not a product of this seam finalization.

## Verification

Local `npx tsc --noEmit` could not run — `frontend/node_modules` is absent on the dev box (no installs permitted per project constraint), so `tsc` is not resolvable. Fell back to source assertions (permitted by the plan's environment constraints):

- `grep -q 'instanceof FormData' src/lib/api/client.ts` → present (guard applied).
- `grep -q 'category' src/lib/api/storage.ts` → present; `! grep -q 'bucket' src/lib/api/storage.ts` → passes (no `bucket` token anywhere, including comments).
- `! grep -rq 'nestor-uploads' src/components/intake/` → passes (all 3 constants deleted).
- No `bucket` reference remains in any of the 5 call-site files.
- All 4 `uploadFile` calls pass `{ intakeId, file, filename, category }`; all 4 `signedDownloadUrl` calls pass `{ intakeId, path, expiresIn }`; all 3 `removeFile` calls pass `{ intakeId, paths }`.
- Every `signedDownloadUrl`/`FileRow` path argument is truthy-guarded before the call (`field.storage_path` / `artifact.storage_path` / `storagePath` / `file.path`), so the `string | null` → `string` narrowing holds under strict mode.
- Full-compile confirmation is deferred to the 09-04 combined UAT / any CI run that has `node_modules` installed, alongside the live end-to-end upload/download (D-13).

## Follow-ups for Later Plans

- **09-04 (D-13 combined UAT):** prove a real multipart upload round-trip (browser boundary → server key authoring → signed-url download) end-to-end against the deployed image; run `tsc --noEmit` in an environment with dependencies installed to confirm the full frontend compile.
- Optional cleanup: prune the now-unread `storage_bucket` / `storage_path_prefix` fields from `IntakeField` and the dead `sanitizeFilenameForStorage` helper.

## Self-Check: PASSED

Both task commits (47be9e8, 15dff7a) present in `git log`; all 9 modified files tracked and committed; no file deletions; no untracked files; only frontend paths touched (no backend/, infra/, STATE.md, or ROADMAP.md).
