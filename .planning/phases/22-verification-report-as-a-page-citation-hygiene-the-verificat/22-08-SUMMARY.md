---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 08
subsystem: frontend
tags: [verification-report, citations, collapsible, sheet, nav-rail, a11y, d-22-3, d-22-4]
requires:
  - "frontend/src/lib/research/citationIndex.ts (buildCitationIndex, plan 22-02)"
  - "frontend/src/components/intake/CitationPanel.tsx (CitationMarker + CitationTierGlyph exports, plan 22-03)"
  - "frontend/src/components/intake/VerificationReport.tsx nine anchor ids + sourcesCited const (plan 22-07)"
  - "@/components/ui/collapsible, @/components/ui/sheet (vendored, unmodified)"
provides:
  - "A page-level Sheet hosting CitationPanel, reachable from ANY section's [n] marker"
  - "Section E8 collapsed on load with its source figure visible and announced while closed"
  - "A sticky section nav rail with IntersectionObserver active marking"
  - "THE buildCitationIndex SWITCHOVER — the module now has its first and only consumer"
affects:
  - "frontend/src/routes/admin.pulse.runs.$runId.verification.tsx (the component's one mount — untouched, props unchanged)"
tech-stack:
  added: []
  patterns:
    - "WAI-ARIA accordion shape: <h2> wraps CollapsibleTrigger (a heading is not permitted content for a button)"
    - "Radix Dialog as a page-level host so open state is independent of any collapsed container"
    - "IntersectionObserver keyed on a joined-id STRING, not the entry array, so it is not torn down every render"
key-files:
  created: []
  modified:
    - frontend/src/components/intake/VerificationReport.tsx
    - .planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/deferred-items.md
decisions:
  - "The rail lists the unverified and cost sections unconditionally, because both always render; every other entry is gated on the same length the section itself gates on, so the rail can never advertise a destination the document lacks"
  - "The unverified rail entry passes no separate count — the existing unverifiedTitle key already carries the figure in its own parentheses; one number, once"
  - "sourcesCited gained a FOURTH reader (the rail) rather than a second .length call, strengthening 22-UI-SPEC §3.2 beyond the criterion's stated count of 3"
metrics:
  duration: ~55min
  completed: 2026-08-12
  tasks: 3
  commits: 4
---

# Phase 22 Plan 08: Collapsed Citation List + Page-Level Sheet + Section Nav Rail Summary

The citation list now opens closed with its source figure legible and announced, the citation panel
was hoisted out of that list into a root-level Radix Sheet so a `[n]` click from any section still
opens something visible, and a sticky nav rail puts every rendered section one click from the top —
all on existing locale keys, with `buildCitationIndex` finally wired to its first consumer.

## What was built

**Task 1 — the panel is page-level, and the claim index honours dedupe aliases (`da5379b`).**
The hand-rolled `first_claim_id` loop is gone; `buildCitationIndex(citations)` replaces it. `CitationPanel`
moved out of the citation-list block to the component root inside a `Sheet` (`side="right"`,
`w-full overflow-y-auto border-l-4 bg-paper sm:max-w-lg`, accent left rule, `sr-only` `SheetTitle`
using the existing `citation.regionLabel`). `CitationPanel` itself went in **unchanged and passed no
`runId`**. The Sheet is a sibling of the entire report block (line 858 vs the block closing at 839) —
outside every collapsible and every section, verified structurally, not asserted.

**Task 2 — section E8 rebuilt on `Collapsible` with `defaultOpen={false}` (`08e89ea`).**
The whole trigger row is the heading and carries `t("verification.citationsCount", { count: sourcesCited })`
on the right, so the figure is readable AND — because it sits inside the button — announced without
expanding. Chevron rotates only (`text-ink/50`, never accent). Expanded rows reuse `CitationMarker`
and `CitationTierGlyph` (no re-implementation, no duplicated glyph helper), plus the retrieved date
and title. No inner scroll box, no height cap, no renumbering, no positional counter.

**Task 3 — the nav rail (`7445186`).** `lg:sticky lg:top-4 lg:w-56` left column inside a
`lg:flex lg:items-start lg:gap-8` wrapper, degrading to a scrollable chip row directly under the
funnel (which is where it sits in source order, so nothing is reordered for small screens). Labels
reuse the nine existing section-title keys. `IntersectionObserver` with `rootMargin: "-8% 0px -70% 0px"`
marks the topmost section still inside the reading band; `disconnect()` on unmount. Active entry takes
`text-ink` + a 2px `#FF2D87` left rule, inactive entries the same 2px rule in `border-transparent`,
so the mark moving shifts nothing.

