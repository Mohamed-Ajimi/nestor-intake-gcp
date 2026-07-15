# Canvas → code fuse notes ROUND 2 (pull of 2026-07-15, client-intake-form only)

Target: frontend/src/components/intake/IntakeForm.tsx (hosted by frontend/src/routes/intake.$id.tsx)
Baseline: the app is ALREADY a per-section stepper (sidebar nav + Stap X/Y + Vorige/Volgende). The canvas redesign keeps that model and upgrades the chrome. Fuse the design intent below; the canvas's <script> and its invented content for sections 3-12 are PROTOTYPE FILLER — the real form renders fields from the backend template schema. Do NOT fabricate fields/sections.

## Header (IntakeForm header block)
- CHANGE: `<header class="mb-10">` → `mb-12 border-b border-ink/15 pb-10` (canvas used inline padding-bottom:2.5rem = pb-10; use the Tailwind class)

## Layout grid
- CHANGE: `grid gap-8 md:grid-cols-[320px_1fr]` → `grid gap-8 md:grid-cols-[300px_minmax(0,1fr)]` (narrower sidebar; minmax guards overflow)
- CHANGE: form column gets `min-w-0`
- KEEP: sidebar `hidden md:block` responsive behavior (canvas is desktop-only; do not remove mobile handling)

## Sidebar — NEW progress header (above the section nav)
- ADD: row `flex items-baseline justify-between gap-3 px-3`:
  - label `font-mono text-[11px] uppercase tracking-wider text-ink/60` → "Voortgang" (use i18n key if the form is translated; check existing t() usage)
  - counter `font-mono text-[11px] tabular-nums text-ink/60` → "{cur+1} / {total}"
- ADD: progress bar under it: track `mt-2 h-1 bg-ink/10 mx-3`, fill `h-1 bg-ink` width = ((cur+1)/total)*100% (inline style width, derived from existing step state — purely presentational)
- CHANGE: nav `mt-5 space-y-1 overflow-y-auto max-h-[calc(100vh-12rem)]` (was space-y-1 sticky only; keep sticky top-8 on the wrapper)

## Sidebar — section buttons (numbered + state colors)
- ADD: number column between nav-mark and title: `<span class="w-6 shrink-0 tabular-nums">01</span>` (zero-padded index; `text-ink` when current/completed, `text-ink/40` when future)
- CHANGE state classes: current = `bg-paper2 text-ink` + `nav-mark nav-mark-green` (unchanged); COMPLETED (before current / dirty-done) = `text-ink hover:bg-ink/5` + `nav-mark nav-mark-ink`; future = `text-ink/60 hover:bg-ink/5 hover:text-ink` + plain `nav-mark`. Map onto the app's existing section-state logic (it already tracks per-section state for nav-mark variants — extend to text color + numbers).

## Form area
- CHANGE: textareas rendered by FieldRenderer get `resize-y` (canvas: style="resize:vertical") — textareas only, not inputs
- CHECK: last step's primary button label should read "Verstuur intake →" (canvas). If the app already renders a distinct submit button on the final section, keep its logic — align label/styling only (btn-primary).
- Step label "Stap X / Y" + "Alle wijzigingen opgeslagen" row: unchanged.

## IGNORE (canvas prototype artifacts)
- The entire <script> block (goStep/localStorage) — app already has real step state.
- Invented content of sections 1 and 3–12 (NDA checkbox panel, question repeater cards, upload dropzone, selects): the real form renders from the template schema via FieldRenderer. Do NOT add/alter fields. (If some of these field types later need styling parity, that's a separate task.)
- onclick handlers, data-step-* attributes, element ids (step-counter etc.) — implement with React state, not DOM ids.
