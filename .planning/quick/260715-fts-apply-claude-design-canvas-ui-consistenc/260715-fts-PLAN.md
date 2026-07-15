---
phase: quick-260715-fts
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
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
autonomous: true
requirements: [QUICK-UI-CONSISTENCY]
must_haves:
  truths:
    - "Beheer pages (users/spaces/templates) show the gebruikers/spaces/templates nav ONCE in the sidebar, not twice"
    - "Intake detail sticky-header h1 renders serif lowercase (house heading), back-link/status-select/Bewerken use mono-uppercase"
    - "Admin tables (clients, users, spaces) render inside a boxed border-ink bg-paper wrapper with the standard mono thead"
    - "Sales status badges use house badge-ink/badge-outline/badge-dashed pills instead of ad-hoc colored spans"
    - "No page/section subtitle on the touched pages renders italic"
    - "Frontend compiles: npm run build:dev succeeds with zero type errors"
  artifacts:
    - path: "frontend/src/components/admin/ProductShell.tsx"
      provides: "Duplicate-Beheer-nav suppression when items === ADMIN_NAV"
    - path: "frontend/src/routes/admin.pulse.intakes.$id.tsx"
      provides: "House-style sticky header (serif lowercase h1, mono-uppercase chrome)"
    - path: "frontend/src/routes/admin.sales.projects.index.tsx"
      provides: "House badge pills + shadcn Button CTA + standard row action link"
  key_links:
    - from: "frontend/src/components/admin/ProductShell.tsx"
      to: "ADMIN_NAV manage block"
      via: "conditional render skipped when primary items already ARE ADMIN_NAV"
      pattern: "items !== ADMIN_NAV|items === ADMIN_NAV"
---

<objective>
Apply the Claude Design canvas edits (2026-07-15 pull) to the frontend source: UI-consistency
fixes across Pulse, Sales, Beheer, and client-facing pages, pre-UAT.

Purpose: Unify drifted page chrome (headings, back-links, tables, inputs, badges, subtitles) onto
the established house style before the Phase 12 parity UAT, so visual review isn't polluted by
known inconsistencies.

Output: Presentation-only class/markup edits across ~15 frontend files. Zero behavior change.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260715-fts-apply-claude-design-canvas-ui-consistenc/DIFF-NOTES.md

