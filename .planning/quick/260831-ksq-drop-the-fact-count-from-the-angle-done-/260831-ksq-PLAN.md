---
phase: quick-260831-ksq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py
  - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
autonomous: true
requirements: [QUICK-260831-ksq]

must_haves:
  truths:
    - "The live-feed `agent_done` row for a research angle reads `Angle NN done · {provider}` — completion and provider only, no fact count and no `an unknown number of facts` clause."
    - "A degrading provider result (no `facts`, `facts: None`, `facts: 7`, `facts: \"none found\"`) still records EXACTLY ONE `agent_done` row — the D-V01-7 lost-row guarantee survives the removal of the helper that used to carry it."
    - "The `agent_done` row's `meta` dict is unchanged: `angle`, `provider`, `cost`, `audit_id`."
    - "The D-06 site proof still BITES: forcing the row's text builder to raise degrades the row and leaves the paid angle intact, and the assertion goes RED if the construction is hoisted out of `emit_safe`'s thunk."
    - "Both `agent_fail` emissions still carry `· 0 facts ·` — a failed angle really did establish zero."
  artifacts:
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py"
      provides: "`_agent_done_text` (the named, monkeypatchable row-text builder) replacing `_fact_count_label`/`_UNKNOWN_FACTS`; the count-free `agent_done` emission"
      contains: "_agent_done_text"
    - path: "tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py"
      provides: "the inverted contract (done line carries NO count) plus the re-pointed D-06 site proof"
      contains: "_agent_done_text"
  key_links:
    - from: "research_division._record_result"
      to: "research_division._agent_done_text"
      via: "called INSIDE the `build=lambda:` thunk"
      pattern: "build=lambda:"
    - from: "test_run_event_emit.test_j_the_done_line_is_still_built_inside_the_emitters_try"
      to: "research_division._agent_done_text"
      via: "monkeypatch.setattr forcing a RuntimeError"
      pattern: "monkeypatch\\.setattr\\(rd, \"_agent_done_text\""
---

<objective>
Drop the fact-count clause from the research-angle `agent_done` feed row, so the operator's
row reads `Angle 03 done · claude` instead of
`Angle 03 done — an unknown number of facts · claude`.

Purpose: the clause is near-useless in practice. `_fact_count_label` prints a real number only
when the provider result carries a countable `facts` list, and three of the four streams
(`gemini`, `openai`, `claude`) return a `{status, report}` prose envelope that never has one. The
overwhelming majority of rows therefore read "an unknown number of facts", which is noise. The
operator was told the `own` stream loses a real number and asked for the removal anyway.

Output: a count-free done line, the D-V01-7 lost-row guarantee preserved, and the D-06 site proof
re-pointed at a lever that still exists and still bites.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@CLAUDE.md

