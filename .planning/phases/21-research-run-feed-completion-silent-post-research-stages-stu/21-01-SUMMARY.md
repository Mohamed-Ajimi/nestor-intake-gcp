---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 01
subsystem: ui
tags: [react, vitest, run-feed, observability, typescript]

# Dependency graph
requires:
  - phase: 15.3
    provides: the run-event contract, RunFeed.tsx and the dedicated run page
provides:
  - "A pure feedRows.ts carrying the settle rule and the hidden-rows rule, testable without a DOM"
  - "15 vitest assertions pinning both rules — the first MEASURED frontend rules on the run page"
  - "RunFeed.tsx consuming both rules instead of re-deriving them inline"
  - "The measurement that meta.is_live is a CONSTANT, not a liveness signal"
affects: [21-02, 21-03, 21-04, 21-05, 21-06, 21-07, 21-08, any future run-feed work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Extract a rule out of a component into lib/ so a node-env vitest can assert it — no jsdom needed"
    - "Liveness as a single conjunction, so no later branch can grant it on a subset of conditions"

key-files:
  created:
    - frontend/src/lib/research/feedRows.ts
    - frontend/src/lib/research/feedRows.test.ts
  modified:
    - frontend/src/components/research/RunFeed.tsx

key-decisions:
  - "meta.is_live is a constant, not a signal — the LIVE badge now derives from the same rule as the spinner"
  - "A settled agent_run gets CircleDot, not CheckCircle2 — the positional rule cannot know an outcome"
  - "agent_retry deliberately does NOT settle a row — the unit of work is still in flight"
  - "The plan's `npm run lint` criterion is unsatisfiable at this base commit; verified per-file instead"

patterns-established:
  - "Pure-rule extraction: a rule inside a component cannot be asserted without a DOM, so it moves to lib/"
  - "CRLF-safe prettier verification on Windows worktrees: strip CR, then check via --stdin-filepath"

requirements-completed: [SC2, SC3, D-07, D-08, D-09]

# Metrics
duration: 40min
completed: 2026-08-10
---

# Phase 21 Plan 01: Run Feed Settle + Collapse Gate Summary

**Agent rows stop spinning once their work is finished or the engine has moved on, and the "Show more" toggle now appears only when it actually hides rows — both rules extracted into a pure module and pinned by 15 real vitest assertions rather than by reading the source.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 3 of 3
- **Files modified:** 3 (2 created, 1 modified)
- **Vitest:** **51 tests passing across 5 files** (15 of them new, in `feedRows.test.ts`) — 0 failing
- **tsc:** `--noEmit` exits 0
- **i18n audit:** `RESULT: PASS — A/B/C clean` (CHECK B unchanged; this plan adds no `t()` key)
- **`frontend/package.json` and `frontend/package-lock.json`: UNTOUCHED.** No dependency was added; `vitest` and `lucide-react` were already present. `frontend/vitest.config.ts` is also unchanged — the existing `src/**/*.test.ts` include glob picked the new file up with no config edit.

## Accomplishments

- **The spinner is now a claim about NOW.** `isRowLive` returns true only when all four of `kind === "agent_run"`, `feedActive`, `isLastGroup` and "not already settled" hold. SC2 therefore holds by construction: a run that has ENDED has zero spinners anywhere, and a phase the engine has MOVED PAST has zero spinners.
- **The collapse toggle is gated on real hidden rows** — `isComplete && hasHiddenRows(body.length)`. SC3 holds by construction.
- **Both rules are MEASURED, not inspected.** This is the first behaviour on the run page with real assertions behind it, and it needed no new dependency.
- **A stale claim in `RunFeed.tsx`'s own header is corrected.** It asserted the frontend had no test framework; vitest 3.2.4 and `vitest.config.ts` have been committed for some time. What is genuinely absent is jsdom / `@testing-library/react`, so the memo-boundary warning survives — narrowed to what is actually true, and pointed at `feedRows.test.ts` for the two rules that now ARE measured.

## Task Commits

1. **Task 1: Create the pure settle + hidden-rows module** — `c3b010d` (feat)
2. **Task 2: Pin both rules with vitest assertions** — `ebebe35` (test)
3. **Task 3: Wire RunFeed to the rules and gate the toggle** — `1b5d928` (fix)

`git diff --stat` against the phase base shows exactly the three paths the plan named.

## Files Created/Modified

- `frontend/src/lib/research/feedRows.ts` — `COLLAPSED_PREVIEW_ROWS`, `AGENT_TERMINAL_KINDS`, `settledSeqs`, `isRowLive`, `hasHiddenRows`. Imports nothing from React and nothing from `@/components`; the single import is a TYPE.
- `frontend/src/lib/research/feedRows.test.ts` — 15 assertions, each named after the behaviour it protects rather than the function it calls.
- `frontend/src/components/research/RunFeed.tsx` — consumes all four exports; `feedActive` + `isLastGroup` passed down as primitives; `live` computed in the map ABOVE the `FeedRow` memo boundary; `settled` behind a `useMemo` keyed on the group's array identity.

## Decisions Made

**`meta.is_live` cannot be leaned on — and this is the answer to the open question in 21-CONTEXT's `<specifics>`.**
The plan's measured fact is confirmed and now recorded in the code: of the three production `agent_run` emit sites (`research_division.py:2392`, `workshop.py:525`, `workshop_rank.py:1837`), exactly ONE sets that flag — `research_division.py:2407`, as the literal `True`. It is a CONSTANT, not a liveness signal. The LIVE badge read it at the old `RunFeed.tsx:348`, which is why the badge outlived its row for the same reason the spinner did. Both now derive from the same `live` prop, so **the two can no longer disagree**. `metaBool` lost its only caller and was removed rather than left as a dead helper inviting the next reader to reach for it.

**A settled `agent_run` renders `CircleDot`, not a tick.** The positional settle rule knows only that the row is no longer about now — it cannot know whether the agent SUCCEEDED (the finish row carries that). `CheckCircle2` would assert an outcome the rule cannot know; a frozen `Loader2` reads as a hung spinner, which is the defect itself.

**`agent_retry` does not settle.** A retry means the unit of work is still in flight, so settling on it would re-create the defect one row earlier and harder to see. A test pins this.

**The memo boundaries are unchanged.** Every new prop crossing one (`isLastGroup`, `feedActive`, `live`) is a primitive.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `frontend/node_modules` absent; restored with `npm ci`**
- **Found during:** Task 1 (verification)
- **Issue:** No dependencies installed in the worktree, so `tsc`, `vitest` and `eslint` could not run at all.
- **Fix:** `npm ci --prefix frontend` — lockfile-faithful, per CLAUDE.md's standing rule (never `npm install`). Installs nothing new and leaves `package.json` / `package-lock.json` byte-identical.
- **Verification:** `git status --porcelain` shows neither manifest modified.

**2. [Rule 1 — Bug] Two acceptance criteria of Task 3 were literally unsatisfiable as written; both reconciled**
- **Found during:** Task 3
- **Issue A — the import line.** The criterion requires `grep "from \"@/lib/research/feedRows\""` to match **exactly one line** *and* that line to name all four symbols. The single-line form is **103 characters**, past prettier's `printWidth: 100`, so prettier wraps it — and a wrapped import puts the path on a line naming none of the symbols, failing the criterion, while the unwrapped form fails the `npm run lint` criterion. The two criteria contradict each other.
- **Fix A:** a `// prettier-ignore` directive on the import, with a comment naming why. Both criteria now hold: one line carrying all four names, and prettier reports the file clean.
- **Issue B — the header phrase.** Task 3(h) instructs correcting the sentence "this repo has no frontend test framework", while an acceptance criterion requires `grep "no frontend test framework"` to exit **non-zero**. Quoting the stale claim in order to correct it would trip the scan.
- **Fix B:** the correction describes the old claim without spelling it verbatim — the same "described rather than spelled" idiom this file already uses for its security and accessibility scans (see its own lines about that). The measurement is fully recorded; only the trigger string is avoided.

**3. [Rule 1 — Bug] Two pre-existing prettier deviations in `RunFeed.tsx`, normalised**
- **Found during:** Task 3 (verification)
- **Issue:** `stableAfterRow` and the collapse-toggle ternary were both wrapped where prettier joins them. Pre-existing, not caused by this plan — but invisible locally, because `core.autocrlf=true` makes prettier report one `Delete ␍` per line on **every** file and buries the real findings.
- **Fix:** normalised both. Zero behaviour change; `RunFeed.tsx` now passes `prettier --check` in the LF form that is actually committed.
- **Note:** `feedRows.ts` had one of its own (a wrapped `settledSeqs` signature), fixed the same way.

---

**Total deviations:** 3 auto-fixed (1 × Rule 3, 2 × Rule 1). **No scope creep** — no engine file, no `components/ui/`, no dependency, no config.

## Issues Encountered

**`npm run lint` cannot exit 0 at this base commit, and that is not this plan's doing.**
`frontend/scripts/c.ts` — an ad-hoc Supabase scratch script this phase never touches, imported by nothing in `src/` — carries 3 genuine `@typescript-eslint/no-explicit-any` errors. Since the script is `eslint .`, that one file reddens the whole command no matter what any plan does. **The criterion was red before this plan started.**

What was verified instead, per-file, is stronger than the criterion's intent:

```
npm exec --prefix frontend -- eslint --config frontend/eslint.config.js \
  frontend/src/components/research/RunFeed.tsx \
  frontend/src/lib/research/feedRows.ts \
  frontend/src/lib/research/feedRows.test.ts
```

→ **zero non-prettier rule violations** across all three files, and all three pass `prettier --check` on their committed LF content. Every remaining local report is a CRLF artifact of this Windows worktree (`git ls-files --eol` confirms `i/lf w/crlf`); CI checks out LF and never sees them. `frontend/cloudbuild.yaml` has no lint/tsc/vitest step, which is why this went unnoticed.

Logged for the phase, not fixed, in `deferred-items.md` alongside the CRLF-safe verification recipe — **the next plan in this phase that is handed a `npm run lint` criterion should read it before treating a red result as its own.**

## Known Stubs

None. No placeholder, no hardcoded empty value, no unwired data source. Both rules are fully implemented and exercised.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. `feedRows.ts` reads only `seq` and `kind` — an integer and an enum — and never touches `text`, `meta`, an intake id or a tenant id, so it cannot leak one (T-21-01-02). Every event string remains a React TEXT CHILD; no raw-HTML prop and no markdown renderer was introduced (T-21-01-01). `settledSeqs` is one linear pass per group inside a `useMemo` keyed on the group's array identity, so it cannot run on a cursor blink (T-21-01-03). Nothing was installed (T-21-01-SC).

## Next Phase Readiness

Ready. The two frontend defects the operator named are closed and both are regression-pinned.

**For the plans that add rows to the eight silent stages (21-02 … 21-06):** the collapse toggle will start appearing on those phases once their `body` exceeds `COLLAPSED_PREVIEW_ROWS` (2) — that is correct and intended. The gate remains meaningful for short phases.

**For anyone tempted by the D-08 alternative:** the cheap fix is in and correct by construction. The only state it can leave visibly wrong is a row settled by POSITION rather than identity when a stage interleaves starts and finishes out of order — the deferred correlation-key work (~22 emit sites) is still the escalation path, and 21-CONTEXT says to take it only if the cheap fix demonstrably leaves a wrong state on screen. **Nothing can demonstrate that until the ~$45 run executes**, which is exactly what D-01 sequences this phase before.

**Not verified by anything here:** the memo boundaries. Still inspected, not measured — this plan adds rows to the feed and so makes that gap more consequential, not less.

## Self-Check: PASSED

Verified against `git ls-tree -r HEAD` and `git log`, not against memory:

- `frontend/src/lib/research/feedRows.ts` — tracked at HEAD ✓
- `frontend/src/lib/research/feedRows.test.ts` — tracked at HEAD ✓
- `frontend/src/components/research/RunFeed.tsx` — modified, committed in `1b5d928` ✓
- `.planning/.../21-01-SUMMARY.md` — tracked at HEAD ✓ (required `git add -f`; `.planning/` is gitignored)
- `.planning/.../deferred-items.md` — tracked at HEAD ✓
- Commits `c3b010d`, `ebebe35`, `1b5d928`, `8f778b7` all present ✓
- `git status --porcelain` empty — nothing left uncommitted in the worktree ✓
- `STATE.md` and `ROADMAP.md` NOT modified — the orchestrator owns those writes ✓

**Worktree base:** this agent hit the documented stale-base trap on startup — `merge-base`
was `a3a0c96` against an expected base of `eac6f2b`. Corrected with `git reset --hard`
before any file was read, and both positive-presence sentinels (`21-01-PLAN.md`,
`21-CONTEXT.md`) confirmed present afterwards. **That makes it 24 in a row.**

---
*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Completed: 2026-08-10*