DIFF-NOTES.md is the AUTHORITATIVE worklist: per-file before→after Tailwind class changes plus a
"RECURRING RULES" section (rules 1-7) and explicit IGNORE items. If a change needs disambiguation,
reference HTML snapshots live in the session scratchpad at
`C:\Users\ajimimo\AppData\Local\Temp\claude\C--Users-ajimimo-Desktop-MOELD-nestor-intake-gcp\f604d827-a066-4dc9-a308-0fd8b16f8aad\scratchpad\ds-bundle\pages\` (original) and `...\ds-bundle\pulled\` (edited) — use only if present; DIFF-NOTES.md alone is sufficient.
</context>

<pre_verified_facts>
Planner already confirmed these against source — executor should trust them, not re-derive:

1. **SpaceSwitcher/LanguageSwitcher are shared components**, mounted ONLY in
   `frontend/src/components/admin/ProductShell.tsx` (lines ~62-74):
   `@/components/admin/SpaceSwitcher` and `@/components/LanguageSwitcher`.
   `admin.pulse.intakes.$id.tsx` contains NO local switcher copies — the canvas's "ad-hoc
   switcher styling" on the intake-detail snapshot describes drift that may live inside the
   shared components themselves, or may not exist in source at all (snapshot was hand-authored).
   → Executor: inspect `SpaceSwitcher.tsx` and `LanguageSwitcher.tsx` against DIFF-NOTES lines
   for pulse-intake-detail-review; if they already match the "standard variant" (label-mono
   label, border-ink, chevrons-up-down, combobox), the switcher items are a NO-OP. Do not
   invent changes.

2. **Duplicate Beheer nav root cause**: `admin.users.tsx:165`, `admin.spaces.tsx:116`,
   `admin.templates.tsx:109` all render `<ProductShell product={t("shell.productManage")}
   items={ADMIN_NAV}>`. ProductShell then ALSO renders the superadmin manage block mapping
   `ADMIN_NAV` (lines ~99-121). Fix in ProductShell: skip the manage block when
   `items === ADMIN_NAV` (reference equality is safe — all callers pass the same imported
   constant). Do NOT change the three route files' ProductShell invocations.

3. **Intake detail h1 drift confirmed** at `admin.pulse.intakes.$id.tsx:901`:
   `<h1 className="text-xl font-semibold tracking-tight text-ink">` — target per DIFF-NOTES:
   `font-serif text-2xl font-normal lowercase tracking-tight text-ink`. Sticky header wrapper is
   at line ~888; the back-link / status-select / Bewerken button are in the same header block.

4. **auth.login LanguageSwitcher wrapper**: change is on the wrapper div in `auth.login.tsx`
   (`w-36` → `w-40`), not inside LanguageSwitcher.tsx.
</pre_verified_facts>

<execution_rules>
- **Verify-before-edit**: DIFF-NOTES "before" strings were hand-authored from canvas snapshots.
  Before every edit, grep/read the actual class string in the TSX. If it differs slightly, apply
  the DESIGN INTENT (the "after" state per the recurring rules), never a blind string replace.
  If a described "before" state simply doesn't exist in source, record it as a no-op in the
  SUMMARY and move on.
- **Presentation-only**: className / static markup / icon-to-text-arrow edits ONLY. Do not touch
  data fetching, mutations, TanStack Query keys, auth logic, route paths, handlers, or i18n keys.
- **IGNORE list (canvas artifacts — do NOT implement)**: prototype `href`/`action`/`onclick`
  links, logo `<img>` → text flatten, logo class tweaks, nested `<main>` → `<div>`
  (skip; the app logo is a PNG and semantics fixes are out of scope).
- **shadcn constraint**: `frontend/src/components/ui/` must not be modified directly per project
  rules — EXCEPT that DIFF-NOTES explicitly allows the SelectTrigger house style to land either
  in `ui/select.tsx` or per-usage. Prefer per-usage `className` on the `<SelectTrigger>` in
  `admin.templates.tsx` (tailwind-merge via `cn()` lets usage classes override); only edit
  `ui/select.tsx` if the usage-level override provably cannot win the merge.
- **Recurring rules 1-7** in DIFF-NOTES apply across ALL touched files (drop italic subtitles,
  boxed tables, standard inputs, house h1, mono chrome links with `← ` prefix, house badges,
  `text-red-600` asterisks).
</execution_rules>

<tasks>

<task type="auto">
  <name>Task 1: Pulse routes + shared shell components</name>
  <files>frontend/src/routes/admin.pulse.intakes.$id.tsx, frontend/src/routes/admin.pulse.intakes.new.tsx, frontend/src/routes/admin.pulse.clients.tsx, frontend/src/routes/admin.pulse.clients.$id.tsx, frontend/src/routes/admin.pulse.search.tsx, frontend/src/components/admin/SpaceSwitcher.tsx, frontend/src/components/LanguageSwitcher.tsx</files>
  <action>
    Apply DIFF-NOTES entries for pulse-intake-detail-review/-decomposed, pulse-intake-new,
    pulse-clients-list, pulse-client-detail, pulse-search:

    1. `admin.pulse.intakes.$id.tsx` sticky header (block starting ~line 888):
       - h1 (line 901): `text-xl font-semibold tracking-tight` → `font-serif text-2xl font-normal lowercase tracking-tight` (keep `text-ink`).
       - back-link: `text-xs font-medium` → `font-mono text-xs uppercase tracking-wider`.
       - status `<select>`: → `border border-ink/30 bg-paper px-2.5 py-1.5 font-mono text-xs uppercase tracking-wider text-ink` (preserve existing behavior/handlers untouched).
       - Bewerken button: → `font-mono text-xs uppercase tracking-wider` + `hover:bg-ink/90` (was `text-xs font-medium` + `hover:bg-ink/80`).
       - Drop `italic` from section subtitles in this route.
    2. SpaceSwitcher.tsx / LanguageSwitcher.tsx: verify against the "standard variant" described
       in DIFF-NOTES (label-mono label, border-ink trigger, chevrons-up-down h-4 w-4 opacity-50,
       combobox). Per pre_verified_facts #1, these are likely already standard → expected NO-OP;
       only edit if a real drift is found. Never fork a page-local copy.
    3. `admin.pulse.intakes.new.tsx`: container `mx-auto max-w-2xl py-8` → `max-w-2xl`; card
       `border-ink/10 ... shadow-sm` → `border-ink` (no shadow); Klantnaam label →
       `block font-mono text-[11px] uppercase tracking-wider text-ink/70` with asterisk span
       `ml-1 text-red-600`; footer row + `border-t border-ink/15 pt-6`; Annuleer link →
       `font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink`.
    4. `admin.pulse.clients.tsx`: subtitle drop `italic`; table wrapper `mt-6` →
       `mt-6 border border-ink bg-paper`; thead row → `border-b border-ink font-mono text-xs uppercase tracking-wider text-ink`.
    5. `admin.pulse.clients.$id.tsx`: back-link — remove lucide ArrowLeft icon, use plain text
       `← Klanten` prefix (keep the Link component/`to` unchanged; remove the now-unused
       ArrowLeft import).
    6. `admin.pulse.search.tsx`: replace mono-eyebrow + base paragraph header with
       `<h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">ai-zoek</h1>`
       (or the existing i18n title text, lowercased styling via classes — do not hardcode over an
       i18n key if one is used) + subtitle `mt-1 text-sm text-ink/60`.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit</automated>
  </verify>
  <done>All six Pulse-area entries applied (or recorded as no-op with source evidence); no lucide ArrowLeft remains in clients.$id back-link; typecheck passes.</done>
