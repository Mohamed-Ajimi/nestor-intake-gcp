---
phase: 18-human-report-upload-client-delivery
plan: 02
subsystem: frontend
tags: [react, tanstack, i18n, report-delivery, admin-ui, recipient-picker, phase-machine]

# Dependency graph
requires:
  - phase: 18-human-report-upload-client-delivery
    provides: "POST /deliver, POST /report/replace, GET /report backend verbs + DeliverBody/ReportView contract (18-01)"
  - phase: 10-notifications
    provides: "RecipientPicker + listSpaceMembers members-read (reused for the Deliver/Replace dialogs)"
  - phase: 09-storage
    provides: "storage.uploadFile({category:'reports'}) + signedDownloadUrl seam"
  - phase: 16-research-trigger-progress-bridge
    provides: "in_research status + derivePhase machine (the delivery UI's host phase)"
provides:
  - "deliverReport / replaceReport / getReport + ReportView on the frontend intake seam (intakes.ts)"
  - "phaseShowsFinalReport includes in_research — the admin block mounts during a run"
  - "FinalReportBlock: staged-upload -> explicit Deliver -> post-delivery Replace, PDF-only, no auto-deliver"
  - "Admin route reloads the intake from the backend view after deliver/replace (no client-side status fake)"
  - "finalReport.deliver/delivering/delivered/deliverFailed/staged/stagedHint/replaceConfirm/reNotify/silentReplace in NL/FR/EN"
affects: [18-03-client-report-page, 18-04-live-uat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "stage-then-deliver: uploadFile stages a key in local state (client-invisible); an explicit RecipientPicker-driven verb flips status + sends mail (D-01)"
    - "backend-view-as-truth: the admin onChange reloads via getIntake, never fakes the delivered status client-side (T-18-08)"

key-files:
  created: []
  modified:
    - frontend/src/lib/api/intakes.ts
    - frontend/src/lib/intake-phase.ts
    - frontend/src/components/intake/FinalReportBlock.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json

key-decisions:
  - "Deliver + Replace dialogs both reuse RecipientPicker type='results' (D-02/D-05) — one picker, results copy family, no new dialog component"
  - "Post-delivery offers TWO replace paths: re-notify (RecipientPicker → replaceReport with recipients) and silent replace (replaceReport with recipients=[]) (D-04/D-05)"
  - "The block gates itself on phaseShowsFinalReport(phase); the admin route mounts it under showFinalReport unchanged"
  - "hasResultsToken prop kept on the surface (admin wires it) but no longer drives delivered state — voided to keep prop churn minimal"

patterns-established:
  - "Staged file is local-only (stagedPath/stagedMeta); clearing = local reset, no backend delete (D-06 — pre-deliver the object is unlinked)"

requirements-completed: [REPORT-01, REPORT-03]

# Metrics
duration: ~8min
completed: 2026-07-22
---

# Phase 18 Plan 02: Admin Report-Delivery UI Summary

**Awakened the dormant `FinalReportBlock` from a gated-off stub into the real staged-upload → explicit-Deliver → post-delivery-Replace flow: extended the frontend intake seam with `deliverReport`/`replaceReport`/`getReport`+`ReportView`, made `phaseShowsFinalReport` include `in_research` so the block mounts during a run, replaced the admin route's client-side `delivered` status fake with an authoritative `getIntake` reload, tightened the file input to PDF-only, and added the NL/FR/EN delivery i18n keys.**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-07-22
- **Tasks:** 3
- **Files modified:** 7 (0 created, 7 modified)

## Accomplishments
- **Seam extended** (`intakes.ts`): `ReportView` type + `deliverReport`/`replaceReport`/`getReport`, all with snake_case wire bodies (`storage_path`) mirroring the 18-01 backend contract. `deliverReport` is the sole `in_research → delivered` transition verb.
- **Phase machine** (`intake-phase.ts`): `phaseShowsFinalReport` now includes `in_research` (the block mounts once a run is in research); `derivePhase` logic unchanged; the stale Phase-16 comment refreshed to describe the Phase-18 delivery inputs.
- **FinalReportBlock repaired**: upload only STAGES a PDF locally (D-01 — client-invisible, status untouched); an explicit "Deliver" button opens `RecipientPicker` (type="results"); confirm calls `deliverReport` → status flips + mail sent. Post-delivery shows Replace with re-notify (RecipientPicker) OR silent replace (`recipients=[]`). Input tightened to `accept=".pdf"` (D-10). `maybeAutoDeliver` deleted; stale "not wired this milestone" / "scope ceiling stops at decomposed" comments removed.
- **Admin wiring** (`admin.pulse.intakes.$id.tsx`): the FinalReportBlock `onChange` now reloads the intake via `getIntake(intake.id)` and merges `status`/`final_report_artifact_id`/`results_link_sent_at` — the backend Deliver verb is the sole authority (T-18-08). The `? "delivered" :` client-side literal is gone.
- **i18n**: nine delivery keys authored per-locale in NL (parity source), FR, EN.

## Task Commits

1. **Task 1: extend intake seam + phase visibility** — `dff6178` (feat) — `deliverReport`/`replaceReport`/`getReport`+`ReportView`; `phaseShowsFinalReport` includes `in_research`.
2. **Task 2: repair FinalReportBlock** — `179b738` (feat) — staged-upload + Deliver/Replace dialogs, PDF-only, `maybeAutoDeliver` removed.
3. **Task 3: admin reload + NL/FR/EN i18n** — `0146fd4` (feat) — `getIntake` reload replaces the status fake; nine `finalReport.*` keys added.

## Files Created/Modified
- `frontend/src/lib/api/intakes.ts` — added `ReportView` + `deliverReport`/`replaceReport`/`getReport` in a new "Report delivery" section.
- `frontend/src/lib/intake-phase.ts` — `phaseShowsFinalReport` array now contains `"in_research"`; Phase-16 comment block refreshed for Phase 18.
- `frontend/src/components/intake/FinalReportBlock.tsx` — rewrote the stubbed parts: staged-upload state (`stagedPath`/`stagedMeta`), `onDeliverConfirm`/`onReplaceConfirm`/`onSilentReplace`, two `RecipientPicker` mounts (type="results"), `getReport` metadata fetch, PDF-only input. Kept `bytesLabel`, `sanitizeFilenameForStorage`, drag-drop, `onDownload` signed-URL blob flow, and the `uploadFile({category:"reports"})` call.
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — `onChange` reloads via `getIntake` and merges the seam-view fields.
- `frontend/src/locales/{nl,fr,en}/intake.json` — nine new `finalReport.*` delivery keys.

## Decisions Made
- **Both dialogs reuse `RecipientPicker` (`type="results"`).** No new dialog component — the Deliver and Replace-re-notify flows both mount `RecipientPicker` with the results copy family (D-02/D-05).
- **Two post-delivery replace paths.** Re-notify (opens `RecipientPicker` → `replaceReport(..., { recipients })`) and silent replace (a direct `replaceReport(..., { recipients: [] })` button) — matching D-04 (repoint, status stays delivered) + D-05 (optional re-notify).
- **`hasResultsToken` prop retained but voided.** The plan said keep the prop surface to minimize churn; the delivered state is now read from `intakeStatus === "delivered"`, so the prop is `void`-discarded rather than removed.
- **Staged-file clear is local-only.** Pre-delivery the staged storage key is unlinked server-side (D-06), so the Remove/swap path just resets `stagedPath`/`stagedMeta` — no backend delete call.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] No `node_modules` in the worktree — type-check could not run as written**
- **Found during:** Task 1 verification (`cd frontend && npx tsc --noEmit`)
- **Issue:** Git worktrees do not share the parent checkout's `node_modules`; the worktree's `frontend/` had none, so `npx tsc` printed the "not the tsc you are looking for" stub and `tsc` could not resolve `vite/client` types.
- **Fix:** Symlinked the parent repo's already-installed `frontend/node_modules` into the worktree's `frontend/` (`ln -s`), then ran the check via `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json`. `node_modules` is gitignored, so the symlink is not committed and does not affect the merge. This is a harness-only accommodation — the verification command's INTENT (a clean `tsc --noEmit`) ran and passed for all three tasks.
- **Files modified:** none (symlink only; not tracked)
- **Verification:** `tsc --noEmit -p tsconfig.json` exits 0 after each task; the plan's i18n presence node check prints "i18n ok".
- **Committed in:** n/a (no file change)

