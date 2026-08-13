---
phase: 23-report-legibility-business-friendly-funnel-labels-and-an-hon
plan: 03
subsystem: frontend-work-phase-banner
tags: [i18n, work-phase, uat-fix, sse, wiring, honesty]
requires:
  - "frontend/src/lib/research/workPhase.ts (deriveWorkPhasePresentation — plan 23-02)"
  - "frontend/src/components/intake/ResearchRunProgress.tsx (useActiveResearchRun — unchanged)"
  - "frontend/src/locales/{en,nl,fr}/intake.json (the five nextStep.inResearch*Body keys — plan 23-02)"
provides:
  - "NextStepBanner Props.researchRunStatus — the deep-research run status, exhaustively mapped over WorkPhasePresentation"
  - "IntakeOpenRunLink({ runId }) — the link surface, no longer owning a stream"
  - "the intake detail route as the single owner of the page's one research SSE connection"
affects:
  - "/admin/pulse intake detail — the work-phase banner now says what is true of the live run"
  - "the app's ONLY navigation into the run page (preserved, re-plumbed)"
tech-stack:
  added: []
  patterns:
    - "Hook lifted to the route so two consumers share ONE stream — the call moved, it did not multiply"
    - "Rules-of-hooks-safe conditional connection: the CALL stays unconditional, the ARGUMENT carries the gate (undefined is the hook's documented do-not-connect value)"
key-files:
  created:
    - .planning/phases/23-report-legibility-business-friendly-funnel-labels-and-an-hon/deferred-items.md
  modified:
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/intake/ResearchRunProgress.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
---

# Plan 23-03 — the work-phase banner tells the truth about the live run

## What an operator now sees

**On an intake whose research run has finished:** the Work phase panel says the research run has
finished and the results are ready to review — it no longer says "Nestor is researching" and no
longer tells them to "let run-research run". The intake's own status stays `in_research` until they
press Deliver, exactly as before; only the sentence stopped lying about it.

**While the run is still going:** the panel still says so.

**When no run state is known** (no run, or the stream has produced nothing yet): the panel claims
neither running nor finished. That is the default, so a caller that was never updated degrades to
neutral copy rather than to a false claim.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Split the banner's `in_research` branch on the run's presentation; retire `nextStep.inResearchBody` with its last referrer | `90a5ca7` |
| 2 | The intake page owns its one research stream and feeds the banner | `e547fec` |
| 3 | Record the phase's deferred items and both corrections to `22-UAT.md` | `479f7e1` |

## Verification — every number

Run from `frontend/` unless noted.

| # | Check | Baseline (`27594dc`) | After | Verdict |
|---|-------|----------------------|-------|---------|
| 1 | `npm test` | 123 passed / 9 files | **123 passed / 9 files** | green |
| 2 | `npx tsc --noEmit` | 0 errors | **0 errors** | no new errors |
| 3 | `node scripts/i18n-audit.mjs` | PASS | **PASS, exit 0** (107 CHECK-D advisories, unchanged) | green |
| 4 | `bash frontend/scripts/ci_no_hardcoded_dutch.sh` (from repo root) | exit 1 | **exit 1** | unchanged |
| 5 | `grep -rn "run-research" frontend/src \| wc -l` | 0 | **0** | ✓ |
| 6 | `grep -rn "inResearchBody" src \| wc -l` | 1 | **0** | ✓ retired |
| 6b | `grep -rn "inResearchRunningBody" src \| wc -l` | 0 | **4** | ✓ non-zero |
| 7 | `grep -c "useActiveResearchRun(" src/routes/admin.pulse.intakes.$id.tsx` | 0 | **1** | ✓ criterion is 1 |
| 8 | `grep -c "IntakeOpenRunLink" src/routes/admin.pulse.intakes.$id.tsx` | 2 | **3** | see note below |
| 9 | phase-wide `git diff --name-only 48b946c..HEAD -- frontend` | — | **14 files**, all inside the three plans' `files_modified` | ✓ |

**react-hooks lint** on the three touched components: **3 findings at baseline, 3 after — zero new.**
None is a rules-of-hooks violation; all three are pre-existing (`exhaustive-deps` warning at `:485`,
a CRLF `prettier/prettier` error at `:656`, and an unused-disable warning on the same line).

**`ResearchRunProgress.tsx` diff extent:** a single hunk, `@@ -237,22 +237,27 @@` — confined to
`IntakeOpenRunLink` and its docstring. `useActiveResearchRun` itself, the unrendered
`ResearchRunProgress` component body, and the run page are all untouched.

### Note on criterion 8 — a miscounted literal, reported not chased

