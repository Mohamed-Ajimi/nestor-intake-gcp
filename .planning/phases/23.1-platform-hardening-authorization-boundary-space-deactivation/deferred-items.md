# Phase 23.1 — Deferred Items

Items shipped knowingly, recorded so they are never discovered later as surprises.
Created by plan `23.1-08` (wave 1). Plans 14 and 15 append to this file in later waves.

---

## DEF-23.1-01 — dropping `rehype-raw` costs two badges on the sales battlecard

**Recorded by:** plan 23.1-08, task 1.
**Commit:** see `23.1-08-SUMMARY.md`.

### What changed

`rehype-raw` was removed from `frontend/package.json`, `frontend/package-lock.json` and from
`frontend/src/components/sales/BattlecardMarkdown.tsx` (T-23.1-30). It rendered
author-supplied HTML with no sanitiser.

### The consequence — this is NOT free

`BattlecardMarkdown.tsx` synthesises raw tags in `transformContent()`:

- `[v]` / `[!]` / `[?]` / `[x]` and the legacy emoji `✅ ❓ 🚩 ►` become `<marker data-type="…">`
- `[H]` / `[M]` become `<conf data-level="…">`

and registers `marker` / `conf` component handlers that render `MarkerBadge` and
`ConfidenceBadge`. Those handlers **only ever fired because `rehype-raw` turned the raw tags
into real nodes.** With the plugin gone, react-markdown drops the raw tags and
**neither badge renders.** Status markers and H/M confidence pills disappear from battlecard
output.

The handlers and both badge components were deliberately LEFT IN PLACE, with a comment at
the handler site, so reinstatement is a one-line change.

### Why this is acceptable

Both reachable render paths are on the legacy Supabase sales route, which is inert without
`VITE_SUPABASE_*`:

- `frontend/src/routes/admin.sales.projects.$id.tsx:1081` — the `raw_markdown` fallback
- `frontend/src/components/sales/BattlecardBlocks.tsx:39` and `:52` — the `blocks` path,
  reached from `admin.sales.projects.$id.tsx:1076`

> **Correction to the plan.** `23.1-08-PLAN.md` states the sole caller is `:1081`. That is
> wrong — `BattlecardBlocks.tsx` is a second, and in practice the PRIMARY, path (`:1073`
> prefers `battlecard.blocks` and only falls back to `raw_markdown`). Both sit on the same
> inert route, so the disposition is unchanged, but the blast radius is two call paths.

`frontend/src/lib/supabase.ts:6` exports `null` when `VITE_SUPABASE_URL` /
`VITE_SUPABASE_ANON_KEY` are absent, and every data path in the sales route is guarded by
`if (!supabase)`. No battlecard can load, so no badge can be missed.

### If the sales path is ever revived

Do **NOT** restore plain `rehype-raw` — that restores the unsanitised-HTML capability for
every caller of `ReactMarkdown`. Use `rehype-sanitize` with a schema allowing exactly
`marker[data-type]` and `conf[data-level]`. Adding that dependency is forbidden in phase 23.1
(`23.1-CONTEXT.md` § 9 defers dependency work to its own phase).

---

## DEF-23.1-02 — frontend lint is not a CI gate this phase

Carried from `23.1-CONTEXT.md` § "shipped knowingly". Restated here because plan 23.1-08
touched frontend source and did NOT run lint or any `--fix` sweep, by instruction.

Measured at this plan's base (`3c8cd10`): `npm run lint` is red — 61 errors + 38 warnings on
an LF checkout (54 `no-explicit-any`, 4 `no-empty`, 2 `prefer-const`, 1 prettier), plus
~29,300 `prettier/prettier` "Delete ␍" artifacts on this machine because `core.autocrlf=true`.
Running `eslint --fix` here would rewrite every file's line endings and bury the diff.

The gates for plan 23.1-08 were `tsc` + `vitest` + `scripts/i18n-audit.mjs`, all green.
A lint-cleanup phase should be scheduled separately.

---

## DEF-23.1-03 — docs outside `frontend/` still name the two deleted components

**Found by:** plan 23.1-08, task 2. **Out of scope, deliberately NOT fixed.**

Plan 23.1-08's `files_modified` covers `frontend/**` only, and its `<done>` grep is scoped to
`frontend/src`, which is now at zero hits. But `git grep` over TRACKED files repo-wide shows
the deleted names surviving in documentation:

| File | Line | What it says |
|------|------|--------------|
| `CLAUDE.md` | 63 | lists `NestorBriefingPDF.tsx` as a `@react-pdf/renderer` consumer |
| `AGENTS.md` | 63 | identical line |
| `docs/handbook/12-frontend.md` | 448, 635, 733 | describes both files as existing dead code |
| `docs/handbook/19-known-gaps-and-roadmap.md` | 107 | lists both as "Removable" |

Nothing is broken — these are prose, and `docs/handbook/19` in particular is now simply
DONE rather than wrong. But `CLAUDE.md:63` and `AGENTS.md:63` are load-bearing context files
read at the start of every session, and they now name a file that does not exist.

A doc-sync pass should update them. Editing them from this plan would have exceeded its
declared file scope on a wave where isolation is disabled and other plans are writing.

## DEF-23.1-04 — `ContextPackPDF.tsx` and `pdfFonts.ts` are also dead

**Found by:** plan 23.1-08, task 2. **Out of scope, deliberately NOT deleted.**

Task 2 required confirming `pdfFonts.ts` keeps a consumer after `NestorBriefingPDF.tsx` is
deleted. It does — `ContextPackPDF.tsx:2` — so no third file was dropped and the plan's STOP
condition did not trigger.

But `ContextPackPDF.tsx` is itself imported by NOTHING. The only apparent hits are a SUBSTRING
trap: `ContextPackBlock.tsx:73/374/578` define and call a local `downloadContextPackPDF`, the
jsPDF exporter, which merely CONTAINS the string `ContextPackPDF`. `docs/handbook/12-frontend.md:448`
independently records the same finding ("not imported by anything; the shipped export is jsPDF").

So the real dead set is `ContextPackPDF.tsx` + `pdfFonts.ts` + the `@react-pdf/renderer`
dependency, and removing all three together would be the complete cleanup. Plan 23.1-08
explicitly forbids removing `@react-pdf/renderer`, and deleting a third file was out of its
scope, so this is left for a follow-up. Note that the dependency removal belongs to the
dependency phase deferred by `23.1-CONTEXT.md` § 9.
