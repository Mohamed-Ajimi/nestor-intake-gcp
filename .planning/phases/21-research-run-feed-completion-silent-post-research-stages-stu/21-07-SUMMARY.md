---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 07
subsystem: tribunal-engine-observability
tags: [stage-labels, WR-03, SC6, divider, read-path, run-feed]
status: PAUSED — blocking operator decision at Task 1
requires:
  - "tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py::_stage_event_label (15.3-03)"
  - "tribunal/nestor_pulse_sdk/runs/stages.py::ENGINE_STAGES (the schema, 13 entries)"
  - "tribunal/nestor_pulse_sdk/tests/test_stage_schema.py (the 15.1-13 WR-03 guard)"
provides:
  - "PENDING — awaiting the Task 1 ruling"
affects:
  - "the divider text RunFeed.tsx renders verbatim as the uppercase phase label"
tech-stack:
  added: []
  patterns: []
key-files:
  created: []
  modified: []
decisions:
  - "PENDING — Task 1 is a blocking operator decision, not guessed"
metrics:
  duration: ~35 min (Task 1 measurement only)
  completed: PAUSED 2026-08-10
---

# Phase 21 Plan 07: Stage Labels — PAUSED at the Task 1 Decision

**No source file has been modified.** Task 1 is a `checkpoint:decision` with
`gate="blocking"` and the plan forbids starting Task 2 before it is answered.
This file records the measurement that informs the ruling.

## STATUS: AWAITING OPERATOR RULING

The decision, verbatim from the plan: *How `report_spec` (and `done`, and any
future non-schema marker) stops rendering as a raw snake_case key: by DECLARING
it in `ENGINE_STAGES["tribunal"]` as D-15 proposes, or by giving the READ PATH a
label for it while leaving the ordered schema at thirteen.*

**Options:** `option-declare` | `option-read-path` (planner's recommendation).

---

## ⚠ THE PLAN'S FACT 4 IS HALF WRONG, AND THE HALF THAT IS WRONG CHANGES THE DECISION

The plan states the raw-key defect is **LATENT** — that `report_spec` can only be
written on the interactive branch, which never fires for seam runs, and therefore
*"the operator has almost certainly never seen a `report_spec` divider on screen"*.

**That is correct about `report_spec` and it is wrong about the defect.** There
are **TWO** raw-key leaks, not one. The second is `done`, and it fires on **every
single completed run**.

### How this was measured (executed, not grepped)

The `_SET_STAGE_RE` extraction over `pipeline.py`, with each extracted key passed
through the real `_stage_event_label`:

| key | `_stage_event_label(key)` | raw key? |
|---|---|---|
| `adjudicate` | `Adjudication` | |
| `conflict` | `Conflict detection` | |
| `coverage` | `Coverage gate` | |
| `deep_research` | `Deep research` | |
| `distill` | `Claim distillation` | |
| **`done`** | **`done`** | **⛔ RAW KEY** |
| `gate` | `Verification gates` | |
| `intake` | `Adaptive intake` | |
| `merge` | `Cross-provider merge` | |
| **`report_spec`** | **`report_spec`** | **⛔ RAW KEY** |
| `research_division` | `Research division` | |
| `synthesize` | `Final synthesis` | |
| `verify` | `Skeptic verification` | |

13 keys extracted; 13 stages declared.

### The proof that `done` is NOT latent

Driving the full stubbed pipeline through 21-06's own harness (`_engine_run` +
`_ScriptedProvidersAudited`, rows read at `run_events._writer`) and printing the
`text` of every `divider` row — i.e. exactly the string `RunFeed.tsx:339-347`
renders — a complete, ordinary, **non-interactive** run emits **13 dividers**:

```
intake             'Adaptive intake'
research_division  'Research division'
deep_research      'Deep research'
distill            'Claim distillation'
merge              'Cross-provider merge'
gate               'Verification gates'
verify             'Skeptic verification'
adjudicate         'Adjudication'
coverage           'Coverage gate'
verify             'Skeptic verification'
conflict           'Conflict detection'
synthesize         'Final synthesis'
done               'done'                *** RAW KEY ON SCREEN ***
```