---

**Total deviations:** 1 (blocking harness fix, no source impact)
**Impact on plan:** None on the deliverables — the endpoint seam, block behavior, admin wiring, and i18n keys match the plan exactly. The only deviation is the mechanism used to run the type-check inside a worktree with no local install.

## Issues Encountered
- **Dev machine caveat (project memory):** npm/node ARE available; the only wrinkle was the worktree lacking `node_modules` (fixed via the parent-repo symlink above). No live/browser UAT was run — that is scoped to runbook 18-04.

## Deferred Issues
- None.

## Known Stubs
- None. The block is fully wired: upload stages, Deliver/Replace call the real backend verbs, the delivered report metadata is fetched via `getReport`, and the admin route reloads the authoritative intake view.

## Threat Flags
None — no new security surface beyond the plan's `<threat_model>`. T-18-08 (client-side status fake) is mitigated by the `getIntake` reload; T-18-09 (non-PDF) by `accept=".pdf"` (backend enforces authoritatively, 18-01); T-18-10 (staged file visibility) by the stage-then-explicit-deliver flow (D-01). No package installed (T-18-SC).

## Next Phase Readiness
- **18-03** (client report page) consumes `GET /report` + the storage signed-url seam — the `ReportView` type added here is the shared contract shape.
- **18-04** (live UAT) verifies the FinalReportBlock appears during `in_research`, staging holds the file without client visibility, Deliver flips status + sends mail, and Replace works post-delivery.
- Deploy: frontend-only change — no backend/migration; follow the frontend deploy runbook before UAT.
- No known blockers.

## Self-Check: PASSED

- Files verified present: `intakes.ts`, `intake-phase.ts`, `FinalReportBlock.tsx`, `admin.pulse.intakes.$id.tsx`, `nl/intake.json`, `fr/intake.json`, `en/intake.json`.
- Commits verified in git log: `dff6178` (Task 1), `179b738` (Task 2), `0146fd4` (Task 3).
- `tsc --noEmit` exits 0; i18n presence check prints "i18n ok".

---
*Phase: 18-human-report-upload-client-delivery*
*Completed: 2026-07-22*
