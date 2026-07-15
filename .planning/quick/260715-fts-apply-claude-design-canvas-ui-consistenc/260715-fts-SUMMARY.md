---
phase: quick-260715-fts
plan: 01
subsystem: frontend-ui
tags: [ui-consistency, tailwind, house-style, pre-uat]
requires: []
provides:
  - "Duplicate-Beheer-nav suppression in ProductShell (items !== ADMIN_NAV guard)"
  - "House-style sticky header on intake detail (serif lowercase h1, mono-uppercase chrome)"
  - "Sales status badges on the badge-ink/badge-outline/badge-dashed + mark-green system"
  - "Standardized boxed tables (clients/users/spaces) + standard inputs/selects (sales new, SalesContextFields, templates SelectTrigger)"
affects: [12-UAT visual review]
tech-stack:
  added: []
  patterns: ["per-usage SelectTrigger className override via cn()/tailwind-merge instead of editing ui/select.tsx"]
key-files:
  created: []
  modified:
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/routes/admin.pulse.intakes.new.tsx
    - frontend/src/routes/admin.pulse.clients.tsx
    - frontend/src/routes/admin.pulse.clients.$id.tsx
    - frontend/src/routes/admin.pulse.search.tsx
    - frontend/src/routes/admin.sales.projects.index.tsx
    - frontend/src/routes/admin.sales.projects.$id.tsx
    - frontend/src/routes/admin.sales.projects.new.tsx
    - frontend/src/components/sales/SalesContextFields.tsx
    - frontend/src/components/admin/ProductShell.tsx
    - frontend/src/routes/admin.users.tsx
    - frontend/src/routes/admin.spaces.tsx
    - frontend/src/routes/admin.templates.tsx
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/routes/auth.login.tsx
decisions:
  - "Sales badge map rewritten once in SalesStatusBadge (shared by list + detail) mirroring Pulse STATUS_VARIANT; unspecified statuses (gereviewd/gevalideerd/gearchiveerd) mapped to the analogous Pulse variants (reviewed/validated_by_client/archived)"
  - "Boxed-table rule applied by wrapping ONLY the <table> branch in a border-ink bg-paper div, so loading/error/empty states are not double-boxed"
  - "templates SelectTrigger house style landed per-usage (className via cn merge) — ui/select.tsx untouched"
metrics:
  duration: "~12 min"
  completed: "2026-07-15"
---

# Quick 260715-fts: Apply Claude Design Canvas UI Consistency Summary

Presentation-only Tailwind/markup unification across 15 frontend files (Pulse, Sales, Beheer, client-facing) per DIFF-NOTES, with duplicate-Beheer-nav fix in ProductShell; zero behavior change, build green.

## Commits

| Task | Commit | Scope |
|------|--------|-------|
| 1 | eca918d | Pulse routes (intake detail/new, clients list/detail, search) |
| 2 | 8a0c373 | Sales routes (list/detail/new) + SalesContextFields |
| 3 | 8907172 | ProductShell nav fix, Beheer pages, FieldRenderer, auth.login |

## Per-Entry Ledger (DIFF-NOTES → outcome)

### Task 1 — Pulse + shared shell
- **intake detail back-link** → APPLIED: `text-xs font-medium` → `font-mono text-xs uppercase tracking-wider` (ArrowLeft icon kept — the review entry specified class change only; icon removal was only specified for client detail).
- **intake detail h1** → APPLIED: `font-serif text-2xl font-normal lowercase tracking-tight text-ink`.
- **intake detail status select** → APPLIED: `border-ink/30 bg-paper font-mono text-xs uppercase tracking-wider text-ink` (existing focus classes + handlers preserved).
- **intake detail Bewerken button** → APPLIED: mono-uppercase + `hover:bg-ink/90`.
- **intake detail section subtitle italic** → APPLIED: dropped (line ~1336, section.description).
- **SpaceSwitcher / LanguageSwitcher standardization** → NO-OP (as pre-verified): both components already render the standard variant — `label-mono text-ink/40` eyebrow, `border border-ink bg-paper px-3 py-2 font-mono text-xs uppercase tracking-wider` trigger, `ChevronsUpDown h-4 w-4 opacity-50`, `role="combobox"` (SpaceSwitcher.tsx TRIGGER_CLASS lines 30-32; LanguageSwitcher.tsx lines 27-29). The canvas drift did not exist in source. Files unmodified.
- **intake new container** → APPLIED on the form view (`mx-auto max-w-2xl py-8` → `max-w-2xl`). The post-create success view (separate early-return, centered card) kept its `mx-auto ... py-8` container — the canvas snapshot showed the form state; deliberately not left-aligned the success card.
- **intake new card / label / asterisk / footer / cancel link** → APPLIED exactly per DIFF-NOTES.
- **clients list subtitle italic** → APPLIED.
- **clients list boxed table + thead** → APPLIED: table branch wrapped in `border border-ink bg-paper` div (outer `mt-6` wrapper unchanged so loading/error/empty states are not boxed); thead → `border-b border-ink font-mono text-xs uppercase tracking-wider text-ink`.
- **client detail back-link** → APPLIED: both back-link instances now plain-text `← {label}`; ArrowLeft usage + import removed.
- **search page header** → APPLIED: eyebrow `<p>` → `<h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">` keeping the existing i18n key `search.eyebrow` ("AI-zoek alles", rendered lowercase via class); subtitle → `mt-1 text-sm text-ink/60`.

