---
phase: 23-report-legibility-business-friendly-funnel-labels-and-an-hon
plan: 01
subsystem: frontend-verification-report
tags: [i18n, legibility, verification-report, uat-fix]
requires:
  - "frontend/src/components/intake/VerificationReport.tsx (the funnel render site)"
  - "frontend/src/locales/{en,nl,fr}/intake.json (the verification block)"
provides:
  - "KNOWN_FUNNEL_STAGES / isKnownFunnelStage / humanizeFunnelStage (@/lib/research/funnelLabels)"
  - "verification.funnelLabel.* (18), verification.funnelTip.* (18), verification.funnelUnknownTip — en/nl/fr"
affects:
  - "The gate-funnel section of the superadmin verification report page"
tech-stack:
  added: []
  patterns:
    - "Pure enumerated rule module under lib/research/ with named-per-member vitest coverage (the verificationGate.ts house pattern)"
    - "Local title/aria-label tooltip atom (the NextStepBanner house pattern) — no portal, no shadcn primitive, no dependency"
    - "t(template-literal key, { defaultValue }) as the mitigation for DEF-22-03's audit blind spot"
key-files:
  created:
    - frontend/src/lib/research/funnelLabels.ts
    - frontend/src/lib/research/funnelLabels.test.ts
  modified:
    - frontend/src/components/intake/VerificationReport.tsx
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
decisions:
  - "All 18 engine funnel keys labelled, not the 6 the UAT lists — the component renders every numeric entry of the flat dict"
  - "Control characters are replaced by a SPACE, not deleted, so a \\n inside an engine key cannot fuse two words into a nonsense token"
  - "humanizeFunnelStage raises only the first character — title-casing would make an engine key look like curated copy"
metrics:
  duration: ~35 min
  completed: 2026-08-13
  tasks: 3
  commits: 4
---

# Phase 23 Plan 01: Business-Friendly Funnel Labels Summary

Every gate-funnel row on the verification report now reads as a business phrase with an
explanatory ⓘ tooltip in en/nl/fr, and an engine key this build has never seen degrades to a
humanized phrase instead of a raw snake_case token.

## What was built

**Task 1 — `frontend/src/lib/research/funnelLabels.ts` + its tests (commits `f4d402b` RED, `170a3c6` GREEN).**
A pure module in the `verificationGate.ts` house register: `KNOWN_FUNNEL_STAGES` enumerates all
eighteen engine keys (nine from `gates.py` `_FUNNEL_KEYS`, nine from `pipeline.py` `_build_funnel`)
each with a trailing comment stating what the engine counts in it; `isKnownFunnelStage` is a
case-sensitive `Set` membership test; `humanizeFunnelStage` is the degrade-safe fallback. The
module holds **no display copy** — all 111 strings live in the locale files, because a TypeScript
label map would be a fourth, untranslated copy and the one the i18n parity audit cannot see.

**Task 2 — 37 key paths per language (commit `1e0d690`).** `verification.funnelLabel.*` (18),
`verification.funnelTip.*` (18) and `verification.funnelUnknownTip`, at three-way key parity. The
English strings are the plan's verbatim source of truth. No label value in any language contains
an underscore — that is the entire finding.

**Task 3 — the render site (commit `e154c2b`).** The raw `{stage}` span is replaced by the
resolved label plus a local `InfoTip` atom (a `title` + `aria-label` ⓘ span mirroring
`NextStepBanner.tsx`; no dependency added). `aria-label` now interpolates the resolved label
rather than the raw key, without renaming `verification.funnelStage` itself. The superseded
comment block arguing that the stage key is rendered raw was rewritten.

## Metrics the plan asked for

| Measure | Result |
|---|---|
| `tsc --noEmit` errors — HEAD baseline | **0** |
| `tsc --noEmit` errors — after all three tasks | **0** (no new errors) |
| `funnelLabels.test.ts` test count | **30** (criterion: ≥ 24) |
| Full `npm test` | **107 passed / 8 files**, green |
| `node scripts/i18n-audit.mjs` | **PASS** — A/B/C clean (107 CHECK D advisories, all pre-existing and unrelated) |
| `git diff --stat` vs base | exactly the **6** files in `files_modified`, no others |

## nl/fr wording notes

No label string was changed from the plan's given text — all 18 nl and all 18 fr labels are
verbatim. The 18 tooltips per language plus `funnelUnknownTip` were newly authored (the plan
specified their content, not their wording). Two notes:

- **`should_have_been_checked` carries both required elements in all three languages**, verified
  by the plan's own assertion: en "shipped unexamined" + "zero"; nl "ongecontroleerd meegeleverd"
  + "is dit nul"; fr "livrées sans examen" + "ce chiffre est zéro".
