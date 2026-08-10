---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 06
subsystem: tribunal-engine-observability
tags: [run-events, feed, adjudicate, coverage, conflict, synthesize, stage-events, observability, SC1]
requires:
  - "tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py (21-03 spine + 21-05 _sentence_or_none)"
  - "tribunal/nestor_pulse_sdk/runs/run_events.py::emit_safe (15.3-01)"
  - "tribunal/nestor_pulse_sdk/runs/stages.py::stages_for (the capstone's authority)"
  - "tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py (the stubbed harness)"
provides:
  - "the adjudicate / coverage / conflict / synthesize feed bodies — SC1 CLOSED"
  - "a schema-derived capstone test that fails naming any stage which goes silent"
  - "recipe step (h) in HOW TO ADD THE NEXT STAGE: a row that names a population must count it"
  - "_write_final_report(resumed=False) — feed-only, defaulted, no caller changed"
affects:
  - "21-07 changes stage LABELS, not bodies; the capstone will hold it to SC1"
  - "frontend RunFeed.tsx now receives a non-empty body for every stage the run reports"
tech-stack:
  added: []
  patterns:
    - "a count that names a POPULATION is walked inside the thunk, never approximated at the call site"
    - "a defensive outer-level binding, so a closing row can read a name bound only inside a branch"
    - "an exclusion is PINNED as a set assertion, never a hardcoded skip"
key-files:
  created: []
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
    - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
decisions:
  - "D-03 honoured: zero new event kinds — dispatch / plan / thinking / agent_fail only"
  - "D-04: each of the four emits a header, per-item rows where they exist, and a closing line"
  - "D-05: one RowBudget for adjudicate and one for conflict, each created once and flushed once"
  - "D-06 honoured: no hand-emitted divider or summary; every text built inside a thunk"
  - "D-13 as amended 2026-08-10: the coverage re-entry row is a MONEY signal and is kept"
  - "21-CONTEXT's summary-meta hypothesis is REFUTED by measurement, not asserted into truth"
  - "own_research is excluded from the capstone by a PINNED SET, because the pipeline never writes the key"
metrics:
  duration: ~85 min
  completed: 2026-08-10
---

# Phase 21 Plan 06: SC1 Closed — the Last Four Stages Get Bodies

`adjudicate`, `coverage`, `conflict` and `synthesize` were the last four of the
eight stages 15.3 left silent. Adjudication now names every claim the
fact-checking threw out, not just how many. The coverage gate — the emptiest
stage in the engine, and the one guarding the largest bill — now reports the
population it is checking, the paid re-check it dispatches, the breaker's refusal
verbatim, and its own verdict. Conflict detection distinguishes a contradiction
it RESOLVED (the report lost a claim) from one it left CONTESTED (both sides
ship). Synthesis shows the subtractive scrub that makes the whole Tribunal stick
to the delivered report — and emits a row on the resume path, where it never had
one. **No stage the pipeline reports is silent any more, and that is now asserted
from the schema rather than from a list.**

## The numbers the plan asked for

| Measurement | Base (`ee3c169`) | After |
|---|---|---|
| `test_run_event_emit.py` passing tests | **56** | **67** (+11; the plan required ≥ 8) |
| full 44-file engine gate | 1898 passed, 13 skipped, 6 errors | **1909 passed, 13 skipped, 6 errors, 0 failures** |
| `grep -c "await set_stage(" pipeline.py` | **23** | **23** — unchanged |
| `grep -c "run_events.open_run" pipeline.py` | **1** | **1** — no second call |
| `grep -c "stage_events\.emit_adjudicate"` | 0 | **3** (required ≥ 3) |
| `grep -c "stage_events\.emit_coverage"` | 0 | **4** (required ≥ 4) |
| `grep -c "stage_events\.emit_conflict"` | 0 | **3** (required ≥ 3) |
| `grep -c "stage_events\.emit_synthesize"` | 0 | **3** (required ≥ 3) |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | 44 | **44** — file NOT edited |
| `_adjudicate_budget` / `_conflict_budget` | — | each **1** assignment, **1** `.flush(` |

