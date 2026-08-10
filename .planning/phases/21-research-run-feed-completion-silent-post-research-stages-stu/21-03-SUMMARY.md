---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 03
subsystem: tribunal-engine-observability
tags: [run-events, feed, verify, stage-events, observability]
requires:
  - "tribunal/nestor_pulse_sdk/runs/run_events.py::emit_safe (15.3-01)"
  - "tribunal/nestor_pulse_sdk/runs/stage_feed.py::truncate_task_prompt"
  - "tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py (the stubbed harness)"
provides:
  - "tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py — the SHARED SPINE for all eight silent stages"
  - "MAX_ROWS_PER_STAGE / RowBudget — the per-stage row bound and the visible elision row (D-05)"
  - "the verify stage's feed body: dispatch header, per-cluster lifecycle rows, per-verdict rows, closing degradation line"
affects:
  - "21-05 and 21-06 EXTEND stage_events.py for the remaining seven stages — see THE PATTERN below"
  - "frontend RunFeed.tsx now receives a non-empty body for verify, which is what 21-02's collapse-toggle gate needs"
tech-stack:
  added: []
  patterns:
    - "one module-level _STAGE_<NAME> constant + one emit_<stage>_* function per feed ROW"
    - "any walk over model-shaped data lives in a separate composer marked CALLED ONLY FROM INSIDE A build() THUNK"
    - "per-item emits take a RowBudget second-positional and guard on budget.take()"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
    - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
decisions:
  - "D-03 honoured: zero new event kinds — dispatch / agent_run / agent_done / agent_fail / thinking only"
  - "D-05: MAX_ROWS_PER_STAGE = 25, NESTOR_TRIBUNAL_FEED_ROWS_PER_STAGE override, elision stated as a visible row"
  - "D-06 honoured: no hand-emitted divider or summary; every text built inside a build= thunk"
  - "ONE RowBudget spans BOTH verification branches — the bound is a property of the stage, not of the branch"
  - "_verify_closing_item bound ONCE and shared by the feed row and the stage detail"
metrics:
  duration: ~75 min
  completed: 2026-08-10
---

# Phase 21 Plan 03: The Verify Stage Gets a Body — Summary

`verify` — the stage the operator named twice and the one carrying most of a run's
spend — emitted **zero** run events and rendered as a heading with nothing under it.
It now emits a dispatch header, a start and finish row per claim cluster, a row per
refutation and supersession, a named failure row for every cluster that was not
checked, and G-10's closing degradation sentence. The shared spine those rows sit on
(`stage_events.py`, the row budget, the visible elision row) is what plans 21-05 and
21-06 extend for the remaining seven silent stages.

## THE PATTERN — read this before writing 21-05 or 21-06

The recipe is written into `stage_events.py`'s module docstring under
**"HOW TO ADD THE NEXT STAGE"**, so it travels with the code rather than only with
this file. In short:

| Step | What |
|---|---|
| a | Add `_STAGE_<NAME>` holding the key **exactly** as `ENGINE_STAGES["tribunal"]` declares it. Never invent one — an undeclared key renders as raw snake_case at the operator (the WR-03 defect class). |
| b | One `emit_<stage>_*` function per feed ROW, under a banner comment naming the stage. `run_id` positional first, everything else keyword-only, returns `None`. |
| c | Any row whose text needs a **walk** over model-shaped data gets a separate `_<stage>_<row>_event(...)` composer whose docstring carries the marker `CALLED ONLY FROM INSIDE A build() THUNK`. |
| d | Per-item rows take a `RowBudget` as their **second positional** argument and guard on `budget.take()`. One budget per stage per run, created at the stage's opening, `flush(noun)`-ed at its close so the elision row lands before the next divider. |
| e | Only `run_events._META_FIELDS` keys may be set. Prove the subset with a **recorder**, not a grep. |

**Three traps the next executor will hit if nobody says so:**

