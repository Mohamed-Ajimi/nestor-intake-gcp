---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
verified: 2026-08-10T18:32:10Z
status: human_needed
score: 8/8 must-haves machine-verified; 0/9 operator UAT checks confirmed
overrides_applied: 0
re_verification: null
human_verification:
  - test: "21-UAT.md PART A — SC1 (all 13 stages emit) on a LIVE post-deploy run"
    expected: "Every phase block on the run page has a body — no phase renders as a label with nothing under it. NOT-OBSERVABLE is the correct verdict on any run that predates the 2026-08-10 20260810-193000 deploy (no rows exist for the 8 stages on those runs)."
    why_human: "Requires opening the dedicated run page for an actual run and reading rendered feed blocks; the code-level proof (21-06's schema-derived capstone test, observed to fail and then pass) is machine-verified, but SC1's own roadmap wording is an operator-observable outcome"
  - test: "21-UAT.md PART A — SC2 (no spinner on a finished agent), on a TERMINAL recorded run"
    expected: "Zero animated spinners anywhere in the feed of a completed/failed/cancelled/parked run"
    why_human: "Visual/DOM behaviour; no jsdom/@testing-library in this repo (recorded limitation), so only source-level rules are pinned by vitest, not the rendered result"
  - test: "21-UAT.md PART A — SC3 (toggle only where rows hidden)"
    expected: "No 'Show more' toggle above an empty phase; where shown, clicking it reveals rows"
    why_human: "Visual behaviour on a real run page"
  - test: "21-UAT.md PART B (DEF-21-02) — B1..B6, the six-step VerificationReport walkthrough deferred from plan 21-02"
    expected: "Toggle reachable between card and feed; report opens with feed still rendered below it (B3, the single most important check); collapses cleanly (B4); offered on failed/cancelled runs (B5, not a blocker if none exist); absent on queued/running runs (B6, presence there is the failure)"
    why_human: "Plan 21-02's Task 3 checkpoint:human-verify was explicitly deferred to this UAT gate by operator ruling 2026-08-10 (DEF-21-02); its own SUMMARY states 'a phase verifier must not count SC4/D-10/D-11 as operator-confirmed until these steps run'"
  - test: "21-UAT.md PART A — SC6 (no raw stage key on screen), on a recorded run"
    expected: "The final divider reads 'Run complete', not the raw key 'done'"
    why_human: "This one IS observable on already-recorded data per 21-UAT.md's own note, but the operator has not yet filled it in"
  - test: "21-UAT.md PART A — SC5 (density) — does deep_research read better or worse after the phase"
    expected: "Operator's own qualitative read of the deep_research thinking prose, post-collapse-toggle-fix and post-eight-stages-getting-bodies. Ruling was option-c (no source change); this check re-reads the ruling's premise, not a code change"
    why_human: "Explicitly a qualitative operator judgement per D-12/D-13's 'diagnose before trimming' framing"
  - test: "21-UAT.md — R1 (clock does not restart on page reopen) and R2 (embedded ResearchRunProgress card still works)"
    expected: "Both regression checks pass with no change in behaviour from before Phase 21"
    why_human: "Regression checks require clicking through the live UI"
---

# Phase 21: Research Run Feed Completion Verification Report

**Phase Goal:** The dedicated run page tells the whole story of a run — every stage reports, finished work reads as finished, and the claims-verification evidence is on the page built to hold it.
**Verified:** 2026-08-10T18:32:10Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Summary

