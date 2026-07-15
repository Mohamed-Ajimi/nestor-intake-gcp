---
phase: quick
plan: 260715-j7f
subsystem: frontend-intake
tags: [ui, canvas-fuse, i18n, presentation-only]
requires:
  - Phase 12 cutover frontend (IntakeForm stepper baseline)
provides:
  - Round-2 canvas chrome on the client intake form (sidebar progress header/bar, numbered three-state rows, scrollable nav, header hairline, submit arrow, resizable textareas)
affects: []
tech-stack:
  added: []
  patterns:
    - Sidebar progress derived purely from existing currentStep/completedSections state (no new state)
key-files:
  created: []
  modified:
    - frontend/src/components/intake/IntakeForm.tsx
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json
decisions:
  - "Sidebar counter rendered as raw numerics (`{n} / {total}`) — no i18n interpolation; only the 'Voortgang' label goes through t(\"form.progress\")"
  - "Submit arrow is a frontend presentation suffix appended to schema.submit.label — label text stays schema-sourced per locale"
  - "Future (not-done, not-active) rows now get a plain nav-mark; nav-mark-ink narrowed to done rows only (puts the previously unused `done` flag to work)"
metrics:
  duration: ~10 min
  completed: 2026-07-15
  tasks: 2
  commits: 2
---

# Quick Task 260715-j7f: Fuse Round-2 Canvas Redesign of Client Intake Form — Summary

Round-2 canvas chrome fused into the client intake stepper — progress header + bar, zero-padded three-state section rows, scrollable sticky sidebar, header hairline, 300px/minmax grid, submit arrow, and resize-y textareas — with zero behavior change.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | IntakeForm sidebar/header/grid redesign + form.progress i18n key (nl/fr/en) | b7fa30b |
| 2 | FieldRenderer longtext textarea resize-y + build gate | 5b5259b |

## What Changed

- **Header:** `mb-10` → `mb-12 border-b border-ink/15 pb-10` (hairline separator).
- **Grid:** `md:grid-cols-[320px_1fr]` → `md:grid-cols-[300px_minmax(0,1fr)]`; form column got `min-w-0` (overflow guard). Aside keeps `hidden md:block`.
- **Sidebar:** `sticky top-8` moved from nav to a wrapper div containing (a) "Voortgang" label + `n / total` tabular counter, (b) h-1 progress bar with inline width `((currentStep+1)/sections.length)*100%`, (c) nav reclassed `mt-5 space-y-1 overflow-y-auto max-h-[calc(100vh-12rem)]`.
- **Section rows:** new zero-padded number column (`String(idx+1).padStart(2,"0")`, `text-ink` when active/done, `text-ink/40` future); button classes now three-state (active `bg-paper2 text-ink`, done `text-ink hover:bg-ink/5`, future `text-ink/60 hover:...`); nav-mark-ink narrowed from all non-active rows to done rows only; `sectionDirty` override, `changed` badge, key/onClick untouched.
- **Submit:** standard last-step label renders `schema.submit.label + " →"`; `form.submitting` and `validationPhase.approveSubmit` branches untouched.
- **i18n:** `form.progress` added after `form.step` in nl ("Voortgang"), fr ("Progression"), en ("Progress").
- **FieldRenderer:** longtext textarea className is `inputCls + " resize-y"`; shared `inputCls` constant unchanged.

## Verification

- `npx tsc --noEmit` — clean (run after Task 1 and again in Task 2 gate).
- `npm run build:dev` — built in 19.34s, all locale JSON parsed.
- `git diff frontend/src/components/intake/IntakeForm.tsx` (pre-commit) — only JSX/className/label-suffix hunks; no edits inside handleChange, saveCurrentSection, goToSection, validateCurrent, handleNext, handleSubmit, doSubmit, or any useEffect (T-quick-01 mitigation satisfied).
- Pre-existing dirty files (`frontend/src/routeTree.gen.ts`, `.planning/STATE.md`, untracked `AGENTS.md`) left untouched and unstaged.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None — all new chrome is wired to existing live state (currentStep, completedSections, dirtyFields).

## Self-Check: PASSED

- frontend/src/components/intake/IntakeForm.tsx contains `max-h-[calc(100vh-12rem)]` and `currentStep + 1` width math — FOUND
- form.progress present in nl/fr/en intake.json — FOUND
- FieldRenderer longtext carries `resize-y` — FOUND
- Commits b7fa30b, 5b5259b — FOUND on master