</task>

<task type="auto">
  <name>Task 2: Sales routes</name>
  <files>frontend/src/routes/admin.sales.projects.index.tsx, frontend/src/routes/admin.sales.projects.$id.tsx, frontend/src/routes/admin.sales.projects.new.tsx, frontend/src/components/sales/SalesContextFields.tsx</files>
  <action>
    Apply DIFF-NOTES entries for sales-projects-list, sales-project-detail, sales-project-new:

    1. `admin.sales.projects.index.tsx`:
       - "+ Nieuw project" CTA: switch to the shadcn `Button` component (default variant) as used
         in Pulse, replacing the raw styled element — visual result: mono-uppercase, bg-ink,
         border-ink, h-10 px-6.
       - Status badges: replace ad-hoc colored spans with house pills — GELEVERD → `badge-ink`;
         IN ONDERZOEK → `badge-outline` + `mark-green`; INGEDIEND → `badge-ink`; CONCEPT →
         `badge-dashed`. If badges are produced by a helper (e.g. SalesStatusBadge or a
         STATUS_VARIANT map), edit the map/helper once rather than each call site.
       - Row action: `Open →` span → anchor/Link styling `font-mono text-[11px] uppercase tracking-wider text-ink hover:underline` (keep existing navigation mechanism — if the row
         is already a Link wrapper, style the span accordingly; do not add new routing).
    2. `admin.sales.projects.$id.tsx`: back-link `mb-4 ... text-[10px]` → `mb-3 ... text-xs`;
       subtitle drop `italic`; SalesStatusTracker done-step `bg-fluoGreen` → `bg-agenic-green`
       (verify the `agenic-green` token exists in styles.css/tailwind config — if only
       `fluoGreen` exists, keep the class that resolves to the same colour and note it);
       blue status span (`bg-blue-500/10 text-blue-700`) → `badge-ink`.
    3. `admin.sales.projects.new.tsx`: h1 `mt-6` → `mt-3`; subtitle `mt-2` → `mt-1`; ALL text
       inputs → `border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink` (drop `font-mono`, drop `border-ink/30`).
    4. `SalesContextFields.tsx`: ALL selects → same standard string as #3 (replace
       `border-ink/30 ... font-mono ... bg-paperLight` variants).
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit</automated>
  </verify>
  <done>Sales list/detail/new match house chrome: shadcn Button CTA, badge-* pills, standard inputs/selects, no italic subtitles; typecheck passes.</done>