1. **Do not write the emitter's function name or the literal `build=lambda` in prose.**
   The plan's acceptance one-liner asserts `src.count('emit_safe') == src.count('build=lambda')`,
   so a single mention in a docstring breaks a gate that is otherwise correct. This
   module refers to it as *"the thunk-taking entry point of `runs/run_events.py` (the
   public one whose name ends in `_safe`)"* and to *"the `build=` thunk"* — `build=`
   alone does not match. `workshop.py` already uses the same evasion for the same reason.
2. **`MAX_ROWS_PER_STAGE` is resolved at IMPORT.** `monkeypatch.setenv` after import
   silently does nothing. Tests must set the module attribute or pass `limit=` explicitly.
3. **The dispatch header is emitted BEFORE the stage's first `set_stage`, and that is
   correct.** `RunFeed.tsx` builds each block with `events.find(e => e.kind === "divider")`
   and renders the divider at the top regardless of its position in the group, so
   emission order of dispatch vs divider does not affect the render. Verified by reading
   `RunFeed.tsx:208-217`; do not "fix" it.

## Public surface of `stage_events.py`

**The spine — shared, do not fork:**

| Name | Kind | Purpose |
|---|---|---|
| `MAX_ROWS_PER_STAGE` | `int` = 25 | per-stage per-item row bound; `NESTOR_TRIBUNAL_FEED_ROWS_PER_STAGE` override |
| `CLAIM_CHARS` / `LABEL_CHARS` | `int` = 110 / 60 | clip widths for claim text and for an entity/attribute label |
| `clip_claim(text)` / `clip_label(text)` | `-> str` | never-raising one-line clips over `truncate_task_prompt` |
| `RowBudget(run_id, stage, limit=None)` | class | `.take() -> bool`, `.flush(noun) -> None`, `.used`, `.elided` |

`RowBudget.take()` returns `True` exactly `limit` times, then counts refusals in
`elided`. `flush(noun)` emits ONE `thinking` row reading
`"{N} more {noun}(s) not shown — the feed shows the first {limit}"` and zeroes the
counter, so a second call is a no-op and a stage inside its budget announces nothing.

**The verify helpers:**

| Function | Kind | Budgeted |
|---|---|---|
| `emit_verify_dispatch(run_id, *, groups_selected, groups_total, multi, claims_selected, claims_total)` | `dispatch` | no (one per stage) |
| `emit_verify_batch_dispatch(run_id, *, selected, total)` | `dispatch` | no (per-claim branch; mutually exclusive) |
| `emit_verify_group_run(run_id, budget, *, group)` | `agent_run` | yes |
| `emit_verify_group_done(run_id, budget, *, group, verdicts)` | `agent_done` | yes |
| `emit_verify_group_failed(run_id, budget, *, group, reason)` | `agent_fail` | yes |
| `emit_verify_batch_done(run_id, budget, *, verified, selected)` | `agent_done` | yes |
| `emit_verify_verdicts(run_id, budget, *, group, verdicts)` | `thinking` × N | yes, per row |
| `emit_verify_closing(run_id, *, text)` | `thinking` | no (one per stage) |

Internal composers, all marked `CALLED ONLY FROM INSIDE A build() THUNK`:
`_verify_group_run_event`, `_verify_group_done_event`, `_verify_group_failed_event`,
`_verdict_tally`, `_noteworthy_verdicts`, `_verify_verdict_event`.

`emit_verify_verdicts` emits a row only for a `refute` or `superseded` verdict —
`support` is the expected outcome and is already carried by the tally on the
cluster's finish line. A `superseded` row appends its `superseded_note` when present.

**Deliberately NOT set: `is_live`.** It is written at exactly one production site as
a literal `True`, so it is a constant rather than a liveness signal, and the run page
derives liveness from position and run state (plan 21-01).

## The numbers the plan asked for