- **`funnelUnknownTip` (fr)** renders "research engine" as `moteur de recherche`, the term the fr
  locale already uses for this product's research. It reads slightly toward "search engine" in
  isolation; the surrounding sentence ("d'une partie du moteur de recherche pour laquelle cet
  écran ne dispose pas encore de description") disambiguates it. Flagging it as the one phrase a
  native reviewer might want to retune.

## Deviations from Plan

### Criterion corrections (measured, not assumed)

**1. Task 3's two no-regression counts are `2` at HEAD, not the `1` the plan states.**
- **Found during:** Task 3 acceptance.
- **Issue:** The plan asserts `grep -c 'funnelEntries.map'` returns `1` and
  `grep -c 'typeof count === "number"'` returns `1`. Both actually return **2**, and both returned
  **2 at HEAD as well** — `funnelEntries.map` also appears in the `funnelMax` computation
  (`:409`), and `typeof count === "number"` also appears in `ReportSection` (`:224`). A
  planning-time miscount, not a regression.
- **Resolution:** The criterion's stated PURPOSE ("the row set, row order and the CR-01 numeric
  filter are untouched — a NO-REGRESSION guard, explicitly not a progress gate") is satisfied:
  both counts are byte-identical to HEAD. Verified by grepping the HEAD blob directly. No code
  changed to chase the literal number — doing so would have meant editing untouched code to
  satisfy a miscounted gate.

### Implementation choices inside the plan's latitude

**2. Control characters become a SPACE rather than being deleted.**
- **Where:** `humanizeFunnelStage`.
- **Why:** The plan says "strip control characters, collapse whitespace runs to one space". Read
  as outright deletion, `"checked\nincidentally"` would become `"Checkedincidentally"` — two words
  fused into a nonsense token an operator could misread as a real engine name. Replacing each
  control character with a space yields `"Checked incidentally"` and still fully satisfies the
  stated guarantee (no `\n` or `\t` can reach the row). Written as the `\p{C}` Unicode property
  escape so this source file itself carries no control byte. Pinned by a named test.

**3. `npm ci` was run in the worktree.**
- **Why:** The worktree had no `node_modules`, so nothing could be verified. This restores the
  **committed lockfile** exactly (never `npm install`, per the project rule); it installs no new
  package and adds nothing to `package.json`. The plan's T-23-SC disposition ("this plan installs
  NO packages") is intact — `git diff` touches no manifest.

### Environment note (not a deviation)

`eslint` reports 952 `prettier/prettier` "Delete `␍`" errors on the changed files, and
`prettier --check` fails on **untouched** files too (e.g. `src/locales/en/common.json`). This is
the working tree's CRLF checkout under `core.autocrlf`, pre-existing and repo-wide. The **staged
LF blobs** — what actually lands in the commit — were extracted and checked: all pass Prettier
cleanly, and `--end-of-line auto` reports every changed file clean. Zero non-CRLF lint findings.
Out of scope to fix; not logged as a new deferred item since it is a local checkout condition
rather than a repo defect.

## What this plan deliberately did NOT do

- No funnel row dropped, added, reordered, merged or renumbered — only label text changed (D-22-2).
- The figures, the bar geometry and the CR-01 `typeof === "number"` DROP filter are untouched.
- IN-06 (a negative funnel value renders a full-width bar, DEF-22-12) is **not** fixed — a real
  deferred finding, and not this requirement.
- `research.currentStage` untouched — 23-03 owns that boundary.
- No package installed; no shadcn tooltip primitive added.

## Threat model outcomes

- **T-23-01 (echoing an unknown engine key):** mitigated. The label reaches the DOM as a React
  text child and as `title` / `aria-label` attribute values, all auto-escaped. `InfoTip`'s
  docstring records the ban on routing it through `dangerouslySetInnerHTML` or `MdText`.
- **T-23-02 (layout DoS):** mitigated and pinned by tests — output capped at 80 chars + `…`,
  control characters neutralised, `truncate`/`w-44` retained as the second guard.
- **T-23-03 (accounting integrity):** accepted — the CR-01 filter and row order verified
  unchanged against HEAD.
- **T-23-04 (honesty):** mitigated — every tooltip written from `gates.py`, `_build_funnel` and
  `report.py::_accounting`, which were read first. No tooltip states a ratio, a percentage or any
  derived figure.
- **T-23-SC (supply chain):** no package installed. No Package Legitimacy Audit required.

## Known Stubs

None. Every funnel row has a real data source (the engine's own funnel dict), real curated copy in
three languages, and a defined fallback for the unknown-key path.

## Self-Check: PASSED

Files verified present:
- `frontend/src/lib/research/funnelLabels.ts` — FOUND
- `frontend/src/lib/research/funnelLabels.test.ts` — FOUND
- `frontend/src/components/intake/VerificationReport.tsx` — FOUND (modified)
- `frontend/src/locales/{en,nl,fr}/intake.json` — FOUND (modified)

Commits verified in `git log`:
- `f4d402b` test(23-01): add failing tests for the funnel-stage vocabulary — FOUND
- `170a3c6` feat(23-01): the funnel-stage vocabulary and its degrade-safe humanizer — FOUND
- `1e0d690` feat(23-01): business-friendly funnel labels and tooltips in en, nl and fr — FOUND
- `e154c2b` feat(23-01): render a business label and a tooltip in each funnel row — FOUND

## TDD Gate Compliance

Task 1 ran the full RED/GREEN cycle with gate commits in order: `f4d402b` (`test(...)`, tests
failing — module absent) then `170a3c6` (`feat(...)`, 30 tests green). No REFACTOR commit was
needed; the first implementation was already in the house register and Prettier-clean.
