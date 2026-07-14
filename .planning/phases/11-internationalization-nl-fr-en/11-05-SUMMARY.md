---
phase: 11-internationalization-nl-fr-en
plan: 05
subsystem: frontend-i18n
tags: [i18n, react-i18next, date-fns, react-pdf, intake]

requires:
  - phase: 11-01
    provides: "i18next singleton, getDateLocale, resolveErrorKey, intake.json catalogs, I18nextProvider mount"
  - phase: 11-03
    provides: "intake.json form/schema keys + externalized IntakeForm/FieldRenderer/FieldDisplay (same catalog files — sequential ordering)"
provides:
  - "ResearchResultsPanel + intake.$id.results route externalized (nl/fr/en)"
  - "8 AI/artifact intake components externalized (AIReviewPanel, AISkillsPanel, NextStepBanner, ResearchArtifacts, RecipientPicker, HandoffBlock, FinalReportBlock, ContextPackBlock)"
  - "3 date-fns nl call sites swapped to getDateLocale(i18n.language) (NextStepBanner, ResearchArtifacts, ContextPackBlock)"
  - "ContextPackPDF + NestorBriefingPDF render via a typed pre-resolved labels prop (Pitfall 3) — no useTranslation inside the detached pdf() tree"
  - "results/aiReview/aiSkills/nextStep/artifacts/recipients/handoff/finalReport/contextPack/pdf sub-objects in nl/fr/en intake.json"
affects:
  - "11-07/11-08 (phase-gate full Dutch scan; error-code enum growth)"
  - "Any future NestorBriefingPDF caller (must supply the labels prop)"

tech-stack:
  added: []
  patterns:
    - "Per-component useTranslation('intake') sub-object namespacing (results.*, aiReview.*, etc.)"
    - "Pitfall 3: react-pdf / jsPDF exporters take pre-resolved label strings as props built at the in-provider call site — never useTranslation inside the detached render tree"
    - "date-fns call-site swap: import { nl } → getDateLocale(i18n.language) with an embedded-literal format string parameterized via t()"
    - "Trans component for <strong>-wrapping banner strings; i18next _one/_other plural keys via t(key, {count})"

key-files:
  created: []
  modified:
    - frontend/src/components/intake/ResearchResultsPanel.tsx
    - frontend/src/routes/intake.$id.results.tsx
    - frontend/src/components/intake/AIReviewPanel.tsx
    - frontend/src/components/intake/AISkillsPanel.tsx
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/intake/ResearchArtifacts.tsx
    - frontend/src/components/intake/RecipientPicker.tsx
    - frontend/src/components/intake/HandoffBlock.tsx
    - frontend/src/components/intake/FinalReportBlock.tsx
    - frontend/src/components/intake/ContextPackBlock.tsx
    - frontend/src/components/intake/ContextPackPDF.tsx
    - frontend/src/components/intake/NestorBriefingPDF.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json

key-decisions:
  - "PDF exporters (react-pdf + the jsPDF helpers in ResearchResultsPanel/ContextPackBlock) receive pre-resolved label strings/objects from the in-provider caller; the detached tree never calls the i18n hook (Pitfall 3)"
  - "The mode: 'admin' | 'klant' discriminant literal is a code/data value (not display text) and is left untouched — deferred as a cross-cutting rename outside 11-05 scope"
  - "buildResearchMarkdown + NestorBriefingPDF are currently unused exports; still converted to the labels-prop pattern so no hardcoded Dutch remains and future callers must supply localized strings"

patterns-established:
  - "Pitfall-3 pre-resolved-labels prop for any imperative/detached PDF render (react-pdf and jsPDF)"
  - "date-fns nl → getDateLocale(i18n.language) with t()-parameterized format literals"

requirements-completed: [I18N-01]

duration: ~90min
completed: 2026-07-14
---

# Phase 11 Plan 05: Intake results/AI/PDF externalization Summary

**ResearchResultsPanel + 8 AI/artifact intake components + the results route externalized to nl/fr/en, three date-fns nl call sites swapped to getDateLocale, and both react-pdf exporters (plus the two jsPDF helpers) converted to pre-resolved labels props (Pitfall 3).**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-07-14T09:30:00Z (approx)
- **Completed:** 2026-07-14T11:00:00Z
- **Tasks:** 3
- **Files modified:** 15 (12 components/routes + 3 catalogs)

## Accomplishments
- ResearchResultsPanel.tsx (the 45-string densest file in the set, 4 sub-components) + intake.$id.results.tsx fully externalized, including interpolated/pluralized keys (basedOn, viewFragments, sources).
- 8 AI/artifact components externalized: AIReviewPanel, AISkillsPanel, NextStepBanner, ResearchArtifacts, RecipientPicker, HandoffBlock, FinalReportBlock, ContextPackBlock.
- Three date-fns `import { nl }` call sites (NextStepBanner, ResearchArtifacts, ContextPackBlock) swapped to `getDateLocale(i18n.language)`; the `date-fns/locale` nl import removed from all three.
- ContextPackPDF + NestorBriefingPDF render every display string from a typed `labels` prop; neither calls the i18n hook. HandoffBlock builds ContextPackPDF's labels via `t()` + locale-aware `fmtDate` at the in-provider call site.
- The two jsPDF helpers in scope (ResearchResultsPanel per-question PDF toasts, ContextPackBlock `downloadContextPackPDF`) also take pre-resolved labels / route their user-facing strings through `t()`.
- FR + EN translations authored for every new key (D-12); nl fallback guaranteed by 11-01 runtime.

