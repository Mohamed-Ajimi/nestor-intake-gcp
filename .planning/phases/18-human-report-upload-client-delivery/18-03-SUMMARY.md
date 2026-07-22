---
phase: 18-human-report-upload-client-delivery
plan: 03
subsystem: frontend
tags: [react, tanstack, i18n, report-delivery, client-ui, download-only, status-gate]

# Dependency graph
requires:
  - phase: 18-human-report-upload-client-delivery
    provides: "getReport(id) + ReportView contract on the frontend seam (18-02); POST /deliver flips status to delivered (18-01)"
  - phase: 09-storage
    provides: "storage.signedDownloadUrl seam (attachment signed URL, TTL-clamped server-side)"
  - phase: 12-cutover
    provides: "authenticated client surfaces — intake.$id.results.tsx clone target + intake.index.tsx list"
provides:
  - "intake.$id.report.tsx — authenticated, delivered-only client report page (download-only, D-08); chat space reserved (D-07)"
  - "intake.index.tsx delivered-only 'View report' CTA deep-linking /intake/$id/report (D-09)"
  - "reportPage.* i18n block + list.ctaReport in NL/FR/EN"
affects: [18-04-live-uat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "delivered-only exact-equality gate: status !== 'delivered' → navigate /intake (REPORT-02 invisibility, NOT a rank/>= comparison)"
    - "download-only via signed URL: signedDownloadUrl → fetch → blob → anchor click → revoke (no iframe/embed/PDF viewer, D-08)"
    - "layout reservation: a static font-mono placeholder label holds space for the Phase-19 chat with no chat UI/data (D-07)"

key-files:
  created:
    - frontend/src/routes/intake.$id.report.tsx
  modified:
    - frontend/src/routeTree.gen.ts
    - frontend/src/routes/intake.index.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json

key-decisions:
  - "The report route clones intake.$id.results.tsx (authReady, beforeLoad redirect, cancel-flag load, minimal chrome) but CHANGES the gate from the results route's isValidatedOrLater(>=) to an EXACT status !== 'delivered' redirect (Pitfall 2 / REPORT-02)"
  - "routeTree.gen.ts regenerated via the @tanstack/router-generator Generator class run programmatically (no tsr/router CLI bin present in the worktree) — canonical output, not a hand-edit"
  - "The delivered-date is rendered as a single localized sentence (reportPage.deliveredOn) rather than a dt/dd label pair, to match the plan's full-sentence key value"
  - "Download reuses FinalReportBlock's signed-URL blob flow verbatim (expiresIn: 300); failures surface reportPage.loadFailed via toast"

patterns-established:
  - "A second client entry point to a delivered report (list CTA) complements the 18-01 email CTA (D-09 two entry points)"

requirements-completed: [REPORT-02]

# Metrics
duration: ~12min
completed: 2026-07-22
---

# Phase 18 Plan 03: Client Report Page + List CTA Summary

**Built the client-facing side of delivery (REPORT-02): a NEW authenticated `intake.$id.report.tsx` route that renders ONLY when the intake status is exactly `delivered` — showing report metadata (filename, delivered date, size) and a signed-URL download button with no inline viewer (D-08), reserving static layout space for the Phase-19 chat (D-07) — plus a delivered-only "View report" CTA on the client intake list (D-09), all wired through NL/FR/EN `reportPage.*` copy.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-07-22
- **Tasks:** 2
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments
- **New client report route** (`intake.$id.report.tsx`): clones the auth + load structure of the results route (`authReady`, `beforeLoad` → `/auth/login` if signed out, cancel-flag `useEffect`, minimal authenticated chrome). The status gate is the EXACT `status !== "delivered"` → `navigate({ to: "/intake" })` redirect (Pitfall 2), NOT the results route's `isValidatedOrLater(>=)`. Loads `getIntake` (gate) then `getReport` (metadata), storing the `ReportView`.
- **Download-only** (D-08): a metadata card (font-mono labels: filename, localized delivered date, size via a local `bytesLabel` copied from `FinalReportBlock`) plus a primary Download button running the `signedDownloadUrl({expiresIn:300}) → fetch → blob → anchor(download=filename) → revoke` flow. NO `<iframe>`, `<embed>`, or PDF viewer.
- **Chat space reserved** (D-07): a bordered `border-dashed` placeholder section renders `reportPage.chatComingSoon` as a static muted label ONLY — no input, no message list, no chat logic, no data fetch.
- **Route registration**: `routeTree.gen.ts` regenerated via the `@tanstack/router-generator` `Generator` class (run programmatically — no `tsr`/router CLI bin in the worktree), registering `/intake/$id/report` canonically alongside the existing `/intake/$id/results` entry.
- **List CTA** (`intake.index.tsx`): `RowCta.target` widened to include `"report"`; `rowCta` returns `{ label: t("list.ctaReport"), target: "report" }` for `status === "delivered"` (before the generic result fallback, D-09); `openRow` navigates to `/intake/$id/report` for that target.
- **i18n**: `list.ctaReport` + a full `reportPage` block (heading, loading, deliveredOn, size, download, downloading, loadFailed, notAvailable, backToOverview, brand, logout, chatComingSoon) authored per-locale in NL (parity source), FR, EN.

## Task Commits

1. **Task 1: delivered-only client report route** — `6a6710c` (feat) — `intake.$id.report.tsx` (auth beforeLoad + exact `delivered` gate + `getReport` metadata + signed-URL download + chat placeholder); `routeTree.gen.ts` registers `/intake/$id/report`.
2. **Task 2: list "View report" CTA + reportPage i18n** — `fddac8e` (feat) — `rowCta`/`openRow` delivered → report branch; `list.ctaReport` + `reportPage.*` in NL/FR/EN.

## Files Created/Modified
- `frontend/src/routes/intake.$id.report.tsx` (created) — the authenticated, delivered-only, download-only client report page with the reserved chat placeholder.
- `frontend/src/routeTree.gen.ts` — regenerated to register `/intake/$id/report`.
- `frontend/src/routes/intake.index.tsx` — `RowCta` widened + delivered `report` branch in `rowCta`/`openRow`.
- `frontend/src/locales/{nl,fr,en}/intake.json` — `list.ctaReport` + a new `reportPage` block.

## Decisions Made
- **Exact-equality gate, not a rank comparison.** The results route gates at `validated_by_client` via `isValidatedOrLater(>=)`; the report route MUST be invisible for any non-`delivered` status, so the gate is a literal `status !== "delivered"` redirect (REPORT-02 / Pitfall 2). A delivered intake whose `getReport` fails (race 404 / read error) also degrades to an error + back-to-overview link, leaking nothing research-side.
- **`routeTree.gen.ts` regenerated, not hand-edited.** No `tsr` / router CLI bin exists in the worktree, but `@tanstack/router-generator` exposes a `Generator` class; running it programmatically with the project `getConfig` produced canonical output (verified: `/intake/$id/report` import, route object, union types, and `preLoaderRoute` all present).
- **Delivered date as one localized sentence.** The plan's `reportPage.deliveredOn` value is a full "Bezorgd op {{date}}" sentence, so it renders as a single value line (not a dt/dd label pair) with `new Date(delivered_at).toLocaleDateString(i18n.language)`.
- **Download flow reused verbatim.** `signedDownloadUrl({ expiresIn: 300 }) → fetch → blob → anchor → revoke` mirrors `FinalReportBlock.onDownload`; the 300s TTL is clamped ≤900s server-side (T-18-12).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] No `node_modules` and no `tsr` CLI in the worktree**
- **Found during:** Task 1 (route registration + `tsc` verification)
- **Issue:** Git worktrees do not share the parent checkout's `node_modules`, and even after symlinking it there is no `tsr` / router CLI bin to run `npx tsr generate`.
- **Fix:** (a) Symlinked the parent repo's installed `frontend/node_modules` into the worktree (gitignored — not committed), matching the wave-2 accommodation. (b) Ran the route generator via the `@tanstack/router-generator` `Generator` class programmatically (`getConfig` + `new Generator({config,root}).run()`), which regenerated `routeTree.gen.ts` canonically. Ran `tsc` via `node node_modules/typescript/bin/tsc`.
- **Files modified:** none beyond the planned `routeTree.gen.ts` regeneration (symlink is untracked).
- **Verification:** `tsc --noEmit -p tsconfig.json` exits 0 after both tasks; `/intake/$id/report` present in `routeTree.gen.ts`; all `reportPage.*` + `list.ctaReport` keys present in NL/FR/EN.
- **Committed in:** n/a for the symlink; the regenerated `routeTree.gen.ts` is in Task 1 (`6a6710c`).

