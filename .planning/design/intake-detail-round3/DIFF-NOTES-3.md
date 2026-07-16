# DIFF-NOTES-3 — Intake detail canvas round 3 fuse worklist

Source: `.planning/design/intake-detail-round3/raw.diff` (pages/ = generated, pulled/ = operator-edited on claude.ai/design; 19 snapshots of `admin.pulse.intakes.$id`).
Method: full read of steps 01–08 + frequency analysis of all +/- lines + targeted slicing of steps 09–19. Every distinct change is classified below. An executor should be able to fuse from this file alone.

Verified against current React source (line numbers as of commit 792237d):
- Route: `frontend/src/routes/admin.pulse.intakes.$id.tsx`
- `frontend/src/components/intake/NextStepBanner.tsx`, `IntakeWorkflowStepper.tsx`, `FieldDisplay.tsx`, `FieldRenderer.tsx`, `ContextPackBlock.tsx`, `RecipientPicker.tsx`, `AISkillsPanel.tsx`
- `frontend/src/components/admin/ProductShell.tsx`

---

## Recurring rules (appear in all/most of the 19 steps — fuse once in React)

### R1 — Sticky sidebar + horizontal clip (all 19 steps)
- `<body>` gains `style="overflow-x:clip"`.
  React: no `<body>` access per page — apply `overflow-x-clip` on the ProductShell root `<div className="flex min-h-screen bg-paper">` (ProductShell.tsx ~line 38) or add `overflow-x: clip` to `body` in `frontend/src/styles.css`. Prefer the ProductShell root class (scoped, no global side effects).
- ProductShell `<aside>`:
  OLD `hidden w-64 shrink-0 flex-col border-r border-ink px-5 py-6 md:flex`
  NEW same + `style="position:sticky;top:0;height:100vh;overflow-y:auto"`
  React (ProductShell.tsx line 40): add Tailwind `sticky top-0 h-screen overflow-y-auto` (aside is `hidden md:flex`, so plain utilities are fine; use `h-screen` for 100vh).

### R2 — Merged workflow panel (all 19 steps) — the big structural change
Three stacked blocks (NextStepBanner above stepper, stepper, statusBanner below) are fused into ONE bordered card, in a NEW order:

```
<div class="mb-8 border border-ink/15 bg-paper">          ← new panel wrapper
  <div class="px-6 pt-6 pb-4"> …IntakeWorkflowStepper… </div>   ← was <div class="mb-6">
  [statusBanner strip — only when that state renders one]
  [NextStepBanner — always last of the core trio]
  [semantic search section — steps 12–18 only, see R9]
  [scope-note block — step 11 only, see S6]
</div>
```

- Stepper wrapper: OLD `mb-6` → NEW `px-6 pt-6 pb-4`. React: route line ~1057 `<div className="mb-6"><IntakeWorkflowStepper …/></div>`. IntakeWorkflowStepper's own internal markup is UNCHANGED.
- statusBanner strip: OLD `mb-6 border border-ink/10 bg-paper2 px-4 py-3 text-sm text-ink/70` → NEW `border-t border-ink/10 bg-paper2 px-6 py-3 text-xs text-ink/70`. React: route lines 1105–1108 (`STATUS_WITH_BANNER` block).
- NextStepBanner outer div: OLD `mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5` → NEW `border-t border-ink/10 border-l-4 bg-paperLight px-6 py-5` (inline `borderLeftColor` accent per phase UNCHANGED; all inner markup UNCHANGED). React: NextStepBanner.tsx line 320.
- ROUTE REORDER REQUIRED: current JSX order is NextStepBanner (line ~977) → semantic search (~1015) → stepper (~1057) → editBanner → statusBanner (~1105). New order inside the panel: stepper → statusBanner → NextStepBanner → semantic search. The edit-mode yellow editBanner (route ~1440s region `border-l-agenic-yellow`) was NOT part of the panel in the snapshots (step 19 shows the panel with stepper + NextStepBanner only) — keep editBanner where it is, outside/below the panel.
- States without a statusBanner (steps 04/05 AI-review) render panel = stepper + NextStepBanner only; the conditional rendering handles this automatically.
- SkillRunProgress card (step 03/10, the big `font-mono text-2xl tabular-nums` timer card) stays ABOVE the panel, unchanged.
- AIReviewPanel top banner (`data-ai-review-block`) stays BELOW the panel, unchanged.