**The unchanged `await set_stage(` count is again the strongest single proof that
this plan added observability and did not touch behaviour.**

### Body rows in the stubbed run — 0 → N, per stage

Measured by driving the real pipeline against the stubbed harness and reading
`run_events._writer`, using `RunFeed.tsx`'s own `body` filter (`kind` is neither
`divider` nor `summary`). Measured at the base commit AND after, in the same way.

| stage | before | after | what they are |
|---|---|---|---|
| `adjudicate` | **0** | **3** | 1 `dispatch` + 1 `thinking` drop row + 1 closing `thinking` |
| `coverage` | **0** | **2** | 1 `dispatch` + 1 closing `thinking` |
| `conflict` | **0** | **2** | 1 `dispatch` + 1 closing `thinking` |
| `synthesize` | **0** | **3** | 1 `dispatch` + 1 scrub `thinking` + 1 writing `thinking` |

The clean harness's conflict detector returns `[]` and its coverage gate PASSES,
so the per-item conflict rows and both re-entry rows do not appear on the clean
run. That is why they are proved against a one-hook subclass and at unit level
respectively rather than counted as zero and called a pass — the exact vacuity
this file's own header warns about.

### Every stage's body, from the same measurement

`intake` 2 · `workshop` 12 · `research_division` 2 · `deep_research` 7 ·
`distill` 5 · `merge` 3 · `gate` 2 · `verify` 16 · `adjudicate` 3 ·
`coverage` 2 · `conflict` 2 · `synthesize` 3. **Twelve of twelve reported
stages have a body.** `own_research` is the thirteenth declared stage and is
covered below.

## THE PROOF THE CAPSTONE GATE BITES

The plan's most important criterion: a capstone test nobody has seen fail is a
capstone test nobody has verified. Both coverage emitters that fire on a clean
run were temporarily neutered with an early `return`, the capstone was run, and
the file was restored with `git checkout -- <that one path>` (verified: the
temporary marker greps to 0 and `git diff --stat HEAD` on that file is empty).

**Observed failure output, verbatim:**

```
E   AssertionError: SC1 VIOLATED — these declared stages emitted no body row (a row whose kind is
neither divider nor summary): ['coverage']. Each of them renders as a phase heading with nothing
under it. Rows actually recorded per stage: {'intake': ['divider', 'thinking', 'tool', 'summary',
'summary'], ..., 'coverage': ['divider', 'summary'], ...}
E   assert not ['coverage']
```

The failure names the silent stage, and the per-stage kind dump shows `coverage`
reduced to exactly `['divider', 'summary']` — a heading with nothing under it,
which is the defect in the operator's own words. Restored, the file is green at
67 passing.

## 21-CONTEXT's summary-meta hypothesis: **REFUTED**

The hypothesis (`<specifics>`): *"the silent stages' summary lines are probably
rendering nearly empty because `state["items"]` is 0 for a stage that never
reported detail rows — worth confirming, because if so, D-04's per-item rows fix
the summary line for free."*

**Its first half is right and its conclusion is wrong.** `coverage` IS the only
stage of the thirteen whose automatic summary reports `actions: 0`. But measured
before AND after this plan, that meta is `{'worked': '0s', 'actions': 0}`
**both times** — unchanged by the two body rows the stage now emits.

The mechanism, read out of `pipeline.py` rather than inferred:
`_stage_event_summary_meta` builds the summary from `state["items"]`;
`state["items"]` is written only by `_stage_log_items(detail)`, i.e. from the
**`detail` argument of `set_stage`**; and `meta["items"]` comes from
`detail["summary"]["items_read"]`. **Run events never touch that state.** The
feed body and the summary line are driven by different inputs, so per-item rows
cannot fix the summary "for free" or otherwise.