The `done` divider comes from `pipeline.py:4660`
(`_stage_log_transition(run_id, "done", ...)`) → `_stage_event_boundary`
(line 601) → `build=lambda: (_stage_event_label(stage_key), None)` (line 571).
There is no interactive branch involved. **Every completed run the operator has
ever opened ends with a divider whose text was produced by the raw-key fallback.**

It renders as `DONE` (RunFeed uppercases), which is why it has never been
reported as "rubbish information" — it happens to be an English word. But it is
still a raw stage key on the operator's screen, produced by a fallback rather
than by any label anyone chose, and SC6's outcome clause forbids exactly that.

### Why this is decision-relevant, not trivia

**`done` cannot be fixed by `option-declare`.** `stages.py:36` states the rule:
*"The terminal 'done' position is implicit (current_stage == 'done')"* — the UI
infers completion from `current_stage`, it is not a checklist row. Declaring
`done` in `ENGINE_STAGES` would add a phantom terminal row to every run's ordered
checklist and break the exact-list assertion at `test_stage_schema.py:116-130`.

So under `option-declare` the outcome is: `report_spec` gets a schema entry,
**and `done` still needs a read-path label anyway.** That ships BOTH mechanisms —
the phantom row *and* the second label source — which is strictly worse than
either option on its own. Under `option-read-path`, one map handles both markers
uniformly and the schema stays at thirteen.

**This does not pre-empt the ruling** — the operator may still prefer the schema
entry for `report_spec` specifically. It is recorded here because the plan's
options were written as if `report_spec` were the only marker in play, and it is
not.

---

## Everything else in the plan's `<measured_facts>` VERIFIED as written

| Fact | Verdict |
|---|---|
| **FACT 1** — the recurrence guard already exists and is registered | ✅ `test_every_set_stage_key_in_the_pipeline_is_declared` at `test_stage_schema.py:175-203`, with its `len(found) >= 8` vacuity guard and `{"gate","verify","synthesize"} <= found` positive control. Registered in `cloudbuild.test-gates.yaml` (`EXPECTED_FILES=13`). |
| **FACT 2** — `report_spec` was deliberately excluded by 15.1-13 | ✅ `_NON_SCHEMA_MARKERS` at `test_stage_schema.py:38-48`, with the written phantom-row rationale and *"listed here explicitly so the exception is reviewable, not silently absorbed"*. |
| **FACT 3** — the phantom-row cost is real | ✅ declaring it would also break the exact 13-name list assertion at lines 116-130. |
| **FACT 4** — `report_spec` is interactive-only | ✅ **for `report_spec`** — now at `pipeline.py:4213` (not 3955; 21-06 shifted the lines), inside `if interactive_report:` at 4206, `return`ing at 4218. ⛔ but see above: the *defect* is not latent, because `done` is. |
| **FACT 5** — the stale "fourteen" claim | ✅ **and there are THREE, not two.** See below. |
| **FACT 6** — the read-path generalisation | ✅ CONTINUE-HERE.md, paid off at G-10 and G-5. |

### FACT 5 correction: there are THREE stale "fourteen" claims, not two

The plan names `pipeline.py:483` and `test_run_event_emit.py`'s header. Measured:

- `pipeline.py:225` — *"15.3-03: the fourteen `{key, label}` pairs."*  ← **the plan does not mention this one**
- `pipeline.py:490` — *"has carried a label for all fourteen stages since Phase 15"*
- `test_run_event_emit.py:15` — *"label for all fourteen stages since Phase 15"*

`grep -ci "fourteen" pipeline.py` returns **2**. The plan's acceptance criterion
*"`grep -ci "fourteen" pipeline.py` returns 0"* therefore requires fixing **both**
pipeline.py lines, not just the docstring at 490. (`test_run_event_emit.py:2358`
and `test_workshop_loop.py:1076` also contain "fourteen"/"fourteenth" but both are
correct forward-looking prose about a hypothetical 14th stage — they must NOT be
touched.)

---

