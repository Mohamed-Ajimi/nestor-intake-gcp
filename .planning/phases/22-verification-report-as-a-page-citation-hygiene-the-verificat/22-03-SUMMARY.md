---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 03
subsystem: ui
tags: [react, i18n, radix, hover-card, citations, accessibility, typescript]

# Dependency graph
requires:
  - phase: 15.6
    provides: renderCitationMarker, CitationPanel and the [n] numbered-citation surface
  - phase: 15.3
    provides: citations/numbering.py — the retrieval-date-proxy contract this plan obeys
provides:
  - "CitationMarker — a CONTROLLED HoverCard preview over the [n] marker, no network call"
  - "CitationTierGlyph (exported) — tier marks AND the text label rendered as one unit"
  - "citation.retrieved replacing citation.published in all three locales"
  - "The full Phase 22 verification.* key set (12 keys) in en/nl/fr, ahead of the plans that consume them"
  - "The measurement that the i18n audit is BLIND to every interpolated t(key, {...}) call — 102 sites"
affects: [22-04, 22-05, 22-06, 22-07, 22-08, any later plan reading verification.* or citation.* keys]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Controlled Radix HoverCard when a click on the trigger must win over the open preview"
    - "Ship the a11y text label INSIDE the glyph component, so glyph and label cannot drift across call sites"
    - "Front-load a phase's whole locale key set in one wave-1 plan so later plans never race on the JSON files"

key-files:
  created: []
  modified:
    - frontend/src/components/intake/CitationPanel.tsx
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json

key-decisions:
  - "Tasks 1 and 2 land as ONE commit — the plan's own two constraints are jointly satisfiable no other way"
  - "CitationTierGlyph renders glyph + text label together rather than leaving the label to each call site"
  - "role=img added to the glyph group so its aria-label is actually announced"
  - "The plan's CHECK B atomicity rationale is FALSE; the atomicity was honoured for an independent reason"
  - "Two acceptance criteria were already failing at HEAD before any edit; both reconciled to purpose"

patterns-established:
  - "Verify a lint/grep criterion against HEAD before treating a non-zero count as your own regression"
  - "When a comment would make a grep gate ambiguous, reword the comment — do not weaken the gate"

metrics:
  duration: ~35 min
  tasks-completed: 2
  files-modified: 4
  commits: 1
  completed: 2026-08-11
---

# Phase 22 Plan 03: Citation Hover Preview + Citation Hygiene Summary

A `[n]` citation marker now previews its title, retrieved date and quality tier in a controlled Radix
HoverCard with zero network calls, and the product has stopped calling a crawler retrieval date a
publication date — a live factual misstatement that was on screen until this commit.

## What Was Built

**Task 1 — the phase's full locale key set + the `published`→`retrieved` rename.**
Twelve new `verification.*` keys (`backToRun`, `navLabel`, the five `stat*` tiles, `citationsCount`,
`hoverTierLabel`, `hoverClickHint`, `emptyReport`, `retry`) added to `en`/`nl`/`fr`, copy taken
verbatim from the 22-UI-SPEC copywriting contract. `citation.published` removed from all three files
and replaced with `citation.retrieved`. All three locales end at **593 keys with byte-identical key
sets**. `verification.hideAction` deliberately survives (parity, not usage, is what CHECK A measures);
`verification.notAvailable` deliberately not added.

**Task 2 — `CitationMarker` and the label fix.**
- `CitationTierGlyph` (exported): three `.mark-ink` / `.mark-outline` spans, filled count `4 - tier`,
  with the tier's text label rendered beside them **inside the same component**.
- `CitationMarker`: a controlled `HoverCard` (`open` / `onOpenChange`, `openDelay` 120, `closeDelay`
  80) wrapping the **byte-identical** `[n]` trigger button. Click handler is `setOpen(false)` then
  `onOpen(citation)`. Content is a closed list of exactly four lines.
- `renderCitationMarker` kept as a thin wrapper with an unchanged signature — `VerificationReport.tsx`
  needed no edit, proven by `tsc` passing against its three existing references.
- `CitationPanel`'s date line now reads `citation.retrieved`, with a comment recording why.

## Key Decisions

**1. Tasks 1 and 2 committed together — forced by the plan's own constraints.**
Task 1's acceptance criteria require `citation.published` to be absent *at task 1's commit*, while
measured fact 1 requires the locale rename and the `CitationPanel.tsx` edit to be *atomic*. Those two
are jointly satisfiable only in a single commit. Committing task 1 alone would have produced a commit
that renders the raw string `citation.published` on screen.

**2. `CitationTierGlyph` owns its text label.**
The plan described the helper as returning three `<span>`s with the label "rendered beside it". I put
the label inside the component. This is the stronger form: it makes the plan's own must-have ("a glyph
plus a text label, **always both**") structurally impossible to violate, and it is what actually
delivers the stated reason for exporting the helper — that 22-08's citation rows and this hover card
cannot disagree about how a tier looks. Chip background/padding stays at the call site.

