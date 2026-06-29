---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 10
subsystem: api
tags: [react, storage, gcs, api-seam, supabase-retirement, scope-ceiling]

# Dependency graph
requires:
  - phase: 06-intake-crud-parity-frontend-api-seam (plan 05)
    provides: apiFetch transport + ApiResult contract (lib/api/client.ts) the storage seam extends
provides:
  - "frontend/src/lib/api/storage.ts — typed Phase-9 storage seam stub (uploadFile/removeFile/signedDownloadUrl) over apiFetch"
  - "FieldRenderer/FieldDisplay file fields routed off supabase.storage onto the storage seam"
  - "Research*, FinalReport, Handoff post-decomposed components gated off + free of inline supabase"
  - "API-03 done-condition met for the 8 files this plan owns (0 inline supabase)"
affects: [phase-09-storage-gcs, phase-07-research-backend, api-03-sweep]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Storage seam stub: typed ApiResult functions over apiFetch that surface a graceful error until the Phase-9 GCS backend lands"
    - "Scope-ceiling gating: post-decomposed components early-return null via derivePhase()+phaseShowsResearch/phaseShowsFinalReport"

key-files:
  created:
    - frontend/src/lib/api/storage.ts
  modified:
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/components/intake/FieldDisplay.tsx
    - frontend/src/components/intake/ResearchArtifacts.tsx
    - frontend/src/components/intake/ResearchResultsPanel.tsx
    - frontend/src/components/intake/AdminResearchResultsPanel.tsx
    - frontend/src/components/intake/FinalReportBlock.tsx
    - frontend/src/components/intake/HandoffBlock.tsx

key-decisions:
  - "Storage seam routes through apiFetch (no forked fetch); upload/remove/signed-url endpoints land in Phase 9, so the stub returns ApiResult.error until then"
  - "Post-decomposed components neutralized (gated off + inert), NOT wired to a research backend (Phase-Ceiling Note A4): research-backend DB/RPC ops left as inert stubs"
  - "Used namespace import (import * as storage) in FieldRenderer/ResearchArtifacts to avoid a name collision with local removeFile()"
  - "HandoffBlock gated behind phaseShowsResearch so it never renders this milestone (flow stops at decomposed) — its context-pack synthesis is replaced by the API seam in sibling Phase-6 plans"

patterns-established:
  - "Phase gate via derivePhase(minimal-input)+phaseShows* keeps exported component signatures stable while making dead UI return null"

requirements-completed: [API-03, INTAKE-05]

# Metrics
duration: ~35min
completed: 2026-06-29
---

# Phase 6 Plan 10: Neutralize lingering inline Supabase in components/intake/* Summary

**Added `lib/api/storage.ts` (typed Phase-9 upload/remove/signed-URL seam over apiFetch) and stripped all inline Supabase from the remaining seven `components/intake/*` files — file fields now route through the storage seam, and the post-decomposed Research/FinalReport/Handoff components are gated off and inert.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-29T17:30Z (approx)
- **Completed:** 2026-06-29T18:05Z
- **Tasks:** 3 (2 produced commits; Task 3 is an assertion-only sweep)
- **Files modified:** 8 (1 created, 7 modified)

## Accomplishments
- New `frontend/src/lib/api/storage.ts` storage seam stub: `uploadFile`, `removeFile`, `signedDownloadUrl`, all returning `ApiResult<T>` over the Phase-5 `apiFetch` transport (no forked fetch). Removes the anon-key browser→storage path (T-06-27).
- `FieldRenderer.tsx` / `FieldDisplay.tsx` file upload/remove/download re-pointed onto the storage seam; both files now have 0 inline supabase references (Task 1 acceptance met).
- `ResearchArtifacts.tsx`, `ResearchResultsPanel.tsx`, `AdminResearchResultsPanel.tsx`, `FinalReportBlock.tsx`, `HandoffBlock.tsx` stripped of all inline supabase (`.from`/`.rpc`/`.functions.invoke`/`.storage`) and gated off behind the phase helpers; their research-backend ops are inert (Phase 7+) and no `run-research`/`Tribunal`/`tg_bump_to_in_research` token was introduced (T-06-28, INTAKE-05 scope ceiling).
- All 8 owned files verified at 0 inline supabase call-sites.

## Task Commits

1. **Task 1: Storage seam stub + re-point FieldRenderer/FieldDisplay** - `ec6865e` (feat)
2. **Task 2: Gate off + neutralize the post-decomposed components** - `50a00e2` (feat)
3. **Task 3: Sweep assertion (no inline supabase on the intake surface)** - no code change required in owned files (0 call-sites); full-surface assertion completes post-merge (see Issues Encountered)

**Plan metadata:** committed with this SUMMARY.

