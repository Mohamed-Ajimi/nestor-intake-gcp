---
phase: quick-260716-i0j
plan: 01
subsystem: frontend-admin-intake-detail
tags: [design-sync, canvas-round-3, ui-restyle, i18n]
requires: []
provides:
  - "Merged workflow panel (stepper -> status strip -> NextStepBanner -> semantic search -> scope-note) on admin intake detail"
  - "House-style archive confirm dialog (native confirm() removed)"
  - "Deferred-delete visualization with Herstel undo (onUndoDeferRemove seam)"
  - "Inline context-pack first-section preview (extractPackPreview)"
  - "Inline 'Naam · email' recipient rows in both mail pickers"
affects: [parity-UAT, future-design-rounds]
tech-stack:
  added: []
  patterns:
    - "Panel-idiom border-t strips inside a single bordered card"
    - "Plain-text markdown slicing for previews (no dangerouslySetInnerHTML)"
key-files:
  created: []
  modified:
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/admin/ProductShell.tsx
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/components/intake/FieldDisplay.tsx
    - frontend/src/components/intake/ContextPackBlock.tsx
    - frontend/src/components/intake/RecipientPicker.tsx
    - frontend/src/locales/nl/admin.json
    - frontend/src/locales/fr/admin.json
    - frontend/src/locales/en/admin.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json
decisions:
  - "D2 applied: inline '· email' (step-15 variant) in BOTH validation and results pickers"
  - "D5 applied: scope-note persistent block added AND onStartAutoResearch toast kept"
  - "D6 applied: semantic search normalized to border-t border-ink/10 (no nested double border, no inner mb-6)"
  - "DeliveredAtEditor save button left as-is (not in any snapshot, per plan)"
metrics:
  duration: "~12 min"
  completed: "2026-07-16T11:16:56Z"
  tasks: 3
  files: 13
---

# Phase quick-260716-i0j Plan 01: Fuse Round-3 Canvas Redesign of Admin Intake Detail Summary

Round-3 Claude Design canvas fused into the React admin intake detail page: one merged bordered workflow panel (stepper -> status strip -> NextStepBanner -> semantic search -> scope-note), all R1-R9 recurring restyles, plus four KEPT additive behaviors (archive dialog, deferred-delete viz with Herstel undo, inline context-pack preview, inline recipient emails) with 9 new i18n keys in nl/fr/en.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Merged workflow panel + recurring restyles R1-R9 | d816bf1 | route, NextStepBanner, ProductShell, FieldDisplay |
| 2 | Four KEPT proposals + scope-note (S1-S4, S6) | 958cc2a | route, FieldRenderer, ContextPackBlock, RecipientPicker |
| 3 | i18n catalogs nl/fr/en + final build gate | cc20510 | 6 locale JSON files |

## What Was Built

**Task 1 (style):**
- ProductShell: root gains `overflow-x-clip`; sidebar `<aside>` pinned via `sticky top-0 h-screen overflow-y-auto`.
- NextStepBanner outer div: `mb-5 border border-ink/30` -> `border-t border-ink/10` (accent border-left + all inner markup unchanged).
- Route JSX reorder: NEW `mb-8 border border-ink/15 bg-paper` panel containing stepper (`px-6 pt-6 pb-4`), status strip (`border-t border-ink/10 bg-paper2 px-6 py-3 text-xs`), NextStepBanner, semantic search (`border-t border-ink/10 bg-paperLight p-4`, D6 normalization). RecipientPicker mount, AI-review block, success modal, editBanner all stay outside/below the panel in unchanged relative order.
- Header: StatusPill deleted (select is the only status control; Meta-row StatusPill kept per D1); select restyled `border-ink px-3` no focus:border-ink; Annuleer/Opslaan buttons -> mono uppercase style.
- Intake-info h2 -> serif lowercase with border-b; `min-w-0` added to Meta dd (route) and FieldDisplay dd; schema sections boxed (`border border-ink/10 bg-paper p-6`); both LinkRow/ResultsLinkRow Kopieer buttons -> mono-outline.

