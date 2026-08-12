---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 09
subsystem: planning-artifacts
tags: [uat, documentation, deferral-closure, phase-21-reconciliation]
requires:
  - "22-04 (D-22-5 element removal + IntakeOpenRunLink)"
  - "22-05 (read-path dedupe seam + also_claim_ids on the wire)"
  - "22-08 (collapsed citation list, page-level Sheet, nav rail)"
provides:
  - "22-UAT.md — the Phase 22 operator walkthrough, zero-spend, all verdict slots unfilled"
  - "DEF-21-02 closure — six named successors 22-B1..22-B6 visible from both Phase 21 documents"
affects:
  - ".planning/phases/21-.../21-UAT.md (annotated only, no verdict filled)"
  - ".planning/phases/21-.../deferred-items.md (DEF-21-02 closure section)"
  - ".planning/phases/22-.../deferred-items.md (cross-reference, no new DEF id)"
tech-stack:
  added: []
  patterns:
    - "Supersession-with-named-successor: a deferred check made unanswerable by a later design ruling is marked SUPERSEDED and rewritten, never dropped and never answered in either direction"
key-files:
  created:
    - .planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/22-UAT.md
  modified:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-UAT.md
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/deferred-items.md
    - .planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/deferred-items.md
decisions:
  - "The five interaction behaviours with zero automated coverage (U1-U5) are labelled as such in the UAT and each carries its own operator verdict slot — they are never presented as verified"
  - "Only DEF-21-02's six navigation checks are reconciled; every Phase 21 check needing a post-deploy live run stays OPEN, because Phase 22 changed no engine write path and triggered no run"
  - "The 22 deferred-items cross-reference deliberately claims NO DEF-22-NN id, so it cannot collide with an id a later plan takes"
metrics:
  duration: ~35 min
  completed: 2026-08-11
  tasks: 2
  files_created: 1
  files_modified: 3
  insertions: 667
  deletions: 0
---

# Phase 22 Plan 09: The Operator UAT + Phase 21's DEF-21-02 Closure Summary

**Phase 22 now has a walkable zero-spend operator UAT whose every verdict slot is unfilled, and Phase
21's six deferred DEF-21-02 checks are closed by reconciliation — three carried forward and three
marked SUPERSEDED by the operator's own D-22-1 ruling, each with a named successor visible from both
Phase 21 documents.**

## THE NUMBER THE PLAN ASKED FOR FIRST: `21-UAT.md` was not filled in

| Measurement | Before this plan | After this plan |
|---|---|---|
| `grep -c "awaiting operator" 21-UAT.md` | **40** | **40** |

**Equal, as required.** The diff on that file is **36 insertions / 0 deletions** — every line added is
an annotation, and not one verdict, not PART A, not R1/R2, and not the operator's verbatim walkthrough
quote was touched.

## What was built

**Task 1 — `22-UAT.md` (commit `d8dc410`, 568 lines).** Structure, recording rules and the
out-of-scope-table idiom copied from `21-UAT.md`. Contents:

- **Header:** status `AWAITING OPERATOR`, the ⛔ zero-spend callout, the four recording rules
  (verbatim / routed / NOT-OBSERVABLE is real / "looks good" is not a PASS), and preconditions that
  point at **plan 22-10's DERIVED deploy surface** rather than naming services — a stale surface list
  is the 2026-08-06 trap and this document must not re-import it.
- **⛔ KNOWN AND OUT OF SCOPE table, 8 rows:** DEF-21-01, DEF-21-03, DEF-21-04 plus all five Phase 22
  items DEF-22-01…05. Each row says what the operator will see and why it is not a Phase 22 failure.
  DEF-22-03 carries an extra instruction, because it is the one that can mask a real defect: a green
  i18n audit is not proof a key resolves, so **a label rendering as a raw key name IS a finding**.
- **⚠ "WHAT PHASE 22 DID NOT PROVE"** — three limits stated before any check, so nothing below is
  over-read. It contains the U1–U5 table below, the display-only dedupe caveat, and the statement that
  no run was triggered.
