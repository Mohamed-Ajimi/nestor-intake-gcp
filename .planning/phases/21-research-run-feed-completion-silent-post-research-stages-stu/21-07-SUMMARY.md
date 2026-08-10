---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 07
subsystem: tribunal-engine-observability
tags: [stage-labels, WR-03, SC6, divider, read-path, run-feed, D-15]
requires:
  - "tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py::_stage_event_label (15.3-03)"
  - "tribunal/nestor_pulse_sdk/runs/stages.py::ENGINE_STAGES (13 ordered entries)"
  - "tribunal/nestor_pulse_sdk/tests/test_stage_schema.py (the 15.1-13 WR-03 declaration guard)"
provides:
  - "stages.NON_SCHEMA_STAGE_LABELS — the second label source for written-but-undeclared keys"
  - "_stage_event_label resolving EVERY key any source knows, raw-key fallback preserved"
  - "the strengthened WR-03 guard: declaration AND label resolution, over a UNION of three sources"
  - "SC6 CLOSED — no raw stage key can reach the operator's screen"
affects:
  - "the divider text RunFeed.tsx renders verbatim as the uppercase phase label"
  - "a future stage added without a label now fails the build instead of shipping as an identifier"
tech-stack:
  added: []
  patterns:
    - "resolve a truncated/raw identifier on the READ path, never by widening the identifier (G-10, G-5, now this)"
    - "an exemption from one requirement must not silently become an exemption from all of them"
    - "a guard over a UNION of sources, because a single-file source scan has blind spots"
key-files:
  created: []
  modified:
    - tribunal/nestor_pulse_sdk/runs/stages.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
    - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
    - tribunal/nestor_pulse_sdk/tests/test_stage_schema.py
decisions:
  - "OPERATOR RULING 2026-08-10: option-read-path — the ordered schema stays at 13, report_spec is NOT declared"
  - "the ruling covers BOTH done and report_spec — one map, both markers"
  - "15.1-13's phantom-row reasoning was REVIEWED AND UPHELD, not reversed"
  - "the guard iterates the UNION of extracted ∪ declared ∪ allowlist — stronger than the plan asked"
  - "the raw-key fallback is deliberately KEPT and pinned by a negative control"
metrics:
  duration: ~95 min
  completed: 2026-08-10
---

# Phase 21 Plan 07: SC6 Closed — No Raw Stage Key Reaches the Operator

The plan was written to fix a **latent** defect on an interactive branch that
never fires for seam runs. Measurement before writing any code found a **second**
raw-key leak that was not latent at all: **every completed run ever opened ended
on a divider whose text was literally `done`.** Both are now labelled on the read
path, the ordered schema is untouched at thirteen, and the guard that missed this
has been widened from "is the key declared" to "does the key resolve to a label",
over a union of sources rather than one file.

## THE OPERATOR'S RULING, RECORDED VERBATIM

> **(1) `option-read-path`.** Give the read path labels; the ordered schema stays
> at **thirteen**. Do NOT declare `report_spec` in `ENGINE_STAGES["tribunal"]`.
>
> **(2) Confirmed: it must cover BOTH `done` and `report_spec`.** The operator
> accepted your correction — `done` renders as a raw-key fallback on every
> ordinary completed run, `done` cannot be declared because `stages.py:36`
> documents the terminal position as implicit, and shipping two mechanisms would
> be worse than either alone. One map, both markers.
>
> **(3) Widen the guard to the union.** Test (a) must iterate
> **keys-extracted-from-`pipeline.py` ∪ every declared schema key ∪
> `_NON_SCHEMA_MARKERS`**.

**Date of ruling: 2026-08-10.** No phantom checklist row was accepted, because
`option-declare` was not selected.

## THE CORRECTION TO THE PLAN'S PREMISE — measured before any code was written

The plan's FACT 4 concluded the defect was latent. It is right about
`report_spec` and wrong about the defect. Every `set_stage` key extracted from
`pipeline.py`, passed through the real `_stage_event_label` at the base commit:

| key | resolved to | raw? |
|---|---|---|
| `adjudicate` `conflict` `coverage` `deep_research` `distill` `gate` `intake` `merge` `research_division` `synthesize` `verify` | their labels | |
| **`done`** | **`done`** | ⛔ |
| **`report_spec`** | **`report_spec`** | ⛔ |

Then the full stubbed pipeline was driven through 21-06's own harness and every
`divider` row's `text` printed — the exact string `RunFeed.tsx:339-347` renders.
A complete, **non-interactive** run emitted 13 dividers ending:

```
synthesize   'Final synthesis'
done         'done'          *** RAW KEY ON SCREEN ***
```

The `done` divider comes from `pipeline.py:4660` → `_stage_event_boundary` →
`build=lambda: (_stage_event_label(stage_key), None)`. No interactive branch is
involved. It renders as `DONE`, which is why it was never reported — it happens
to be an English word — but it was produced by a fallback rather than by any
label anyone chose.

**Why this decided the mechanism:** `done` *cannot* be declared (`stages.py:36`
documents the terminal position as implicit), so `option-declare` would have
fixed `report_spec` and still needed a read-path label for `done` — shipping the
phantom row **and** the second source. `option-read-path` handles both with one
map. The operator ruled on that basis.

### After the fix, same measurement

```
synthesize   'Final synthesis'
done         'Run complete'
RAW-KEY DIVIDERS EMITTED BY A COMPLETE RUN: []
```

## SC6 verified EXHAUSTIVELY, and the check is FAIL-ABLE

**Exhaustive:** the assertion runs over the **union of every source that can put
a key on a divider** — 15 keys — not over one file's grep:

```
adjudicate -> Adjudication          merge             -> Cross-provider merge
conflict   -> Conflict detection    own_research      -> Own research
coverage   -> Coverage gate         report_spec       -> Report shaping
deep_research -> Deep research      research_division -> Research division
distill    -> Claim distillation    synthesize        -> Final synthesis
done       -> Run complete          verify            -> Skeptic verification
gate       -> Verification gates    workshop          -> Question workshop
intake     -> Adaptive intake
RAW KEY LEAKS: []
```

**Fail-able — the guard was OBSERVED to fail.** `report_spec`'s label was
temporarily removed from `NON_SCHEMA_STAGE_LABELS` and the file re-run. Two of
the three new tests went red, each naming `report_spec` and each stating the
repair. **Verbatim:**

```
E   AssertionError: these stage keys resolve to THEMSELVES, so the run page's phase divider
renders the raw snake_case key to the operator: ['report_spec']. Give each one a label - an
ordered checklist step goes in ENGINE_STAGES['tribunal'], a written-but-not-a-step marker goes
in stages.NON_SCHEMA_STAGE_LABELS. This is the WR-03 defect class: the UI shows a bare key with
no label.
E   assert not ['report_spec']

E   AssertionError: 'report_spec' is exempt from being declared in ENGINE_STAGES, which is
deliberate - but it is still WRITTEN to run.current_stage and the divider renders whatever the
resolver returns, so it also needs a label. Add 'report_spec' to stages.NON_SCHEMA_STAGE_LABELS.
E   assert 'report_spec' != 'report_spec'

======================== 2 failed, 7 passed in 32.60s =========================
```

Restored with `git checkout --` on that single path; `git diff` against HEAD for
`stages.py` is **empty**, and the file is green again at **9 passed**.

## The WR-03 defect class cannot recur

| Test | What it makes impossible |
|---|---|
| `test_every_set_stage_key_in_the_pipeline_is_declared` (**untouched, 15.1-13**) | a `set_stage` key that is not declared and not allowlisted |
| **(a)** `test_every_pipeline_stage_key_resolves_to_a_human_label` | a key any source knows about rendering as itself |
| **(b)** `test_the_non_schema_allowlist_cannot_grow_into_a_raw_key_leak` | exempting a key from declaration *without* labelling it, in the same edit |
| **(c)** `test_the_raw_key_fallback_still_exists_for_an_unknown_key` | (a) and (b) becoming vacuous if the resolver ever labelled everything |

A new stage without a label now **fails a test**; it cannot surface as an
identifier.

## Deviations from Plan