The plan asserts `grep -c "IntakeOpenRunLink"` returns **2**; it returns **3**. The third line is the
explanatory comment Task 2 added above the lifted hook, which names the component it was lifted out
of. The criterion's purpose — the link is still imported and still rendered — is met exactly
(import at `:59`, render at `:1220`). Editing a correct comment to satisfy a literal number would be
the wrong trade. This is the **third** miscounted grep-count criterion in this phase; plan 23-01
reported two others, both of which were already wrong at HEAD.

## The two load-bearing constraints, verified explicitly

**Exactly ONE research SSE connection on the intake detail page.** `useActiveResearchRun` has one
call site on that page (`admin.pulse.intakes.$id.tsx:326`) and zero inside `IntakeOpenRunLink`. The
full `ResearchRunProgress` feed component is not imported on that page at all (D-22-5), so its own
internal call at `:638` cannot fire there; the run page's call is a different page. **The call moved,
it did not multiply.** A second call would have opened a second stream to the same endpoint and held
a second server handler open to its `MAX_STREAM_SECONDS` cap (T-23-21).

**The "Open run" link survives.** It is the app's ONLY navigation into the run page and Phase 22
nearly deleted it by accident (T-23-22). `IntakeOpenRunLink` is still defined, still returns
`<OpenRunLink runId={runId} />`, still renders `to="/admin/pulse/runs/$runId"`, and is still rendered
by the route at `:1220`.

**The connection gate is unchanged.** The hook's argument is gated by the same
`RESEARCH_SURFACE_STATUSES` test that gates the link's render, so the stream opens for exactly the
same intakes, at exactly the same times, as before this change — not merely for similar ones. It was
not widened (an unconditional call would open a stream for every draft and submitted intake) and not
dropped.

## Deviations

**This plan was executed in two parts.** The wave-3 executor was terminated mid-flight by a provider
error (`Your organization has disabled Claude subscription access for Claude Code`) after committing
Task 1, with Task 2 complete but uncommitted in its worktree and Task 3 unstarted. Rather than
re-dispatch and redo the work, the orchestrator ran the documented safe-resume path: verified the
worktree's base was correct, merged the committed Task 1, carried the uncommitted Task-2 work onto
the main tree verbatim, verified it there against the full gate battery, and committed it. Tasks 2
and 3 were then completed inline. **No work was lost and nothing was redone from scratch.**

**The stale-base trap did NOT fire on this worktree** — the first of the phase's three spawns to land
on its correct base (`27594dc`). Plans 23-01 and 23-02 both spawned at `a3a0c96`, 31 commits stale,
and both were saved by the merge-base assertion.

## Corrections to source documents

Both are recorded in full, with evidence, in this phase's `deferred-items.md`:

- **`22-UAT.md` § UAT-22-F1 says the funnel has 6 keys.** It has **18 numeric** ones. Measured
  derivation: `_build_funnel` (`pipeline.py:973-1085`) returns **20** keys — 9 gate-owned from
  `gates.py:120-129` plus 11 stage-owned — of which `verification_degraded` (bool) and
  `degradation_reasons` (list) are dropped by the strict `typeof === "number"` filter at
  `VerificationReport.tsx:403`. Plan 23-01 labelled exactly those 18. **Phase 23's own planning
  documents reached 18 by "nine plus nine", which is the right total by the wrong route** —
  `pipeline.py` contributes eleven, two non-numeric. Anyone extending the label set must count what
  `_build_funnel` returns and then apply the numeric filter.
- **`22-UAT.md` § UAT-22-F4 calls defect 3 CLIENT-FACING.** It is operator-facing: the string has
  exactly one render site, under `/admin/pulse`. Real defect, fixed by 23-02; wrong framing.

## Deferred

- **DEF-23-01** — `research.currentStage` prints a raw pipeline stage key on the run page. One live
  site (`admin.pulse.runs.$runId.index.tsx:274`), one dead (`ResearchRunProgress.tsx:938`, inside the
  unrendered body per DEF-22-01). A different vocabulary on a different page.
- **DEF-23-02** — `backend/scripts/ci_no_run_research.sh:26-30`'s comment cites the Dutch UI string
  that 23-02 removed. Routed here from `23-02-SUMMARY.md`. The guard's regex is anchored to
  invocation syntax and is unaffected; only the comment is stale.

## Known stubs

None. `deriveWorkPhasePresentation` and the five bodies that plan 23-02 left uncalled are now wired
and reachable.

## What this does NOT prove

**Nothing here is OBSERVED.** Every criterion in this phase is satisfiable on the tree alone — there
was no run, no deploy, and **zero spend**, as the plan required. No test covers the banner
*component*: `workPhase.test.ts` pins the rule and `funnelLabels.test.ts` pins the vocabulary, but
the wiring itself (the prop reaching the branch, the single stream, the surviving link) is verified
by static assertion and typecheck, not by a rendering test. An operator opening a finished intake is
still the first real look at it.

## Self-Check: PASSED
