# Canvas → code fuse notes (pull of 2026-07-15)

STATUS: pull COMPLETE — all 17 pages fetched to pulled/, diffed against pages/. Fuse pending.

## pulse-intake-detail-decomposed.html → admin.pulse.intakes.$id.tsx
- IDENTICAL change-set to pulse-intake-detail-review.html (same route): standardized SpaceSwitcher + LanguageSwitcher, serif-lowercase h1, mono-uppercase back-link/status-select/Bewerken, drop italic subtitle. Fuse ONCE in the route/components.

## RECURRING RULES (apply consistently while fusing)
1. Drop `italic` from all page/section subtitles.
2. Tables: wrapper `border border-ink bg-paper`; thead row `border-b border-ink font-mono text-xs uppercase tracking-wider text-ink`.
3. Inputs/selects: `border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink` (sans, not mono).
4. Page h1: `font-serif text-3xl (2xl in sticky headers) font-normal lowercase tracking-tight text-ink`; subtitle `mt-1 text-sm text-ink/60`.
5. Buttons/links in chrome: `font-mono text-xs uppercase tracking-wider`; text back-links use `← ` prefix, no lucide arrow icon.
6. Status pills: house badge classes (badge-ink / badge-outline / badge-dashed + mark-*) everywhere, incl. Sales.
7. Required asterisk: `text-red-600`.

Legend: real design changes to fuse vs canvas artifacts to ignore (e.g. `action="....html"` prototype links added by the canvas).

## auth-login.html → frontend/src/routes/auth.login.tsx
- CHANGE: LanguageSwitcher wrapper `w-36` → `w-40` (frontend/src/components/LanguageSwitcher.tsx usage on login page)
- IGNORE: `action="admin-home.html"` added to form (canvas prototype link)

## admin-home.html → frontend/src/routes/admin.index.tsx
- NO design changes. Only canvas prototype links (pulse card href="#"→"pulse-intakes-list.html", logout onclick). IGNORE all.

## pulse-intakes-list.html → admin.pulse.intakes.index.tsx / ProductShell.tsx
- NO design changes. Prototype links only. NOTE: sidebar `<img agenic-logo.png onerror>` flattened to text `<div>agenic</div>` — canvas artifact (asset missing on canvas), DO NOT change app logo. Same flattening appears on other Pulse pages; ignore everywhere.

## pulse-intake-new.html → frontend/src/routes/admin.pulse.intakes.new.tsx
- CHANGE: page container `mx-auto max-w-2xl py-8` → `max-w-2xl` (left-align form under header, drop extra top padding)
- CHANGE: form card `border border-ink/10 bg-paper p-6 shadow-sm` → `border border-ink bg-paper p-6` (full ink border, no shadow)
- CHANGE: Label (Klantnaam) `text-sm font-medium leading-none peer-disabled:... text-sm font-semibold text-ink` → `block font-mono text-[11px] uppercase tracking-wider text-ink/70`; asterisk `<span class="font-normal text-ink/60">*</span>` → `<span class="ml-1 text-red-600">*</span>`
- CHANGE: footer row `flex items-center justify-between` → + `border-t border-ink/15 pt-6`; Annuleer link `text-sm text-ink/60 hover:text-ink hover:underline` → `font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink`

## pulse-clients-list.html → frontend/src/routes/admin.pulse.clients.tsx
- CHANGE: subtitle `mt-1 font-sans text-sm italic text-ink/60` → `mt-1 font-sans text-sm text-ink/60` (drop italic)
- CHANGE: table wrapper `mt-6` → `mt-6 border border-ink bg-paper` (boxed table, same as intakes list)
- CHANGE: thead row `border-b border-ink/30 font-mono text-[10px] uppercase tracking-wider text-ink/70` → `border-b border-ink font-mono text-xs uppercase tracking-wider text-ink` (match intakes table header)

