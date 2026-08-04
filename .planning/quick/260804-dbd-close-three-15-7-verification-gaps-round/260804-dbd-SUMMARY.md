---
quick_id: 260804-dbd
phase: quick
plan: 260804-dbd
type: execute
status: complete
executed: 2026-08-04
base_commit: 94a7647
requirements: [D-W4-9, D-W4-10, D-W4-11]
commits:
  - hash: 8eff424
    subject: "fix(quick-260804-dbd): hold the workshop loop to a minimum round floor"
  - hash: 868775b
    subject: "refactor(quick-260804-dbd): remove attach_discovery_riders' inert max_size"
  - hash: 9f5a120
    subject: "feat(quick-260804-dbd): persist every workshop note as a run event"
gate: NOT RUN — owed at 15.8
---

# Quick task 260804-dbd — close three 15.7 verification gaps

All three tasks executed in order. **`max_size` WAS removed** — zero remaining callers were proved
by an AST walk over `tribunal/**/*.py` (20 `attach_discovery_riders` call sites, 0 passing
`max_size`) **before** the signature changed, so the "leave the parameter in place" fallback in the
plan did not apply. `clamp_groups`' own `max_size` is a different, legitimately binding parameter;
all 14 of its call sites are untouched.

## THE GATE WAS NOT RUN AND IS OWED

**No pytest run exists for any of this.** This machine has no Python 3.11, no pytest, no sqlalchemy
and no Docker; the only interpreter is the stdlib-only bundled
`C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe` (3.14). **No green suite is
claimed.**

This change must be re-gated in **15.8's Cloud Build** via `tribunal/cloudbuild.test-engine.yaml`
against baseline **`7c89be5c` = 1538 passed / 0 failed / 13 skipped, `collecting: 36 of 36 expected
files`**. **No new test FILE was added**, so `EXPECTED_FILES` stays **36**; the passed count must
**RISE by 10** — the number of new test functions, counted as
`git diff 94a7647 -- tribunal/nestor_pulse_sdk/tests/ | grep -c '^+\(async \)\?def test_'` = 10, with
0 removed. **A count that does not rise must be EXPLAINED, not merely noted.** Read the build's text
via `gcloud builds describe` — `gcloud builds submit | tail` returns the PIPE's exit code, so a
FAILED build reports exit 0.

## What was proved on this machine, and how

The `ast`-lift harness was **not** used for name resolution anywhere. `workshop_loop.py` is
stdlib-only by design, so it was loaded as a **real module by file path**
(`importlib.util.spec_from_file_location`) — an honest import that resolves names for real.

### 1. Mutation column for the round floor (red-before / green-after)

Driven against the **committed source text**, not a hand-written copy. The single line
`should_exit = bool(criteria_ok and floor_ok)` was asserted to appear **exactly once**, replaced with
the pre-fix form `should_exit = bool(criteria_ok)`, and the mutated text `exec`'d into a fresh module.

| Source | round-1 clean case (all three criteria hold) |
|---|---|
| **pre-fix text** (floor removed) | `should_exit is True` — **RED**, the loop exits after one pass |
| **committed text** | `should_exit is False` — **GREEN**, the floor holds it open |

A test that passes on unfixed source proves nothing; this one fails on it.

### 2. Behaviour battery against the real module — 31 checks, all PASS

`_LOOP_MIN_ROUNDS == 4`; round 1 clean → `coverage_ok`/`quality_ok`/`saturation_ok` all True,
`should_exit` **False**, `floor_ok` False, `min_rounds` 4, `hold_reason` non-empty and >40 chars
naming both digits, `degradation_reason` **empty**; round 4 → `should_exit` **True**, `hold_reason`
empty; `max_rounds=2` at round 1 → False with `min_rounds` degraded to **2**; at round 2 → **True**
with `cap_reached` True (**the cap wins**); `max_rounds=1` at round 1 → **True**; `min_rounds=10**6`
against cap 10 → exits at 10 (**a floor cannot hang the loop**); a WEAK winner at round 1 →
`should_exit` False with `hold_reason` **empty** (**a hold is distinguishable from a failure**);
8-shape hostile battery (`round_no=None`, non-list winners, string `client_questions`, garbled
`min_rounds`, `max_rounds=0`, negatives) → never raises, always a bool; env knob honoured at 7 and
falling back to 4 on garbage.