---

**Total deviations:** 1 (blocking harness fix; the only source impact is the intended `routeTree.gen.ts` regeneration).
**Impact on plan:** None on the deliverables — the route, gate, download flow, list CTA, and i18n match the plan exactly.

## Issues Encountered
- No frontend test framework exists (RESEARCH § Wave 0); gating/download behavior is verified structurally + by `tsc` here and by live UAT in 18-04. No browser/live run was performed (dev-machine caveat + worktree scope).

## Deferred Issues
- None.

## Known Stubs
- **Intentional (Phase-19 deferred):** the `reportPage.chatComingSoon` placeholder is a static label reserving layout space for the Phase-19 Q&A chat (D-07). It renders no chat UI, fetches no data, and is explicitly scoped to a future phase — not a data-wiring stub for this plan's goal (which is delivered-only download, fully wired via `getReport` + `signedDownloadUrl`).

## Threat Flags
None — no new security surface beyond the plan's `<threat_model>`. T-18-11 (pre-delivery visibility) is mitigated by the exact `status !== "delivered"` front gate + the delivered-only list CTA, defense-in-depth with the 18-01 backend GET /report 404. T-18-12 (signed URL TTL) uses `expiresIn: 300` (server clamps ≤900s). T-18-13 (chat placeholder scope creep) is a static label only, no data fetch. No package installed (T-18-SC).

## Next Phase Readiness
- **18-04** (live UAT) verifies: a delivered intake shows the "View report" CTA; the report page downloads the PDF via the signed URL; a non-delivered intake redirects to `/intake`; a logged-out user is bounced to `/auth/login`; the chat placeholder shows but has no chat surface.
- Deploy: frontend-only change — no backend/migration; follow the frontend deploy runbook before UAT.
- No known blockers.

## Self-Check: PASSED

- Files verified present: `intake.$id.report.tsx` (created), `routeTree.gen.ts`, `intake.index.tsx`, `nl/fr/en intake.json` (modified).
- Commits verified in git log: `6a6710c` (Task 1), `fddac8e` (Task 2).
- `tsc --noEmit -p tsconfig.json` exits 0; `/intake/$id/report` registered in `routeTree.gen.ts`; all `reportPage.*` + `list.ctaReport` keys present in NL/FR/EN.

---
*Phase: 18-human-report-upload-client-delivery*
*Completed: 2026-07-22*