| Measurement | Base (`eac6f2b`) | After |
|---|---|---|
| `test_run_event_emit.py` passing tests | **33** | **43** (+10; the plan required ≥ 6) |
| `grep -c "await set_stage(" pipeline.py` | **23** | **23** — unchanged |
| `grep -c "run_events.open_run" pipeline.py` | **1** | **1** — no second call |
| `grep -c "_verify_closing_item(" pipeline.py` | 2 | **2** — its `def` and its ONE call site |
| `grep -c "stage_events\.emit_verify" pipeline.py` | 0 | **9** (plan required ≥ 7) |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | 44 | **44** — file NOT edited |
| verify body rows in the stubbed run | **0** | **16** (1 dispatch, 6 `agent_run`, 6 `agent_done`, 3 `thinking`) |

The unchanged `await set_stage(` count is the strongest single proof that this plan
added observability and did not touch behaviour.

**`git diff -U0` hunk headers** (untouched-region proof): every hunk is a pure
insertion except one — `@@ -3538 +3616 @@`, the single `_verify_closing_item(...)` →
`_verify_closing` rebinding step (e) allows. No hunk intersects **1610-1690** (the
load-bearing shadowed `set_stage` shim) or **530-570** (`_stage_event_boundary`).

## Verification results

**Task 1 — the spine one-liner:** prints `spine ok ['agent_done', 'agent_fail',
'agent_run', 'dispatch', 'thinking']`, exit 0. It executes four assertions a comment
cannot satisfy: every `kind=` literal is in `RUN_EVENT_KINDS`; none is `divider` or
`summary`; the thunk-taking call count equals the `build=lambda` count (no text
composed above a thunk); `RowBudget.take()` returns `True` exactly `limit` times while
`elided` counts the refusals.

- `grep -nE "run_events\.emit\(" stage_events.py` → exit 1 (bare emit never called).
- `grep -c "CALLED ONLY FROM INSIDE" stage_events.py` → **7**.
- Env override: `NESTOR_TRIBUNAL_FEED_ROWS_PER_STAGE=3` → `MAX_ROWS_PER_STAGE == 3`;
  unset → `25`.
- **Meta-key subset proved by execution, not by grep:** every helper driven against a
  recorder installed over `run_events.emit` recorded `{'items', 'sub'}` ⊂
  `_META_FIELDS`; the same drive through the REAL emitter (`open_run` → `_writer` →
  `close_run`) logged no `unknown meta key` and no refused kind, and the keys survived
  the whitelist intact.

**Task 2 — the five-file regression surface:** `127 passed`, 0 failures
(`test_engine_e2e_stubbed`, `test_stage_logging`, `test_run_event_emit`,
`test_verification_buckets`, `test_coverage_reentry`).

**Task 3 — the registered engine gate, run locally with its list extracted FROM the
config** (never retyped; the extractor asserts `len(paths) == EXPECTED_FILES == 44`,
that there are no duplicates, and that every named file exists before running):

```
1885 passed, 13 skipped, 6 errors in 151.78s
```

The **6 errors are pre-existing and are not caused by this plan** — 4 in
`test_dispatch_pii.py::test_never_raises` and 2 in
`test_fact_list_parser.py::test_parser_never_raises`, all `ValueError: the
environment variable is longer than 32767 characters` raised by pytest's own
`_update_current_test_var` teardown on very long parametrised ids. Confirmed by
running those two files ALONE (`159 passed, 6 errors`); neither file, nor any module
they exercise, appears in this plan's three-file diff. The plan's `<verification>`
step 4 anticipates exactly these six.

**The 44 gate paths, as extracted from `tribunal/cloudbuild.test-engine.yaml`:**

