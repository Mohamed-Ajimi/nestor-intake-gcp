---
quick_id: 260804-dbd
phase: quick
plan: 260804-dbd
type: execute
wave: 1
depends_on: []
autonomous: true
description: "Close three 15.7 verification gaps by operator ruling (2026-08-04)"
files_modified:
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
  - tribunal/nestor_pulse_sdk/tests/test_workshop_loop.py
  - tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
  - tribunal/nestor_pulse_sdk/tests/test_question_grouping.py
  - tribunal/nestor_pulse_sdk/tests/test_workshop_scope_guard.py
  - tribunal/nestor_pulse_sdk/tests/test_research_division_assignment.py
  - .planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-CONTEXT.md
  - .planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-VERIFICATION.md
requirements: [D-W4-9, D-W4-10, D-W4-11]

must_haves:
  truths:
    - "The workshop loop cannot exit before round 4 even when all three criteria hold, so an exp11-shaped healthy brief gets its COMBINE, its cross-question synthesis and its INVENT evidence gate"
    - "`should_exit` and the `break` site agree — there is ONE authority for the floor and it is inside `exit_verdict`"
    - "A configured cap below the floor still terminates: the cap wins and the floor degrades to it"
    - "A reader of the verdict can tell 'criteria met but floor not reached' from 'criteria not met'"
    - "`attach_discovery_riders` no longer accepts a parameter that binds nothing, and no caller anywhere passes one"
    - "Every `workshop_note` reaches a durable run artifact, not only a capped log line"
  artifacts:
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py"
      provides: "_LOOP_MIN_ROUNDS + the floor inside exit_verdict"
      contains: "_LOOP_MIN_ROUNDS"
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py"
      provides: "attach_discovery_riders with max_size REMOVED"
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py"
      provides: "workshop_notes persisted through run_events.emit_safe"
  key_links:
    - from: "tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py"
      to: "workshop_loop.exit_verdict"
      via: "min_rounds= passed alongside max_rounds"
      pattern: "min_rounds="
    - from: "tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py"
      to: "run_events.emit_safe"
      via: "build=lambda inside the workshop_notes loop"
      pattern: "emit_safe"
---

<objective>
Close three open items in `15.7-VERIFICATION.md` by operator ruling, dated 2026-08-04:

1. **"round number >= 4"** — the workshop loop's self-exit gets a minimum-round floor.
   Closes verification **gap 1 (the BLOCKER)** and **human_verification item 1**.
2. **"clean deprecated"** — `question_grouping.attach_discovery_riders`' inert `max_size`
   parameter is removed. Closes **human_verification item 4**.
3. **"persist"** — `workshop_notes` are written durably as run events, not only logged.
   Closes **human_verification item 5**.

Purpose: gap 1 is a BLOCKER for 15.8's single measuring run. `exit_verdict`'s criterion 3
(SATURATION) is vacuously true in round 1 — no candidate carries a `born_round` yet — so on a
KEEP-heavy brief all three criteria hold at the end of round 1 and the loop breaks after ONE pass,
degenerating Wave 4 into the straight line it replaced. That run is the phase's only evidence.

Output: three code changes (each with tests), plus the ruling ledger and the verification record
brought up to date.

**These are LOCKED operator decisions. Do not revisit, re-argue or soften them.**
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@CLAUDE.md
@.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-VERIFICATION.md
@.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-CONTEXT.md

<environment>
**You cannot run pytest.** This machine has no Python 3.11, no pytest, no sqlalchemy, no Docker.
The only interpreter is the stdlib-only bundled one:

    C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe   (3.14; ast, py_compile, json)

**The gate run for this change is OWED and will be paid in 15.8's Cloud Build**, in
`tribunal/cloudbuild.test-engine.yaml`. The phase baseline it must not regress is build `7c89be5c`
= **1538 passed / 0 failed / 13 skipped**, `collecting: 36 of 36 expected files`. This change adds
**no new test file**, so `EXPECTED_FILES` stays at 36 and the passed count must RISE by the number
of new test functions you add. Say so plainly in the summary; do not claim a green gate.

⛔ **DO NOT use the `ast`-lift harness for NAME RESOLUTION.** It supplies module globals, so it
MANUFACTURES any name a module forgot to import — it hid a missing import used at four sites
through nine plans, `py_compile`, and "38 lifted tests green". Use it for BEHAVIOUR only.

**What you CAN run, and it is enough for the proofs this plan demands:**

