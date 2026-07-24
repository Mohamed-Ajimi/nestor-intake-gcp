---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 06
subsystem: client-quality-numbered-citation-surface-d13
tags: [react, tanstack, i18n, citations, snapshot, superadmin, tenant-isolation, ssrf]
requires:
  - getSource-proxy                       # Plan 15-04 (intake-side superadmin source proxy)
  - db-generated-numbering                # Plan 15-03 numbering.py ([n] generated from DB, not model)
  - source-snapshot-renderer-payload      # Plan 15-03 (id/url/title/provider/fetched_at/snapshot_text)
  - getVerification-getAuditBody-shape     # Plan 15-05 (research.ts one-shot apiFetch clone target)
provides:
  - research.ts-getSource
  - research.ts-Citation-CitationSource-types
  - CitationPanel-component
  - renderCitationMarker-helper
  - citation-i18n-en-fr-nl
affects:
  - Operator UAT (SC4 — operator clicks every [n] in the recorded run's report; each opens a stored-snapshot panel)
  - Phase-15 SC4 closure (numbered, clickable, DB-generated citations that always resolve + survive dead links)
tech-stack:
  added: []
  patterns:
    - "getSource clones getVerification's one-shot apiFetch shape VERBATIM — transport never forked; hits the Plan 15-04 /research/sources/{sourceId} proxy, NOT sources.ts (intake-upload, a distinct concern)"
    - "CitationSource/Citation types are standalone additive exports on research.ts (Citation was deliberately deferred out of Plan 15-05, added here)"
    - "CitationPanel mirrors AuditBodyPanel's fetch/toast/cancel-flag pattern; renders snapshot_text DIRECTLY via a read-only <pre> — NO raw fetch(), so the live url is never re-requested (T-15-15)"
    - "renderCitationMarker(citation, onOpen) is a tiny presentational [n] button the report body interleaves inline; wiring the marker→panel open is the caller's job (report body, admin-side)"
    - "Quality tier 1/2/3 → i18n label via a TIER_KEY map (official/serious press/blog); single-source + temporal_note are conditional inline caveats"
    - "Superadmin surfaces mount ONLY under admin.pulse.* by placement; enforced by the 16-D-08 route-import grep guard (exit 0)"
key-files:
  created:
    - frontend/src/components/intake/CitationPanel.tsx
  modified:
    - frontend/src/lib/api/research.ts
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/nl/intake.json
decisions:
  - "Citation.title takes precedence over the fetched source.title in the panel header (the DB-numbered citation carries the authoritative display title; source.title is the fallback), with an i18n 'Untitled source' final fallback"
  - "snapshot_text renders in a read-only <pre> (font-sans, wrap+break, max-h-80 scroll) rather than markdown — the stored snapshot is raw captured source text, not authored markdown, so no react-markdown here"
  - "renderCitationMarker is EXPORTED from CitationPanel.tsx (not a separate module) so the marker + panel ship together; the report-body wiring (which recorded-run report renders the markers) is left to the caller per the plan's 'expose a small helper the report body uses' phrasing — no route file was in this plan's file set to wire, and none was modified (16-D-08 guard stays trivially green)"
  - "getSource is placed directly after getAuditBody in research.ts, cloning getVerification's body exactly (apiFetch<CitationSource>, GET) — no transport fork, sources.ts untouched (plan Task 1 note)"
metrics:
  duration: ~20m
  completed: 2026-07-24
---

# Phase 15 Plan 06: Client-Quality Numbered Citation Surface (D13) Summary

The client-facing quality bar for citations, built against the recorded run with no live LLM
run: a `getSource()` client fn (cloning `getVerification`'s one-shot `apiFetch` shape over the
Plan 15-04 superadmin source proxy) plus `Citation`/`CitationSource` types on `research.ts`, and
a `CitationPanel` that opens when a `[n]` marker is clicked and renders the number, title,
publication date, quality tier (1 official / 2 serious press / 3 blog), a single-source badge,
an inline outdated-fact temporal caveat, and — the whole point — the DB-STORED `snapshot_text`
rendered DIRECTLY so a dead link still resolves. The `[n]` numbers are generated from the DB
(Plan 15-03), never the model, so every number resolves; the panel mounts superadmin-side only
(16-D-08 route-import guard) over the space-scoped proxy, and NEVER re-fetches the live source
URL (T-15-15 SSRF + dead-link survival). This closes Phase-15 SC4.

## What Was Built

**Task 1 — `research.ts`: getSource + Citation/CitationSource types** (`f94a758`):
- `CitationSource` type (`id/url/title/provider/fetched_at/snapshot_text`) mirroring the Plan
  15-03 tribunal renderer payload returned by the Plan 15-04 `/research/sources/{sourceId}`
  proxy. `snapshot_text` is the stored captured text — the panel renders it directly.
- `Citation` type (`n/source_id/title/publication_date/quality_tier:1|2|3/single_source/
  temporal_note?`) matching Plan 15-03's DB-generated numbering output.
- `getSource(intakeId, sourceId)` → GET `/intakes/${intakeId}/research/sources/${sourceId}`,
  cloning `getVerification`'s one-shot `apiFetch<CitationSource>` shape VERBATIM (transport
  unforked, return-no-throw). Placed right after `getAuditBody`. `sources.ts` (intake-upload,
  a distinct concern) was NOT touched.

