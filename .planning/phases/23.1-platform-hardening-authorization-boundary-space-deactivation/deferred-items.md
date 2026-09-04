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