- **PART A — five sections, one per locked decision,** with the operator's verbatim quote at the head
  of A1, A2, A3, A4 and A5.
- **PART B — the DEF-21-02 reconciliation:** a ⚠ block, the mapping table, and the six successor checks
  22-B1…22-B6, each stating *what changed and why*.
- **Regression checks R1 (clock), R2 (feed / "Show more" / audit drill-down — earned because this
  phase renamed that route file), R3 (`Published:` nowhere).**
- **A 31-row roll-up table plus a sign-off line**, and a closing instruction that A3i and A4c's
  rulings must be ROUTED after sign-off, never absorbed.

**Task 2 — the Phase 21 annotations (commit `98fc309`).**
- `21-UAT.md` PART B: a dated **RECONCILED BY PHASE 22, NOT ABANDONED** block under the "WHY THIS
  SECTION EXISTS" header, plus a one-line pointer on each of the six verdict slots B1–B6.
- `21-.../deferred-items.md` § DEF-21-02: a closure section with the mapping table, the reason three
  steps changed rather than being answered, and the statement that the 21-08 obligation is **discharged
  by pointer**.
- `22-.../deferred-items.md`: an appended cross-reference.

## The five unproven behaviours are human steps, not claims

Plan 22-08 established that this repo has no React Testing Library and that `IntersectionObserver`
never executes under vitest or SSR. All five therefore appear in the UAT as **operator checks with
their own verdict slots**, each explicitly labelled as having no automated coverage:

| # | Behaviour | Slot in `22-UAT.md` | Labelled |
|---|---|---|---|
| U1 | hover intent — appear/dismiss delay, flicker, stick | **A3d** | "UNPROVEN BY ANY GATE: hover intent" |
| U2 | collapse/expand feel | **A3h** | "UNPROVEN BY ANY GATE: the collapse/expand feel" |
| U3 | Esc closes, focus trapped, focus restored to the `[n]` | **A3f** | "UNPROVEN BY ANY GATE" |
| U4 | the document behind the sheet does not scroll | **A3f** | same slot as U3 |
| U5 | `IntersectionObserver` nav-rail section marking | **A2d** | "UNPROVEN BY ANY GATE" |

They are also indexed in the up-front "WHAT PHASE 22 DID NOT PROVE" table, so a reader meets them
before meeting any check.

## Which Phase 21 steps were closed, and the artifact that resolves each

**Closed: the six DEF-21-02 navigation checks — and only those.**

| Phase 21 step | Status | Resolving Phase 22 artifact | Successor |
|---|---|---|---|
| B1 — run page loads via "Open run" | CARRIED FORWARD | `admin.pulse.runs.$runId.index.tsx` still serves `/admin/pulse/runs/:runId`; the entry link is `IntakeOpenRunLink` at `admin.pulse.intakes.$id.tsx:1189` | 22-B1 |
| B2 — toggle BETWEEN the card and the feed | **SUPERSEDED by D-22-1** | The toggle is gone. A `<Link>` occupies the same position: card `:290` → link `:325` → feed `:354` in `admin.pulse.runs.$runId.index.tsx` — I verified the ordering by reading the file, not from the plan | 22-B2 |
| B3 — report opens AND the feed survives beneath it | **SUPERSEDED by D-22-1** | `admin.pulse.runs.$runId.verification.tsx` is a separate leaf route mounting `<VerificationReport>` once app-wide at `:192`; the report cannot be on the feed's page to displace it | 22-B3 |
| B4 — toggle collapses cleanly, feed untouched | **SUPERSEDED by D-22-1** | Same route split; the equivalent property becomes "`Back to run` returns a whole run page" | 22-B4 |
| B5 — offered on failed / cancelled | CARRIED FORWARD | `canHaveVerificationReport(status)` still gates the link, one call site, `…index.tsx:325` | 22-B5 |
| B6 — NO affordance on queued / running | CARRIED FORWARD | Same single gate — its absence is still the correct result | 22-B6 |