### 3. Static undefined-name check — CLEAN and NON-VACUOUS

`ast` walk collecting module-level assignments, imports, defs, classes, function params,
comprehension/for/with/except targets, walrus, match captures, `global`/`nonlocal` and
`builtins.__dict__`, flagging every `ast.Name` load resolving to none of them.

**CLEAN** on `workshop_loop.py`, `workshop_rank.py`, `question_grouping.py`, `pipeline.py`.

**Shown non-vacuous:** on a deliberately broken copy of `workshop_loop.py` (a typo'd builtin and two
typo'd module globals) it flags exactly 3 findings — `maxx` at line 230, `_LOOP_MIN_ROUNDSS` and
`_safe_intt` at line 705. **A check that cannot fail proves nothing.**

### 4. AST proofs

- **Zero `max_size` callers:** every `Call` whose callee is `attach_discovery_riders` — 20 sites, **0**
  with a `max_size` keyword. Run **before** the signature changed. Grep alone would not have been
  enough, because `clamp_groups` shares the keyword name; the tool sorts by callee, which is how the
  14 `clamp_groups` sites were positively identified as out of scope.
- **The thunk:** the `emit_safe` call at `pipeline.py:2036` has `stage='workshop'`, `kind='plan'`, a
  `Lambda` `build=`, **no `JoinedStr`/`BinOp`/`Call` among any other argument**, a default-bound loop
  parameter `n`, and `str()` **inside** the lambda body. Exactly one workshop-stage site.

### 5. `py_compile` on all 9 edited files — OK

Syntax only. It proves nothing about names or behaviour, which is why 3 and 4 exist.

## Task 1 — the minimum-round floor (D-W4-9, commit `8eff424`)

Closes **gap 1 (the BLOCKER)** and **human_verification item 1**.

The defect: `exit_verdict`'s criterion 3 (SATURATION) is **vacuously true in round 1** —
`_stamp_loop_candidates` stamps `born_round = round_no + 1`, so a round-1 winner set structurally
cannot contain a loop-born candidate. On a KEEP-heavy brief all three criteria hold at the end of
round 1 and the loop breaks after ONE pass: no COMBINE, no cross-question synthesis, the meta-review's
guidance never used, no INVENT through the evidence gate, and the two cross-cutting slots filled by
ordinary candidates by rank.

- `_LOOP_MIN_ROUNDS = _env_int("NESTOR_TRIBUNAL_WORKSHOP_LOOP_MIN_ROUNDS", 4)` at
  `workshop_loop.py:72`, documented in the tunables comment register. **The literal `4` appears in
  exactly one place** (verified: one non-comment occurrence of the default).
- **The floor is enforced INSIDE `exit_verdict`, never at the `break`.** A floor at
  `workshop_rank.py`'s break site would leave the verdict dict — read by the round records, the stage
  feed and the tests — reporting `should_exit: true` while the loop ran on. Verified: **0** occurrences
  of a `round_no >=` test within 3 lines of `should_exit` in `workshop_rank.py`.
- `effective_floor = min(floor, max(1, cap))` — **the cap always wins**, so
  `for round_no in range(1, max_rounds + 1)` remains the sole termination guarantee.
- New verdict keys: `min_rounds` (the **effective** floor, so the record says what actually applied),
  `floor_ok`, `hold_reason`. `hold_reason` is non-empty **only** when `criteria_ok and not floor_ok`,
  written via `_reason_floor_not_reached` in the house style of `_reason_cap_with_weak`. It is **not**
  a degradation and stays out of `degradation_reason` (D-12's alarm-fatigue rule).
- `workshop_rank.py`: `min_rounds` read **inside** the function (same idiom as `max_rounds`, so a
  monkeypatched constant is picked up at run time), passed to `exit_verdict`, plus one `log.info`
  before the break block that fires on a non-empty `hold_reason` and reads fields straight off the
  verdict.
- **The exp11 reconciliation the verification asked for:** neither account was wrong. "Winner set
  clean from round 1" and "exits round 4" are the same run once the criteria are ANDed with a floor.

### Tests changed, not just added

- `test_exemption_a_a_cross_cutting_winner_never_counts_as_weak` asserted `should_exit is True` at
  `round_no=3`. Raised to `workshop_loop._LOOP_MIN_ROUNDS` (**the constant, not a hand-typed 4**), with
  a docstring paragraph saying why the round moved and that the subject is still Exemption A.
- **Re-read the whole `exit_verdict` section**: the only other `should_exit is True` assertions are at
  `round_no=4` and `round_no=10`, both above the floor. The `round_no=3` tests that assert only
  `quality_ok`/`coverage_ok` are unaffected and untouched. Checked and unaffected as the plan listed:
  `1 <= r < _LOOP_MAX_ROUNDS`, `== _LOOP_MAX_ROUNDS`, `>= 3`, `< _LOOP_MAX_ROUNDS`, and
  `test_workshop_scope_guard.py`'s `should_exit is False` at round 1 (still False, still because
  `quality_ok` is False).
- **Two now-false docstrings corrected.** `_script`'s claimed the all-KEEP case "correctly exits in
  round 1"; it now states the floor mechanism and why the early-WEAK arm is still necessary (it is the
  only arm driving criteria 1 and 2 through a genuine FAIL and back). `test_engine_e2e_stubbed.py`'s
  asserted the round-1 exit as engine behaviour; it now says it is a consequence of that file's pin.