```
test_reliability_retry        test_reliability_breaker      test_terminal_states
test_feed_enrichment          test_fact_list_parser         test_citation_anchors
test_report_sections          test_status_gates             test_coverage_reentry
test_workshop_critique        test_workshop_scope_guard     test_workshop_tournament
test_workshop_languages       test_own_researcher           test_cost_serpapi
test_factlist_fallback        test_checkpoint_resume        test_provider_resume
test_engine_e2e_stubbed       test_research_division_assignment
test_distiller_coverage       test_hash_chain_replay        test_stale_reclaim
test_brief_input              test_web_fetch_replay         test_dispatch_pii
test_stage_logging            test_run_events               test_run_events_api
test_run_event_emit           test_source_resolution        test_distiller_separators
test_claim_attribution        test_question_grouping        test_discovery_bracket
test_workshop_loop            test_pipeline_dispatch_clause test_yield_schema
test_yield_records            test_pipeline_assignment_yield
test_research_division_yield  test_workshop_round_yield     test_synthesis_opus5
test_suite_hygiene
```
(all under `nestor_pulse_sdk/tests/`, `.py`)

## The ten new tests

Each carries the guard the plan asked for. Vacuity guards assert `"verify" in
_stage_sequence(statements)` **before** any filter runs, so a harness that stopped
early fails loudly rather than passing on an empty filter.

| Test | Proves |
|---|---|
| `test_verify_stage_is_no_longer_a_label_with_nothing_under_it` | ≥ 2 body rows, using `RunFeed.tsx`'s own `body` filter |
| `test_verify_emits_exactly_one_dispatch_header` | `== 1`, never `>= 1` |
| `test_a_verify_cluster_row_pairs_with_a_finish_row` | the engine half of `feedRows.ts::settledSeqs`' positional pairing |
| `test_a_failed_verify_cluster_says_why` | a crashed cluster names its cause; **negative control**: the bare word `"failed"` fails the SAME named predicate |
| `test_the_verify_row_budget_states_its_elision_as_a_row` | exactly one elision row carrying the REAL refused count (7), idempotent flush |
| `test_a_verify_stage_inside_its_budget_emits_no_elision_row` | the counterfactual — a healthy stage announces nothing |
| `test_no_verify_emit_can_fail_the_run` | degraded group + non-mapping verdicts raise nothing AND still record their rows; **negative control**: the obvious construction genuinely raises |
| `test_the_verify_closing_line_is_emitted_when_there_is_a_sentence` | the counterfactual for the blank-row fix below |
| `test_the_verify_closing_row_carries_the_same_sentence_as_the_stage_detail` | the feed row and `stage_detail` are the same sentence (bound once) |
| `test_a_raising_verify_composer_costs_the_row_and_not_the_run` | the STRUCTURAL D-06 proof at this site, and "the run completes" end to end |

Rows are read at `run_events._writer` — the deepest seam that is still not Postgres —
so `emit`, `emit_safe` and the real `build()` thunk all stay in the path under test.
No Postgres, no provider key, no network, no mocking library.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `emit_verify_closing` emitted a BLANK feed row for an empty sentence**
- **Found during:** Task 3, by test (f) driving `emit_verify_closing(run_id, text=None)`
- **Issue:** `run_events.emit` accepts an empty `text` and queues it, so a funnel that
  produced no closing sentence put a blank line in the feed. `RUN_EVENT_KINDS`' own
  comment calls a blank line "worse than an absent one", and a blank row is squarely
  the "rubbish information" half of the operator's UAT complaint. My own module
  docstring states the rule; the helper broke it.
- **Fix:** `None` or all-whitespace now emits nothing. The check is a string test on a
  value the caller already holds — the same class of work as `RowBudget.take()`, so it
  cannot raise and does not move work out of the emitter's try.
- **Files modified:** `tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py`
- **Commit:** `449dad5`
- **Note:** this makes Task 3's diff **two** paths rather than the one its acceptance
  criterion names. The criterion's purpose is fully met: `cloudbuild.test-engine.yaml`
  is NOT in the diff and `EXPECTED_FILES` is still 44. The fix was committed
  separately from the tests so each remains atomic.

### Documentation deviations