**Left OPEN, deliberately.** Phase 21's PART A (SC1–SC6) and R1/R2 are untouched. **SC1 in particular
cannot be closed by anything in Phase 22** — it needs a run that executed after the deploy, and this
phase changed no engine write path and triggered no run. The Phase 21 UAT remains **UNRUN** and Phase
21's verification remains `human_needed`; nothing here alters that. Both Phase 21 documents now say so
explicitly, so a later reader cannot mistake the PART B closure for a phase-wide one.

## Acceptance criteria — measured, with baselines taken BEFORE editing

**Task 1 — all eight criteria PASS, none required reconciliation.** This is the first plan in the
phase to hit no bad criterion; the reason is structural, not luck — Task 1 creates a new file, so
every criterion is a property of my own output rather than a prediction about an existing tree, which
is where the other eight plans' 20+ bad criteria came from.

| Criterion | Required | Measured | |
|---|---|---|---|
| `22-UAT.md` exists | yes | yes | PASS |
| `grep -c "SUPERSEDED"` | ≥ 3 | **4** | PASS |
| `grep -cE "22-B1\|…\|22-B6"` | ≥ 12 | **21** | PASS |
| `grep -c "awaiting operator"` | ≥ 20 | **98** | PASS |
| `grep -ciE "duplicates removed\|N fewer\|reduced by\|[0-9]+% fewer"` | **0** | **0** | PASS |
| `grep -c "Retrieved"` | ≥ 1 | **3** | PASS |
| `grep -cE "DEF-21-01\|DEF-21-03\|DEF-21-04\|DEF-22-01"` | ≥ 4 | **4** | PASS |
| `grep -ciE "do not trigger\|zero spend\|no spend"` | ≥ 1 | **3** | PASS |

**Task 2 — all seven criteria PASS.**

| Criterion | Required | Baseline before edit | After | |
|---|---|---|---|---|
| `grep -c "SUPERSEDED" 21-UAT.md` | ≥ 4 | **0** | **4** | PASS |
| `grep -c "CARRIED FORWARD" 21-UAT.md` | ≥ 3 | **0** | **4** | PASS |
| `grep -c "22-UAT.md" 21-UAT.md` | ≥ 7 | **0** | **7** | PASS |
| `grep -c "awaiting operator" 21-UAT.md` | **unchanged** | **40** | **40** | PASS |
| `grep -c "RECONCILED" 21-…/deferred-items.md` | ≥ 1 | 0 | **1** | PASS |
| `grep -c "DEF-21-01" 21-…/deferred-items.md` | **unchanged** | **1** (via `git show HEAD:`) | **1** | PASS |
| `grep -c "DEF-21-02" 22-…/deferred-items.md` | ≥ 1 | 0 | **2** | PASS |
| `git diff --cached --name-only` lists all 4 `files_modified` | yes | — | all 4 | PASS |

**Anti-substring-trap check, run because eleven criteria in this phase have collided on a bare
substring.** The `22-B*` criterion is a bare-substring pattern, so I additionally verified the
anchored form: `grep -c "^#### 22-B<i> — "` returns **exactly 1** for each of i = 1…6, at lines 402,
416, 429, 445, 460, 473. No id is duplicated and no prefix collision exists (there is no `22-B10` to
be caught by a `22-B1` prefix).

**Note on `SUPERSEDED` vs `SUPERSEDES`.** The plan's `must_haves.artifacts` block requires the
literal string **`SUPERSEDES`**, while the acceptance criterion counts **`SUPERSEDED`**. These are
different strings — `SUPERSEDED` does not contain `SUPERSEDES` — so satisfying one does not satisfy
the other. Both are present and both were measured separately: `SUPERSEDED` = 4 (the header block plus
three mapping-table rows), `SUPERSEDES` = 3 (one per superseded successor heading). Recorded because a
reader checking only one of the two would draw the wrong conclusion about the other.

## Deviations from Plan