- The e2e stub fixture pins `_LOOP_MIN_ROUNDS = 1` beside its existing `_LOOP_MAX_ROUNDS = 2`, in the
  file's "AN OVERRIDE, NOT THE PRODUCTION VALUE" register, explaining that the fake proposes every
  round so the production floor would move that file's cost/call-count/model-list assertions **for a
  property of THE FAKE**, and pointing at `test_workshop_loop.py` as the owner of the floor.
- 7 new tests, including the stage-B arm the verification said was missing:
  `test_an_all_keep_script_still_runs_the_full_floor_of_rounds` drives `_run_stage_b` with
  `weak_first_rounds=0` and asserts `rounds >= _LOOP_MIN_ROUNDS` (as a range, because evolve runs at
  temperature 1.0 and a hard round number is a flaky test by construction).

## Task 2 — `max_size` removed (D-W4-10, commit `868775b`)

Closes **human_verification item 4**. Done in the safe order, and the order was the task:

1. **Caller first.** `workshop_rank.py` now calls `attach_discovery_riders(groups, riders)` — **neither
   bound**. It does **not** add `max_riders=`: `_D6_MAX_RIDERS_PER_GROUP` is *derived* from
   `discovery_bracket._DISCOVERY_PER_PARENT_CAP`, so restating it at a call site would create a second
   authority for it. That reasoning is a comment at the call site.
2. **Zero callers proved by AST** (see above) — 19 test call sites updated, `max_riders=` left alone on
   the three calls that passed both.
3. **Only then the signature.** Parameter removed, the `_ = max_size` line and its comment deleted, and
   the docstring paragraph rewritten: it no longer documents a parameter that does not exist, keeps the
   surviving point (**a total-size number must never be re-purposed as a rider budget** — that
   restated-premise mistake produced CR-09), records the 2026-08-04 ruling so nobody "restores" it, and
   states that `clamp_groups`' `max_size` is a different, legitimate parameter so nobody "finishes the
   job".