**Task 3 also recorded DEF-22-03/04/05 (`89861e2`)** — see below.

### The `buildCitationIndex` switchover is WIRED

Explicitly resolved, because the success criteria demand a straight answer: **the module now has a
consumer.** Before this plan it was imported by nothing and Waves 1–2's marker-loss protection was
dead code. `grep -c "buildCitationIndex" VerificationReport.tsx` → **2** (the import and the one
call); `grep -c "citationsByClaim.set"` → **0** (the loop is gone). The mechanism, stated without a
yield figure: the engine emits one citation entry per normalized source URL and drops the rest, a
dropped entry takes its `first_claim_id` with it, `also_claim_ids` carries those absorbed ids onto
the survivor, and the index resolves both — so a verdict row whose claim introduced only an absorbed
source keeps its marker. Numbers are preserved as assigned at synthesis; the rendered sequence is
sparse and that is correct.

## Measured baselines and results

Everything below was measured on this worktree, at the base `e35b6b0` BEFORE any edit and again after.

| Gate | Baseline at `e35b6b0` | After plan 22-08 |
|------|----------------------|------------------|
| `npx tsc --noEmit` | exit 0 | exit **0** |
| `npx vitest run` | **77 passed / 7 files** | **77 passed / 7 files**, 0 failing |
| `node scripts/i18n-audit.mjs` | `RESULT: PASS`, exit 0, **107** CHECK D advisories | `RESULT: PASS`, exit 0, **107** advisories |
| `npm run build` | (not re-measured at base) | exit **0** |
| `eslint` on `VerificationReport.tsx` | **672 errors, ALL `prettier/prettier` `Delete ␍`**, 0 non-prettier | **0 problems** |

The plan's stated vitest floor was "≥ 70 passing (61 base + 22-02's additions)". The true base on this
tree is **77**, matching the executor briefing and not the stale 61 quoted in earlier plans in this
phase. 77 ≥ 70, so the criterion holds either way.

**The eslint 672 → 0 delta is a line-ending artifact, not a code improvement.** The file is stored
LF in the index and checked out CRLF (`core.autocrlf=true`), so every line read as `Delete ␍`.
Running `npx prettier --write` on the file to normalise the indentation of the document block inside
the two new wrapper divs also stripped the CRs. Since git normalises on commit, the committed blob is
LF either way and the diff carries no line-ending noise. **Zero non-`prettier/prettier` violations
existed before and zero exist now** — that is the number that matters.

`git diff --name-only e35b6b0 HEAD` lists exactly two paths: `VerificationReport.tsx` and
`deferred-items.md`. Nothing under `frontend/src/components/ui/`, no `package.json`, no
`package-lock.json`. `routeTree.gen.ts` was touched by the build and reverted with
`git checkout --` before committing, as the plan requires. `npm ci` was used (never `npm install`)
and the lockfile is byte-unchanged.

## Deviations from Plan

### 1. [Criterion reconciled] `grep -c "SheetTitle"` cannot return `1` — the import line necessarily matches

- **Found during:** Task 1, verifying acceptance criteria
- **Criterion as written:** "`grep -c "SheetTitle" …` returns `1`, and it carries `className="sr-only"`."
- **Measured:** **2**. `grep -c` counts matching LINES, and the identifier appears on the import line
  (`import { Sheet, SheetContent, SheetHeader, SheetTitle } …`) as well as at its one render site.
  There is no way to render `SheetTitle` at all and score 1, short of deleting the import — which
  would not compile.
- **Stronger form verified instead:** `grep -c "<SheetTitle"` → **1**, at line 870, and it carries
  `className="sr-only"` with `t("citation.regionLabel")`. Exactly one accessible title is rendered,
  which is the criterion's actual purpose (Radix Dialog warns and the sheet is unnamed without it).
- **Nothing was deleted to make a grep go green.**

### 2. [Criterion reconciled] `sourcesCited` is on **4** lines, not the 3 the plan predicted

- **Found during:** Task 3
- **Criterion as written:** "returns `3` — the single declaration, the stat tile, and the collapsed
  trigger. (It is 2 before this task.)"
- **Measured:** **2** at HEAD before editing (declaration `:352`, stat tile `:551`) — the plan's
  starting figure is correct. **4** after: `:352` declaration, `:422` the rail's citations entry,
  `:551` the stat tile, `:786` the collapsed trigger.