### 1. [Correction to the plan's premise] The plan's mapping table calls B2/B3/B4's successors "supersedes"; the report PAGE has no status gate, and 22-B6 had to be scoped accordingly

- **Found during:** Task 1, while writing A1 and 22-B6.
- **What the plan implies:** the plan's measured fact 7 and 22-UI-SPEC §1.1 both say availability "is
  gated by `canHaveVerificationReport`", and 22-UI-SPEC's States table specifies a
  `verification.notAvailable` screen for "a deep link to a queued/running run".
- **What is actually on disk:** the verification **page** deliberately carries **no** status gate. Its
  module header (`admin.pulse.runs.$runId.verification.tsx:38-47`) states the reason: `locateResearchRun`
  returns two ids and no run state by design, and the only other way to learn a status would be to
  stream the intake's *latest* run — which for a historical run is a different run, so it would gate
  run X's report on run Y's state. A deep link is answered by the report's own data instead. And
  `verification.notAvailable` **was never added to the locales** — plan 22-03 states it was deliberately
  omitted, and `grep -n "notAvailable"` on the route file returns nothing.
- **Why this mattered enough to handle explicitly:** an operator who typed a verification URL for a
  running run and saw an empty report instead of a "not available" screen would have recorded a defect
  against correct, deliberate behaviour. And 22-B6 as inherited from Phase 21 B6 is ambiguous about
  *which* surface the absent affordance is on.
- **How it was handled:** A1 carries a ⚠ block naming the empty-state / load-error behaviour as
  deliberate and telling the operator not to record it as a defect; 22-B6 is explicitly scoped to **the
  LINK on the run page, not the report page**. Nothing was weakened — the gate genuinely exists, at one
  call site, on the run page (`…index.tsx:325`), which is exactly where 22-B2/B5/B6 check it.

### 2. [Verified rather than trusted] Three positional facts the UAT asserts were read out of the code

The UAT tells the operator what they should see; if it is wrong, the operator records a false defect.
So the three positional claims were measured, not inherited from the plan:

- **22-B2's "between the card and the feed"** — `admin.pulse.runs.$runId.index.tsx`: `<RunStatusCard>`
  at `:290`, the `<Link>` at `:325-336`, `<RunFeed>` at `:354`. The claim holds.
- **A5b's "the link is still on the intake page"** — `IntakeOpenRunLink` imported at
  `admin.pulse.intakes.$id.tsx:57`, mounted at `:1188`.
- **A1's empty/error states** — `VerificationReport.tsx`: `verification.loadError` at `:474-475`,
  `verification.retry` at `:515`, `verification.emptyReport` at `:656`. There is no `notAvailable`
  branch, consistent with deviation 1.

### 3. [Scope] The 22-side cross-reference claims no `DEF-22-NN` id

The plan said "append a short cross-reference"; it did not ask for a new id. I gave the appended
section a plain heading instead of `DEF-22-06`. **Reason:** plan 22-10 executes after me and may take
the next id, and the NEVER-RENUMBER rule means a collision would have to be reported rather than
resolved. Claiming no id makes a collision impossible. The `DEF-21-02` grep criterion is satisfied
either way (measured 2).

### 4. [Environment — the 32nd recorded occurrence] STALE WORKTREE BASE

`git merge-base HEAD c74f5e8` returned **`a3a0c96`** — the same stale commit as all 31 prior
occurrences project-wide, and every prior executor in this phase. `git reset --hard c74f5e8` corrected
it. **All four positive-presence sentinels then passed**, which is the part that matters here more than
usual: this plan's entire output is a *description* of Waves 1–4, so a stale base would have produced
a UAT describing a product that does not exist on the branch. `rev-list --count` would have read green.

## No yield claim, and no duplicate-count question — checked explicitly

The operator's ban is honoured in both directions:

- **No count is asked for.** A4a asks only the observable property: **"no two entries in the citation
  list point at the same source."** A4's header carries a ⛔ block explaining *why* a number cannot be
  asked for — the collapse depends on how often a best-effort URL resolution succeeded during that
  specific run, which is runtime data, and no count field is emitted anywhere by design.