## `own_research`: handled deliberately — it is ALREADY LABELLED, and needs no exclusion

The orchestrator flagged this as the shape most likely to produce a labelling
blind spot. Measured, it does not:

- `own_research` **is declared** in `ENGINE_STAGES["tribunal"]` with the label
  `"Own research"` (`stages.py:53`). So `_stage_event_label("own_research")`
  returns `Own research` — **it is not a raw-key leak and never can be.**
- It is **never written** by any `set_stage` call, anywhere: absent from the
  13-key extraction over `pipeline.py`, and the only non-pipeline writers are
  `stage_feed.py` (writes `workshop`) and `runs/adapter.py` (the **`adk`** engine,
  a different schema). Confirmed: it emits **no divider** in the stubbed run.

**Conclusion: `own_research` requires NO action in this plan and NO entry in any
allowlist.** A key that is never written cannot reach the screen, and if it is
ever wired it already has a label waiting. This is the opposite of 21-06's
situation — there the body requirement could not be satisfied for it, here the
label requirement is already satisfied for it. It falls through no gap.

## A REAL blind spot found instead: `workshop`

Both the existing guard and the plan's proposed test (a) extract keys from
`pipeline.py` **only**. Two declared stages are written elsewhere or not at all:

```
declared stages with NO divider in a complete run: ['own_research', 'workshop']
```

`workshop` is written by `StageFeed` (`stage_feed.py:126`), **not** by a
`set_stage` call in `pipeline.py` — `pipeline.py:1752-1763` documents this as
deliberate (D-F, 15.2-24). So a source-scan over `pipeline.py` **cannot see it**,
and a future StageFeed-written key with no schema entry would slip past the
guard exactly as `gate` and `report_spec` did.

`workshop` itself is safe today (it is declared and labelled `Question
workshop`). **The recommendation for Task 3 is that test (a) iterate the UNION of
(keys extracted from `pipeline.py`) ∪ (every declared schema key) ∪
(`_NON_SCHEMA_MARKERS`)**, which closes the StageFeed hole rather than merely
reproducing the existing test's reach. That is strictly stronger than the plan
asks for and costs nothing.

> **Separately noted, NOT fixed here:** `workshop` emits body rows but **no
> divider**, so its block on the run page has no phase heading. That is a
> *divider-presence* defect, not a *label* defect, and is therefore outside SC6
> and outside this plan. Logged as a finding for the phase, not actioned.

---

## Baselines pinned at the base commit `a05ec48`

Every one read out of the file, none from memory:

| Measurement | Value |
|---|---|
| `grep -c "await set_stage(" pipeline.py` | **23** |
| `grep -c "run_events.open_run" pipeline.py` | **1** |
| `grep -ci "fourteen" pipeline.py` | **2** |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | **44** |
| `EXPECTED_FILES` in `cloudbuild.test-gates.yaml` | **13** |
| `test_stage_schema.py` passing | **6 passed** |
| declared tribunal stages | **13** |
| `set_stage` keys extracted from `pipeline.py` | **13** |
| dividers in a complete stubbed run | **13** (one raw: `done`) |

## Stale-base trap — caught, **27th consecutive occurrence**

The worktree forked from **`a3a0c96`** — the same commit every previous time.
`git merge-base` caught it; `git rev-list --count` would have read green. All
four positive-presence sentinels then passed against the corrected tree
(`stage_events.py`, 21-05's `_sentence_or_none`, `21-06-SUMMARY.md`,
`21-07-PLAN.md`) before any measurement was trusted.

## Deviations from Plan

None yet — no source change has been made. The two corrections above
(`done` is a second, non-latent leak; three "fourteen" claims not two) are
corrections to the plan's *premises*, surfaced for the ruling rather than acted
on unilaterally.

## Known Stubs

None — no code written.

## Threat Flags

None — no source modified.

## Self-Check

- `.planning/.../21-07-SUMMARY.md` — this file, committed with `git add -f`
- no source file modified: `git diff --name-only` against `a05ec48` lists only
  this SUMMARY
- STATE.md and ROADMAP.md — **NOT modified** (the orchestrator owns those writes)