- `workshop_loop.py` is **stdlib-only by design** (`import os`, `from typing import ...` — see its
  module docstring, which says being drivable on this interpreter is the point). Load it as a REAL
  module by file path — this is a real import, not a lift, and it resolves names honestly:

      import importlib.util, pathlib
      p = pathlib.Path("tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py")
      spec = importlib.util.spec_from_file_location("wl", p)
      wl = importlib.util.module_from_spec(spec); spec.loader.exec_module(wl)

- `python.exe -m py_compile <file>` on every file you edit (syntax only — it proves nothing about
  names or behaviour).
- A **static undefined-global check** on every production file you edit: parse with `ast`, collect
  module-level assignments, imports, function/class defs, function params, comprehension targets
  and `builtins.__dict__`, then flag every `ast.Name` load that resolves to none of them. Report it
  as CLEAN **and** state what it flags on a deliberately broken copy, so the check is not vacuous.
</environment>

<interfaces>
<!-- Extracted from the merged tree at e4d55b5. Use these directly; no exploration needed. -->

`tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py`
- constants block at `:106-110` — `_TOURNAMENT_ROUNDS_MIN`, `_TOURNAMENT_ROUNDS_MAX`,
  `_LOOP_MAX_ROUNDS = _env_int("NESTOR_TRIBUNAL_WORKSHOP_LOOP_ROUNDS", 10)`,
  `_FLOOR_PER_QUESTION`, `_CROSS_CUTTING_SLOTS`. Each is documented in the comment block at
  `:80-105` — **that comment block is where a new constant's rationale goes.**
- `exit_verdict(*, winners, client_questions, round_no, max_rounds=None) -> dict` at `:600-696`.
  Criterion 3 is `:661-669`. Returns keys: `round_no, max_rounds, winner_count, coverage_ok,
  quality_ok, saturation_ok, should_exit, cap_reached, weak_winners, resurrected_winners,
  new_entrants, degradation_reason`.
- `_reason_cap_with_weak(weak, total)` `:544` and `_reason_cap_with_resurrected(resurrected, total)`
  `:554` — the house style for a reason sentence: `f"question workshop: ..."`, names its count as a
  digit, states the CONSEQUENCE not just the event, comfortably over 40 chars.
- `_safe_int(value, default=0)` `:113` — never raises, excludes `bool` explicitly.

`tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py`
- `:4197` `max_rounds = max(1, int(workshop_loop._LOOP_MAX_ROUNDS))` — read INSIDE the function, so
  a test monkeypatching the module constant is picked up at run time. Mirror this exactly.
- `:4200` `for round_no in range(1, max_rounds + 1):`
- `:4542-4547` the `exit_verdict(...)` call.
- `:4583-4593` `if verdict.get("should_exit"): log.info(...); break`
- `:4792-4794` the ONE production `attach_discovery_riders` call.

`tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py`
- `attach_discovery_riders(groups, riders, *, max_size=None, max_riders=None)` at `:1050`.
  `max_size` is read and discarded at `:1108-1110` (`_ = max_size`); its docstring paragraph is
  `:1085-1091`. `max_riders` defaults to `_D6_MAX_RIDERS_PER_GROUP` (`:213`), which equals
  `discovery_bracket._DISCOVERY_PER_PARENT_CAP` by the derivation at `:195-213`.
- **`:179` and `:1592` reference `max_size` for `clamp_groups`, a DIFFERENT function with a
  legitimate binding parameter (`:764`, `:799`). DO NOT TOUCH EITHER.**

`tribunal/nestor_pulse_sdk/runs/run_events.py`
- `emit_safe(run_id, *, stage: str, kind: str, build: Callable[[], tuple[str, Optional[dict]]])`
  at `:401`. Read its docstring before use: **a caller's arguments are evaluated before the callee
  is entered**, so the text MUST be built inside the `build=lambda:` thunk. Do not hoist `build()`
  into a local.
- `RUN_EVENT_KINDS` at `:69` — a CLOSED vocabulary of twelve:
  `thinking, tool, search, plan, streams, dispatch, agent_run, agent_done, agent_retry, agent_fail,
  summary, divider`. `emit` DROPS a row whose kind is not in it (`:332-336`). **An invented kind is
  a silently discarded event.**
- `_META_FIELDS` at `:109` — `meta` keys outside that allowlist are dropped with a WARNING.
- `MAX_TEXT_CHARS = 400`, applied with a visible `…` (`:568-572`).
- Stage keys come from `runs/stages.py`; `workshop` → label `Question workshop`.

`tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py`
- `:1989` `for note in (workshop_result.get("workshop_notes") or [])[:4]: log.info(...)`
- `run_events` is imported as a MODULE at `:454` (never `from ... import emit`) — there is a D-06
  call-site grep gate that counts bare `emit(` calls and requires zero. Keep the module form.