### Task 2 — Sales
- **projects list CTA** → APPLIED: raw styled `<Link>` → `<Button asChild><Link .../></Button>` (same pattern as Pulse intakes list; Button default = mono-uppercase bg-ink border-ink h-10 px-6).
- **SalesStatusBadge house pills** → APPLIED once in the shared helper (used by list AND detail): concept→badge-dashed, ingediend→badge-ink, geleverd→badge-ink, in_onderzoek→badge-outline+mark-green (all four per DIFF-NOTES). Unspecified statuses aligned with the Pulse STATUS_VARIANT analogues: gereviewd→badge-outline+mark-green, gevalideerd→badge-ink+mark-green, gearchiveerd→badge-outline text-ink/40 border-ink/40.
- **row action Open →** → APPLIED as styled span `font-mono text-[11px] uppercase tracking-wider text-ink hover:underline` (row navigates via existing TableRow onClick; no new routing added per plan).
- **detail back-link mb-3/text-xs** → APPLIED.
- **detail subtitle italic** → APPLIED (project_title line).
- **detail tracker bg-fluoGreen → bg-agenic-green** → APPLIED. Token verified: `--color-agenic-green: #BFEC40` exists in styles.css line 31 (identical to fluoGreen line 32). Note: source uses fluoGreen for the CURRENT step (done steps are bg-ink); the only fluoGreen occurrence was renamed — same rendered colour.
- **detail blue status span → badge-ink** → APPLIED via the shared SalesStatusBadge map (detail imports it; no local blue span existed in the detail file).
- **new: h1 mt-3 / subtitle mt-1** → APPLIED.
- **new: all text inputs standardized** → APPLIED (5 occurrences via replace-all of the exact drifted string).
- **SalesContextFields selects** → APPLIED: single `selectCls` const → `w-full border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink` (also covers the "Andere…" free-text input which reuses selectCls).

### Task 3 — Beheer + client-facing
- **ProductShell duplicate Beheer nav** → APPLIED: manage block now `{isSuperadmin && items !== ADMIN_NAV && (...)}` — reference equality per pre-verified fact 2; the three Beheer route invocations untouched.
- **users/spaces/templates header flex-wrap** → APPLIED (all 3).
- **users/spaces/templates subtitle italic** → APPLIED (all 3).
- **users/spaces boxed tables + thead** → APPLIED (same wrap-the-table-branch pattern as clients list). Templates has no table (button list) — not applicable per plan.
- **templates SelectTrigger** → APPLIED per-usage: `className="h-10 border-ink bg-paper2 shadow-none focus:border-ink focus:ring-0"` — cn()/tailwind-merge lets these win over the base h-9/border-input/bg-transparent/shadow-sm/focus:ring-1. `ui/select.tsx` NOT modified.
- **FieldRenderer asterisk** → APPLIED: the single `text-red-500` occurrence (required-asterisk span, line 35) → `text-red-600`; no other occurrences in the file.
- **auth.login switcher wrapper** → APPLIED: `w-36` → `w-40` (wrapper div in auth.login.tsx; LanguageSwitcher.tsx untouched).

### IGNORE items — all untouched
Prototype `href`/`action`/`onclick` links, logo `<img>`→text flatten, logo class tweaks, nested `<main>`→`<div>` semantics: none implemented.

## Deviations from Plan

**1. [Minor] Boxed-table rule applied by wrapping only the table branch**
- **Found during:** Tasks 1 and 3
- **Issue:** The literal "wrapper mt-6 → mt-6 border border-ink bg-paper" div also contains loading/error/empty-state branches; blind application would box skeletons and double-box the already-bordered empty states.
- **Fix:** Kept the outer `mt-6` div, wrapped the `<table>` render branch in a new `border border-ink bg-paper` div (clients, users, spaces) — same rendered result as the canvas for the loaded-table state.

**2. [No-op] SpaceSwitcher / LanguageSwitcher** — already standard in source (canvas snapshot drift was hand-authored); files not modified, so the final touched set is exactly the 15 files in plan frontmatter.

**3. [Scoped] intake-new success card kept centered** — the container change was applied to the form view only; the post-create confirmation card retains `mx-auto ... py-8` (centered celebration state, not shown in the canvas).

Everything else executed exactly as written.

## Verification

- `npx tsc --noEmit`: zero errors after Task 1, Task 2, and Task 3 edits.
- `npm run build:dev`: succeeded ("✓ built in 22.48s", Nitro output generated).
- `git diff --stat 9c21684..HEAD`: exactly the 15 planned files, 70 insertions / 67 deletions, no deletions of tracked files.
- Grep gates: `italic` count = 0 in admin.pulse.clients.tsx / admin.users.tsx / admin.spaces.tsx / admin.templates.tsx; `text-red-500` absent from FieldRenderer.tsx.
- Lint: repo baseline is fully red (prettier "Delete ␍" on every line of every file — CRLF checkout, including untouched files like admin.index.tsx with 148 pre-existing errors). Touched files introduce no new error classes beyond the unavoidable per-line CRLF errors that any added line carries.
- Pre-existing `frontend/src/routeTree.gen.ts` modification and untracked `AGENTS.md` left untouched.

## Known Stubs

None — all edits are className/static-markup only; no data paths added or stubbed.

## Threat Flags

None — no new endpoints, auth paths, file access, or schema surface (T-Q260715-01 mitigations held: no handler/query/auth edits in the diff).

## Self-Check: PASSED

- Commits eca918d, 8a0c373, 8907172 present on master (`git log --oneline -4`).
- All 15 modified files exist and compile; no files created or deleted.