**3. `role="img"` on the glyph group.** An `aria-label` on a bare `<span>` is not reliably announced;
without `role="img"` the mandated `verification.hoverTierLabel` string would have been dead markup.

## Deviations from Plan

### Reconciled acceptance criteria (both were already failing at HEAD, before any edit)

**1. [Integrity] `grep -c '"notAvailable"' …/en/intake.json` returns `0` — UNSATISFIABLE.**
It returned **1 at HEAD**, before I touched anything. The match is `reportPage.notAvailable`
("Report not available yet") at line 186 — a pre-existing, in-use key in an unrelated block. Satisfying
the criterion literally would mean deleting a live key from one locale, breaking CHECK A parity and
CHECK B resolution — the exact opposite of the plan's intent.
**Reconciled to purpose** (the action text says: do not add `verification.notAvailable`) and verified
in the stronger, precisely-scoped form: `verification.notAvailable === undefined` in all three
locales. Confirmed by parsing the JSON, not by grepping the file.

**2. [Integrity] `grep -c 'getSource' CitationPanel.tsx` returns `2` — WRONG AT HEAD.**
It returned **4 at HEAD**: one import, one call, and **two pre-existing comment mentions** the plan did
not account for. It now returns 5 because I added one more comment mention — the sentence documenting
that the marker makes *no* call. The criterion's stated purpose is "the hover card adds no third call
site", so I verified that instead: `grep -c 'getSource('` is **2 now and 2 at HEAD** (one docstring,
one real invocation at line 190), i.e. **exactly one call site, unchanged, inside `CitationPanel`
only**.

### Gate-integrity finding: the i18n audit cannot see interpolated keys

Measured fact 1 asserts "the rename and the `CitationPanel.tsx` edit must land in the SAME commit or
**CHECK B** goes red." **This is false.** I measured it: with the locales renamed and
`CitationPanel.tsx` still calling `t("citation.published", { date })`, the audit printed
`RESULT: PASS — A/B/C clean` and exited 0.

Cause, from `scripts/i18n-audit.mjs:126-128`:
- `RE_SINGLE = /[^.A-Za-z]t\(\s*"([^"]+)"\s*\)/g` — requires the call to **close immediately** after
  the string, so `t("k", {...})` never matches.
- `RE_TWO` requires a **string** second argument, so an interpolation object never matches.

So **every `t("key", { … })` call is invisible to CHECK A, B and C**. There are **102 such call sites**
under `frontend/src`. A renamed or deleted interpolated key ships green and renders the raw key name on
screen. This is a real hole in the phase's own safety net and worth a follow-up (a fourth check
resolving interpolated keys would close it). The plan's *conclusion* — keep the rename atomic — was
still correct, and I honoured it, but for the independent reason that a non-atomic commit would render
a raw key, not because any gate would have caught it.

Two smaller planner inaccuracies, immaterial: unused locale keys produce **zero** CHECK D advisories
(the count held at 107 across every run, so the stated "one more advisory" cost of an unused key is
nil); and the plan's artifact `exports` list omits `CitationTierGlyph` even though its own action text
mandates exporting it.

### Environment

`frontend/node_modules` was absent in this fresh worktree, so no gate could run. Resolved with
`npm ci` (868 packages from the committed lockfile) per project instruction — **never `npm install`**.
This installs no new package name and left `package.json` / `package-lock.json` unmodified, so
threat T-22-SC holds: no registry resolution of an unpinned name, no new dependency.

## Out-of-Scope Discoveries

Recorded here rather than in `deferred-items.md` — plan 22-01 owns that file this wave.

1. **Repo-wide CRLF vs prettier (pre-existing, DEF-21-01).** Every file in the Windows checkout trips
   `prettier/prettier` "Delete `␍`" on every line — an untouched `VerificationReport.tsx` reports 410
   such errors. Not touched: normalising line endings would produce an enormous diff across unrelated
   files. Verified per-file and filtered instead.
2. **`react-refresh/only-export-components` warning, pre-existing.** `CitationPanel.tsx` has exactly
   one such warning, on `renderCitationMarker`. Proven pre-existing by linting the HEAD version of the
   file in isolation: 1 warning, 0 errors — identical to now.
3. **i18n audit blind spot** — see above. The single highest-value follow-up from this plan.
4. **`verification.citationsCount` uses `{{count}}`**, which is i18next's pluralization trigger and has
   no `_one` / `_other` forms. This matches the existing, working `verification.unverifiedTitle`
   pattern in this codebase, so it is consistent rather than novel — flagged only so 22-08 renders it
   knowingly.

## Verification Results

All run inside the worktree at commit `d6ed275`.

