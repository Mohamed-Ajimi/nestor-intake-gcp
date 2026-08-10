---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 05
subsystem: tribunal-engine-observability
tags: [run-events, feed, distill, merge, gate, stage-events, observability]
requires:
  - "tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py (21-03 — the shared spine)"
  - "tribunal/nestor_pulse_sdk/runs/run_events.py::emit_safe (15.3-01)"
  - "tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py (the stubbed harness)"
provides:
  - "the distill / merge / gate feed bodies: dispatch header, bounded per-item rows, closing sentence"
  - "_sentence_or_none — the blank-row rule, in ONE place, for every closing line"
  - "recipe steps (f) and (g) in HOW TO ADD THE NEXT STAGE, for plan 21-06"
affects:
  - "21-06 EXTENDS stage_events.py for adjudicate / coverage / conflict / synthesize — the recipe is unchanged plus steps (f) and (g)"
  - "frontend RunFeed.tsx now receives a non-empty body for six of the eight silent stages"
tech-stack:
  added: []
  patterns:
    - "a data-dependent `kind` is chosen by a never-raising _<stage>_<row>_kind helper, OUTSIDE the thunk"
    - "a row's SELECTIVITY test (does this item earn a row at all) is never-raising and lives in the helper, not at the call site"
    - "a closing sentence is bound to ONE local and handed to both the feed row and stage_detail"
key-files:
  created: []
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/stage_events.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
    - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
decisions:
  - "D-03 honoured: zero new event kinds — dispatch / agent_done / agent_retry / plan / thinking only"
  - "D-04: each of the three emits a header, per-item rows and a closing sentence"
  - "D-05: one RowBudget per stage, created at its opening, flushed at its close"
  - "D-06 honoured: no hand-emitted divider or summary; every text built inside a thunk"
  - "D-14: a fallen-back stream is agent_retry, never agent_fail — it degrades one stream, not the run"
  - "the merge singleton rule and the gate KEEP rule live in the HELPERS, so pipeline.py holds no second copy"
metrics:
  duration: ~95 min
  completed: 2026-08-10
---

# Phase 21 Plan 05: distill, merge and gate Get Bodies — Summary

Three more of the eight silent stages now emit content. `distill` names every
research stream and what reading it yielded — and says, in 15.2-04's own words,
why a stream that stated no fact list fell back to the distiller. `merge` names
each cluster holding more than one stream's version of the same fact, which is
the reconciliation D11's reordering exists to make possible. `gate` itemises
every claim it refused to check, in the gates' own refusal vocabulary. With
`verify` from 21-03, six of the eight now have bodies; `adjudicate`, `coverage`,
`conflict` and `synthesize` remain for 21-06.

## The numbers the plan asked for

| Measurement | Base (`875b396`) | After |
|---|---|---|
| `test_run_event_emit.py` passing tests | **43** | **56** (+13; the plan required ≥ 8) |
| full 44-file engine gate | 1885 passed, 13 skipped, 6 errors | **1898 passed, 13 skipped, 6 errors, 0 failures** |
| `grep -c "await set_stage(" pipeline.py` | **23** | **23** — unchanged |
| `grep -c "run_events.open_run" pipeline.py` | **1** | **1** — no second call |
| `grep -c "stage_events\.emit_distill"` | 0 | **3** (plan required ≥ 3) |
| `grep -c "stage_events\.emit_merge"` | 0 | **3** (plan required ≥ 3) |
| `grep -c "stage_events\.emit_gate"` | 0 | **3** (plan required ≥ 3) |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | 44 | **44** — file NOT edited |
| `grep -c "CALLED ONLY FROM INSIDE" stage_events.py` | 7 | **11** |
| `grep -nE "run_events\.emit\(" stage_events.py` | exit 1 | **exit 1** — the bare emitter is still never called |

**The unchanged `await set_stage(` count is the strongest single proof that this
plan added observability and did not touch behaviour.**

### Body rows in the stubbed run — 0 → N, per stage

Measured by driving the real pipeline against the stubbed harness and reading
`run_events._writer`, using `RunFeed.tsx`'s own `body` filter (`kind` is neither
`divider` nor `summary`).