- `emit_safe` precedent sites: `:529` and `:540` in `_stage_event_boundary`.
- `run_id` and `tenant_id` are in scope at `:1989` (`set_stage(run_id, tenant_id, "intake", ...)`
  is called ~10 lines below).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: The minimum-round floor (Ruling 1 — the BLOCKER)</name>
  <files>
tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py
tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
tribunal/nestor_pulse_sdk/tests/test_workshop_loop.py
tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
  </files>

  <behavior>
Drive these against the REAL `workshop_loop.py` loaded by file path (see `<environment>`).

  - A clean winner set (one KEEP per client question, nothing born this round) at `round_no=1`:
    `coverage_ok`, `quality_ok`, `saturation_ok` all True, and `should_exit` **False**.
  - The same set at `round_no=4`: `should_exit` **True**.
  - The same set at `round_no=1` with `max_rounds=2`: `should_exit` False (floor degrades to 2).
  - The same set at `round_no=2` with `max_rounds=2`: `should_exit` **True** — the cap wins, so the
    floor can never make the loop unterminable. Also `cap_reached` True.
  - `round_no=1, max_rounds=1` → `should_exit` True. The degenerate cap still exits.
  - The floor-held verdict is DISTINGUISHABLE: at `round_no=1` with all three criteria met, the new
    boolean reads False and the new reason string is a sentence naming the floor. With criteria NOT
    met at `round_no=1` (e.g. a WEAK winner) that reason string is EMPTY — a reader can tell
    "criteria met but floor not reached" from "criteria not met".
  - `degradation_reason` is UNCHANGED in meaning: still empty unless `cap_reached and not
    quality_ok`. The floor sentence does NOT go into it (the loop driver appends
    `degradation_reason` to `loop_reasons` as a D-12 degradation, and a floor hold is not a
    degradation).
  - The hostile battery still never raises: `round_no=None`, non-list winners, string
    `client_questions` — `exit_verdict` returns a dict with bool `should_exit`.
  - **MUTATION PROOF (red-before / green-after, against the real committed source).** Read
    `workshop_loop.py` as text, replace the single line that ANDs the floor into `should_exit` with
    the pre-fix form (criteria only), `exec` the mutated text into a fresh module, and assert the
    round-1 clean case flips to `should_exit is True`. A test that passes on unfixed source proves
    nothing. Record both columns in the summary.
  </behavior>

  <action>
Implement the floor INSIDE `exit_verdict`, per D-W4-9. **One authority.** A floor applied only at
`workshop_rank.py:4583`'s `break` would leave the verdict dict — which the stage feed and the tests
read — reporting `should_exit: true` while the loop kept running. That is a lie in an audited
record, and this project has been burned by two-authorities defects repeatedly (15.6 CR-01,
D-DEF-01's "ONE authority" fix, D-W4-8's `_CANDIDATES_PER_QUESTION_MAX`).

1. `workshop_loop.py` — add `_LOOP_MIN_ROUNDS = _env_int("NESTOR_TRIBUNAL_WORKSHOP_LOOP_MIN_ROUNDS",
   4)` to the constants block at `:106-110`, and document it in the comment block at `:80-105`
   alongside `_LOOP_MAX_ROUNDS`, in that block's existing register. **Name the constant; the literal
   `4` appears in exactly one place.** The rationale to write there (this is the docstring content,
   not decoration): exp11 measured convergence at round 4; a round-1 exit means no COMBINE runs, no
   cross-question synthesis happens, the meta-review's guidance is never used, no INVENT ever
   reaches the evidence gate, and `select_winners` step 2 finds nothing eligible so the two
   cross-cutting slots get filled by ordinary single-parent candidates by rank. State WHY the floor
   is needed at all: criterion 3 (SATURATION) is **vacuously true in round 1** because no candidate
   carries a `born_round` yet — `_stamp_loop_candidates` stamps `born_round = round_no + 1`, so
   round 1's winner set structurally cannot contain a loop-born candidate.