### 1. [Reconciled against purpose — STRONGER form] The guard iterates a UNION, not the plan's source scan

- **The plan asked for:** test (a) to extract keys with `_SET_STAGE_RE` over
  `pipeline.py` and assert each resolves.
- **Why that is not enough:** `workshop` is written by `StageFeed`
  (`runs/stage_feed.py:126`), **not** by any `set_stage` call in `pipeline.py`,
  and `pipeline.py:1752-1763` records that as deliberate (D-F, 15.2-24). A scan
  of one file **cannot see it** — the identical one-file blind spot that let
  `gate` and then `report_spec` through in the first place. Reproducing the
  existing test's reach would have reproduced its hole.
- **Implemented instead:** the union of *(extracted from `pipeline.py`)* ∪
  *(every declared schema key)* ∪ *(`_NON_SCHEMA_MARKERS`)* — **15 keys vs 13**.
  Approved by the operator as ruling (3).
- The `>= 8` vacuity guard is still computed on the **extracted** set, so a
  broken regex still fails loudly rather than being masked by the schema keys.

### 2. [Rule 1 — bug] TWO pre-existing tests had PINNED the defect and failed

Task 2's own verify command went red at first: `2 failed, 93 passed`. Neither was
caused by a mistake in the change — both tests asserted the old, wrong behaviour.

- **`test_a_stage_with_no_schema_entry_falls_back_to_its_key`** asserted
  `recorder.texts("divider") == ["Final synthesis", "done"]`. Its *reasoning* was
  sound — "a blank divider would be worse than a bare key" — but its **specimen
  was wrong**: it used `done`, which is not a hypothetical unknown key but one
  written at the end of every run. So the test certified a raw key reaching the
  operator on every completed run.
  **Renamed to `test_a_written_marker_is_labelled_and_an_unknown_key_still_falls_back`
  and split into the two properties it conflated:** a *written* marker must be
  labelled, and an *unknown* key must still fall back — the latter now proven
  with an invented key, which is what the old test meant all along.
- **`_label_of()`**, the helper the harness uses to derive expected labels,
  mirrored only `ENGINE_STAGES`. That is *why* a raw `done` divider looked
  correct to every assertion built on it. It now mirrors both sources, in the
  same order as the resolver.

This is the fifth consecutive plan in this phase to hit something written during
planning that did not survive contact with the code — and the first where the
thing that did not survive was an existing **test** rather than an acceptance
criterion.

### 3. [Extended past the plan, per ruling] THREE stale "fourteen" claims, not two

The plan named `pipeline.py:483` and the `test_run_event_emit.py` header, but the
criterion `grep -ci "fourteen" pipeline.py == 0` cannot be met by fixing one
pipeline site. Measured: **2** in `pipeline.py`.

| Site | Action |
|---|---|
| `pipeline.py:225` (import comment, *"the fourteen `{key, label}` pairs"*) | **FIXED** → "the 13 ordered" — **not named by the plan** |
| `pipeline.py:490` (`_stage_event_label` docstring) | **FIXED** → "all 13 of its ordered stages" |
| `test_run_event_emit.py:15` (header) | **FIXED** → "all 13 of its ordered stages" + names the second source |

**Deliberately LEFT UNTOUCHED — both are correct forward-looking prose, not
stale claims:**

- `test_run_event_emit.py:2361` — *"a hardcoded list of thirteen names would go
  stale the day the **fourteenth** is declared"*. This is the capstone's rationale
  for deriving from the schema. It says thirteen is today's count and describes a
  hypothetical fourteenth. Correct as written.
- `test_workshop_loop.py:1076` — *"**Fourteen** keys, and the ten original ones
  are all still present."* This counts keys in a workshop result dict and has
  nothing to do with stage schemas at all.

`grep -ci "fourteen" pipeline.py` is now **0**.

## `own_research`: handled deliberately — NO action needed, and here is the evidence

Flagged as the shape most likely to produce a labelling blind spot. Measured, it
is the opposite:

- **It is already labelled.** `own_research` **is** declared in
  `ENGINE_STAGES["tribunal"]` with label `"Own research"` (`stages.py:53`), so
  `_stage_event_label("own_research")` returns `Own research`. **It cannot leak
  raw, and never could.** It needs no `NON_SCHEMA_STAGE_LABELS` entry.