**Task 2 (feat, all additive):**
- S3: `onArchive` now opens a hand-rolled `role="alertdialog"` overlay (house modal convention); `confirmArchive` carries the previous busy/handleStatusChange body. `confirm(discardChanges)` in handleCancel untouched. `intakeDetail.confirm.archive` key left in catalogs (now unused).
- S2: FieldRenderer Props + FileControl gain `onUndoDeferRemove`; removed files (with `path`, deferred mode only) stay visible as dashed strikethrough rows with a "wordt verwijderd bij opslaan" chip and a Herstel button that filters the path back out of `pendingRemovals` and re-adds the entry to the value. Non-multi restore disabled while a replacement file occupies the slot. WR-04 contract untouched: save still flushes `pendingRemovals` after `saveAnswers` succeeds, cancel still clears it, `handleSlot` replace-path deferral unchanged.
- S4: `extractPackPreview` module-scope pure helper (first `## ` heading + first paragraph, `**` stripped, first-line fallback, null on empty) renders an inline preview card between the "Laatst gegenereerd" meta line and the error line. Plain React text nodes only (T-q3-01 mitigation) — no dangerouslySetInnerHTML, no markdown renderer on this path.
- S1: RecipientPicker rows show `{name} · {email}` (muted email span) in both validation and results pickers; no duplicate email when the member has no name.
- S6: persistent "Einde platform-scope" strip as the panel's last child for `decomposed`/`in_research`/`delivered`, body via `<Trans>` with `decomposed` in a `font-mono` slot; `onStartAutoResearch` toast kept (D5).

**Task 3 (i18n):**
- 9 new keys x 3 locales (27 entries), nested under existing objects: `intakeDetail.archiveDialog.{title,body,confirm,cancel}`, `intakeDetail.scopeNote.{label,body}` (admin), `field.{pendingDelete,restore}`, `contextPack.previewLabel` (intake). Inserted programmatically after verifying byte-identical JSON round-trip (key order, 2-space indent, CRLF preserved — minimal diffs).

## Verification

- `npx tsc --noEmit` clean after each task.
- `npm run build:dev` green (built in 13.5s).
- Locale-completeness node check: `i18n OK` — all 9 keys x 3 locales, Trans `<0>decomposed</0>` slot present in all three scopeNote bodies.
- Grep gates: `confirm(t("intakeDetail.confirm.archive"))` count 0; `onUndoDeferRemove` count 7 in FieldRenderer (>= 3); `confirm(t("intakeDetail.confirm.discardChanges"))` count 1 (untouched); header StatusPill gone, Meta-row StatusPill retained.
- No file deletions across the three commits; shadcn `frontend/src/components/ui/` untouched; no backend changes; IGNORE-list artifacts (html hrefs, `<option selected>`, sample content) absent.

## Deviations from Plan

**1. [Rule 3 - Blocking] DIFF-NOTES-3.md absent from the worktree**
- **Found during:** Load plan
- **Issue:** The plan's authoritative worklist `.planning/design/intake-detail-round3/DIFF-NOTES-3.md` is not committed at the base (the `.planning/` gitignore force-add trap — the pulled/ snapshots ARE committed, the notes file was missed).
- **Fix:** Read the file read-only from the main checkout (`C:\Users\ajimimo\Desktop\MOELD\nestor-intake-gcp\.planning\design\intake-detail-round3\DIFF-NOTES-3.md`) where it exists untracked. No repo mutation; plan content also fully distilled the worklist, so execution was unambiguous.
- **Follow-up:** Orchestrator should `git add -f` DIFF-NOTES-3.md on the main tree so future agents see it.

**2. [Rule 3 - Blocking] node_modules absent in worktree**
- **Found during:** Task 1 verification
- **Fix:** `npm install` in `frontend/` (anticipated by plan constraints; 0 vulnerabilities).

**3. Build regenerated `frontend/src/routeTree.gen.ts`**
- **Found during:** Task 3 final gate (`npm run build:dev` runs the router plugin)
- **Fix:** Discarded via targeted `git checkout -- frontend/src/routeTree.gen.ts` per constraints (no route changes in this task; pre-existing dirty state on the main tree is out of scope).

No functional deviations — all three tasks executed as written.

## Known Stubs

None introduced. The `extractPackPreview` card renders nothing (not a placeholder) when no pack output exists, matching the existing "noPack" empty state.

## Threat Flags

None — no new endpoints, auth paths, or storage patterns. T-q3-01 mitigation applied as planned (preview is plain-string slicing rendered as text nodes).

## Self-Check: PASSED

- All 13 modified files present on disk with expected content (grep-verified key markers: `mb-8 border border-ink/15 bg-paper`, `onUndoDeferRemove`, `contextPack.previewLabel`, `archiveDialog`).
- Commits d816bf1, 958cc2a, cc20510 present on `worktree-agent-a71cdbb6688448a3d` (verified via git log).
- Working tree clean after final commit.