- **No yield figure is stated.** The forbidden-phrase grep returns **0**.
- **The display-only limit is stated three times** — in the up-front "WHAT PHASE 22 DID NOT PROVE"
  block, in A4's closing ⚠, and in the DEF-21-02 closure. Wording used throughout: cost and
  corroboration **still count the duplicate rows** until the write-side identity fix lands in its own
  phase. The "Sources cited" tile is described as the count of distinct sources *shown*, explicitly not
  a statement about what the run paid for.

## Two operator rulings the UAT ASKS rather than assumes

Both are recorded as questions with their own slots, and the roll-up marks them "ruling, not a
pass/fail" so neither can be scored as a check:

1. **A3i — strike the fourth hover line?** `verification.hoverClickHint` ("Click to open the stored
   snapshot"), flagged by 22-UI-SPEC §2.2 as the one addition beyond the ruled three fields. The UAT
   states it is one element and one locale key and that nothing depends on it.
2. **A4c — explain the sparse numbering on screen?** The UAT explains the sparseness in plain words
   (a missing number means that source was the same page as an earlier one; the numbers are not
   renumbered because the downloadable report's `[n]` markers were frozen at synthesis, so renumbering
   would make the page and the report disagree about what `[7]` means) and then records the research
   recommendation to ship **without** an on-screen note, because any wording drifts towards the
   forbidden claim. **The operator decides.**

A closing line requires both rulings to be ROUTED after sign-off — implemented, or deferred with the
operator's agreement — never absorbed silently.

## Known Stubs

None. This plan produced documentation only; every verdict slot is *intentionally* unfilled and that
is the artifact's required state, not a stub.

## Threat Flags

None. No code, no dependency, no registry, no network call, no package install (T-22-SC intact). Four
markdown files under `.planning/`.

**Threat register dispositions honoured:**
- **T-22-28** (a deferred UAT step quietly disappearing) — all six steps carry an explicit status and
  a named successor in **both** Phase 21 documents; the pointer-count criteria are green (7 pointers).
- **T-22-29** (a verdict filled from inference) — every slot ships `_(awaiting operator)_`; the
  unchanged-count criterion on `21-UAT.md` is green at 40/40 and the diff is insertions-only.
- **T-22-30** (a question that cannot be answered honestly) — no duplicate count is requested,
  NOT-OBSERVABLE is declared legitimate, and the zero-spend rule is a ⛔ callout.

## Verification

| Check | Result |
|---|---|
| `test -f 22-UAT.md` | present |
| Task 1's 8 acceptance criteria | 8/8 PASS |
| Task 2's 7 acceptance criteria | 7/7 PASS |
| `21-UAT.md` diff | **36 insertions / 0 deletions** |
| `21-UAT.md` `awaiting operator` | **40 → 40** |
| all 4 `files_modified` staged (`git add -f`) and TRACKED (`git ls-files`) | yes, all 4 |
| research run triggered | **NONE.** No `gcloud`, no build, no deploy, no engine invocation |
| STATE.md / ROADMAP.md modified | **no** — the orchestrator owns those writes |

## Task Commits

1. **Task 1: Write 22-UAT.md** — `d8dc410` (1 file, 568 insertions)
2. **Task 2: Annotate the Phase 21 documents** — `98fc309` (3 files, 99 insertions, 0 deletions)

## Self-Check: PASSED

- `22-UAT.md` — FOUND
- `21-UAT.md` — FOUND, tracked, annotated (insertions only)
- `21-.../deferred-items.md` — FOUND, tracked, closure section present
- `22-.../deferred-items.md` — FOUND, tracked, cross-reference present
- commit `d8dc410` — FOUND in `git log`
- commit `98fc309` — FOUND in `git log`
- All four files confirmed via `git ls-files` (`.planning/` is gitignored, so `git add -f` was used
  throughout and tracking was verified after each commit rather than assumed)

---

*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat · Plan 09 · Wave 5*