## Files Created/Modified
- `frontend/src/lib/api/storage.ts` - Typed storage seam stub over `apiFetch`: `uploadFile`, `removeFile`, `signedDownloadUrl` → `ApiResult<T>`; Phase-9 GCS backend not yet present, so calls surface a graceful error.
- `frontend/src/components/intake/FieldRenderer.tsx` - File/files/download fields upload & remove via `storage.uploadFile`/`storage.removeFile`; `DownloadControl` uses `storage.signedDownloadUrl`. Supabase import removed.
- `frontend/src/components/intake/FieldDisplay.tsx` - `FileRow` open uses `signedDownloadUrl`. Supabase import removed.
- `frontend/src/components/intake/ResearchArtifacts.tsx` - Phase-gated via `derivePhase`+`phaseShowsResearch`; reload inert; uploads/notes route through the storage seam; artifact open/remove via seam; per-source text inert. Supabase import removed.
- `frontend/src/components/intake/ResearchResultsPanel.tsx` - Admin signed-URL via seam; klant token paths, klant synthesis RPC and `ask-research` AI-search neutralized to inert (research backend, Phase 7+). Supabase import + the `supabase.co` literal removed. Exported types (`RRPQuestion`/`RRPArtifact`/`RRPIntake`/`RRPClient`) unchanged.
- `frontend/src/components/intake/AdminResearchResultsPanel.tsx` - `load` no longer fetches (inert empty data); still renders `ResearchResultsPanel`. Supabase import removed.
- `frontend/src/components/intake/FinalReportBlock.tsx` - Phase-gated via `phaseShowsFinalReport`; upload via storage seam; `set_final_report` RPC + artifact fetch + auto-deliver left inert; download via seam. Supabase import removed.
- `frontend/src/components/intake/HandoffBlock.tsx` - Phase-gated via `phaseShowsResearch`; context-pack skill-run fetch, `generate-context-pack` invoke, and `intakes` status update all neutralized to inert. Supabase import removed.

## Decisions Made
- **Storage seam contract:** `uploadFile`/`removeFile`/`signedDownloadUrl` mirror the existing `intakes.ts`/`admin.ts` pattern (import the transport, never fork). The Phase-9 GCS endpoints don't exist yet, so the seam surfaces `ApiResult.error`, which the UI already handles via `toast.error`.
- **Neutralize, don't wire (A4):** Per the RESEARCH Phase-Ceiling Note, the post-decomposed components are dead UI this milestone. Storage ops route through the seam; research-backend DB/RPC ops (`research_artifacts`, `set_final_report`, `get_*_by_token`, `ask-research`) are intentionally left as inert stubs rather than wired — that work belongs to Phase 7+.
- **Namespace import to avoid collision:** `FieldRenderer` and `ResearchArtifacts` already define a local `removeFile`, so the seam is imported as `import * as storage` and called as `storage.removeFile(...)`.
- **Signatures stable for parallel consumers:** all exported component props and exported types are unchanged; gates are internal early-returns and inert handler bodies only.

## Deviations from Plan

None - plan executed as written. The post-decomposed components were neutralized exactly per the Phase-Ceiling Note (gate off + remove inline supabase, do not wire a research backend).

## Issues Encountered
- **Cross-plan Task 3 assertion is post-merge.** The full intake-surface sweep (`components/intake` + `routes/admin.pulse.*` + `routes/index.tsx` + `routes/intake.*`) still reports 8 inline-supabase call-sites, all in `src/components/intake/IntakeForm.tsx` and `src/routes/admin.pulse.intakes.$id.tsx` — files owned by sibling parallel agents/plans, not in this plan's `files_modified`. In this isolated worktree I cannot (and must not) edit other agents' files. My 8 owned files report **0** call-sites. The authoritative 0-across-the-surface assertion is satisfied by the orchestrator post-merge once all wave-4 frontend branches are merged.
- **tsc/build not run locally:** `node_modules` is absent in this worktree (build-environment note). Changes were authored by construction against the plan's acceptance greps; the orchestrator runs authoritative `tsc --noEmit` / build / vitest post-merge.

## Threat Flags

None — the storage seam removes the direct browser→storage path (mitigates T-06-27), and the gated-off post-decomposed components carry no scope-ceiling transition token (mitigates T-06-28). No new trust-boundary surface introduced.

## Known Stubs
- `frontend/src/lib/api/storage.ts` — intentional Phase-9 seam stub. The GCS upload/remove/signed-URL backend endpoints are not implemented yet; until Phase 9 the seam returns `ApiResult.error`, surfaced gracefully by callers. Documented as the planned Phase-9 hand-off (artifact `provides` in plan frontmatter).
- The five post-decomposed components contain inert handler bodies (research-backend DB/RPC ops removed) by design — they are gated off (`return null`) for the entire `≤ decomposed` flow this milestone (INTAKE-05 scope ceiling). Resolved when the research backend lands in Phase 7+.

## Next Phase Readiness
- Phase 9 can implement the GCS backend behind the stable `storage.ts` seam without touching the intake components.
- Orchestrator must run the full-surface API-03 sweep + `tsc`/build/vitest after merging all wave-4 frontend branches; expect IntakeForm.tsx and admin.pulse.intakes.$id.tsx to be cleared by their owning agents.

## Self-Check: PASSED

---
*Phase: 06-intake-crud-parity-frontend-api-seam*
*Completed: 2026-06-29*