### R3 — Sticky header: StatusPill removed, select restyled (all 19 steps)
- StatusPill `<span class="badge-…">` next to the select is DELETED in every step (draft/submitted/reviewed/validated/in_research/delivered/decomposed/archived variants all removed). React: route line ~934 (`<StatusPill status={intake.status} />` in the header flex). The select becomes the only status control in the header.
  NOTE: KEEP the `StatusPill` component and its usage at route line ~1167 — the "Status" row inside Intake-info still shows the badge in every snapshot.
- Status `<select>`: OLD `border border-ink/30 bg-paper px-2.5 py-1.5 font-mono text-xs uppercase tracking-wider text-ink focus:border-ink focus:outline-none` → NEW `border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink focus:outline-none` (border-ink/30→border-ink, px-2.5→px-3, drop `focus:border-ink`). React: route line 925.

### R4 — Intake-info h2 → serif-lowercase house style (all 19 steps)
OLD `text-sm font-semibold uppercase tracking-wide text-ink/60`
NEW `border-b border-ink/30 pb-2 mb-2 font-serif text-2xl font-normal lowercase text-ink`
(same style the section h2s already use). React: route, the Intake-info `<section>` heading (search `intakeDetail.info` / the section with the Meta `<dl className="mt-4">`). `dl mt-4` unchanged.

### R5 — All `<dd>` gain `min-w-0` (all 19 steps, every dl row: Meta, LinkRow, FieldDisplay)
OLD `font-sans text-ink` → NEW `min-w-0 font-sans text-ink`.
React: two definitions cover all rows —
- route line 1416 (`Meta` helper `<dd className="font-sans text-ink">`; LinkRow rows render via the same helper or duplicate the class — grep `<dd` in the route and add `min-w-0` to each)
- FieldDisplay.tsx line 115 (`<dd className="font-sans text-ink">`).

### R6 — Content sections boxed (all steps with sections, 02–19)
OLD `<section id="sec-…" class="scroll-mt-32">` → NEW `scroll-mt-32 border border-ink/10 bg-paper p-6`.
React: route section render loop (each schema section `<section id={…} className="scroll-mt-32">`). Intake-info section already has `border border-ink/10 bg-paper p-6` — unchanged. Section h2/p/dl inner markup unchanged.

### R7 — LinkRow "Kopieer" button restyled mono-outline (steps 02–19; draft keeps primary)
OLD `inline-flex items-center gap-1 border border-ink/10 px-2.5 py-1 text-xs font-medium text-ink/70 hover:border-ink/10 hover:bg-ink/5` (variant without the redundant `hover:border-ink/10` also exists)
NEW `inline-flex items-center gap-1.5 border border-ink px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5`
React: route lines 1506 and 1550 (both LinkRow copy buttons). The draft state's prominent primary Kopieer (`bg-ink … font-mono uppercase … hover:bg-ink/90`, step 01) is UNCHANGED — the two-variant logic (primary in draft, outline elsewhere) stays.

### R8 — Edit-mode header buttons restyled (visible in step 19 only, but it's the shared header)
- Annuleer: OLD `inline-flex items-center gap-1.5 border border-ink/10 bg-paper px-3 py-1.5 text-xs font-medium text-ink/70 hover:bg-ink/5` → NEW `inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5`. React: route line 950.
- Opslaan: OLD `inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 text-xs font-medium text-paper hover:bg-ink/80 disabled:opacity-50` → NEW `…bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50`. React: route line 959.
- (Bewerken button already matches the mono style — unchanged.)
- Optional consistency follow-up (NOT in the canvas): `DeliveredAtEditor` save button at route line 1460 still uses the old `text-xs font-medium … hover:bg-ink/80` style. Not shown in any snapshot; align it or leave it — executor's call, flag in commit message if changed.