- **It is never written.** Absent from the 13-key extraction over `pipeline.py`;
  the only non-pipeline stage writers are `stage_feed.py` (writes `workshop`) and
  `runs/adapter.py` (the **`adk`** engine — a different schema the tribunal
  resolver never consults). It emits **no divider** in a full stubbed run.
- **It is nonetheless COVERED by the new guard**, because the union includes
  every declared schema key. So if it is ever wired, its label is already
  asserted — and 21-06's pinned `_NEVER_REPORTED` set simultaneously drags it
  under the body requirement.

**Conclusion: labelled, covered, and requiring no exclusion.** A later reader
should not re-open this. It fell through no gap: 21-06's problem was that a
*body* could not exist for it; here the *label* already does.

## New finding, routed not absorbed: DEF-21-04

`workshop` emits 12 body rows but **no divider**, so its block on the run page
has no phase heading. Cause: `StageFeed` writes the key, and dividers ride
`_stage_log_transition`, which `pipeline.py:1752-1763` deliberately bypasses for
the workshop span (D-F, 15.2-24).

**Out of scope and not fixed** — it is a divider-*presence* defect, not a
divider-*label* defect, and `workshop` is fully labelled. Logged as **DEF-21-04**
in `deferred-items.md` per the operator's instruction.

## Verification results

| Check | Result |
|---|---|
| Task 2 verify (3 files) | **95 passed, 0 failures** |
| Task 3 verify (`test_stage_schema.py`) | **9 passed** (base: **6**) — **+3**, the criterion's minimum |
| **Full 44-file engine gate** | **1909 passed, 13 skipped, 6 errors, 0 FAILURES** in 140s |
| **13-file test-gates config** | **190 passed, 2 deselected, exit 0** |
| `grep -c "await set_stage("` | **23** — unchanged |
| `grep -c "run_events.open_run"` | **1** — unchanged |
| `grep -ci "fourteen" pipeline.py` | **0** (was 2) |
| `EXPECTED_FILES` engine / gates | **44 / 13** — both read from the files, both unchanged |
| `cloudbuild.test-engine.yaml` | **NOT in the diff** vs base |
| `check_coverage(..., selected_only=True)` | **2 matches**, and `check_coverage` appears in **no diff hunk** |
| declared tribunal stages | **13** — schema untouched |

**The 6 errors are pre-existing and Windows-only** — 4 in `test_dispatch_pii.py`,
2 in `test_fact_list_parser.py`, all `ValueError: the environment variable is
longer than 32767 characters` from pytest's own `PYTEST_CURRENT_TEST` teardown on
very long parametrised ids. Present at every commit including the base; 21-03,
21-05 and 21-06 each recorded the identical six. Neither file is in this plan's
diff. **`grep -c "^FAILED"` is 0**, which is the pass condition.

**Why the engine gate count did not move (1909, same as 21-06):**
`test_stage_schema.py` is registered in `cloudbuild.test-gates.yaml` (13 files),
**not** in the 44-file engine gate — verified by extracting both lists from the
configs. My +3 tests land in the gates config (6→9, inside its 190). The one
engine-gate file I touched, `test_run_event_emit.py`, had a test **renamed**, not
added. So 1909 unchanged is the correct expected result, not a sign the new tests
are unregistered.

## Diff shape

Four files, all in `tribunal/`. Every `pipeline.py` hunk is at lines **225–523** —
`git diff -U0` hunk headers are `@@ -225,3 @@`, `@@ -228,0 @@`, `@@ -488,7 @@`,
`@@ -499,0 @@`. **No hunk intersects the `if interactive_report:` branch** (now at
4206–4218), the `report_spec` write, or the cost trap. All four
`test_stage_schema.py` hunks are pure insertions (`-N,0` — zero deletions
anywhere in the file), inserted at old lines 38/55/63/225, so
`test_every_set_stage_key_in_the_pipeline_is_declared` (old lines 175–203) is
**byte-identical**, vacuity guard and positive control included.

## Stale-base trap — caught, **27th consecutive occurrence**