Also corrected four now-false comment blocks that described the old accepted-but-inert state:
`test_engine_e2e_stubbed.py` (the `max_riders` steering comment and the shed test's docstring),
`test_workshop_scope_guard.py` ("`max_size` is now READ AND DISCARDED"), and two
`test_question_grouping.py` docstrings that reasoned about the parameter no longer binding — all now
say it is **gone**, not merely inert.

Verified: `grep -rn "max_size" --include=*.py tribunal/` returns only `clamp_groups` sites plus the
historical narration inside `attach_discovery_riders`' own docstring (which is accurate history) and
the new ruling text.

## Task 3 — `workshop_notes` persisted (D-W4-11, commit `9f5a120`)

Closes **human_verification item 5**.

- Every note emitted via `run_events.emit_safe`, **module-qualified**, so the D-06 gate that counts
  bare `emit(` calls stays green (the one grep hit in `pipeline.py` is a pre-existing comment,
  unchanged and present at the base commit).
- `stage="workshop"` — a real `ENGINE_STAGES["tribunal"]` key (`runs/stages.py:46`, label "Question
  workshop"). A label on the event, not a stage transition.
- `kind="plan"` — a member of the CLOSED `RUN_EVENT_KINDS`. An invented kind is **dropped** at `emit`,
  which would reproduce the defect being fixed while every test read green.
- **The `[:4]` cap does not survive on the persisted record.** The `log.info` cap is kept, but it now
  logs one further line naming the total and stating the rest were persisted in full — **a truncation
  that records itself is honest; a silent one is the V-01 defect**.
- Text built **inside** the `build=lambda n=note:` thunk, with the loop variable bound through a
  default argument and `str()` coercion inside; `meta=None` because `_META_FIELDS` is an allowlist and
  there is no honest field for a note.
- **One addition beyond the plan (deviation, Rule 2):** `workshop_notes` is guarded with
  `isinstance(..., list)` before `list()`. The plan's `<behavior>` requires a non-list value to cost
  the event and never the run, but `list(7)` raises `TypeError` **at the call site**, outside
  `emit_safe`'s try — which only ever protects the thunk — and `list("abc")` would silently emit three
  single-character events.
- 3 new tests asserting **against the emitted rows, not the log**, using the established
  `monkeypatch.setattr(run_events, "emit", recorder)` seam so the thunk, `emit_safe`'s try and the
  2-tuple check are all real production code: 9 notes → 9 events (complete, not capped); every emitted
  kind asserted a member of the `RUN_EVENT_KINDS` **tuple**, never a hand-typed string; a malformed
  note and a non-list `workshop_notes` cost the events and never the run.
- Also corrected a now-false comment in the shed test that said `pipeline.py` "only logs and never
  persists" `workshop_notes`.

### Documents

`15.7-CONTEXT.md` gains **D-W4-9, D-W4-10, D-W4-11** (verified as the next free numbers — the series
ran D-W4-1…8) in house style: `### D-W4-N — <ruling>`, opening `**Operator decision, 2026-08-04**,
closing …`, with `>` blockquote warnings for the things a future reader could get wrong (the
one-authority placement, `clamp_groups`' legitimate `max_size`, and the render-target caveat) and
code-grounded file:line facts.

`15.7-VERIFICATION.md` marks gap 1 and human_verification 1/4/5 resolved with their rulings and
commits, and adds a `## Ruling pass — 2026-08-04` body section. **The overall status is deliberately
left at `gaps_found`** and the section says so explicitly: the BLOCKER closing is a real change, but
three gaps and two human_verification items remain, and **this pass re-verified nothing** — no
must-have was re-read. Superseded text is kept and marked, as this phase's documents do throughout.
Named as still standing: gap 2 (D7 `langs` ordering), gap 3 (`DROP_CLUSTERED_ONTO_LIVE` with no
production writer), gap 4 (`barred_block`'s oldest-24 slice), and human_verification 2
(`catch_up_matches`) and 3 (`actions` semantics) — both explicitly **NOT RULED**.

Both planning files were `git add -f`'d (`.planning/` is gitignored). Both were already tracked.

## PENDING

- **The pytest gate.** See the section above. This is the only outstanding item, and it cannot be paid
  on this machine.
- The verification record cites D-W4-11's commit as "this commit" plus a `git log` recipe rather than a
  literal hash, because the hash cannot be known before the commit that contains the record. It is
  `9f5a120`.

## Self-check

| Claim | Result |
|---|---|
| 3 commits exist on `master` | `8eff424`, `868775b`, `9f5a120` — confirmed in `git log` |
| No file deletions in any commit | `git diff --diff-filter=D` empty for all three |
| `260804-dbd-PLAN.md` not committed | Confirmed — still staged-but-uncommitted, as the orchestrator left it |
| `.planning/STATE.md` / `ROADMAP.md` not touched | Confirmed — absent from all three commits |
| `_LOOP_MIN_ROUNDS` in `workshop_loop.py` | Present, `:72` |
| `min_rounds=` link `workshop_rank` → `exit_verdict` | Present |
| `max_size` absent from `attach_discovery_riders` | Confirmed by signature read and AST |
| `emit_safe` in `pipeline.py` | 3 call sites, 1 of them the workshop notes |
| D-W4-9/10/11 in `15.7-CONTEXT.md` | Present at lines 493, 545, 575 |

**Self-check: PASSED** — with the pytest gate recorded as PENDING, not as passed.