## pulse-client-detail.html → frontend/src/routes/admin.pulse.clients.$id.tsx
- CHANGE: back-link — replace lucide arrow-left `<svg>` + "Klanten" with plain text `← Klanten` (standard text-arrow back-link style)
- IGNORE: inner `<main>` → `<div>` (canvas fixing invalid nested <main>; check source — if route uses <main> inside ProductShell's <main>, optionally fix semantics, not visual)

## sales-projects-list.html → frontend/src/routes/admin.sales.projects.index.tsx
- CHANGE: "+ Nieuw project" CTA `bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90` → full Button default classes `inline-flex items-center justify-center gap-2 whitespace-nowrap font-mono text-xs uppercase tracking-wider transition-colors ... bg-ink text-paper border border-ink hover:bg-ink/90 h-10 px-6 py-3` (use shadcn Button component like Pulse)
- CHANGE: SalesStatusBadge ad-hoc colored spans → house status pills: GELEVERD `bg-ink text-paper`-span → `badge-ink`; IN ONDERZOEK amber span → `badge-outline` + `mark-green`; INGEDIEND blue span → `badge-ink`; CONCEPT ink/10 span → `badge-dashed` (align sales statuses with Pulse StatusPill system)
- CHANGE: row action `<span class="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink">Open →</span>` → `<a class="font-mono text-[11px] uppercase tracking-wider text-ink hover:underline">Open →</a>` (match Pulse table action links)
- IGNORE: logo text-div class tweak (logo is a PNG in the real app)

## sales-project-detail.html → frontend/src/routes/admin.sales.projects.$id.tsx
- CHANGE: back-link `mb-4 block font-mono text-[10px] uppercase tracking-wider` → `mb-3 block font-mono text-xs uppercase tracking-wider` (standard back-link size/spacing)
- CHANGE: subtitle `mt-1 text-sm italic text-ink/60` → `mt-1 text-sm text-ink/60` (drop italic — same rule as clients list)
- CHANGE: SalesStatusTracker done-step `bg-fluoGreen` → `bg-agenic-green` (token naming; same colour)
- CHANGE: Status badge blue span (`bg-blue-500/10 text-blue-700`) → `badge-ink` (house pill, matches sales list change)
- IGNORE: logo text-div class tweak

## sales-project-new.html → frontend/src/routes/admin.sales.projects.new.tsx (+ SalesContextFields.tsx)
- CHANGE: header rhythm — h1 `mt-6` → `mt-3`, subtitle `mt-2` → `mt-1` (match standard back-link→h1→subtitle spacing)
- CHANGE: ALL text inputs `border border-ink/30 bg-paper px-3 py-2 font-mono text-sm` → `border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink` (standard Input: full ink border, paper2 bg, sans font)
- CHANGE: ALL selects (SalesContextFields) `border border-ink/30 px-3 py-2 font-mono text-sm bg-paperLight focus:outline-none focus:border-ink` → `border border-ink bg-paper2 px-3 py-2 text-sm focus:outline-none focus:border-ink` (same standard)
- IGNORE: logo text-div class tweak

## admin-users.html → frontend/src/routes/admin.users.tsx (+ ProductShell)
- CHANGE: removed duplicate "Beheer" sidebar nav section — on Beheer pages the primary nav already IS gebruikers/spaces/templates, so ProductShell must NOT render the extra ADMIN_NAV block there (duplicate nav fix)
- CHANGE: header row `flex items-start justify-between gap-4` → `flex flex-wrap items-start justify-between gap-4`
- CHANGE: subtitle drop `italic`
- CHANGE: table wrapper `mt-6` → `mt-6 border border-ink bg-paper`; thead `border-b border-ink/30 font-mono text-[10px] ... text-ink/70` → `border-b border-ink font-mono text-xs ... text-ink` (standard table treatment)

## admin-spaces.html → frontend/src/routes/admin.spaces.tsx (+ ProductShell)
- Same 4 rules as admin-users: remove duplicate Beheer sidebar nav; header row + flex-wrap; subtitle drop italic; table boxed (`border border-ink bg-paper`) + thead `border-ink text-xs text-ink`

## admin-templates.html → frontend/src/routes/admin.templates.tsx (+ ProductShell, ui/select.tsx)
- Same shell rules: remove duplicate Beheer nav; header + flex-wrap; drop italic subtitle
- CHANGE: SelectTrigger `h-9 ... border-input bg-transparent ... shadow-sm ring-offset-background focus:ring-1 focus:ring-ring` → `h-10 ... border-ink bg-paper2 ... focus:outline-none focus:border-ink` (house select style — shared ui/select.tsx or per-usage className)

## client-results.html → intake.$id.results.tsx
- UNCHANGED (no design edits)

## client-intake-form.html → frontend/src/components/intake/FieldRenderer.tsx
- CHANGE: required asterisk `text-red-500` → `text-red-600` on ALL field labels (align with admin form asterisk colour)

## pulse-intake-detail-review.html → admin.pulse.intakes.$id.tsx (+ SpaceSwitcher/LanguageSwitcher usage)
- CHANGE: SpaceSwitcher on this page had ad-hoc styling (`border-ink/20`, chevron-down, `text-[10px]` label, hover:border-ink) → standard variant (`label-mono text-ink/40` label in `flex flex-col gap-1`, `border-ink`, chevrons-up-down icon `h-4 w-4 opacity-50`, role=combobox). If the component itself is shared, the drift is in this page's local copy — unify to the shared component.
- CHANGE: LanguageSwitcher segmented NL/FR/EN buttons (`inline-flex border border-ink/20` + three buttons) → standard combobox dropdown ("Nederlands" + chevrons-up-down), full width, as on all other pages.
- CHANGE: sticky-header back-link `text-xs font-medium` → `font-mono text-xs uppercase tracking-wider`
- CHANGE: h1 `text-xl font-semibold tracking-tight` → `font-serif text-2xl font-normal lowercase tracking-tight` (house heading)
- CHANGE: status <select> `border border-ink/10 bg-paper px-2.5 py-1.5 text-xs font-medium text-ink/80` → `border border-ink/30 bg-paper px-2.5 py-1.5 font-mono text-xs uppercase tracking-wider text-ink`
- CHANGE: Bewerken button `text-xs font-medium ... hover:bg-ink/80` → `font-mono text-xs uppercase tracking-wider ... hover:bg-ink/90`
- CHANGE: section subtitle drop `italic`
- IGNORE: logo text-xl→text-lg (logo is PNG in app); inner `<main>` → `<div>` (invalid nested main — optional semantic fix in source)

## pulse-search.html → frontend/src/routes/admin.pulse.search.tsx
- CHANGE: page header `<p class="font-mono text-xs uppercase tracking-wider text-ink/60">AI-zoek alles</p>` + `<p class="mt-3 font-sans text-base text-ink/70">…</p>` → `<h1 class="font-serif text-3xl font-normal lowercase tracking-tight text-ink">ai-zoek</h1>` + `<p class="mt-1 text-sm text-ink/60">…</p>` (standard page header pattern)