2. `exit_verdict` — add `min_rounds: Optional[int] = None`, mirroring `max_rounds` exactly
   (`_safe_int` coercion, module constant as the default). Compute:
     - `floor = max(1, <coerced min_rounds>)`
     - `effective_floor = min(floor, cap)` — **THE CAP ALWAYS WINS.** Assert this interaction in a
       test (see `<behavior>`): at `round_no == cap` the floor is necessarily satisfied, so the
       loop's `for round_no in range(1, max_rounds + 1)` bound remains the sole termination
       guarantee and the floor can never make the loop unterminable.
     - `floor_ok = current >= effective_floor`
     - keep `criteria_ok = coverage_ok and quality_ok and saturation_ok` as its own named value, so
       "the three criteria" stays readable, then `should_exit = bool(criteria_ok and floor_ok)`.
   Add to the returned dict: `min_rounds` (the effective floor, so the record says what actually
   applied, not what was configured), `floor_ok`, and `hold_reason`. `hold_reason` is non-empty
   **only** when `criteria_ok and not floor_ok`, written in the house style of
   `_reason_cap_with_weak` via a new `_reason_floor_not_reached(round_no, floor)` helper: name both
   numbers as digits, say the criteria were met, say the loop is continuing anyway and why.
   `degradation_reason` keeps its existing composition untouched.

3. `workshop_rank.py` — at `:4197`, alongside the existing `max_rounds` line, read
   `min_rounds = max(1, int(workshop_loop._LOOP_MIN_ROUNDS))` **inside the function** (same idiom,
   same reason: a test monkeypatching the module constant must be picked up at run time). Pass
   `min_rounds=min_rounds` in the `exit_verdict` call at `:4542-4547`. Do **not** add any
   round-number test at the `break` site — the `break` reads `should_exit` and that is the point.
   Add one `log.info` immediately before the `break` block, in the existing logging register, that
   fires when `verdict.get("hold_reason")` is non-empty: the run's record should show that the
   criteria were met in round N and the floor held. Read the fields off the verdict; do not
   recompute anything.

4. `test_workshop_loop.py` — add the `<behavior>` tests in the `exit_verdict` section (`:455`ff).
   **One existing test breaks and must be updated:**
   `test_exemption_a_a_cross_cutting_winner_never_counts_as_weak` (`:527-544`) asserts
   `should_exit is True` at `round_no=3`. Its subject is Exemption A, not the floor — raise its
   `round_no` to `workshop_loop._LOOP_MIN_ROUNDS` (not a hand-typed 4) and note in the docstring why
   the round number moved. Re-read the whole `exit_verdict` section and confirm no OTHER test
   asserts `should_exit is True` below the floor; the ones at `round_no=3` that assert only
   `quality_ok` / `coverage_ok` are unaffected and must not be touched.
   Also **fix the now-wrong docstring at `:860-869`**: `_script`'s docstring says the all-KEEP case
   "correctly exits in round 1 — which proves nothing about the loop." Under the floor it no longer
   does. Rewrite that paragraph to state the current mechanism (the floor guarantees ≥4 rounds; the
   WEAK-for-two-rounds script is still what makes coverage and quality FAIL early, which is a
   different and still-necessary thing to exercise). Add a stage-B-level test driving
   `_run_stage_b` with an all-KEEP script and asserting `result["counts"]["rounds"] >=
   workshop_loop._LOOP_MIN_ROUNDS` — that is the end-to-end arm the verification says is missing.
   Checked and unaffected, do not change: `:1009` (`1 <= r < _LOOP_MAX_ROUNDS`), `:1528`, `:1723`
   (`== _LOOP_MAX_ROUNDS`), `:1844` (`>= 3`), `:2053` (`< _LOOP_MAX_ROUNDS`), and
   `test_workshop_scope_guard.py:1625/1633` (`should_exit is False` at round 1 because
   `quality_ok` is False — still False, for the same reason).

5. `test_engine_e2e_stubbed.py` — its shared stub fixture already pins
   `monkeypatch.setattr(_loop_mod, "_LOOP_MAX_ROUNDS", 2)` at `:1416`. Add
   `monkeypatch.setattr(_loop_mod, "_LOOP_MIN_ROUNDS", 1)` immediately below it, with a comment in
   the file's existing "AN OVERRIDE, NOT THE PRODUCTION VALUE" register explaining precisely why:
   the fake proposes one new question every round, so under the production floor the loop would run
   to its cap and move this file's cost, call-count and model-list assertions **for a reason that is
   a property of THE FAKE** — the file's own docstring at `:864` already names that hazard. Point
   the comment at `test_workshop_loop.py` as the file that owns the floor. Then update the `:864`
   docstring paragraph, which currently asserts the round-1 exit as engine behaviour, to say the
   round-1 exit here is a consequence of the pinned floor.
  </action>

  <verify>
    <automated>
py="C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe"
"$py" -m py_compile tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py \
  tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py \
  tribunal/nestor_pulse_sdk/tests/test_workshop_loop.py \
  tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
# real import + behaviour battery + the mutation column (script to scratchpad, not the repo)
"$py" <scratchpad>/drive_floor.py
# the literal 4 lives in exactly one place
grep -v '^\s*#' tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_loop.py | grep -c '_LOOP_MIN_ROUNDS'
# the break site did NOT grow a second authority
grep -n -A3 'should_exit' tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py | grep -c 'round_no >='
    </automated>
  </verify>

  <done>