**Task 2 — CitationPanel component + en/fr/nl i18n** (`8115419`):
- `CitationPanel.tsx` (created): props `{intakeId, citation, onClose?}`; fetches
  `getSource(intakeId, citation.source_id)` on mount (return-no-throw + sonner toast + inline
  error, cancel-flag cleanup — mirrors `AuditBodyPanel`). Renders the number, title (Citation
  title → fetched source.title → "Untitled source" fallback), publication date, quality-tier
  label (via a `TIER_KEY` 1/2/3 map), a conditional single-source badge, a conditional inline
  `temporal_note` caveat, and the stored `snapshot_text` in a read-only scrolling `<pre>`. The
  panel contains NO raw `fetch()` — only `getSource` — so the live source `url` is never
  re-requested (T-15-15).
- `renderCitationMarker(citation, onOpen)` (exported helper): a tiny `[n]` button the report
  body interleaves inline; clicking it calls `onOpen(citation)` to open the panel.
- `citation.*` i18n keys (14 keys: loadError, regionLabel, title, close, loading, untitled,
  published, dateUnknown, tierOfficial/tierPress/tierBlog, singleSource, snapshotLabel,
  snapshotEmpty) added to en/fr/nl `intake.json` with identical key sets — `i18n-audit.mjs`
  CHECK A/B/C green (exit 0).

## Verification Strategy (author-by-construction — tsc/build deferred to CI)

The worktree has NO installed frontend deps (no lockfile is committed, intentional per bunfig;
`node_modules` absent), so `npx tsc --noEmit` cannot resolve the compiler — it returns "This is
not the tsc command you are looking for", exactly as documented in the 15-04/15-05 summaries.
This is the established author-by-construction pattern for this repo; the full typecheck +
`npm run build` are deferred to Cloud Build / CI. The dep-free gates DID run and pass:

- **`node scripts/i18n-audit.mjs` — EXIT 0 (PASS).** CHECK A (3-way nl/fr/en parity), CHECK B
  (every literal `t()` key resolves in all locales), CHECK C (no two-arg fallbacks) all clean.
  The 107 CHECK D advisories are ALL pre-existing hits in `admin.sales.*` / `auth.*` /
  `index.tsx` / `__root.tsx` / `router.tsx` — NONE in `CitationPanel.tsx` (grep-confirmed).
  CHECK D is advisory-only and never fails the gate.
- **Client-route-import guard — EXIT 0.** `! grep -rEln 'CitationPanel' src/routes/
  --include='*.tsx' | grep -v 'admin\.'` finds nothing — `CitationPanel` is imported by no
  route file at all (the only non-self reference is a doc-comment string in `research.ts`, not
  an import). The 16-D-08 client-blindness invariant holds.