### R9 — Semantic search section moved INSIDE the workflow panel (steps 12–18)
The whole `showSemanticSearch` `<section class="border border-ink/20 bg-paperLight p-4 mb-6">` block is byte-identical but relocated: it now sits inside the merged panel, after NextStepBanner, before the panel's closing tag. Its own classes and inner markup are UNCHANGED (including 🔍 Zoek button and result rows). React: move the `{showSemanticSearch && (<section …>)}` block (route lines 1014–1050ish) into the new panel wrapper as the last child.

---

## Per-component changes (grouped by target file)

### frontend/src/routes/admin.pulse.intakes.$id.tsx
1. Build the merged workflow panel wrapper `mb-8 border border-ink/15 bg-paper` and reorder children: stepper (in `px-6 pt-6 pb-4` div) → statusBanner (restyled per R2) → `<NextStepBanner …/>` → semantic search (R9) → scope-note (S6, decomposed only). (R2, R9)
2. Remove header `<StatusPill/>` (line ~934); keep Meta-row StatusPill (line ~1167). (R3)
3. Restyle status select (line 925). (R3)
4. Intake-info h2 → serif lowercase (R4).
5. `min-w-0` on Meta/LinkRow `<dd>` (line 1416 + any inline dd). (R5)
6. Section loop: add `border border-ink/10 bg-paper p-6` to each section (R6).
7. LinkRow Kopieer buttons → mono-outline (lines 1506, 1550) (R7).
8. Edit-mode Annuleer/Opslaan header buttons → mono (lines 950, 959) (R8).
9. Archive confirm dialog: replace `confirm(t("intakeDetail.confirm.archive"))` (line 701) with house-style dialog — see S3.
10. Scope-note block for decomposed — see S6 (currently only a toast at line 676).

### frontend/src/components/intake/NextStepBanner.tsx
- Outer div (line 320): `mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5` → `border-t border-ink/10 border-l-4 bg-paperLight px-6 py-5`. Everything else (accent colors, PrimaryBtn/SecondaryBtn/RunningClock, all phase texts) UNCHANGED.

### frontend/src/components/admin/ProductShell.tsx
- Root div: add `overflow-x-clip` (R1).
- `<aside>` (line 40): add `sticky top-0 h-screen overflow-y-auto` (R1).

### frontend/src/components/intake/FieldDisplay.tsx
- Line 115: `<dd className="font-sans text-ink">` → `min-w-0 font-sans text-ink` (R5).

### frontend/src/components/intake/IntakeWorkflowStepper.tsx
- NO internal changes. Only its route-level wrapper changes (R2).

### Components with ZERO changes in this round
AIReviewPanel.tsx (all suggestion cards/ExtraQuestionsSection identical), SkillRunProgress.tsx, ContextPackBlock.tsx (existing markup; see S4 for the kept PROPOSED preview), ResearchArtifacts.tsx, FinalReportBlock.tsx, RecipientPicker.tsx (see S5), AISkillsPanel.tsx (see S7), FieldRenderer.tsx (see S2 for the kept PROPOSED visualization).

---

## State-specific / new functionality (PROPOSED blocks — user's verdict)

All four PROPOSED blocks from snapshot generation were **KEPT verbatim** (zero diff lines inside them). Keeping = the operator endorses them → they are NEW functionality to build, not restyles.

### S1 — RecipientPicker dialogs (steps 07 + 15): KEPT
- Step 07 (validation): member rows show name only, email in `title` attribute.
- Step 15 (results): member rows show name **plus inline email** — `Els Vermeulen <span class="text-ink/50">· els.vermeulen@vandelay.be</span>`.
- Current React (RecipientPicker.tsx line 139): `label = m.name ?? m.email` — name only, no tooltip, no inline email.
- The two snapshots are mutually inconsistent → NEEDS DECISION D2 below. Everything else about the dialog (overlay, checkbox rows pre-checked per D-07, ghost cancel + primary confirm) matches existing React.