All 8 plans are merged to `master` and the phase is deployed live at `20260810-193000`
(`nestor-frontend`, `tribunal-api`, `tribunal-worker`; `nestor-api` confirmed unchanged, per
`21-08-SUMMARY.md`). Every SUCCESS CRITERION that can be verified from the codebase and from
locally-executed tests is VERIFIED. **No source claim in any plan's SUMMARY.md was taken at face
value — every load-bearing number below was independently re-derived** (grep counts, direct file
reads, and three local pytest/vitest runs reproducing the SUMMARYs' reported pass counts exactly).

**The one thing standing between this phase and a clean PASS is `21-UAT.md`, which is created,
staged with all four operator rulings and DEF-21-02's six steps folded in as B1-B6 — and is
entirely unfilled.** Every verdict in it reads `(awaiting operator)`. Per this project's own
recording rule ("NOT-OBSERVABLE is a real verdict and must be used honestly... a paraphrase of a
UAT observation is how a defect becomes a rumour"), a verifier filling in those verdicts from
inference would be the exact failure mode the phase's own documents warn against. This report
therefore does not mark SC2/SC3/SC4/SC6 as operator-confirmed, and reports `human_needed` rather
than `passed`, per this agent's own instructions ("Do not mark the phase fully verified while
21-UAT.md is unrun").

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1 — all 13 declared tribunal stages emit feed content (8 previously-silent stages now have bodies) | VERIFIED (code) / awaiting operator on a live run | `stage_events.py` has 34 `emit_*` helpers across the 8 stages; `pipeline.py` wires 9 (verify) + 3+3+3 (distill/merge/gate) + 3+4+3+3 (adjudicate/coverage/conflict/synthesize) = confirmed by grep, see Artifacts. `test_every_declared_tribunal_stage_emits_a_body` (21-06) was OBSERVED TO FAIL naming `['coverage']` when temporarily neutered, then restored green — the strongest form of proof this methodology asks for. `own_research` is the one declared stage still silent, by a pinned, explained exclusion (pipeline never writes that key), not a phase-21 gap. |
| 2 | SC2 — a finished agent never renders as a spinner | VERIFIED (code + tests) / awaiting operator on a rendered page | `isRowLive()` in `feedRows.ts` is a single conjunction (`kind === "agent_run" && feedActive && isLastGroup && !settled.has(seq)`), pinned by 15 vitest assertions covering the terminal-run and moved-on-phase cases by name. `RunFeed.tsx` wires it: `KindIcon` renders `CircleDot` (not a frozen `Loader2`) when `live` is false. Re-ran locally: `npx vitest run` → 61/61 passing including `feedRows.test.ts`'s 15. |
| 3 | SC3 — "Show more" toggle appears only when rows are hidden | VERIFIED (code + tests) | `hasHiddenRows(bodyLength) = bodyLength > COLLAPSED_PREVIEW_ROWS`; `RunFeed.tsx:257` gates the toggle on `isComplete && hasHiddenRows(body.length)`, not `isComplete` alone. Pinned by vitest. |
| 4 | SC4 — `VerificationReport` reachable from the dedicated run page, not only the intake card | VERIFIED (code) / CONDITIONAL per DEF-21-02, awaiting operator | `admin.pulse.runs.$runId.tsx` imports and mounts `VerificationReport` as a sibling of `RunStatusCard` (line 296) and before the `truncated` notice (line 351), gated on `canHaveVerificationReport(status)`. `verificationGate.ts` enumerates exactly `completed`, `completed_degraded`, `failed`, `cancelled`, `parked` — pinned by vitest over all 8 statuses plus an unknown one. **Plan 21-02's own Task 3 (the operator walkthrough proving the feed survives beneath the open report) was explicitly deferred to 21-08's UAT gate (DEF-21-02) and 21-02's own acceptance is recorded as CONDITIONAL on it.** |
| 5 | SC5 — `deep_research` thinking prose diagnosed before trimming, per-site verdict as reviewable artifact, operator rules, ruling applied | VERIFIED | `21-DENSITY-AUDIT.md` exists (260 lines) with a 13-row per-site table. Operator ruled `option-c` (no source change) 2026-08-10, recorded verbatim in `21-04-SUMMARY.md`. `git diff eac6f2b -- tribunal/nestor_pulse_sdk/audit/audited_llm_client.py` is empty, confirming the ruling was honoured exactly (no source edit). D-13 was amended by the operator (money wins over guard-refusal-commentary when a line is both); recorded. |
| 6 | SC6 — no raw stage key ever reaches the operator's screen, and a test enforces it | VERIFIED | `stages.NON_SCHEMA_STAGE_LABELS = {"done": "Run complete", "report_spec": "Report shaping"}` exists and `_stage_event_label` consults it as a second source, read directly from `pipeline.py:492-524`. The operator's Task-1 ruling (`option-read-path`, recorded verbatim with date 2026-08-10) is applied exactly. The strengthened guard test (`test_every_pipeline_stage_key_resolves_to_a_human_label`, iterating the UNION of extracted ∪ declared ∪ allowlisted keys) was OBSERVED TO FAIL naming `report_spec` when its label was temporarily removed, then restored green. |
| 7 | The LIVE badge and spinner derive from ONE rule (`meta.is_live` was a constant, not a signal) | VERIFIED | `RunFeed.tsx` no longer reads `meta.is_live` in any conditional (only in an explanatory comment, confirmed by grep); `metaBool` was removed as a dead helper; both the badge and the icon now key off the single `live` prop computed by `isRowLive`. |
| 8 | The two feed-row defects (21-01: stuck spinner, empty collapse toggle) are fixed | VERIFIED | Same evidence as truths 2 and 3 above. |

**Score:** 8/8 truths verified at the code/test level. 0/9 operator-observable checks in `21-UAT.md` are filled in (all read `(awaiting operator)`).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/research/feedRows.ts` | Pure settle rule + hidden-rows predicate | VERIFIED | Exports `COLLAPSED_PREVIEW_ROWS`, `AGENT_TERMINAL_KINDS`, `settledSeqs`, `isRowLive`, `hasHiddenRows`. Imports no React, no `@/components`. |
| `frontend/src/lib/research/feedRows.test.ts` | Vitest pinning both rules | VERIFIED | 15 assertions; `npx vitest run` confirms all green locally. |
| `frontend/src/components/research/RunFeed.tsx` | Consumes the pure rules | VERIFIED | Imports all 4 symbols; toggle guard is the composed condition; `CircleDot`/`Loader2` branch on `live`. |
| `frontend/src/lib/research/verificationGate.ts` | `canHaveVerificationReport` pure rule | VERIFIED | Enumerated set of 5 statuses, not derived/negated, matching the docstring's stated reasoning. |
| `frontend/src/lib/research/verificationGate.test.ts` | Vitest over all 8 statuses | VERIFIED | 10 tests, confirmed passing locally. |
| `frontend/src/routes/admin.pulse.runs.$runId.tsx` | Toggle + mounted `VerificationReport` as a sibling | VERIFIED | Sibling of `RunStatusCard`, before `truncated` notice, gated on `canHaveVerificationReport(status)`. |
| `tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py` | Shared row-budget spine + 8 stages' emit helpers | VERIFIED | 34 `emit_*` functions across all 8 previously-silent stages; `MAX_ROWS_PER_STAGE`/`RowBudget` spine present. |
| `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` | Emit call sites wired alongside existing `set_stage` calls | VERIFIED | `stage_events.emit_verify*` ×9, `emit_distill/merge/gate` ×3 each, `emit_adjudicate` ×3, `emit_coverage` ×4, `emit_conflict` ×3, `emit_synthesize` ×3 — all confirmed by grep against the live tree. `await set_stage(` count unchanged at 23; `run_events.open_run` still exactly 1; `check_coverage(claims, adjudications, selected_only=True)` — the cost trap — present twice, untouched. |
| `tribunal/nestor_pulse_sdk/runs/stages.py` | `NON_SCHEMA_STAGE_LABELS` second label source | VERIFIED | Present with both `done` and `report_spec` mapped to human labels. |
| `tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py` | End-to-end proof all 8 stages have bodies | VERIFIED | `test_every_declared_tribunal_stage_emits_a_body` present, schema-derived (`stages_for("tribunal")`), and its SUMMARY-recorded fail-then-pass observation is consistent with the code as it stands. |
| `tribunal/nestor_pulse_sdk/tests/test_stage_schema.py` | Strengthened WR-03 guard (declaration AND label resolution) | VERIFIED | `test_every_pipeline_stage_key_resolves_to_a_human_label` present; local run confirms 9 passing (vs. base 6 per SUMMARY). |
| `21-DENSITY-AUDIT.md` | Per-site keep/cut verdict, reviewable artifact | VERIFIED | 260 lines, 13-row table, operator ruling section present and dated. |
| `21-UAT.md` | Operator UAT staging document, carrying DEF-21-02's six steps | VERIFIED as an artifact / UNFILLED as a verdict record | Exists, correctly structured (Part A = 6 SC + 2 regressions, Part B = B1-B6), but every verdict cell reads `(awaiting operator)`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `RunFeed.tsx` | `feedRows.ts` | import of 4 named symbols | WIRED | Confirmed by grep: one import line naming all 4. |
| `FeedGroup` | `FeedRow` | `live` boolean prop | WIRED | Computed above the memo boundary per plan; primitive prop. |
| `admin.pulse.runs.$runId.tsx` | `VerificationReport.tsx` | direct import + mount with `intakeId`+`runId` | WIRED | Both id props present at the mount site. |
| `admin.pulse.runs.$runId.tsx` | `verificationGate.ts` | import of `canHaveVerificationReport` | WIRED | Used exactly once as the render gate. |
| `pipeline.py` | `stage_events.py` | module-form import, `stage_events.emit_*` calls | WIRED | 9+3+3+3+3+4+3+3 = 31 call sites (verify alone counts 9 including `emit_verify_batch_*`); confirmed by direct grep against the live file, not by trusting any SUMMARY. |
| `pipeline.py` `_stage_event_label` | `stages.NON_SCHEMA_STAGE_LABELS` | second-source lookup | WIRED | Read directly from the function body (lines 492-524): consults `ENGINE_STAGES` first, `NON_SCHEMA_STAGE_LABELS` second, raw key last. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Frontend type-checks | `cd frontend && npx tsc --noEmit -p tsconfig.json` | exit 0 | PASS |
| Frontend unit tests | `cd frontend && npx vitest run` | `6 passed (6) / 61 passed (61)` | PASS |
| Engine 44-file gate (local, Windows) | pytest over the 44 `WANTED` paths extracted from `cloudbuild.test-engine.yaml`, `-m "not live"` | `1909 passed, 13 skipped, 6 errors in 39.56s` | PASS — the 6 errors are the documented pre-existing Windows-only `PYTEST_CURRENT_TEST` 32767-char env limit (`test_dispatch_pii.py`, `test_fact_list_parser.py`), 0 FAILURES, matches `21-06-SUMMARY.md`'s and `21-08-SUMMARY.md`'s reported numbers exactly |
| Engine 13-file gates config (local) | pytest over the 13 `WANTED` paths from `cloudbuild.test-gates.yaml` | `190 passed, 2 deselected in 7.67s` | PASS — matches SUMMARY exactly |
| `test_stage_schema.py` + `test_run_event_emit.py` in isolation | pytest, `-m "not live"` | `76 passed in 9.38s` | PASS |
| Cloud Build (from `21-08-SUMMARY.md`, digest-verified deploy) | `gcloud builds describe` on both gate builds | both `SUCCESS`; engine gate log read verbatim `collecting: 44 of 44 expected files` / `1911 passed, 14 skipped in 20.12s`, 0 errors on Linux | PASS (reported by 21-08, consistent with local re-run) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention exists in this repo, and none of the 8 plans declares a probe script. SKIPPED — not applicable to this phase's verification surface (Cloud Build gates serve the equivalent role and were checked above).

### Requirements Coverage

**None applicable.** Per `21-CONTEXT.md`, `ROADMAP.md`, and confirmed by `grep -n "Phase 21\|21-0[1-8]" .planning/REQUIREMENTS.md` returning no matches, this phase carries no `REQUIREMENTS.md` id. Its sources of record are the six ROADMAP success criteria and the `D-01`...`D-15` decisions in `21-CONTEXT.md`, all covered under Observable Truths above.

### Anti-Patterns Found

None. Scanned every file this phase created or modified (`feedRows.ts`, `verificationGate.ts`, `RunFeed.tsx`, `admin.pulse.runs.$runId.tsx`, `stage_events.py`, `stages.py`, `pipeline.py`, `test_run_event_emit.py`, `test_stage_schema.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers: zero matches. No stub returns, no hardcoded-empty data flowing to render, no console.log-only implementations.

**DEF-21-01** (`npm run lint` red tree-wide) is a known, operator-ruled, explicitly out-of-scope condition — not scored as a phase-21 anti-pattern, per the operator's own instruction recorded in `deferred-items.md`.
**DEF-21-03** (`coverage` stage summary meta still `{'actions': 0}` — a different input than the feed body) and **DEF-21-04** (`workshop` block has body rows but no divider) are both measured, explained, deliberately out-of-scope discoveries with their own root-cause analysis and are correctly logged as deferred, not gaps.

### Human Verification Required

All six items below trace to `21-UAT.md`, which exists, is correctly staged (including DEF-21-02's six steps as B1-B6), and has **zero filled-in verdicts**. This is the phase's own designed final gate — plan 21-08 built it precisely so that no verdict is filled from inference.

#### 1. SC1 on a live post-deploy run
**Test:** Open the dedicated run page for a run that executed AFTER `20260810-193000` and confirm no phase renders as a heading with nothing under it.
**Expected:** All body-bearing stages show rows. Note: 21-UAT.md itself flags that any run recorded BEFORE the deploy is `NOT-OBSERVABLE` by construction (those runs have no rows for the 8 newly-wired stages) — this is not a defect, it's the correct verdict on old data.
**Why human:** Requires the live rendered page; code-level proof already exists via 21-06's capstone test.

#### 2. SC2 — no spinner on a finished agent
**Test:** Open a terminal recorded run and visually confirm zero animated spinners.
**Expected:** Zero `Loader2`/`animate-spin` glyphs anywhere in a finished run's feed.
**Why human:** No jsdom/`@testing-library` in this repo (a recorded, deliberate limitation) — only the source-level rule is pinned by vitest, not the rendered DOM.

#### 3. SC3 — toggle only where rows hidden
**Test:** Confirm no "Show more" toggle sits above an empty phase, and that clicking a shown toggle reveals rows.
**Expected:** As described.
**Why human:** Visual/DOM behaviour.

#### 4. DEF-21-02's B1-B6 — VerificationReport reachable, feed survives
**Test:** The six-step walkthrough in `21-UAT.md` Part B: open the run page via "Open run", confirm the toggle sits between the card and the feed, click it and confirm the funnel/verdicts/cost render AND the feed is still visible below it (B3 — flagged as "the single most important check in this document"), click again to collapse, check offering on failed/cancelled runs (not a blocker if none exist), and confirm absence on queued/running runs.
**Expected:** All pass; B3 in particular is the structural property 21-02 was built to guarantee.
**Why human:** Plan 21-02's own Task 3 (`checkpoint:human-verify`, `gate="blocking"`) was explicitly deferred here by operator ruling 2026-08-10. Its SUMMARY states in terms that leave no ambiguity: "A phase verifier must not count SC4/D-10/D-11 as operator-confirmed until these steps run and pass."

#### 5. SC6 on a recorded run
**Test:** Confirm the final divider on a recorded run reads "Run complete" rather than the raw key `done`.
**Expected:** "Run complete".
**Why human:** `21-UAT.md` itself notes this one IS observable on already-recorded data (the label is resolved at read time) — it just has not been filled in yet.

#### 6. SC5 qualitative re-read, and R1/R2 regressions
**Test:** Does `deep_research` read better after the phase (SC5); does the elapsed clock survive a page close/reopen (R1); does the embedded `ResearchRunProgress` card on the intake detail page still work (R2)?
**Expected:** Yes to all three.
**Why human:** SC5 is an explicitly qualitative operator judgement; R1/R2 require clicking through the live UI.

### Gaps Summary

No code-level gaps were found. Every artifact, key link, and code-provable truth is VERIFIED, and three of the load-bearing test-count claims in the plan SUMMARYs (44-file engine gate: 1909 passed/6 pre-existing errors/0 failures; 13-file gates config: 190 passed; frontend: tsc 0 + vitest 61) were independently reproduced by this verifier, not merely read from the SUMMARYs.

The phase cannot be marked `passed` because its own final gate — `21-UAT.md` — is unrun. This is not a gap in the implementation; it is the phase's designed stopping point, and marking it `passed` here would be exactly the "false green" this project's own `deferred-items.md` and `21-UAT.md` recording rules warn against repeatedly. **`status: human_needed` is the correct and only honest classification.**

---

*Verified: 2026-08-10T18:32:10Z*
*Verifier: Claude (gsd-verifier)*