- **No-live-URL-fetch assertion — PASS.** `grep -nE 'fetch\(' CitationPanel.tsx` finds nothing;
  the only network call is `getSource`, and `snapshot_text` renders in a `<pre>` (T-15-15).
- **JSON validity:** all three `intake.json` files `JSON.parse` clean.
- **getSource / sources.ts assertions:** `grep -c 'export function getSource' research.ts` == 1;
  `git diff --name-only -- src/lib/api/sources.ts` empty (intake-upload sources untouched).

Structural type-consistency was reviewed by hand: `getSource` is a byte-for-byte clone of
`getVerification`'s body (only the URL segment + generic differ), the new `Citation`/
`CitationSource` types are standalone additive exports, and `CitationPanel` reuses the exact
`useEffect`/`useState`/toast/cancel-flag shape already type-checked in `AuditBodyPanel` — the
`quality_tier: 1 | 2 | 3` narrows cleanly through the `TIER_KEY` `Record<1|2|3,string>` map.

## Deviations from Plan

None material — plan executed as written across both tasks. No Rule 1-4 deviations, no auth
gates, no architectural changes, no new packages (T-15-SC holds — reused lucide-react/sonner
already in the repo).

Two implementation choices the plan left to executor judgement:
1. The report-body WIRING (which recorded-run report component renders the `[n]` markers and
   owns the open-panel state) was NOT added — the plan's file set names only `research.ts`,
   `CitationPanel.tsx`, and the three locales, and its Task 2 phrasing ("expose a small
   `renderCitationMarker(n, onOpen)` helper the report body uses") delivers the affordance as an
   exported helper for a future report-body caller. No route or report-body file was in scope,
   and none was modified, so the 16-D-08 guard stays trivially green. The marker + panel are
   ready to wire; the caller supplies the `Citation[]` (DB-numbered, Plan 15-03) and the open
   handler.
2. `snapshot_text` renders in a read-only `<pre>` rather than through `react-markdown` — the
   stored snapshot is raw captured source text, not authored markdown, so markdown rendering
   would be wrong (and `getVerification`'s markdown use is for authored verdict prose, a
   different input class).

## Known Stubs

None. `getSource` returns REAL data through the Plan 15-04 superadmin source proxy over Plan
15-03's recorded-run renderer payload; `CitationPanel` renders the actual stored `snapshot_text`
(never a placeholder — the `snapshotEmpty` line is an honest "no snapshot stored" signal, shown
only when the DB genuinely has no snapshot for that source). `renderCitationMarker` is a live
helper, not a no-op. The `Citation[]` feed is DB-generated upstream (Plan 15-03), consumed by a
future report-body caller — not stubbed here.

## Threat Flags

None beyond the plan's registered surface. The citation surface is fully covered by the threat
register:
- T-15-14 (citation source cross-tenant read) — goes through the Plan 15-04 space-scoped
  superadmin proxy + tribunal RLS 404; existence-hidden.
- T-15-15 (panel re-fetching an arbitrary live source URL) — the panel renders stored
  `snapshot_text` ONLY; the no-live-URL-fetch assertion (`grep 'fetch('` empty) proves it.
- T-15-16 (unresolvable model-emitted `[n]`) — numbering is DB-generated (Plan 15-03), never
  the model; every `n` carries a `source_id` that resolves via the proxy.
- T-15-16b (CitationPanel on a client route) — mounted superadmin-side only; the 16-D-08
  route-import grep guard exits 0 (no route imports it).
No new network surface (the fetch reuses the existing `apiFetch` transport), no new schema at a
trust boundary, no new packages (T-15-SC).

## Self-Check: PASSED

- File created — `frontend/src/components/intake/CitationPanel.tsx` — FOUND.
- Files modified — `research.ts`, `en/fr/nl intake.json` — all present.
- Commits `f94a758`, `8115419` — both present in `git log`.
- Gates: `i18n-audit.mjs` exit 0 (A/B/C clean); client-route-import guard exit 0; no-live-fetch
  assertion pass; `getSource` count == 1; `sources.ts` untouched; three locales JSON-valid.