- **Why the fourth is right and was kept:** the rail needs a row count for the citations entry. The
  alternatives were a second `citations.length` call or `report.citations?.length` — precisely the
  "two independent `.length` calls that can drift" that 22-UI-SPEC §3.2 exists to forbid. Reading the
  one computed const **strengthens** the invariant the criterion was written to protect. Three
  surfaces now show one figure from one value.

### 3. [Rule 2 — a11y correctness] The heading WRAPS the trigger instead of sitting inside it

- **Found during:** Task 2
- **Issue:** 22-UI-SPEC §3.1 says the trigger row "is the section's heading", and the existing
  sections name themselves via `aria-labelledby` pointing at a real `<h2>`. But `CollapsibleTrigger`
  renders a `<button>`, and a heading is not permitted content for a button — an `<h2>` inside it is
  invalid HTML and unreliable for assistive tech.
- **Fix:** `<h2 id="citations-heading"><CollapsibleTrigger …>` — the ordinary WAI-ARIA accordion
  shape. The section keeps its `aria-labelledby="citations-heading"`, the button is still the whole
  row, `aria-expanded` still comes from the primitive, and the accessible name is still the heading
  text plus the count.
- **No spec intent lost:** the row is visually and behaviourally the heading, exactly as sketched.

### 4. [Scope] The nav rail lists `unverified` and `cost` unconditionally

- **Found during:** Task 3
- **Issue:** the plan says "one entry per section E1–E9 **that has rows**". Applied literally to the
  unverified accounting, an operator on a run with `unverified.count === 0` would have a rendered,
  headed, anchored section with no way to reach it from the rail — because that section renders
  either way (it prints `unverifiedNone`). The cost section likewise always renders and has no row
  count at all.
- **Resolution:** the rail mirrors exactly what the document renders. The six verdict sections and
  the citation section are gated on the same lengths their own components gate on; `unverified` and
  `cost` are unconditional. The plan's purpose — "every section that has rows is one click away" —
  is met, and no rendered section is unreachable.

## Threat Flags

None. No new endpoint, auth path, file access or schema change. The two mitigations this plan owns
were applied as written: `citation.title` is rendered as a plain React text child in the list rows
(never through `MdText` / `ReactMarkdown`, so `rehype-raw` cannot see it — T-22-24), and the list
rows render no URL and make no request while `CitationPanel` still reads only the stored
`snapshot_text` (T-22-25). `T-22-27` is closed by the `sr-only` `SheetTitle`, Radix's focus trap and
`aria-current` on the active rail anchor. No package was installed and no registry contacted
(T-22-SC).

## Un-regressed, checked rather than assumed

`CitationPanel.tsx` is **byte-unchanged** (`git diff e35b6b0 HEAD -- …/CitationPanel.tsx` → empty).
Within it: `HoverCard` present (8 hits), `role="img"` present (1), `onClose` present (5) and still
the panel's only close affordance, and `CitationTierGlyph` still renders its text label internally.
`renderCitationMarker` is still imported and still used by the verdict rows at `:156` — the verdict
rows needed no change, as the plan said. `IntakeOpenRunLink` and `ResearchRunProgress.tsx` were not
touched by this plan at all.

## Known Stubs

None.

## Deferred Items Recorded

Appended to `deferred-items.md` at the next unclaimed IDs (the file held DEF-22-01 and DEF-22-02;
nothing was renumbered):

- **DEF-22-03** — `i18n-audit.mjs` CHECK A/B/C cannot see interpolated `t()` calls; **102 sites** in
  `frontend/src` are invisible to it, so a renamed interpolated key ships green.
- **DEF-22-04** — two orphaned locale keys (`intakeDetail.toast.researchResumed`,
  `…researchResumeFailed`) with zero referrers in all three locales, plus the explicit warning not to
  remove the live `research.cancelError` / `cancelOk` siblings.
- **DEF-22-05** — five order-dependent tribunal test failures, identical at the pre-phase commit
  `9afdf2d` (135 passed there vs 169 after, +34 new, 0 new failures); each passes in isolation.

## What is NOT proven

Hover intent, collapse feel, the sheet's focus trap and restore, Esc-to-close, and the "the document
does not scroll" guarantee are **not** provable here: this repo has no React Testing Library setup
and standing one up for one component is out of scope. They ride on the vendored Radix primitives and
belong to operator UAT (plan 22-09). The `IntersectionObserver` active-marking likewise has no gate —
it is browser-only code that never executes under `vitest` or SSR.