**2. The module docstring states rule 3 WITHOUT writing the emitter's function name.**
The plan's Task-1 action asks the docstring to say "every function below calls
`run_events.emit_safe`". Writing that literally would break the plan's OWN acceptance
one-liner, which compares the file-wide counts of `emit_safe` and `build=lambda`. The
substance is stated in full, using the same evasion `workshop.py` already uses ("the
thunk-taking entry point"). Flagged loudly under THE PATTERN above so 21-05/21-06 do
not walk into it.

**3. Two helpers beyond the `must_haves` export list.** `emit_verify_batch_done` (the
plan's own action text asks for it, the frontmatter export list omits it) plus the
spine's `clip_claim` / `clip_label` / `CLAIM_CHARS` / `LABEL_CHARS`. A superset, not a
substitution.

### Stale-base trap — caught, 24th consecutive occurrence

The worktree forked from **`a3a0c96`**, not from the wave base `eac6f2b` — the same
commit this trap has produced every previous time. `git merge-base` caught it; the
positive-presence sentinel (`21-03-PLAN.md` and `21-CONTEXT.md` must exist after the
reset) confirmed the corrected tree before a single edit was spent.

## Known Stubs

None. Every row this plan emits is wired to real pipeline data; nothing is a
placeholder awaiting a later plan.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema
change. Every threat in the plan's register was mitigated by construction:

- **T-21-03-01** (DoS in the paid loop): every per-item emit is guarded by
  `RowBudget.take()`, bounded at 25.
- **T-21-03-02** (malformed model data): every read happens inside a `build=` thunk —
  proved by test (f) with a negative control.
- **T-21-03-03** (claim text disclosure): every site goes through the thunk-taking
  entry point, so `scrub_pii`-then-clamp inside the emitter is unavoidable. No path
  around it was added.
- **T-21-03-04** (tenant binding): `run_events.open_run` count is still exactly 1.
- **T-21-03-05** (silent row loss): the elision is a visible row, asserted by test (e).
- **T-21-03-SC** (package installs): none. `stage_events.py` imports only `os`,
  `typing` and two existing first-party modules; no `requirements.txt` edit.

## Commits

| Hash | Message |
|---|---|
| `cb28630` | `feat(21-03)`: add `stage_events.py` — the shared feed-emitter spine plus the verify helpers |
| `21ff030` | `feat(21-03)`: give the verify stage a body — wire its emit sites into `pipeline.py` |
| `449dad5` | `fix(21-03)`: `emit_verify_closing` must not emit a blank feed row |
| `f060bb5` | `test(21-03)`: prove the verify stage has a body, end to end |

## For the next executor

- **21-05 / 21-06:** extend `stage_events.py` and extend the **PHASE 21 section of
  `test_run_event_emit.py`** — do not create a new test file. That path is already in
  the gate's `WANTED` list and `EXPECTED_FILES` stays 44. The `_Persisted` recorder,
  `_install_writer` and `_names_a_cause` in that section are reusable as-is.
- **Deploy surface:** this plan changes `tribunal/` only → `tribunal-worker`. Re-derive
  the surface from the actual diff at deploy time (D-02); the 2026-08-06 deploy caught
  a third service after a standing note said two.
- **Nothing here has run.** Like the three changes at tag `20260806-175613`, this code
  is proven against the stubbed harness and has never executed against a live model.
  The ~$45 run remains the thing that validates it.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py` — FOUND
- `.planning/phases/21-.../21-03-SUMMARY.md` — FOUND, and verified present in commit
  `b04cdf4` via `git show --name-only` (it needed `git add -f`; `.planning/` is
  gitignored at line 32 and a plain `git add` would have skipped it silently)
- commits `cb28630`, `21ff030`, `449dad5`, `f060bb5`, `b04cdf4` — all present in
  `git log eac6f2b..HEAD`
- `git status --porcelain` — empty; nothing left uncommitted in the worktree
- STATE.md and ROADMAP.md — NOT modified (the orchestrator owns those writes)