Source of truth for this change:
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py` — `_UNKNOWN_FACTS` (:1961),
  `_fact_count_label` (:1964-2002), the `agent_done` emission in `_record_result` (:2130-2163).
- `tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py` — module header (:48-60),
  `test_a_result_missing_the_keys_the_done_line_reads_still_records_its_line` (:793-910),
  `test_j_a_healthy_angle_still_renders_its_fact_count` (:1008-1028),
  `test_j_a_degraded_result_still_records_exactly_one_done_line` (:1031-1074),
  `test_j_the_done_line_is_still_built_inside_the_emitters_try` (:1077-1115).

## THE D-06 DECISION — TAKEN AT PLANNING TIME, DO NOT RE-LITIGATE

`test_j_the_done_line_is_still_built_inside_the_emitters_try` proves **D-06** by
`monkeypatch.setattr(rd, "_fact_count_label", _boom)`. This edit is exactly the "future edit to
the helper" that test's own docstring anticipates. The guarantee is not decorative: hoisting
`build()` above `emit_safe`'s `try` is the "cleanup" that lost about twenty `agent_done` rows on
run `7dcf51d5` (D-V01-7).

**CHOSEN: option (b) — delete the helper AND re-point the lever.**

`_fact_count_label` and `_UNKNOWN_FACTS` are deleted. A new named module-level builder takes the
lever's place and has a REAL production caller inside the same thunk:

    def _agent_done_text(angle_no: int, provider: str) -> str

**Why NOT option (a) (keep `_fact_count_label` uncalled as the lever):** it is not merely
untidy, it is *impossible*. Monkeypatching a function production no longer calls proves nothing —
the thunk would not raise, the row would emit normally, and the D-06 test would go RED against
correct code. A red test on correct code invites deletion of the assertion, which is precisely how
the proof gets lost.

**Why NOT the `.get`-raising `result` lever suggested in the brief:** verified unreachable.
`_record_result` is handed `_enriched`, built at `research_division.py:2494` as
`{**result, "_angle": ..., ...}` — dict-unpacking a mapping does not route through `.get`, so
`_enriched` is a PLAIN dict and its `.get` cannot raise. And `result.get("status")` at `:2488` runs
BEFORE the emit and outside any `try`, so a raising `.get` would kill the paid angle rather than
degrade the row — the test's own `assert len(results) == 1` premise would collapse.

## SCOPE — DO NOT WIDEN

`_fact_count_label` has exactly ONE production consumer (verified: the other hits are its own
definition, docstring and the comments at :2136/:2146).

**Leave alone, all verified as out of scope at planning time:**
- The two `agent_fail` emissions carrying a hardcoded `· 0 facts ·` (`:2482` and `:2566`) — the
  angle FAILED, zero is literally true, and neither is what the operator pasted.
- The checkpoint-restore line (`:2237`), the not-researched line (`:2283`), the retry line
  (`:2626`).
- The whole `own_researcher.py` half — `Own query done — N facts from N pages · N skipped`
  (`own_researcher.py:817`) is a DIFFERENT line with its own self-contained `_skipped_label` /
  `_raw_fact_count`. It shares no symbol with `_fact_count_label`. Its tests
  (`test_own_researcher.py:1096`, `:1226`; `test_run_event_emit.py:1163`, `:1208`) stay green
  untouched.

A repo-wide grep at planning time found `_fact_count_label` / `_UNKNOWN_FACTS` in exactly two
files — `research_division.py` and `test_run_event_emit.py`. There is no third consumer.

## ⛔ GREP HYGIENE — MANDATORY

Every grep gate in this plan is **path-scoped to `tribunal/`** and uses `-I --exclude-dir=__pycache__`.
A repo-root `grep -rn` also matches `.claude/worktrees/agent-af281d695d9b34c35/` — an orphaned
stale tree (NOT a registered worktree) holding a full copy of `tribunal/` — plus `.pyc` binary
hits. Both make a correct edit read as incomplete. **Do not edit or delete that orphaned tree.**

Prefer presence/absence criteria over `grep -c`. Count criteria have repeatedly been wrong here.

## VERIFICATION INTERPRETER

The tribunal suite RUNS on this machine (`tribunal/pyproject.toml` requires `>=3.11`; local
interpreters are 3.11.9). The `>=3.12` floor that blocks local testing belongs to `backend/`, a
DIFFERENT package — do not repeat that confusion.

Use the ready venv, which has `openai` installed (without it the OpenAI-dependent tests SKIP):

    PY="C:/Users/ajimimo/AppData/Local/Temp/claude/C--Users-ajimimo-Desktop-MOELD-nestor-intake-gcp/e0330556-a606-41a2-8dc9-b324db25ce5a/scratchpad/venv-jx2/Scripts/python.exe"

Run from `tribunal/`. Report REAL pass/fail/skip numbers, aiming for **0 skipped** on the scoped
files.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Invert the tests to the new contract and prove them RED against unedited source</name>
  <files>tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py</files>
  <behavior>
    After this task the test file asserts the NEW contract, and the production source is still
    UNTOUCHED, so the changed assertions must be observably RED. A test written after the fix that
    was never red proves nothing.

    - `test_j_a_healthy_angle_still_renders_its_fact_count` → RENAME to
      `test_j_a_healthy_angle_renders_no_fact_count` and invert. The name currently asserts the
      opposite of the new contract and cannot be left as-is. Assert the exact text
      `"Angle 01 done · openai"` for a result carrying `facts: [1, 2, 3]` — i.e. a countABLE result
      still gets no count. Keep the `meta` assertions (`angle`, `provider`, `cost == 1.5`)
      unchanged; they are the operator's explicit carve-out. Delete the now-false
      `.endswith("facts · openai")` assertion.
    - `test_j_a_degraded_result_still_records_exactly_one_done_line` → KEEP all four shapes and
      KEEP the `len(done) == 1` assertion verbatim: that is the D-V01-7 lost-row guarantee and it
      is the reason this test exists. Replace the wording assertions — `rd._UNKNOWN_FACTS in text`
      (:1063) is gone, so assert instead that the text is exactly `"Angle 01 done · openai"` for
      every shape, that `re.search(r"\d+\s+facts", text)` finds nothing, that `"facts"` does not
      appear at all, and keep the `meta` attributability assertions. Update the docstring: the
      `str` case is still not padding, but the reason changes from "len would print 10 facts" to
      "these are the shapes a degrading provider really returns, and none of them may cost the row".
    - `test_a_result_missing_the_keys_the_done_line_reads_still_records_its_line` → keep the
      `pytest.raises(KeyError)` / `pytest.raises(TypeError)` negative control (it documents what the
      ORIGINAL subscript form did and is still true), but delete the two `rd._fact_count_label(...)
      == rd._UNKNOWN_FACTS` assertions at :833-837 — that helper no longer exists. Keep the
      six-row `len(done) == 6` assertion and the no-swallowed-build assertion verbatim. Replace the
      `sum("2 facts" in text ...) == 2` (:899) and the `degraded_texts ... len == 4` (:902-905)
      block with the new contract: ALL six texts carry no count in any form. Reconcile the
      docstring (:799-811).
    - `test_j_the_done_line_is_still_built_inside_the_emitters_try` → re-point the lever from
      `rd._fact_count_label` to `rd._agent_done_text` (signature `(angle_no, provider)`, so `_boom`
      takes two positional args). Everything else in the test is unchanged and must stay: the
      RuntimeError-in-the-emitter-log assertion, the `recorder.of("agent_done") == []` assertion,
      and `assert len(results) == 1`. Rewrite the docstring to name `_agent_done_text` and to state
      that a helper with one production caller is what keeps this proof non-vacuous.
    - Module header (:48-60) — reconcile the 15.4-05 narrative to the new contract. `emit_safe` is
      still not modified; what changed is that the done line no longer renders a count at all, so
      the honest-unknown wording has no remaining site here. Say so; do not delete the D-V01-7
      history.
  </behavior>
  <action>
Edit ONLY the test file in this task. Do not touch `research_division.py` yet — the whole point is
to observe RED against the unedited source.

Work through the five regions named in `<behavior>` above. Do NOT simply delete a test that was
asserting real behaviour; where the behaviour is genuinely gone, INVERT it into a guard for the new
contract (the pattern used for quick task 260831-jx2 in this repo).

Then run the scoped suite from `tribunal/` and CAPTURE THE OUTPUT VERBATIM:

    "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py -q

Expected RED, and record the actual node ids and counts rather than these predictions:
  - `test_j_a_healthy_angle_renders_no_fact_count` — AssertionError, actual text
    `'Angle 01 done — 3 facts · openai'`.
  - `test_j_a_degraded_result_still_records_exactly_one_done_line` — 4 parametrised failures,
    actual text carries `an unknown number of facts`.
  - `test_a_result_missing_the_keys_...` — AssertionError on the no-count assertions.
  - `test_j_the_done_line_is_still_built_inside_the_emitters_try` — **AttributeError** from
    `monkeypatch.setattr(rd, "_agent_done_text", _boom)`, because the lever does not exist yet.
    Record this HONESTLY as "the lever is absent", NOT as a proof of the D-06 contract — that proof
    is owed in Task 3 and is a different assertion.

If any of the four changed regions comes up GREEN against unedited source, that region is not
asserting the new contract — fix the assertion, do not proceed.

Commit the test-only edit with the red output quoted in the message:
`test(260831-ksq): invert the done-line tests to the count-free contract (RED)`
  </action>
  <verify>
    <automated>cd tribunal &amp;&amp; "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py -q ; echo "EXIT=$? (non-zero is REQUIRED at this task)"</automated>
    <automated>cd tribunal &amp;&amp; grep -n -I --exclude-dir=__pycache__ -e '_agent_done_text' -e 'test_j_a_healthy_angle_renders_no_fact_count' nestor_pulse_sdk/tests/test_run_event_emit.py</automated>
    <automated>cd tribunal &amp;&amp; git diff --name-only HEAD~1 HEAD</automated>
  </verify>
  <done>
The test file asserts the count-free contract; the four changed regions are observably RED against
unedited production source with the failure output recorded verbatim; `git diff --name-only`
for the commit lists ONLY `test_run_event_emit.py`.
  </done>
</task>

<task type="auto">
  <name>Task 2: Drop the count from the emission, replace the helper with `_agent_done_text`</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py</files>
  <action>
Two edits in `research_division.py`.

**(1) Replace `_UNKNOWN_FACTS` (:1961) and `_fact_count_label` (:1964-2002)** with the new row-text
builder in the same position:

    def _agent_done_text(angle_no: int, provider: str) -> str

returning `f"Angle {angle_no:02d} done · {provider}"`.

Its docstring MUST state, in prose, both of the following, because a future reader will otherwise
inline this one-line function and silently delete a proof:

  - WHY THE COUNT IS GONE (260831-ksq, operator ruling): `_fact_count_label` rendered a real number
    only when the provider result carried a countable `facts` list, and three of the four streams
    (`gemini`, `openai`, `claude`) return a `{status, report}` prose envelope that never has one —
    so the clause read "an unknown number of facts" on the overwhelming majority of rows. The
    operator was told the `own` stream loses a real number and asked for the removal anyway. The
    honest-unknown rule (T-15.3-23 — never print a `0` the run did not measure) is not weakened;
    it simply has no remaining site here, because no number is claimed at all.
  - WHY IT IS A NAMED FUNCTION AND NOT AN INLINE F-STRING: it is the monkeypatchable lever
    `test_j_the_done_line_is_still_built_inside_the_emitters_try` forces to raise, which is the
    only way to keep proving D-06 AT THIS SITE now that the site no longer raises on its own.
    Inlining it does not "simplify" the emission — it deletes the proof that the row is built
    inside `emit_safe`'s `try`, and hoisting `build()` out of that `try` is exactly what lost about
    twenty `agent_done` rows on run `7dcf51d5` (D-V01-7). Do not inline.

Carry forward the surviving half of the old docstring's reasoning — that the fix belongs at the
call site and NOT in `run_events.emit_safe`, and that a helper called from inside a feed-line thunk
must never raise in production.

**(2) The `agent_done` emission at :2149-2163.** Change the two f-string lines

    f"Angle {i + 1:02d} done — "
    f"{_fact_count_label(result)} · {provider}",

to a single `_agent_done_text(i + 1, provider),`.

  - **KEEP `build=lambda:` a thunk.** This is structural, not stylistic — everything in the row
    must be built inside `emit_safe`'s `try`.
  - **KEEP the `meta` dict byte-identical**: `angle`, `provider`, `cost` (`result.get("cost_usd")`),
    `audit_id` (`result.get("audit_id")`). The operator asked about the visible text, not the
    recorded metadata.
  - Reconcile the comment block at :2132-2148: the `_fact_count_label` references at :2136 and
    :2146 are now stale. The `15.3-03` paragraph about emitting BEFORE the early return stays. The
    D-V01-7 paragraph stays — reworded so it explains why the thunk survives rather than why the
    tolerant helper does. The sentence "The thunk stays a thunk regardless" is the load-bearing
    one; keep its force and re-point it at `_agent_done_text`.

**Touch nothing else in this file.** Specifically: the `agent_fail` emissions at :2476-2485 and
:2559-2569 keep their hardcoded `· 0 facts ·` (a FAILED angle really did establish zero), and the
checkpoint-restore (:2237), not-researched (:2283) and retry (:2626) lines are untouched.

Then run the scoped suite from `tribunal/`:

    "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py -q

Report REAL pass/fail/skip. Target: 0 failed, **0 skipped**. Investigate any skip rather than
accepting it — the venv has `openai` installed precisely so nothing skips here.

Commit: `fix(260831-ksq): drop the fact count from the angle-done run feed line`
  </action>
  <verify>
    <automated>cd tribunal &amp;&amp; "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py -q</automated>
    <automated>cd tribunal &amp;&amp; grep -rn -I --exclude-dir=__pycache__ -e '_fact_count_label' -e '_UNKNOWN_FACTS' nestor_pulse_sdk/ ; echo "ABSENCE REQUIRED — any line above is a leftover"</automated>
    <automated>cd tribunal &amp;&amp; grep -n -I -e '_agent_done_text' -e 'build=lambda' -e '0 facts' nestor_pulse_sdk/pipeline/tribunal/research_division.py</automated>
  </verify>
  <done>
`test_run_event_emit.py` is fully GREEN with 0 failed and 0 skipped (real numbers reported).
`_fact_count_label` and `_UNKNOWN_FACTS` appear NOWHERE under `tribunal/nestor_pulse_sdk/`.
`_agent_done_text` appears in `research_division.py` at both its definition and its call site, the
call site is still inside `build=lambda:`, and BOTH `agent_fail` lines still show `0 facts` in the
third grep.
  </done>
</task>

<task type="auto">
  <name>Task 3: Prove the D-06 assertion still BITES, then close the scope</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py</files>
  <action>
**(1) THE MUTATION PROOF — the deliverable of this task.** A test that can no longer fail is worse
than a deleted one, because it reads as coverage. Green is not proof; RED-on-break is.

Task 2's commit must already be in place (so the mutation can be reverted with
`git checkout --` without losing the fix). Confirm `git status` is clean first.

Temporarily break the D-06 guarantee in `_record_result` — hoist the row construction OUT of the
thunk, which is the exact "cleanup" D-06 exists to catch:

    _row = (_agent_done_text(i + 1, provider), { ...the same meta dict... })
    run_events.emit_safe(run_id, stage="deep_research", kind="agent_done", build=lambda: _row)

Then run ONLY the D-06 test:

    "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py::test_j_the_done_line_is_still_built_inside_the_emitters_try -q

It MUST FAIL — with `_agent_done_text` monkeypatched to raise, the eager construction raises inside
`_record_result`, OUTSIDE `emit_safe`'s `try`, and escapes into `run_angles`. Record the actual
failure output verbatim. **If it PASSES, the assertion is vacuous and the task is not done** — the
lever is not reached, and it must be re-pointed at something that is, before proceeding.

Revert precisely and re-prove green:

    git checkout -- nestor_pulse_sdk/pipeline/tribunal/research_division.py
    git status --short          # must show NO modified files
    "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py -q

**(2) NEIGHBOUR REGRESSION.** The own-research half shares this test file's harness. Run:

    "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py nestor_pulse_sdk/tests/test_own_researcher.py nestor_pulse_sdk/tests/test_run_events.py -q

Report real pass/fail/skip. `Own query done — N facts from N pages · N skipped` is a DIFFERENT line
and must be UNCHANGED — `test_own_researcher.py:1096` and `:1226` assert its exact text and must
stay green without edits.

**(3) SCOPE CLOSURE — confirm, do not assume.**
  - Re-grep for stragglers, path-scoped:
    `grep -rn -I --exclude-dir=__pycache__ -e 'unknown number of facts' -e '_fact_count_label' tribunal/nestor_pulse_sdk/`
    → must return nothing.
  - Confirm the cloudbuild position by READING, not assuming: `test_run_event_emit.py` is already
    registered at `tribunal/cloudbuild.test-engine.yaml:514`, and `EXPECTED_FILES=45` sits at
    `:535`. This change edits two EXISTING files, adds no file and renames none, so **neither the
    file count nor the config changes**. State the two line numbers and the value 45 in the summary
    as confirmation. Do NOT edit either cloudbuild YAML.
  - Note the pass-count movement: no test FUNCTION is added or removed by this plan (four are
    modified in place, one is renamed), so the engine gate's passed count should be FLAT. If the
    executor's edits did change the function count, say so explicitly with the delta.

**(4) NO DEPLOY.** This ships with the next `tribunal-worker` / `tribunal-api` build, together with
the already-committed-and-unbuilt `260831-jx2` change. Do not build, do not deploy, do not trigger
a run.

Commit any summary/doc artefact with:
`docs(260831-ksq): record the D-06 mutation proof and scope closure`
  </action>
  <verify>
    <automated>cd tribunal &amp;&amp; git status --short ; echo "CLEAN TREE REQUIRED — the mutation must be reverted"</automated>
    <automated>cd tribunal &amp;&amp; "$PY" -m pytest nestor_pulse_sdk/tests/test_run_event_emit.py nestor_pulse_sdk/tests/test_own_researcher.py nestor_pulse_sdk/tests/test_run_events.py -q</automated>
    <automated>cd tribunal &amp;&amp; grep -rn -I --exclude-dir=__pycache__ -e 'unknown number of facts' -e '_fact_count_label' nestor_pulse_sdk/ ; echo "ABSENCE REQUIRED"</automated>
    <automated>cd tribunal &amp;&amp; grep -n -I -e 'test_run_event_emit.py' -e 'EXPECTED_FILES=' cloudbuild.test-engine.yaml</automated>
  </verify>
  <done>
The D-06 test was observed RED under the hoisted-construction mutation (failure output recorded
verbatim), the mutation is reverted, `git status --short` is empty, and all three test files are
green with real pass/fail/skip numbers reported. `unknown number of facts` and `_fact_count_label`
are absent from `tribunal/nestor_pulse_sdk/`. The cloudbuild registration (`:514`) and
`EXPECTED_FILES=45` (`:535`) are confirmed unchanged and unedited. No build, no deploy, no run.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| provider response → run-feed row text | Provider-controlled data reaching an operator-visible string |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ksq-01 | Information disclosure / spoofing | `_agent_done_text` | mitigate | The new text is built from `angle_no` (an `int` loop index) and `provider` (an internal stream name from `_PROVIDER_RUNNERS`). Removing `_fact_count_label` REMOVES the last provider-controlled term from this row, strictly narrowing the surface — no provider string reaches the line at all. |
| T-ksq-02 | Denial of service (lost feed row) | `_record_result` thunk | mitigate | `build=lambda:` preserved so the row is built inside `emit_safe`'s `try`; enforced by the re-pointed D-06 test AND by the Task 3 mutation proof that the test goes RED when the construction is hoisted. |
| T-ksq-03 | Repudiation (audit/meta integrity) | `agent_done` `meta` dict | accept | `meta` (`angle`, `provider`, `cost`, `audit_id`) is byte-identical after this change — the operator asked about visible text only, so nothing recorded is lost. |
| T-ksq-SC | Tampering | package installs | N/A | This plan installs nothing. No `npm`/`pip`/`cargo` install task exists; no legitimacy gate applies. |
</threat_model>

<verification>
1. `test_run_event_emit.py` RED at Task 1 against unedited production source, with node ids and
   counts recorded verbatim — not predicted.
2. `test_run_event_emit.py` GREEN at Task 2: 0 failed, 0 skipped, real numbers.
3. The D-06 test observed RED under the hoisted-construction mutation, then reverted to a clean
   tree and re-proved green.
4. `_fact_count_label` / `_UNKNOWN_FACTS` / `unknown number of facts` absent under
   `tribunal/nestor_pulse_sdk/` (path-scoped, `-I --exclude-dir=__pycache__`).
5. Both `agent_fail` lines still carry `· 0 facts ·`; the own-research done line unchanged and its
   two exact-text tests green without edits.
6. `cloudbuild.test-engine.yaml` unedited; registration at `:514` and `EXPECTED_FILES=45` at `:535`
   confirmed by reading.
</verification>

<success_criteria>
- The research-angle `agent_done` row reads `Angle NN done · {provider}` — no count, no
  honest-unknown clause.
- A degrading provider still records EXACTLY ONE done row (D-V01-7 preserved).
- The `meta` dict is unchanged.
- The D-06 site proof survives the deletion of its old lever and is demonstrably non-vacuous.
- Exactly two files modified; nothing built, deployed or run.
</success_criteria>

<output>
Create `.planning/quick/260831-ksq-drop-the-fact-count-from-the-angle-done-/260831-ksq-SUMMARY.md`
when done. It MUST carry: the verbatim RED output from Task 1, the verbatim RED output from the
Task 3 mutation proof, the final pass/fail/skip numbers for all three test files, and the explicit
statement that this is UNBUILT and UNDEPLOYED and ships with the next tribunal build alongside the
already-committed `260831-jx2` change.
</output>