`test_the_coverage_stage_summary_is_no_longer_empty` therefore asserts the ACTUAL
behaviour, with a counterfactual asserting the body rows really are there — so
`actions == 0` cannot be read as "21-06 emitted nothing". The one-line fix (give
that `set_stage` a `detail`) is identified and deliberately not applied; it is
logged as **DEF-21-03**, and the test fails with an instruction if anyone lands
it, so the fix and the deferred item must close together.

## Deviations from Plan

### 1. [Reconciled against purpose] The capstone could not require a body for ALL thirteen declared stages

- **Found during:** Task 3, by measuring the stubbed run before writing the test.
- **The criterion as written:** *"for EVERY key in `[s["key"] for s in
  stages_for("tribunal")]` assert there is at least one recorded event on that
  stage whose `kind` is neither `divider` nor `summary`."*
- **Why it is unsatisfiable:** `own_research` is declared in the schema but the
  pipeline **never writes the key at all** — 0 events, and it does not appear in
  `_stage_sequence`. This is an older, separate, deliberately-pinned gap with its
  own self-retiring test at `test_engine_e2e_stubbed.py`
  (`test_..._own_research...` asserts `"own_research" not in stages`). A stage
  that is never reported has no block on the page to be empty, so no emitter in
  `stage_events.py` could satisfy the criterion for it. The plan's own vacuity
  guard says "at least **twelve** distinct stages", which suggests the planner
  half-knew.
- **What I implemented instead, against the criterion's evident PURPOSE** ("the
  set is the schema's and a stage added later must fail this test until it
  emits"): the list is still derived from `stages_for("tribunal")` and never
  retyped; the declared-but-unreported set is **asserted to equal exactly
  `{"own_research"}`**; and every other declared stage must have a body.
- **Why this is stronger than a hardcoded skip:** the moment somebody wires
  `own_research`, the exclusion assertion fails and drags that stage under the
  body requirement. A skip-by-name would have silently tolerated it forever, and
  would also have silently absorbed any OTHER stage that stopped being reported.
- **This is the fourth consecutive plan in this phase to hit a criterion that
  did not survive contact with the code** (21-01, 21-02, 21-05, now 21-06).

### 2. [Signature superset] Two helpers take more than the plan's stated signature

Both are supersets, not substitutions; all thirteen exported NAMES are exactly as
the plan declares.

- **`emit_adjudicate_dispatch(run_id, *, claims, rule)`** — the plan's signature
  is `(run_id, *, claims)` but its own action text asks the row to name *"under
  which survival rule"*. `SURVIVAL_RULE` is read from an env var at import, so
  two runs of one intake can adjudicate the same verdicts differently with
  nothing on the page saying so. I followed the action text and added `rule`.
- **`emit_coverage_dispatch(run_id, *, claims, adjudications)`** — the plan says
  `(run_id, *, selected)`. Computing `selected` at the call site would have been
  a **walk over model-shaped claim dicts outside the emitter's try**, which is
  precisely the defect rule 3 exists to prevent; and the cheap alternative
  (`len(claims)`) names the WRONG population — every distilled claim rather than
  the gate-selected ones. Since the row's entire purpose is to render the cost
  trap's intersection, a row naming the wrong population would be a confident
  false statement about the guard standing between that stage and ~2,100 paid
  sessions. The walk moved inside the thunk. **This is now recipe step (h).**

### 3. [Rule 3 - blocking issue] `conflict_losers` and `loser_idxs` bound at the outer level

`emit_conflict_done` reads `len(conflict_losers)`, but both names were bound only
inside `if loser_idxs:` — itself inside `if len(survivors) >= 2:`. On a run with
fewer than two survivors the closing row would have raised `NameError` **at the
call site**, the one place outside the emitter's try and therefore the one place
D-06 cannot protect (T-21-06-03). Both are now initialised beside `conflicts` at
the outer level; the inner `loser_idxs: set[int] = set()` became a plain
reassignment. This is one of only two non-additive lines in the whole diff.

### 4. Recipe step (h) added to the `HOW TO ADD THE NEXT STAGE` docstring

Requested by the orchestrator's brief. (h) is the population-honesty rule from
deviation 2, written where it will be read. The docstring's status paragraph was
also updated: all eight are done, SC1 is met, and the `own_research` exclusion is
explained in place so the next reader does not mistake it for an oversight.

### Nothing else

No architectural change, no new event kind, no new meta key, no new test file, no
package install, no `requirements.txt` edit, no CI config edit, no frontend
change. `DEF-21-01` was not re-opened.

### Stale-base trap — caught, **26th consecutive occurrence**

The worktree forked from **`a3a0c96`** — the same commit every previous time,
including all four wave-1 worktrees, 21-05's, and now this one. `git merge-base`
caught it; `git rev-list --count` would have read green throughout. The four
positive-presence sentinels then confirmed the corrected tree before a single
edit was spent, and the `_sentence_or_none` grep specifically proved **wave 2**
had landed rather than merely wave 1 — without it I would have rebuilt 21-05's
work and conflicted with it at merge.

## Verification results

**Task 1 — the kind/meta/thunk/key one-liner:** prints
`ok ['agent_done', 'agent_fail', 'agent_run', 'dispatch', 'plan', 'thinking']`,
exit 0. Every `kind=` literal is in `RUN_EVENT_KINDS`, none is `divider` or
`summary`, the thunk-taking call count equals the thunk count, and all four stage
constants are declared `ENGINE_STAGES["tribunal"]` keys.

Every other Task-1 criterion was proved **by execution against a recorder**, not
by grep:

- all thirteen helpers importable (`hasattr` over the named list);
- every recorded meta key — `{'actions', 'attempt', 'items', 'max', 'sub'}` — is
  in `run_events._META_FIELDS`, and every recorded kind is in `RUN_EVENT_KINDS`;
- **contested vs resolved**: the two texts differ and neither is a substring of
  the other;
- **`emit_coverage_blocked` carries its reason verbatim**: a distinctive
  breaker sentence came back byte-identical;
- **the coverage header counts the SELECTED population**: driven with 3 claims of
  which 2 are `strict == "VERIFY"`, the row reads "2 selected" and `meta.items` is
  2 — not 3;
- four blank-sentence attempts emitted **zero** rows;
- three degraded shapes (a `.get` that raises) cost their rows and raised nothing.

**Task 2 — the six-file regression surface:** `189 passed, 8 skipped`, 0 failures
(`test_engine_e2e_stubbed`, `test_run_event_emit`, `test_coverage_reentry`,
`test_verification_buckets`, `test_report_sections`, `test_checkpoint_resume`).
`test_coverage_reentry` is the behavioural surface for the coverage loop and the
cost trap; `test_report_sections` drives `_write_final_report` directly and pins
that its call shape still works unchanged.

**THE COST TRAP IS PROVABLY UNTOUCHED.**
`grep -n "check_coverage(claims, adjudications, selected_only=True)"` still
matches (twice, as at base), and `git diff -U0` contains **no hunk mentioning
`check_coverage` at all** — the grep over the diff returns nothing.

**`git diff -U0` hunk headers** (untouched-region proof): every hunk is at base
line 1437 or later. **No hunk intersects 530-570** (`_stage_event_boundary`) or
**1610-1690** (the load-bearing shadowed `set_stage` shim). The whole diff has
exactly **two** non-additive lines:

```
-                "name": f"{len(survivors)} survived · {len(dropped)} dropped of {len(claims)} claims",
-            loser_idxs: set[int] = set()
```

the sanctioned inline-to-local rebinding, and the outer-level rebinding of
deviation 3. Everything else is pure insertion.

**`_write_final_report`'s new parameter** is keyword-only WITH a default
(`resumed: bool = False`), so all three existing call sites — the zero-touch
path, the resume entry point, and `test_report_sections.py`'s direct driver —
keep their call shape; only the resume site passes it (T-21-06-04).

**Task 3 — the registered engine gate, list extracted FROM the config** (never
retyped; the extractor asserts `len(paths) == EXPECTED_FILES == 44`, no
duplicates, and that every named file exists before running):

```
1909 passed, 13 skipped, 6 errors in 80.70s
```

The **6 errors are pre-existing and not caused by this plan** — 4 in
`test_dispatch_pii.py` and 2 in `test_fact_list_parser.py`, all
`ValueError: the environment variable is longer than 32767 characters` from
pytest's own `PYTEST_CURRENT_TEST` teardown on very long parametrised ids.
Windows-only, present at every commit including the base; 21-03 and 21-05 each
recorded the identical six. Neither file is in this plan's three-file diff.
**Zero failures**, which is the pass condition, and `grep -c "^FAILED"` is 0.

## The eleven new tests

| Test | Proves |
|---|---|
| `test_the_last_four_stages_are_no_longer_labels_with_nothing_under_them[adjudicate\|coverage\|conflict\|synthesize]` | ≥ 2 body rows and **exactly one** dispatch header per stage (4 parameterisations) |
| `test_every_declared_tribunal_stage_emits_a_body` | **THE CAPSTONE** — schema-derived, exclusion pinned as a set, failure names the silent stage. Observed failing on `['coverage']` |
| `test_coverage_is_no_longer_the_emptiest_stage` | ≥ 2 body rows, exactly one header, and that the header names the SELECTED population |
| `test_the_coverage_stage_summary_is_no_longer_empty` | the summary-meta hypothesis **refuted**, with a counterfactual so `actions == 0` cannot read as "nothing was emitted" |
| `test_a_coverage_reentry_and_a_blocked_reentry_each_say_so` | a `plan` row that says it is **paid for**, and an `agent_fail` row carrying the breaker's reason **verbatim** |
| `test_a_resumed_run_still_reports_final_synthesis` | the resume path's only synthesize row, **plus the non-resumed counterfactual** so a helper ignoring the flag would fail |
| `test_conflict_rows_distinguish_contested_from_resolved` | end to end via a one-hook subclass: one of each, distinct, neither a substring of the other |
| `test_no_emit_in_the_last_four_stages_can_fail_the_run` | all thirteen against degraded input; **two negative controls**; good rows survive; no blank row; no false elision |

Every test carries a vacuity guard asserting the stage appears in
`_stage_sequence(...)` **before** any filter runs. Rows are read at
`run_events._writer` — the deepest seam that is still not Postgres — so `emit`,
`emit_safe` and the real thunk all stay in the path under test. No Postgres, no
provider key, no network, no mocking library. **Zero skips.**

One new one-hook subclass, `_ConflictingDetectorAudited`, parses the claim
indices **out of the prompt production actually sent** — `conflict_detector`
discards entries whose indices are out of range, so a hand-typed pair would have
silently produced a run with no conflicts and a vacuously green test.

## Extended public surface of `stage_events.py`

| Function | Kind | Budgeted |
|---|---|---|
| `emit_adjudicate_dispatch(run_id, *, claims, rule)` | `dispatch` | no |
| `emit_adjudicate_drop(run_id, budget, *, claim)` | `thinking` | yes |
| `emit_adjudicate_done(run_id, *, text, survivors)` | `thinking` | no |
| `emit_coverage_dispatch(run_id, *, claims, adjudications)` | `dispatch` | no |
| `emit_coverage_reentry(run_id, *, attempt, max_attempts, uncovered)` | `plan` | no |
| `emit_coverage_blocked(run_id, *, reason)` | `agent_fail` | no |
| `emit_coverage_done(run_id, *, passed, uncovered, reentries)` | `thinking` | no |
| `emit_conflict_dispatch(run_id, *, survivors, reconciliations)` | `dispatch` | no |
| `emit_conflict_finding(run_id, budget, *, conflict)` | `thinking` | yes |
| `emit_conflict_done(run_id, *, losers, contested, survivors)` | `thinking` | no |
| `emit_synthesize_dispatch(run_id, *, survivors)` | `dispatch` | no |
| `emit_synthesize_scrubbed(run_id, *, removed, reports)` | `thinking` | no |
| `emit_synthesize_writing(run_id, *, ledger, numbered, resumed)` | `thinking` | no |

Composers marked `CALLED ONLY FROM INSIDE A build() THUNK`:
`_adjudicate_drop_event`, `_coverage_selected`, `_coverage_dispatch_event`,
`_conflict_finding_event`. Constants: `_STAGE_ADJUDICATE`, `_STAGE_COVERAGE`,
`_STAGE_CONFLICT`, `_STAGE_SYNTHESIZE`, `_REASON_FACTCHECK`, `_REASON_CONFLICT`,
`_STRICT_VERIFY`.

## Known Stubs

None. Every row this plan emits is wired to real pipeline data.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no
schema change. Every threat in the register was mitigated by construction:

- **T-21-06-01** (THE COVERAGE COST TRAP): the `check_coverage` line is
  byte-identical and appears in **no diff hunk**; `selected_only=True` is still
  passed explicitly; `test_coverage_reentry.py` is green.
- **T-21-06-02** (one row per dropped claim / per conflict): both bounded by
  their own `RowBudget` at `MAX_ROWS_PER_STAGE`, each created once and flushed
  once, with the elision stated as a visible row.
- **T-21-06-03** (a malformed conflict dict, or `conflict_losers` read outside
  its branch): every model-shaped read is inside a thunk, and both names are now
  bound at the outer level (deviation 3). Proved by
  `test_no_emit_in_the_last_four_stages_can_fail_the_run` with two negative
  controls.
- **T-21-06-04** (a signature change to `_write_final_report`): keyword-only WITH
  a default; every existing caller unchanged; `test_report_sections.py` and
  `test_checkpoint_resume.py` both green.
- **T-21-06-05** (conflict tension and claim text in feed rows): every site goes
  through the thunk-taking entry point, so `scrub_pii`-then-clamp inside the
  emitter is unavoidable. No path around it was added.
- **T-21-06-SC** (package installs): none. `stage_events.py` still imports only
  `os`, `typing` and two existing first-party modules.

## Commits

| Hash | Message |
|---|---|
| `4c4f0e5` | `feat(21-06)`: add the adjudicate, coverage, conflict and synthesize feed helpers |
| `60a25ea` | `feat(21-06)`: give the last four stages a body — wire their emit sites |
| `ded2391` | `test(21-06)`: prove SC1 from the schema — no reported stage is silent |

## For the next executor

- **21-07 changes stage LABELS, not bodies.** The capstone will hold it to SC1
  automatically: if a label change ever renames a key, the
  declared-but-unreported set assertion fires first and says so.
- **`own_research` is the one declared stage with no rows**, and it is not this
  phase's gap — the pipeline never writes the key. Wiring it is the self-retiring
  test's job in `test_engine_e2e_stubbed.py`; the capstone's pinned exclusion set
  will force it under the body requirement the day it lands.
- **DEF-21-03 is new**: the coverage summary line is still nearly empty and the
  per-item rows do not fix it. One-line fix identified, deliberately not applied.
- **Deploy surface:** this plan changes `tribunal/` only → `tribunal-worker`.
  Re-derive the surface from the actual diff at deploy time (D-02); the
  2026-08-06 deploy caught a third service after a standing note said two.
- **Nothing here has run.** Like 21-03, 21-05 and the three changes at tag
  `20260806-175613`, this code is proven against the stubbed harness and has
  never executed against a live model. The ~$45 run remains the thing that
  validates it — and it is now the run that would validate the whole feed.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py` — FOUND (modified)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — FOUND (modified)
- `tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py` — FOUND (modified)
- commits `4c4f0e5`, `60a25ea`, `ded2391` — all present in
  `git log ee3c169..HEAD`
- `git diff --name-only ee3c169..HEAD` — exactly the three source files.
  `cloudbuild.test-engine.yaml` is NOT among them and `EXPECTED_FILES` is 44.
- the temporary gate-bite edit is fully reverted: the marker greps to 0 and
  `git diff --stat HEAD` on `stage_events.py` is empty
- STATE.md and ROADMAP.md — **NOT modified** (the orchestrator owns those writes)