Forked from **`a3a0c96`** again — the same commit every previous time, and now
685+ behind. `git merge-base` caught it; `git rev-list --count` would have read
green. All four positive-presence sentinels then passed against the corrected
tree before a single measurement was trusted.

## Known Stubs

None. Both labels are real strings rendered by a real code path, proven by
driving the pipeline end to end.

## Threat Flags

None. No network endpoint, no auth path, no file access, no schema change.

- **T-21-07-01** (raw key rendered to an operator): closed — the resolver now
  consults both sources and test (a) asserts over the union that nothing resolves
  to itself. The fallback is deliberately kept for a newer build's unknown key
  and pinned by test (c).
- **T-21-07-02** (a future exemption re-opening the hole): closed — test (b)
  iterates `_NON_SCHEMA_MARKERS` **itself**, never a copy.
- **T-21-07-03** (silently reversing 15.1-13): closed — the ruling is recorded
  verbatim and dated above, and 15.1-13's reasoning was **upheld**, with the
  allowlist comment updated to say so.
- **T-21-07-04** (DoS): none — one dict lookup on a path that runs once per
  stage transition.
- **T-21-07-SC** (package installs): none. No package installed, no
  `requirements.txt` edited.

## Commits

| Hash | Message |
|---|---|
| `3840d4d` | `docs(21-07)`: record Task 1 measurement — a SECOND raw-key leak, and it is not latent |
| `fe4d98e` | `fix(21-07)`: label the written-but-undeclared stage markers on the read path |
| `32552fb` | `test(21-07)`: make the WR-03 guard cover LABELS, not just declaration |

## For `.planning/CONTINUE-HERE.md`

> **WR-03, third encounter — what the guard now covers and what it still does
> not.** The stage guard used to ask one question: is every `set_stage` key in
> `pipeline.py` declared in `ENGINE_STAGES`? It now asks two, because
> `_NON_SCHEMA_MARKERS` exempted a key from declaration and *nothing* checked
> that an exempt key had a label — so the allowlist itself was the route by which
> a raw key reached the screen. Measured 2026-08-10: **every completed run ended
> on a divider reading literally `done`**, which is why "the raw key is latent"
> was wrong. Both markers (`done`, `report_spec`) are now labelled on the READ
> path via `stages.NON_SCHEMA_STAGE_LABELS`, the ordered schema stays at
> thirteen, and the guard iterates the **union** of extracted ∪ declared ∪
> allowlist — because a scan of `pipeline.py` alone cannot see `workshop`, which
> `StageFeed` writes. **Still NOT covered:** that a reported stage has a divider
> *at all* (`workshop` has none — DEF-21-04); any stage key written by a module
> the union does not enumerate; and the `adk` engine's schema, which
> `_stage_event_label` never consults since it hardcodes `stages_for("tribunal")`.
> **The generalisation held for the third time:** resolve a raw identifier on the
> READ path rather than widening the identifier (G-10, then G-5, now this).

## For the next executor

- **Nothing here has run against a live model.** Like 21-03, 21-05 and 21-06,
  this is proven against the stubbed harness only. The ~$45 run is still the
  thing that validates it.
- **Deploy surface:** `tribunal/` only → `tribunal-worker`. Re-derive from the
  actual diff at deploy time (D-02); the 2026-08-06 deploy caught a third service
  after a standing note said two.
- **DEF-21-04 is new** and belongs with the SC1 family, not with labels.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/runs/stages.py` — FOUND (modified)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — FOUND (modified)
- `tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py` — FOUND (modified)
- `tribunal/nestor_pulse_sdk/tests/test_stage_schema.py` — FOUND (modified)
- commits `3840d4d`, `fe4d98e`, `32552fb` — all present in
  `git log a05ec48..HEAD`
- `cloudbuild.test-engine.yaml` and `cloudbuild.test-gates.yaml` — **NOT** in
  `git diff --name-only` vs base
- the temporary gate-bite edit is fully reverted — `git diff` on `stages.py` is
  empty and the file is green at 9 passed
- STATE.md and ROADMAP.md — **NOT modified** (the orchestrator owns those writes)