</task>

<task type="auto">
  <name>Task 3: Beheer shell/pages + client-facing tweaks + build proof</name>
  <files>frontend/src/components/admin/ProductShell.tsx, frontend/src/routes/admin.users.tsx, frontend/src/routes/admin.spaces.tsx, frontend/src/routes/admin.templates.tsx, frontend/src/components/intake/FieldRenderer.tsx, frontend/src/routes/auth.login.tsx</files>
  <action>
    1. `ProductShell.tsx` duplicate-Beheer-nav fix (per pre_verified_facts #2): wrap the
       superadmin manage `<nav>` block (~lines 99-121) so it renders only when
       `isSuperadmin && items !== ADMIN_NAV`. Reference equality is intentional — all Beheer
       routes pass the imported `ADMIN_NAV` constant. Pulse/Sales pages keep the manage block.
    2. `admin.users.tsx`, `admin.spaces.tsx`, `admin.templates.tsx` (same 3 page rules each):
       header row `flex items-start justify-between gap-4` → add `flex-wrap`; subtitle drop
       `italic`; users+spaces tables: wrapper `mt-6` → `mt-6 border border-ink bg-paper`, thead
       → `border-b border-ink font-mono text-xs uppercase tracking-wider text-ink`.
    3. `admin.templates.tsx` SelectTrigger: add per-usage `className` overriding to the house
       style — `h-10 border-ink bg-paper2 focus:outline-none focus:border-ink` (plus dropping
       shadow-sm/ring visuals via the merge). Only touch `ui/select.tsx` if the usage-level
       override cannot take effect (see execution_rules).
    4. `FieldRenderer.tsx`: required asterisk `text-red-500` → `text-red-600` on ALL field
       labels (grep for `text-red-500` within the file; change only asterisk/label occurrences,
       not error-message text).
    5. `auth.login.tsx`: LanguageSwitcher wrapper `w-36` → `w-40`.
    6. Final proof: run the full dev build and lint.
  </action>
  <verify>
    <automated>cd frontend && npm run build:dev</automated>
  </verify>
  <done>Beheer pages render the management nav exactly once; tables/headers standardized; asterisk red-600; login switcher w-40; `npm run build:dev` completes successfully (and `npm run lint` reports no NEW errors vs pre-existing baseline).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| none new | Presentation-only Tailwind class and static markup edits; no input handling, auth, routing, or data-layer changes |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-Q260715-01 | Tampering | frontend edits accidentally altering handlers/auth gates | mitigate | execution_rules restrict edits to className/static markup; typecheck + build gate every task |
| T-Q260715-SC | Tampering | package installs | accept | no new packages installed in this plan |
</threat_model>

<verification>
1. `cd frontend && npx tsc --noEmit` — zero errors after each task.
2. `cd frontend && npm run build:dev` — succeeds at end of Task 3.
3. `git diff --stat` — only the 15 files in `files_modified` touched (SpaceSwitcher/LanguageSwitcher may be absent if no-op).
4. Grep gates:
   - `grep -c "italic" frontend/src/routes/admin.pulse.clients.tsx frontend/src/routes/admin.users.tsx frontend/src/routes/admin.spaces.tsx frontend/src/routes/admin.templates.tsx` → subtitles no longer italic (any remaining `italic` must be justified non-subtitle usage).
   - `grep -n "text-red-500" frontend/src/components/intake/FieldRenderer.tsx` → no asterisk occurrences remain.
</verification>

<success_criteria>
- All DIFF-NOTES change entries applied or explicitly recorded as no-op (with the actual source string cited) in the SUMMARY.
- All IGNORE items untouched (prototype links, logo flatten, nested-main).
- Zero behavioral diffs: no changes to hooks, handlers, queries, mutations, routes, or i18n keys.
- `npm run build:dev` green.
</success_criteria>

<output>
Create `.planning/quick/260715-fts-apply-claude-design-canvas-ui-consistenc/260715-fts-SUMMARY.md` when done.
Include a per-entry ledger: DIFF-NOTES entry → applied / no-op (with evidence) / deviation (with reason).
</output>