| Gate | Baseline at HEAD | After | Status |
|------|------------------|-------|--------|
| `npx tsc --noEmit` | exit 0 | exit 0 | PASS |
| `node scripts/i18n-audit.mjs` | `PASS`, 107 advisories | `PASS`, 107 advisories | PASS |
| `npx vitest run` | 61 passed / 0 failed | 61 passed / 0 failed | PASS (criterion: ≥61) |
| eslint (non-prettier errors) | 0 errors, 1 warning | 0 errors, 1 warning | PASS (warning pre-existing) |

Criterion-by-criterion:
- `"published"` in en/nl/fr → `0, 0, 0`
- `"retrieved"` in en/nl/fr → `1, 1, 1`
- `"hideAction"` in en → `1` (survives)
- `verification.notAvailable` in en/nl/fr → `undefined` (reconciled form)
- All three locales parse as JSON, exit 0
- 3-way key parity: **593 / 593 / 593**, key sets byte-identical; all 12 new keys present in each
- `citation.published` in `CitationPanel.tsx` → `0`; `citation.retrieved` → `2` (panel + hover read the
  same key, so the two surfaces cannot drift)
- `getSource(` call sites → 1, inside `CitationPanel` only (unchanged from HEAD)
- `HoverCard` imported from `@/components/ui/hover-card`; controlled `open={` / `onOpenChange={` pair
  present at line 99
- Excluded identifiers (`single_source`, `temporal_note`, `snapshot_text`, `citation.url`, `provider`)
  appear **only** in the pre-existing file header (line 20), `CitationPanel`'s own docstring (168) and
  the `CitationPanel` body (249+) — **zero occurrences inside `CitationTierGlyph` (52-87),
  `CitationMarker` (88-159) or `renderCitationMarker` (160-171)**. To achieve this cleanly I reworded
  my own explanatory comment rather than weakening the gate.
- Marker trigger classes **byte-identical** to HEAD, `mx-0.5` included (verified by diff)
- `git diff --name-only` lists exactly the four `files_modified` — nothing under
  `frontend/src/components/ui/`, no `package.json`, no `package-lock.json`

## Threat Model Compliance

| Threat | Disposition | Evidence |
|--------|-------------|----------|
| T-22-06 stored XSS via `citation.title` | mitigated | Rendered as a plain React text child; no `MdText` / `ReactMarkdown` anywhere in `CitationMarker`. Constraint recorded in the component docstring. |
| T-22-07 SSRF via citation URL | mitigated | Hover shows title/date/tier only; `getSource(` call sites unchanged at 1, inside the panel. No `useEffect` and no fetch added to the marker. |
| T-22-08 mislabelled retrieval date | mitigated | One `citation.retrieved` key read by both surfaces; `citation.published` deleted from all three locales in the same commit as the render change, so no stale reference can resurrect it. |
| T-22-SC package tampering | mitigated | `package.json` / `package-lock.json` unchanged; `npm ci` only, no `shadcn add`, no new dependency. |

No new security surface outside the plan's threat model — no endpoint, auth path, file access or schema
change. No Threat Flags.

## Known Stubs

None. Both tasks are fully wired: the hover card renders live `Citation` data through
`renderCitationMarker`'s three existing call sites, and the twelve new locale keys are intentionally
ahead of their consumers by design (this plan's stated purpose is to land them before plans 22-04
through 22-08 need them) — not stubs, and each carries real translated copy in all three languages.

## For the Next Plan

- **The keys already exist.** Do not add `verification.*` keys for the stat strip, the nav, the empty
  state or the retry button — consume them.
- **`CitationTierGlyph` is exported and renders glyph + label together.** Plan 22-08 should import it
  for the citation-list rows, not re-implement it, and should not add its own text label.
- **`CitationPanel` takes no `runId`** — three props only (`intakeId`, `citation`, `onClose`), despite
  22-UI-SPEC §2.6's sketch.
- **22-UI-SPEC §2.6's Sheet hoist is NOT done here** and remains necessary: this plan did not touch
  where `CitationPanel` mounts, so once the citation list collapses by default, a `[n]` click inside a
  verdict row still renders the panel inside a collapsed container.
- **Do not trust the i18n audit to catch a renamed interpolated key.** 102 call sites are invisible to
  it. Grep the call sites by hand when renaming any key used with interpolation.

## Self-Check: PASSED

- `frontend/src/components/intake/CitationPanel.tsx` — FOUND (modified, committed)
- `frontend/src/locales/en/intake.json` — FOUND (modified, committed)
- `frontend/src/locales/nl/intake.json` — FOUND (modified, committed)
- `frontend/src/locales/fr/intake.json` — FOUND (modified, committed)
- Commit `d6ed275` — FOUND in `git log`
- No file deletions in the commit (`git diff --diff-filter=D HEAD~1 HEAD` empty)
- Working tree clean after commit; no untracked artifacts left behind (the temporary lint probe file
  used to establish the pre-existing-warning baseline was removed before staging)