| stage | body rows before | body rows after (clean run) | what they are |
|---|---|---|---|
| `distill` | **0** | **5** | 1 `dispatch` + 3 per-stream (`agent_done`) + 1 closing `thinking` |
| `merge` | **0** | **3** | 1 `dispatch` + 1 multi-member cluster (`thinking`) + 1 closing `thinking` |
| `gate` | **0** | **2** | 1 `dispatch` + 1 closing `thinking` |
| `gate` (a run that actually drops) | **0** | **5** | 1 `dispatch` + 3 `plan` drop rows + 1 closing `thinking` |

The clean harness script KEEPs every claim (`_answer_materiality`: "KEEP
everything"), so its gate drops nothing — which is why the drop rows are proved
against a one-hook subclass rather than against the clean run. A test asserting
zero drop rows on the clean script and calling that a pass is exactly the vacuity
this file's own header warns about.

### The per-local grep counts

| local | `grep -c` | reading |
|---|---|---|
| `_distill_row` | **3** | its ONE assignment plus the two uses the criterion names — the `set_stage` call and the `stage_events` call |
| `_gate_row` | **3** | same shape: one assignment, two uses |
| `_merge_row` | **7** | **not two, and correctly so — see below** |

`_merge_row` was **already a local before this plan** (`pipeline.py`, the merge
close). Its seven lines are: the base assignment, the `_GROUP_VERIFY=false`
fail-loud reassignment, the `factlist_fallbacks` `+=`, one comment naming it, and
then three uses — `emit_merge_done`, `set_stage`, and the pre-existing
`log.info`. The criterion's *purpose* — that the sentence is composed once and
shared, never composed twice — holds exactly: there is one composer and three
readers of it. The plan's "exactly twice" was written for the two locals it
expected to CREATE; `_merge_row` it explicitly told me to pass rather than
rebuild, and that log line predates this phase.

## What each stage now says

**`distill` — "Claim distillation"**

- `emit_distill_dispatch` → one header: how many streams across how many reports.
- `emit_distill_record` → one row per `ProviderFactsRecord`, budget-guarded.
  `agent_done` for a stream that stated its own facts; **`agent_retry` — never
  `agent_fail` — for one that fell back**, carrying 15.2-04's reason verbatim
  ("claude returned no FACTS_START/FACTS_END block — its report will be run
  through the full-extraction distiller"). Per D-14 a fallback degrades ONE
  STREAM's metadata and not the run; an ✗ here would be a false fault report.
- `emit_distill_done` → the closing sentence, the same object `stage_detail` gets.

**`merge` — "Cross-provider merge"**

- `emit_merge_dispatch` → one header.
- `emit_merge_cluster` → one row per **multi-member** cluster only. A singleton
  is the ordinary case and earns nothing. The rule lives in the helper;
  `pipeline.py` loops the groups unconditionally, so there is no second place the
  definition of "multi" can drift.
- `emit_merge_done` → the ALREADY-BOUND `_merge_row`, passed not rebuilt.

**`gate` — "Verification gates"**

- `emit_gate_dispatch` → one header.
- `emit_gate_drop` → one `plan` row per DROP, naming the gate's own reason
  literally (`NOT_FALSIFIABLE` / `NOT_LOAD_BEARING` / `BOTH`, read off
  `gates.py::_DROP_REASONS`). `plan` because a gate decision is a routing
  decision. A KEEP earns nothing — the funnel already counts it.
- `emit_gate_done` → the closing sentence, bound once and shared.

## Extended public surface of `stage_events.py` (for 21-06)

**New on the spine:**

| Name | Purpose |
|---|---|
| `_sentence_or_none(text) -> Optional[str]` | THE BLANK-ROW RULE, in one place. `None` or all-whitespace ⇒ no row. |

**The nine helpers, all `run_id` positional first, everything else keyword-only:**

| Function | Kind | Budgeted |
|---|---|---|
| `emit_distill_dispatch(run_id, *, streams, reports)` | `dispatch` | no |
| `emit_distill_record(run_id, budget, *, record)` | `agent_done` / `agent_retry` | yes |
| `emit_distill_done(run_id, *, text, claims)` | `thinking` | no |
| `emit_merge_dispatch(run_id, *, claims, streams)` | `dispatch` | no |
| `emit_merge_cluster(run_id, budget, *, group)` | `thinking` | yes (multi-member only) |
| `emit_merge_done(run_id, *, text, clusters)` | `thinking` | no |
| `emit_gate_dispatch(run_id, *, claims)` | `dispatch` | no |
| `emit_gate_drop(run_id, budget, *, claim)` | `plan` | yes (DROP only) |
| `emit_gate_done(run_id, *, text, funnel)` | `thinking` | no |

Internal composers marked `CALLED ONLY FROM INSIDE A build() THUNK`:
`_distill_record_event`, `_merge_cluster_event`, `_gate_drop_event`,
`_gate_done_event`. Never-raising helpers that run OUTSIDE the thunk:
`_distill_record_kind`, `_merge_cluster_members`, `_gate_is_drop`.

Constants: `_STAGE_DISTILL`, `_STAGE_MERGE`, `_STAGE_GATE` (each asserted by
execution to be a declared `ENGINE_STAGES["tribunal"]` key), `_MERGE_MIN_MEMBERS`,
`_GATE_DROP`.

## THE PATTERN — two clarifications 21-06 must read

Both are written into `stage_events.py`'s `HOW TO ADD THE NEXT STAGE` docstring,
in place, so they travel with the code:

**(f) A row whose text is PASSED IN must refuse a blank sentence — and must do it
by calling `_sentence_or_none`, not by writing the check again.** 21-03 stated
this rule in its own module docstring and then shipped `emit_verify_closing`
breaking it. A rule that lives only in prose gets re-derived by every next
author, and 21-06 has four more closing lines to add. `emit_verify_closing` now
calls the shared helper too — same behaviour, one home.

**(g) If a row's `kind` varies with the data, that choice is made OUTSIDE the
thunk, so it must not be able to raise.** `kind` is an argument to the emitter,
not something the thunk returns. `emit_distill_record` is the worked example:
`_distill_record_kind` reads `record.reports_fell_back` inside its own try and
falls back to `agent_done`. Reading that attribute inline in the argument list
would put rule 3's exact defect back at the call site while looking like a
one-liner. The same reasoning covers a row's SELECTIVITY test
(`_merge_cluster_members`, `_gate_is_drop`): "does this item earn a row" is
decided before the emitter is entered, so it is never-raising too.

**The trap 21-03 flagged still stands and I hit no new form of it:** the plan's
acceptance one-liner compares the file-wide counts of the emitter's name and the
thunk literal, so neither may appear in prose. The additions use the same evasion.

## Verification results

**Task 1 — the kind/meta/thunk one-liner:** prints `ok ['agent_done',
'agent_fail', 'agent_run', 'dispatch', 'plan', 'thinking']`, exit 0. Every
`kind=` literal is in `RUN_EVENT_KINDS`, none is `divider` or `summary`, and the
thunk-taking call count equals the thunk count.

Every other Task-1 criterion was proved **by execution, not by grep**, in one
driver against a recorder installed at `run_events._writer`:

- the nine helpers are importable (`hasattr` over the named list);
- `_STAGE_DISTILL` / `_STAGE_MERGE` / `_STAGE_GATE` are each in
  `[s["key"] for s in ENGINE_STAGES["tribunal"]]`;
- `_distill_record_kind` returns `agent_done` / `agent_retry` / `agent_done`
  (clean / fell-back / degraded) and every return is in `RUN_EVENT_KINDS` —
  which the `kind="..."` regex cannot see, so it is asserted separately;
- a claim with `gate.reason == "NOT_FALSIFIABLE"` produces a row containing that
  literal;
- a two-member group produces ONE cluster row and a singleton produces ZERO;
- every recorded meta key — `{'items', 'provider', 'sub'}` — is in
  `run_events._META_FIELDS`, and every recorded kind is in `RUN_EVENT_KINDS`.

**Task 2 — the five-file regression surface:** `182 passed`, 0 failures
(`test_engine_e2e_stubbed`, `test_run_event_emit`, `test_stage_logging`,
`test_factlist_fallback`, `test_gate_replay`). `test_gate_replay` and
`test_factlist_fallback` are the behavioural surfaces for the gate and the
distiller; a change to what the pipeline DECIDES turns one of them red.

Budgets: `_distill_budget`, `_merge_budget` and `_gate_budget` are each created
exactly once and flushed exactly once. The `emit_merge_cluster` loop is at line
2914 — **below** the `groups` rebind (2879/2893) and **above** the checkpoint
write (3002), which is the placement the plan's ⚠ demands.

**`git diff -U0` hunk headers** (untouched-region proof): every hunk is at base
line 2596 or later. **No hunk intersects 530-570** (`_stage_event_boundary`) or
**1610-1690** (the load-bearing shadowed `set_stage` shim). Two hunks are
non-additive — `@@ -2663,21 +2707 @@` and `@@ -2995,10 +3065 @@` — and those are
exactly the two inline-to-local sentence rebindings step (e) allows. That both
preserved their strings is not asserted in prose: it is proved by
`test_the_closing_feed_row_is_the_same_sentence_as_the_stage_detail`, which
compares the emitted row against the `set_stage` JSON for all three stages.

**Task 3 — the registered engine gate, run locally with its list extracted FROM
the config** (never retyped; the extractor asserts `len(paths) ==
EXPECTED_FILES == 44`, no duplicates, and that every named file exists before
running):

```
1898 passed, 13 skipped, 6 errors in 48.41s
```

The **6 errors are pre-existing and are not caused by this plan** — 4 in
`test_dispatch_pii.py::test_never_raises` and 2 in
`test_fact_list_parser.py::test_parser_never_raises`, all `ValueError: the
environment variable is longer than 32767 characters` raised by pytest's own
`_update_current_test_var` teardown on very long parametrised ids. They are
Windows-only, present at every commit including the base, and 21-03 recorded the
identical six. Neither file appears in this plan's three-file diff. **Zero
failures** is the pass condition and it is met.

## The thirteen new tests

| Test | Proves |
|---|---|
| `test_the_stage_is_no_longer_a_label_with_nothing_under_it[distill\|merge\|gate]` | ≥ 2 body rows and exactly ONE dispatch header, using `RunFeed.tsx`'s own `body` filter (3 parameterisations) |
| `test_distill_names_each_stream_and_what_it_yielded` | one row per dispatched stream, each naming the provider AND a number |
| `test_a_fallen_back_stream_says_why` | the fallback row carries 15.2-04's reason; **negative control**: the clean run emits ZERO `agent_retry`; and no `agent_fail` (D-14) |
| `test_merge_names_a_multi_stream_cluster_and_ignores_singletons` | the cluster-row count equals production's OWN multi count, parsed out of `_merge_row` |
| `test_gate_drop_rows_name_the_gate_reason` | row count `== min(funnel["dropped"], budget)`, reasons read off `gates._DROP_REASONS` |
| `test_the_gate_budget_states_its_elision` | exactly one elision row carrying the REAL refused count (7), idempotent flush |
| `test_no_distill_merge_or_gate_emit_can_fail_the_run` | four degraded shapes cost their rows and nothing else; **four negative controls**; the good rows survive; no blank row; no false elision |
| `test_a_raising_distill_composer_costs_the_row_and_not_the_run` | the STRUCTURAL D-06 proof at the new sites, and "the run completes" end to end |
| `test_the_closing_feed_row_is_the_same_sentence_as_the_stage_detail[distill\|merge\|gate]` | the two rebindings preserved their strings (3 parameterisations) |

Every parameterisation carries a vacuity guard asserting the stage appears in
`_stage_sequence(...)` **before** any filter runs. Rows are read at
`run_events._writer` — the deepest seam that is still not Postgres — so `emit`,
`emit_safe` and the real thunk all stay in the path under test. No Postgres, no
provider key, no network, no mocking library. **Zero skips**: the merge test's
skip branches did not fire because the stubbed run really does form one
multi-member cluster.

Two one-hook subclasses drive branches the clean script never reaches:
`_LostStreamProvidersAudited` (already in the harness) for the fallback, and a
new `_DroppingGateAudited` in this file for the drops.

## Deviations from Plan

### Auto-fixed / clarified

**1. [Rule 2 — missing critical functionality] The blank-row rule was extracted
to `_sentence_or_none`, and `emit_verify_closing` now calls it.**

- **Found during:** Task 1, from this plan's inherited context — 21-03's own
  SUMMARY records that `emit_verify_closing(text=None)` shipped emitting a BLANK
  feed row, against a rule its own module docstring already stated.
- **Why this is not just tidying:** I was adding three more closing-line helpers
  with exactly the same hazard, and 21-06 adds four more. Restating the rule in
  seven docstrings is the "thirty edits, each of which is a chance to miss one"
  anti-pattern this codebase already names. One named function is checkable.
- **What changed in 21-03's code:** `emit_verify_closing`'s two-line inline check
  became one call. Behaviour is identical and is pinned in both directions by the
  two existing tests (`..._is_emitted_when_there_is_a_sentence` and the blank
  half of `test_no_verify_emit_can_fail_the_run`), both still green.
- **Note on the plan's "do not restructure what 21-03 wrote":** this is the one
  place I did touch it. The instruction's intent — do not reshape the spine or
  the verify helpers — is respected; nothing else in 21-03's code moved.
- **Commit:** `f044f11`

**2. Recipe steps (f) and (g) added to the `HOW TO ADD THE NEXT STAGE`
docstring.** Requested by the orchestrator's brief ("if you extend or clarify the
pattern, update the docstring in place so it stays the single source of truth").
(f) is the blank-row rule above. (g) is new and is a real gap the plan's design
forced me to confront: `emit_distill_record`'s `kind` depends on the data, `kind`
is not something the thunk can return, and reading the attribute inline would
have reintroduced rule 3's defect at the call site. 21-06's `adjudicate` and
`conflict` stages will very likely need the same shape.

### Nothing else

No architectural change, no new event kind, no new meta key, no new test file, no
package install, no `requirements.txt` edit, no CI config edit.

### Stale-base trap — caught, 25th consecutive occurrence

The worktree forked from **`a3a0c96`**, not from the wave-2 base `875b396` — the
same commit this trap has produced every previous time, now including all four
wave-1 worktrees of this phase and this one. `git merge-base` caught it; the
positive-presence sentinel (`stage_events.py` from 21-03, plus `21-03-SUMMARY.md`
and `21-05-PLAN.md`) confirmed the corrected tree before a single edit was spent.
`git rev-list --count` would have read green throughout.

## Known Stubs

None. Every row this plan emits is wired to real pipeline data; nothing is a
placeholder awaiting a later plan.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no
schema change. Every threat in the plan's register was mitigated by construction:

- **T-21-05-01** (one `plan` row per dropped claim): bounded by `_gate_budget` at
  `MAX_ROWS_PER_STAGE`, the elision stated as a visible row, asserted by
  `test_the_gate_budget_states_its_elision` with the real refused count.
- **T-21-05-02** (one row per merge cluster): same budget, and the helper emits
  only for multi-member clusters, so singletons — the bulk of any run — cost
  nothing. Measured: 1 cluster row for 6 clusters in the stubbed run.
- **T-21-05-03** (a malformed record, group or gate dict): every read happens
  inside a thunk, proved by `test_no_distill_merge_or_gate_emit_can_fail_the_run`
  with four negative controls and by the raising-composer test through the real
  pipeline.
- **T-21-05-04** (claim text and provider reasons in feed rows): every site goes
  through the thunk-taking entry point, so `scrub_pii`-then-clamp inside the
  emitter is unavoidable. No path around it was added.
- **T-21-05-05** (the inline-to-local rebindings): proved by cross-surface
  comparison, not by inspection — the emitted row IS the `stage_detail` sentence
  for all three stages. The unchanged `await set_stage(` count is the backstop.
- **T-21-05-SC** (package installs): none. `stage_events.py` still imports only
  `os`, `typing` and two existing first-party modules.

## Commits

| Hash | Message |
|---|---|
| `f044f11` | `feat(21-05)`: add the distill, merge and gate feed helpers to `stage_events.py` |
| `728ca5a` | `feat(21-05)`: give distill, merge and gate a body — wire their emit sites |
| `abf0f8b` | `test(21-05)`: prove distill, merge and gate have bodies, end to end |

## For the next executor

- **21-06:** extend `stage_events.py` and the **PHASE 21 section of
  `test_run_event_emit.py`** — do not create a new test file. `EXPECTED_FILES`
  stays 44. `_Persisted`, `_install_writer`, `_names_a_cause`, `_21_05_STAGES`,
  `_ELISION_MARKER`, `_providers_the_run_dispatched` and `_DroppingGateAudited`
  in that section are all reusable as-is.
- **Read recipe steps (f) and (g)** before writing a closing line or a
  data-dependent `kind`. They exist because this plan needed them.
- **Deploy surface:** this plan changes `tribunal/` only → `tribunal-worker`.
  Re-derive the surface from the actual diff at deploy time (D-02); the
  2026-08-06 deploy caught a third service after a standing note said two.
- **Nothing here has run.** Like 21-03 and like the three changes at tag
  `20260806-175613`, this code is proven against the stubbed harness and has
  never executed against a live model. The ~$45 run remains the thing that
  validates it.