## Task Commits

1. **Task 1: Externalize ResearchResultsPanel + intake.$id.results route** - `d6880a1` (feat)
2. **Task 2: Externalize AI/artifact components + three date-locale swaps** - `29745c7` (feat)
3. **Task 3: PDF label externalization via pre-resolved props (Pitfall 3)** - `31ab140` (feat)

## Files Created/Modified
- `frontend/src/components/intake/ResearchResultsPanel.tsx` - useTranslation across 4 sub-components; results.* keys
- `frontend/src/routes/intake.$id.results.tsx` - resultsRoute.* keys; effect-set error strings routed via t()
- `frontend/src/components/intake/AIReviewPanel.tsx` - aiReview.* across 8 exported sub-components
- `frontend/src/components/intake/AISkillsPanel.tsx` - aiSkills.* keys
- `frontend/src/components/intake/NextStepBanner.tsx` - nextStep.* keys, getDateLocale swap, Trans for <strong> lines
- `frontend/src/components/intake/ResearchArtifacts.tsx` - artifacts.* keys, getDateLocale swap, localized SOURCE/TYPE option labels
- `frontend/src/components/intake/RecipientPicker.tsx` - recipients.* keys; TYPE_COPY moved in-component and derived from t()
- `frontend/src/components/intake/HandoffBlock.tsx` - handoff.* keys; toLocaleDateString(i18n.language); builds ContextPackPDF labels
- `frontend/src/components/intake/FinalReportBlock.tsx` - finalReport.* keys
- `frontend/src/components/intake/ContextPackBlock.tsx` - contextPack.* keys, getDateLocale swap, jsPDF labels threaded via buildPdfLabels()
- `frontend/src/components/intake/ContextPackPDF.tsx` - ContextPackPDFLabels prop; Footer takes footer string
- `frontend/src/components/intake/NestorBriefingPDF.tsx` - NestorBriefingPDFLabels prop; buildResearchMarkdown labels param
- `frontend/src/locales/{nl,fr,en}/intake.json` - additive sub-objects (results, resultsRoute, aiReview, aiSkills, nextStep, artifacts, recipients, handoff, finalReport, contextPack, pdf)

## Decisions Made
- **Pitfall 3 honored everywhere:** react-pdf exporters and the jsPDF helpers receive pre-resolved strings from the in-provider caller. HandoffBlock resolves ContextPackPDF's dated labels with the locale-aware `fmtDate` before `generateContextPackBlob`.
- **`mode: "admin" | "klant"` left as-is:** it is an application/data discriminant (a code literal), not display text; renaming it is a cross-cutting change touching sibling files outside this plan. Documented in deferred-items.md.
- **Unused exports converted anyway:** `NestorBriefingPDF`/`generateBriefingBlob`/`buildResearchMarkdown` have no current callers but were converted to the labels-prop pattern so no hardcoded Dutch remains and any future caller is forced to supply localized strings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Ran `npm install` in the worktree frontend**
- **Found during:** Setup (before Task 1)
- **Issue:** `frontend/node_modules` was absent in the fresh worktree, so `npx tsc --noEmit` / `vitest` could not run.
- **Fix:** `npm install` in `frontend/` (uses the committed lockfile from 11-01; no new deps added).
- **Files modified:** none (node_modules is gitignored)
- **Verification:** tsc + vitest run successfully afterwards.
- **Committed in:** n/a (no tracked changes)

---

**Total deviations:** 1 (blocking — env bootstrap, no source change).
**Impact on plan:** None on scope. All three tasks executed as written.

## Issues Encountered
- **CI Dutch guard still reports the intake component set as non-clean**, from two out-of-scope sources: (a) the `mode: "admin" | "klant"` discriminant literal + code comments in ResearchResultsPanel (a data value, not UI text), and (b) `IntakeWorkflowStepper.tsx:126` (`"Klant is nog aan het invullen."`), a file NOT in this plan's `files_modified` (owned by a sibling 11-03/11-06 externalization plan). Both logged to `deferred-items.md`. All in-scope user-visible Dutch prose IS externalized. The phase-gate full scan (post-Wave) is where the guard is expected to go green once every plan's files are complete.

## Known Stubs
None introduced by this plan. (The intake AI/artifact/research surfaces this plan externalizes are themselves phase-gated dead UI for the current milestone — that gating predates 11-05 and is unchanged; only their strings were externalized.)

## Next Phase Readiness
- All 11-05 component/route/PDF files render in the active locale; nl fallback guaranteed.
- Sibling waves (11-07 admin, 11-08 backend mail) touch disjoint files; no overlap with this plan's set except the shared intake.json catalogs, which were extended additively under new sub-objects (no existing key removed/renamed).
- Deferred: `mode` enum rename (or a targeted guard exemption) and IntakeWorkflowStepper.tsx — for the owning plan / phase gate.

## Self-Check: PASSED

- All 15 modified source files + the SUMMARY exist on disk.
- Commits d6880a1, 29745c7, 31ab140 present on `worktree-agent-a6be015c736727f76`.
- `npx tsc --noEmit` clean (exit 0); vitest 35/35 pass; no file deletions across the three task commits.

---
*Phase: 11-internationalization-nl-fr-en*
*Completed: 2026-07-14*