`exit_verdict` returns `should_exit: False` on an all-criteria-met round-1 verdict and `True` at
round 4; the cap still wins when it is below the floor; `min_rounds`, `floor_ok` and `hold_reason`
are on the verdict; the mutation column flips the round-1 case to True on pre-fix source text; the
`break` site has no round check of its own; the two now-false docstrings
(`test_workshop_loop.py:860-869`, `test_engine_e2e_stubbed.py:864`) are corrected; the e2e is pinned
to `_LOOP_MIN_ROUNDS = 1` so its arithmetic is unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Remove the inert `max_size` parameter (Ruling 2)</name>
  <files>
tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py
tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
tribunal/nestor_pulse_sdk/tests/test_question_grouping.py
tribunal/nestor_pulse_sdk/tests/test_workshop_scope_guard.py
tribunal/nestor_pulse_sdk/tests/test_research_division_assignment.py
tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
  </files>

  <action>
**RUNS AFTER TASK 1 — it edits `workshop_rank.py`, which Task 1 also edits.** Sequential, never
parallel: this project lost a full plan to two parallel dispatches on one file.

`attach_discovery_riders(groups, riders, *, max_size=None, max_riders=None)` accepts `max_size`,
reads it into `_` at `:1108-1110` and binds nothing since CR-09. Its docstring keeps it only because
"live callers still pass it positionally by keyword, and REMOVING it would be a silent TypeError in
a stage that must never raise." Remove it — **in the safe order, and the order is the whole task.**

1. **Caller first.** `workshop_rank.py:4792-4794` currently passes
   `max_size=question_grouping._D6_MAX_GROUP_SIZE`. Drop the argument entirely and call
   `attach_discovery_riders(groups, riders)`. **Do NOT add an explicit `max_riders=`.** The
   docstring's own derivation (`question_grouping.py:195-213`) is that `_D6_MAX_RIDERS_PER_GROUP`
   equals `discovery_bracket._DISCOVERY_PER_PARENT_CAP`, so a rider is shed only when the discovery
   stage has already over-allocated against its own rule. Re-stating that number at a call site
   would create a second authority for it — the exact defect class this phase keeps paying for.
   State that reasoning in a one-line comment at the call site.

2. **Prove zero remaining callers**, production AND test, before touching the signature:
   `grep -rn "attach_discovery_riders" --include=*.py tribunal/` then `grep -rn "max_size"
   --include=*.py tribunal/`. Update every test call site that passes `max_size=`:
     - `test_question_grouping.py` — `:390, :672, :689, :712, :728, :771, :802, :816, :836, :884,
       :1077, :1079`
     - `test_workshop_scope_guard.py` — `:769, :1056, :1093, :1110`
     - `test_research_division_assignment.py` — `:1009, :1048, :1092`
   Delete only the `max_size=` argument; leave any `max_riders=` on those calls alone (`:771` and
   `:1093` pass both). Several of those tests carry docstrings that reason about `max_size` no
   longer binding (`test_question_grouping.py:378-381, :740, :755`) — rewrite them to say the
   parameter is GONE, not merely inert.
   **`clamp_groups(..., max_size=...)` IS A DIFFERENT FUNCTION with a real binding parameter
   (`question_grouping.py:764`, `:799`). Every `max_size=` in `test_question_grouping.py` at
   `:260, :276, :487, :501, :514, :547, :565, :589, :595, :608, :620, :902`, plus
   `question_grouping.py:1592` and the comment at `:179`, belongs to it and MUST NOT BE TOUCHED.**
   Sort call sites by which function they target before editing anything.

3. **Then the signature.** Remove `max_size` from `attach_discovery_riders`, delete the `_ =
   max_size` line and its comment at `:1108-1110`, and rewrite the docstring paragraph at
   `:1085-1091` so it no longer documents a parameter that does not exist. Keep the paragraph's
   surviving point — that a total-size number must never be re-purposed as a rider budget, because
   that restated-premise mistake is what produced CR-09 — and record that the parameter was removed
   by operator ruling on 2026-08-04 rather than silently dropped, so a future reader does not
   "restore" it.