### S2 — Deferred-delete visualization in edit mode (step 19): KEPT → BUILD
FieldRenderer already defers deletes functionally (WR-04, `onDeferRemove`, line ~414), but a deferred file currently just disappears from the draft list. The kept design keeps it visible:
```html
<li class="flex items-center justify-between border border-dashed border-ink/30 bg-paper2/50 px-3 py-2 text-sm">
  <span class="truncate text-ink/40 line-through">productcatalogus-verpakkingen.pdf · 8,1 MB</span>
  <span class="ml-3 flex shrink-0 items-center gap-2">
    <span class="font-mono text-[10px] uppercase tracking-wider text-ink/50">wordt verwijderd bij opslaan</span>
    <button class="text-xs font-medium text-ink underline underline-offset-2 hover:text-ink/70">Herstel</button>
  </span>
</li>
```
Target: FieldRenderer.tsx FileControl (edit mode / `onDeferRemove` present). Requires: keep removed files in a "pending removal" list in the draft, render the dashed row, and a **Herstel** (undo) action that un-defers. New i18n keys needed (`wordt verwijderd bij opslaan`, `Herstel`). Behavioral — see NEEDS DECISION D3.

### S3 — Archive confirm dialog (step 18): KEPT → BUILD
Replaces `confirm()` at route line 701. Kept markup:
- overlay `fixed inset-0 bg-ink/40 z-50`; centered `role="alertdialog"` card `w-full max-w-md border border-ink bg-paper p-6 shadow-lg`
- h2 `font-serif text-2xl font-normal lowercase text-ink` — "Intake archiveren?"
- body `mt-3 font-sans text-sm leading-relaxed text-ink/70` — "Het project wordt afgesloten en verdwijnt uit de actieve intake-lijst. De intake wordt alleen-lezen; de resultaten-pagina van de klant blijft bereikbaar."
- footer right-aligned: SecondaryBtn "Annuleer" (`border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider hover:border-2`) + PrimaryBtn "Archiveer" (`bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85`).
Implement with shadcn AlertDialog (or the RecipientPicker Dialog pattern) styled to match. New i18n keys. Note: `confirm(discardChanges)` at line 779 was NOT redesigned — leave it (or optionally reuse the same dialog; flag as follow-up).

### S4 — Inline context-pack preview (step 11): KEPT → BUILD
In ContextPackBlock, between the "Laatst gegenereerd: …" meta line and the questions accordion, add:
```html
<div class="mt-4 border border-ink/15 bg-paper p-4">
  <div class="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink/50">Inhoud — preview</div>
  <p class="font-serif text-lg lowercase text-ink">context summary</p>
  <p class="mt-1 font-sans text-sm leading-relaxed text-ink/80">…first summary paragraph of the pack…</p>
</div>
```
The app currently only exposes this behind the "Bekijk laatste" modal. Content = the pack's context-summary section (first heading + paragraph), not the whole markdown. Target: ContextPackBlock.tsx (~after the meta/actions row, before questions accordion ~line 570s). See NEEDS DECISION D4.

### S5 — Step 11 scope-note block moved inside panel: see S6/D5.

### S6 — "Einde platform-scope" note block (step 11, decomposed): moved INSIDE the panel
Snapshot markup (kept, relocated as last child of the workflow panel):
```html
<div class="mb-5 border border-ink/10 bg-paper2 px-4 py-3 text-sm text-ink/70">
  <span class="mr-2 font-mono text-[10px] uppercase tracking-wider text-ink/50">Einde platform-scope</span>
  Automatische research valt buiten deze fase (stopt bij <span class="font-mono text-xs">decomposed</span>). De onderzoeksfase wordt buiten dit systeem gestart en opgevolgd.
</div>
```
React today has NO such block — only `toast.message(autoResearchOutOfScope)` when the CTA is clicked (route line 676). Building it = a persistent note rendered in phase `awaiting_research_start`. See NEEDS DECISION D5.

### S7 — AISkillsPanel transcribe button (steps 01–19): NO ACTION
The "Transcribeer <filename>" enabled button exists identically in pages/ and pulled/ (zero diff lines) AND is already implemented in React (AISkillsPanel.tsx lines 124–150, per-source buttons from 12-03). Round-3 fuse: nothing to do.

### Popup steps 07 / 15 / 18 backgrounds
The underlying page in the popup snapshots carries the same recurring edits as its base step (already covered by R1–R9). The dimmed-page + fixed-overlay presentation is canvas staging, not a design change.

---

## NEEDS DECISION (not purely presentational)

- **D1 — Header StatusPill removal (R3).** Removes the redundant status badge; the `<select>` is then the only header status indicator. Low risk (badge still shown in Intake-info), but it deletes a visible state signal (e.g. the pill's updating/color semantics). Recommend: accept as designed.
- **D2 — RecipientPicker email display is inconsistent between the two kept snapshots.** Step 07 = tooltip-only (`title={email}`), step 15 = inline `· email` in muted text. Pick ONE for both validation and results pickers. Recommend: inline email (step 15 style) — more informative, matches D-07 transparency intent.
- **D3 — Deferred-delete visualization (S2).** Requires changing FieldRenderer draft-state semantics: deferred-removed files must stay in the rendered list (flagged), plus a new "Herstel" un-defer action (needs a small API change from `onDeferRemove(paths)` to also support un-defer, and the parent draft in the route must track pending removals without dropping the file from the value until save). Behavioral, touches WR-04 contract.
- **D4 — Inline context-pack preview (S4).** Needs a rule for WHAT to show (snapshot shows the "context summary" heading + one paragraph). Requires parsing/slicing the pack markdown. Decide: first section only (recommended, matches snapshot) vs. full markdown collapsed.
- **D5 — Scope-note as persistent block (S6).** Today the out-of-scope message is a toast fired on CTA click; the design makes it an always-visible note in the decomposed state, inside the workflow panel. Recommend: build the static block AND keep the toast on click (harmless duplication), or drop the toast.
- **D6 — Semantic search inside the workflow panel (R9).** Purely layout, but it couples a data tool into the "workflow" card and its `bg-paperLight p-4 mb-6` box now nests inside a bordered panel (double border look, bottom gap from `mb-6` inside the panel). Fuse as-is per canvas; if the nested `mb-6` looks off in the real app, trimming it to `m-0 border-x-0 border-b-0 border-t border-ink/10` is a defensible normalization — flag whichever is done.

---

## IGNORE list (canvas artifacts — do NOT port)

- Prototype navigation: `href="admin-home.html"`, `href="pulse-client-detail.html"`, any `*.html` links, `onclick` handlers, `<form action>` — React uses router links/handlers.
- `<option selected>` attributes and hardcoded status option lists — React binds `value`.
- All sample content: Vandelay data, dates (10/14/15/16 jul 2026), timer values (01:23, 00:47), search results (V2/V3/V4 rows), file names/sizes — placeholders only (except where they define STRUCTURE, e.g. S2/S4 markup).
- Comment re-indentation: the canvas de-indented several `<!-- src: … -->` comments (they appear as - / + pairs with identical text). Pure whitespace.
- Move-artifact +/- pairs: every NextStepBanner/statusBanner/semantic-search inner line appears as both - and + because the blocks were relocated — the inner markup itself is unchanged (only the outer wrappers changed, per R2/R9).
- Line-ending warnings (LF/CRLF) at the top of raw.diff / diffstat.txt.
- Popup snapshot staging: fixed overlays, "Onderliggende pagina = stap X, gedimd" comments.
- `supabase`/`badge-*`/`mark-*` utility classes referenced in deleted StatusPill markup — the classes themselves stay (used in Meta row).

---

## Fuse checklist (suggested execution order)

1. ProductShell: R1 (2 class edits).
2. NextStepBanner: outer div class swap (1 edit).
3. Route: R2 panel + reorder (stepper/statusBanner/NextStepBanner/semantic-search), R3 select + StatusPill removal, R4 h2, R5 dd, R6 sections, R7 copy buttons, R8 edit buttons.
4. FieldDisplay: R5.
5. S3 archive dialog (new component + i18n).
6. S6 scope-note block (new conditional block + i18n) — after D5.
7. S4 inline CP preview (ContextPackBlock) — after D4.
8. S2 deferred-delete visualization (FieldRenderer + route draft state) — after D3.
9. S1/D2 RecipientPicker inline emails.
10. Regenerate snapshots / visual check across all 19 states.