4. Update the two comment blocks in `test_engine_e2e_stubbed.py` that describe the old state:
   `:1438-1445` ("Production passes only `max_size`, so the effective budget is always
   `_D6_MAX_RIDERS_PER_GROUP`") and `:2840-2843` ("`max_size` is now accepted, discarded, and
   non-binding"). Production now passes NEITHER, and the effective budget is the default. The
   steering advice — a test that wants a shed must lower `_D6_MAX_RIDERS_PER_GROUP` — is unchanged
   and still correct.

**If you cannot prove zero remaining callers, DO NOT remove the parameter.** Leave it in place,
finish everything else, and say so loudly and specifically in the summary. `attach_discovery_riders`
runs inside a stage that must never raise, and a missed caller is a `TypeError` in production.
  </action>

  <verify>
    <automated>
py="C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe"
"$py" -m py_compile tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py \
  tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py \
  tribunal/nestor_pulse_sdk/tests/test_question_grouping.py \
  tribunal/nestor_pulse_sdk/tests/test_workshop_scope_guard.py \
  tribunal/nestor_pulse_sdk/tests/test_research_division_assignment.py \
  tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
# ZERO callers of attach_discovery_riders pass max_size, anywhere.
"$py" <scratchpad>/no_max_size_caller.py   # ast: walk every Call whose func attr/name is
                                           # attach_discovery_riders; assert no keyword 'max_size'
# the parameter is gone from the signature, and clamp_groups' is untouched
grep -n "def attach_discovery_riders" -A2 tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py
grep -c "max_size" tribunal/nestor_pulse_sdk/pipeline/tribunal/question_grouping.py   # clamp_groups only
    </automated>
  </verify>

  <done>
An AST walk over all of `tribunal/**/*.py` finds zero `attach_discovery_riders` calls with a
`max_size` keyword; the parameter is absent from the signature and the `_ = max_size` line is gone;
the docstring no longer documents it; the caller passes neither `max_size` nor `max_riders`;
`clamp_groups`' own `max_size` is untouched at all 14 of its sites. If instead the parameter was
kept, the summary says so in its first paragraph with the caller that blocked removal.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Persist `workshop_notes` (Ruling 3) + the two ruling documents</name>
  <files>
tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-CONTEXT.md
.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-VERIFICATION.md
  </files>

  <behavior>
  - A run whose workshop produces N notes (N > 4) emits N run events — the persisted record is
    COMPLETE, not capped. Assert against the emitted rows, not the log.
  - Every emitted event carries a `kind` that is a member of `run_events.RUN_EVENT_KINDS`. Assert
    membership against the tuple, not against a hand-typed string — an out-of-vocabulary kind is
    DROPPED at `emit` (`run_events.py:332`), which would reproduce the very defect being fixed while
    every test read green.
  - A note that is not a string, and a `workshop_notes` value that is not a list, cost the event and
    never the run: the pipeline still completes.
  </behavior>

  <action>
**RUNS AFTER TASK 2.** Part A is code; part B is the ruling record.

**A — persist the notes.** `pipeline.py:1989` is
`for note in (workshop_result.get("workshop_notes") or [])[:4]: log.info(...)`. That is the same
inert-logging class as V-01, whose stage logging made the runbook's own diagnosis instruction
unfollowable. `workshop_rank.py:4885-4895` folds `loop_notes + disc_notes + group_notes +
rider_notes + cov_notes` into that list in that order, and `loop_notes` alone contributes up to 10
per-round drop summaries — so `rider_notes` and `cov_notes` are **structurally unreachable** behind
the `[:4]` slice. The operator's only record that a discovered question was dropped is invisible in
the run's artifacts.

Emit each note through `run_events.emit_safe`, at the same site, keeping the module-qualified form
(`run_events.emit_safe(...)`) — `pipeline.py:440-453` explains that the D-06 call-site gate counts
bare `emit(` calls and requires zero.

Decisions, made here and to be restated in the code comment:
  - **`stage="workshop"`** — a real `ENGINE_STAGES["tribunal"]` key (`runs/stages.py:46`, label
    "Question workshop"), so `_stage_event_label` renders it. Not the currently-open stage name;
    `emit_safe`'s `stage` is a label on the event, not a transition.
  - **`kind="plan"`** — `RUN_EVENT_KINDS` is a CLOSED twelve-value vocabulary and a kind outside it
    is dropped at `emit`, so a new kind is not an option without a matching frontend change. `plan`
    ("branch — routing / planning") is the vocabulary's decision/routing line and is what a workshop
    note is: a record of what the question workshop dropped, shed or repaired. **State in the
    comment that the render target is `docs/design/prototypes/ResearchRunImproved.tsx` — a design
    prototype, not a shipped component.** The shipped `frontend/src/components/intake/
    ResearchRunProgress.tsx` renders the STAGE FEED (`kind: "item" | "summary"`), a different
    surface; the run-event stream is fetched by `frontend/src/lib/api/research.ts` against the
    backend proxy (`backend/app/api/research_routes.py`) and typed with `kind` as a plain `string`
    precisely so an unrendered kind still produces a line. So the events ARE persisted and
    retrievable; do not claim a specific rendering.
  - **The `[:4]` cap does NOT survive on the persisted record.** The operator said persist, and a
    cap that silently drops notes reproduces the defect being fixed. Persist every note. Keep the
    existing `log.info` at `[:4]` — persisting does not require removing the log — but the log must
    no longer be silently lossy: after the loop, when there are more than 4, log one line naming the
    total and stating that all of them were persisted as run events. A truncation that is itself
    recorded is honest; a silent one is the V-01 defect.

Build the text INSIDE the thunk — **read `emit_safe`'s docstring first**: a caller's arguments are
evaluated before the callee is entered, so an f-string at the call site is outside the protection.
Bind the loop variable through a default argument (`build=lambda n=note: (...)`) so the thunk cannot
capture a later iteration's value, and coerce the note to `str` inside the thunk, not outside. Pass
`meta=None` — `_META_FIELDS` is an allowlist and there is no honest field for a note; the text is
the record. `emit` already bounds text at `MAX_TEXT_CHARS = 400` with a visible `…`.

Add the `<behavior>` assertions to `test_engine_e2e_stubbed.py` — it already drives the pipeline end
to end with stubs and already collects run events. Find its existing run-event capture rather than
building a second one.

**B — the ruling record.** Two files, both under `.planning/` which is **gitignored — every planning
file must be `git add -f`.**

`15.7-CONTEXT.md`: append **D-W4-9, D-W4-10, D-W4-11** to the `## Implementation Decisions` block
(the series runs D-W4-1…8 today; D-W4-9 is the next free number — verify before writing). **Match
the house style exactly**: `### D-W4-N — <one-line ruling>`, opening with **`**Operator decision,
2026-08-04**, closing human_verification item N of `15.7-VERIFICATION.md`**, then what was ruled,
WHY it was ruled that way, and what it changes in code. Use the existing entries' devices where they
apply: a `>` blockquote for a warning a future reader could get wrong, and code-grounded file:line
facts rather than paraphrase.
  - **D-W4-9** — the minimum-round floor. Include: criterion 3 is vacuously true in round 1 because
    `born_round` is stamped `round_no + 1`; the floor lives inside `exit_verdict` so `should_exit`
    and the `break` cannot disagree; the cap always wins so termination is unchanged; what a
    round-1 exit costs (no COMBINE, no cross-question synthesis, no INVENT through the evidence
    gate, the 2 cross-cutting slots filled by rank). Note the reconciliation the verification asked
    for: exp11's "clean from round 1" and "exits round 4" are now BOTH consistent — the floor is
    what makes them so.
  - **D-W4-10** — `max_size` removed, in the safe order, caller first, zero-callers proved by AST.
    Say explicitly that `clamp_groups`' `max_size` is a different, legitimate parameter, so nobody
    "finishes the job" later.
  - **D-W4-11** — `workshop_notes` persisted as `stage="workshop"`, `kind="plan"` run events, the
    persisted record complete, the log cap kept but its truncation now recorded.

`15.7-VERIFICATION.md`: mark the three closed items resolved — gap 1 in the `gaps:` frontmatter
block, and human_verification items 4 and 5 — each naming the ruling (D-W4-9/10/11) and the commit
that closed it. **Do not fabricate a new overall status.** The BLOCKER closing IS a real status
change, so state precisely what is now closed and what still stands:
  - the D7 `langs` ordering gap (gap 2 — `_normalise_langs` sweeps before `enforce_group_coverage`)
  - `DROP_CLUSTERED_ONTO_LIVE`, defined with no production writer (gap 3)
  - `barred_block`'s oldest-24 slice (gap 4)
  - human_verification item 2, `catch_up_matches` counting newcomers in its own median — **NOT
    ruled**
  - human_verification item 3, `actions` semantics including `admission_resolver_calls` — **NOT
    ruled**
Keep the report body's analysis intact; superseded text stays visible and marked, as this phase's
documents do throughout.
  </action>

  <verify>
    <automated>
py="C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe"
"$py" -m py_compile tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py \
  tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
# the note text is built INSIDE the thunk, never at the call site
"$py" <scratchpad>/thunk_check.py   # ast: the emit_safe call's `build` arg is a Lambda and no
                                    # JoinedStr/BinOp appears among the call's other arguments
# the chosen kind is in the closed vocabulary
grep -n "RUN_EVENT_KINDS" tribunal/nestor_pulse_sdk/runs/run_events.py
grep -n 'kind="plan"' tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
# the D-06 gate stays green: zero bare emit( calls
grep -c "run_events.emit_safe" tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
# the ledger grew by exactly three entries and the numbers are free
grep -n "^### D-W4-" .planning/phases/15.7-*/15.7-CONTEXT.md
git add -f .planning/phases/15.7-*/15.7-CONTEXT.md .planning/phases/15.7-*/15.7-VERIFICATION.md
    </automated>
  </verify>

  <done>
Every `workshop_note` is emitted as a `stage="workshop"`, `kind="plan"` run event with its text
built inside the `build=` thunk; the persisted record is complete while the `log.info` cap survives
with its truncation recorded; `D-W4-9/10/11` are appended to `15.7-CONTEXT.md` in house style dated
2026-08-04; `15.7-VERIFICATION.md` marks gap 1 and human_verification items 4 and 5 resolved with
their rulings and commit, and names the four items that still stand plus the two human_verification
items the operator did not rule on. Both planning files are `git add -f`'d.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| model output → `workshop_notes` → `run_events` → DB → operator UI | Note text is partly model-authored and partly engine-authored; it now reaches a persisted, operator-rendered surface it did not reach before |
| env → `_LOOP_MIN_ROUNDS` | An operator-set env var now influences how many paid LLM rounds a run performs |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-DBD-01 | Tampering | `workshop_notes` → `run_events.emit` | mitigate | Text is scrubbed (`scrub_pii`) and bounded at `MAX_TEXT_CHARS = 400` by `emit` itself; `meta=None` so nothing crosses the `_META_FIELDS` allowlist. No new sanitiser is written — one authority, the existing emitter. |
| T-DBD-02 | Denial of Service | note volume → the run-event queue | accept | `_MAX_QUEUE = 5000` per run and the buffer's `deque(maxlen=...)` already bound it; realistic note counts are under 40 (≤10 loop + disc + group + rider + cov). |
| T-DBD-03 | Denial of Service | `_LOOP_MIN_ROUNDS` set absurdly high | mitigate | `effective_floor = min(floor, cap)` and the driver's `range(1, max_rounds + 1)` mean the round cap is the sole termination bound; asserted by a test. |
| T-DBD-04 | Information disclosure | a workshop note reaching a client-visible surface | accept | The run-event stream is a superadmin research surface behind the space-scoped backend proxy (`backend/app/api/research_routes.py`); notes contain the client's own question text, not third-party data. |
| T-DBD-05 | Tampering | npm/pip/cargo installs | n/a | **This plan installs no packages.** No `Package Legitimacy Audit` is required. |
</threat_model>

<verification>
- Every edited file passes `py_compile` on the bundled interpreter.
- The static undefined-global check is CLEAN on `workshop_loop.py`, `workshop_rank.py`,
  `question_grouping.py` and `pipeline.py`, and is shown to be NON-VACUOUS by reporting what it
  flags on a deliberately broken copy.
- The round-floor mutation column is recorded with both readings (pre-fix source text → round-1
  clean case exits; fixed source → it does not).
- `git grep -n "max_size" tribunal/` returns only `clamp_groups` sites.
- **The pytest gate is OWED, not paid.** State in the summary: this change must be re-gated in
  15.8's Cloud Build via `tribunal/cloudbuild.test-engine.yaml` against baseline `7c89be5c` =
  1538 passed / 0 failed / 13 skipped, `collecting: 36 of 36`. No new test FILE is added, so
  `EXPECTED_FILES` stays 36; the passed count must RISE by the number of new test functions, and a
  count that does not rise must be EXPLAINED, not merely noted. Read the build's text via
  `gcloud builds describe` — `gcloud builds submit | tail` returns the PIPE's exit code, so a
  FAILED build reports exit 0.
</verification>

<success_criteria>
- The workshop loop cannot exit before round 4 (or the cap, whichever is lower), and the verdict
  dict says so in a field a reader can distinguish from "criteria not met".
- `should_exit` remains the only authority the `break` site consults.
- `attach_discovery_riders` has no `max_size` parameter and no caller passes one — or the parameter
  survives and the summary says why in its first paragraph.
- Every `workshop_note` reaches a persisted run event.
- `15.7-CONTEXT.md` carries D-W4-9/10/11 in house style; `15.7-VERIFICATION.md` records exactly what
  closed and exactly what still stands.
</success_criteria>

<output>
Create `.planning/quick/260804-dbd-close-three-15-7-verification-gaps-round/260804-dbd-SUMMARY.md`
when done. It must state plainly: the pytest gate was NOT run on this machine and is owed at 15.8,
and the mutation-proof columns for the round floor.
</output>
