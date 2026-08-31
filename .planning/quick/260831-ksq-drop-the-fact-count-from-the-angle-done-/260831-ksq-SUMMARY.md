---
phase: quick-260831-ksq
plan: 01
subsystem: tribunal-run-feed
tags: [run-events, research-division, d-06, d-v01-7, operator-ruling]
requires: []
provides: ["_agent_done_text", "count-free agent_done row"]
affects: [tribunal-worker, tribunal-api]
tech-stack:
  added: []
  patterns: ["named monkeypatchable row-text builder as a D-06 lever"]
key-files:
  created: []
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py
    - tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py
decisions:
  - "D-06 option (b): delete _fact_count_label AND re-point the lever at a new named builder with a real production caller"
metrics:
  duration: ~25 min
  completed: 2026-08-31
---

# Quick 260831-ksq: Drop the fact count from the angle-done feed row — Summary

The research-angle `agent_done` row now reads `Angle 03 done · claude` instead of
`Angle 03 done — an unknown number of facts · claude`. `_fact_count_label` and
`_UNKNOWN_FACTS` are deleted; `_agent_done_text(angle_no, provider)` replaces them and
carries the D-06 site proof forward on a lever production actually calls.

**Base:** `ae8e31a` → **HEAD:** `3ecfecd`. Exactly two files changed.

| Commit | Message |
|---|---|
| `95f9d95` | `test(260831-ksq): invert the done-line tests to the count-free contract (RED)` |
| `3ecfecd` | `fix(260831-ksq): drop the fact count from the angle-done run feed line` |

---

## THE RED PROOF (Task 1) — real, and it failed for the right reason

Tests were inverted **first**, against unedited production source. Baseline before any edit
was **67 passed, 0 failed, 0 skipped**. After the test-only edit, against the *unchanged*
`research_division.py`:

```
7 failed, 60 passed in 5.04s
EXIT=1
```

All four changed regions went red. Verbatim:

```
__ test_a_result_missing_the_keys_the_done_line_reads_still_records_its_line __
nestor_pulse_sdk\tests\test_run_event_emit.py:928: in test_a_result_missing_...
    assert not re.search(r"\d+\s+facts", text), (
E   AssertionError: a done row rendered a fact count, which 260831-ksq removed:
    'Angle 01 done — 2 facts · openai'
E   assert not <re.Match object; span=(16, 23), match='2 facts'>

________________ test_j_a_healthy_angle_renders_no_fact_count _________________
nestor_pulse_sdk\tests\test_run_event_emit.py:1067: in test_j_a_healthy_angle_...
    assert done[0]["text"] == "Angle 01 done · openai", (
E   AssertionError: the healthy done line changed shape: 'Angle 01 done — 3 facts · openai'
E   assert 'Angle 01 don...acts · openai' == 'Angle 01 done · openai'
E     - Angle 01 done · openai
E     + Angle 01 done — 3 facts · openai
E     ?               ++++++++++

_ test_j_a_degraded_result_still_records_exactly_one_done_line[shape0-no facts key at all] _
_ test_j_a_degraded_result_still_records_exactly_one_done_line[shape1-a None under facts] _
_ test_j_a_degraded_result_still_records_exactly_one_done_line[shape2-an int, which len refuses] _
_ test_j_a_degraded_result_still_records_exactly_one_done_line[shape3-a str] _
nestor_pulse_sdk\tests\test_run_event_emit.py:1125:
    assert text == "Angle 01 done · openai", (
E   AssertionError: the degraded done line (...) is not the count-free row:
    'Angle 01 done — an unknown number of facts · openai'

_________ test_j_the_done_line_is_still_built_inside_the_emitters_try _________
nestor_pulse_sdk\tests\test_run_event_emit.py:1175:
    monkeypatch.setattr(rd, "_agent_done_text", _boom)
E   AttributeError: <module 'nestor_pulse_sdk.pipeline.tribunal.research_division'>
    has no attribute '_agent_done_text'
```

**The last one is recorded honestly as "the lever does not exist yet" — it is NOT a proof of
D-06.** That proof is a different assertion and is below.

Note: `·` and `—` render as `?` in the raw Windows console because of the codepage; the runs
above were re-taken with `PYTHONIOENCODING=utf-8` so the characters are the real ones.

---

## THE MUTATION PROOF (Task 3) — the D-06 assertion still BITES

Green is not proof; red-on-break is. With Task 2 committed and the tree clean, the row
construction was hoisted **out** of the thunk — the exact "cleanup" D-06 exists to catch:

```python
_row = (_agent_done_text(i + 1, provider), { ...same meta... })
run_events.emit_safe(run_id, stage="deep_research", kind="agent_done", build=lambda: _row)
```

The D-06 test failed, verbatim:

```
_________ test_j_the_done_line_is_still_built_inside_the_emitters_try _________
nestor_pulse_sdk\tests\test_run_event_emit.py:1180: in test_j_the_done_line_...
    results = await _one_angle_returning(
nestor_pulse_sdk\tests\test_run_event_emit.py:1032: in _one_angle_returning
    return await rd.run_angles(
nestor_pulse_sdk\pipeline\tribunal\research_division.py:2594: in run_angles
    gathered = await asyncio.gather(*(_one_angle(i, a) for i, a in enumerate(angles)))
nestor_pulse_sdk\pipeline\tribunal\research_division.py:2508: in _one_angle
    await _record_result(i, provider, _enriched)
nestor_pulse_sdk\pipeline\tribunal\research_division.py:2154: in _record_result
    _agent_done_text(i + 1, provider),
nestor_pulse_sdk\tests\test_run_event_emit.py:1173: in _boom
    raise RuntimeError("synthetic row-text failure for the D-06 site proof")
E   RuntimeError: synthetic row-text failure for the D-06 site proof
1 failed in 2.29s
EXIT=1
```

The traceback **is** the proof: the RuntimeError was raised at `_record_result:2154`, outside
`emit_safe`'s `try`, and escaped up through `_one_angle` and `asyncio.gather` into
`run_angles` — killing the paid angle, so `assert len(results) == 1` never even ran. That is
precisely the D-V01-7 failure mode the thunk prevents.

Reverted with `git checkout --`; `git status --short` shows no modified file, `git diff HEAD`
is empty, and the test is green again (`1 passed in 1.15s`).

---

## Final numbers — real, not predicted

| Run | Result |
|---|---|
| Baseline, before any edit | 67 passed, 0 failed, 0 skipped |
| Task 1, tests inverted vs unedited source | **7 failed**, 60 passed, 0 skipped |
| Task 2, after the source change | **67 passed, 0 failed, 0 skipped** |
| Task 3, three files together | **140 passed, 0 failed, 0 skipped** |

Three files = `test_run_event_emit.py` + `test_own_researcher.py` + `test_run_events.py`.
**Zero skipped everywhere** — the venv has `openai` installed, as intended.

Test-function count is **flat**: 52 at base, 52 at HEAD; 67 collected at base, 67 at HEAD.
Four tests modified in place, one renamed
(`test_j_a_healthy_angle_still_renders_its_fact_count` →
`test_j_a_healthy_angle_renders_no_fact_count`), none added or removed. The engine gate's
passed count should not move.

---

## Which D-06 option was taken, and why the alternative was rejected

**Taken: option (b) — delete the helper AND re-point the lever** at a new named module-level
builder `_agent_done_text(angle_no, provider)` that has a real production caller inside the
same thunk.

**Option (a), keeping `_fact_count_label` uncalled purely as a lever, was rejected because it
is not merely untidy — it is impossible.** Monkeypatching a function production no longer
calls proves nothing: the thunk would not raise, the row would emit normally, and the D-06
test would go RED against correct code. A red test on correct code gets deleted, which is
exactly how the proof is lost.

The `.get`-raising `result` lever suggested in the brief was rejected at planning time as
unreachable (`_enriched` is a plain dict built by `{**result, ...}`, so its `.get` cannot
raise), and this execution did not revisit it.

Both reasons are written into `_agent_done_text`'s docstring with an explicit **"do not
inline"**, because the obvious future "simplification" of a one-line function silently deletes
the proof.

---

## Deviations from Plan

### [Rule 3 — unsound gate, reported not "fixed"]

Task 2's and Task 3's verify steps demand that
`grep -rn -e '_fact_count_label' -e '_UNKNOWN_FACTS' -e 'unknown number of facts'` under
`nestor_pulse_sdk/` **return nothing**. As literally written that gate is **unsound: it
contradicts the plan's own Task 2 mandate**, which explicitly requires the new docstring to
name `_fact_count_label` and to quote the phrase "an unknown number of facts" as the reason
the clause was dropped. Both cannot be satisfied at once.

Per the repo's standing rule — a gate red on correct code invites you to undo the fix; prove
the gate sound before touching source — **I did not delete the mandated prose.** The nine
remaining hits are all comments and docstrings *about* the removal, in the two files this task
edited. The sound form of the gate was proven instead:

```
_fact_count_label present: False
_UNKNOWN_FACTS   present: False
_agent_done_text present: True
rendered row      -> 'Angle 01 done · openai'
rendered row (12) -> 'Angle 12 done · claude'
```

plus a filtered grep for any **live code** reference (a call, an assignment, a `def`, an
attribute access) which returned empty, and the suite being green — a stale call would have
raised `AttributeError`. The symbols are gone from the code; only the explanation remains.

### [No docs commit]

The plan's Task 3 ends with `docs(260831-ksq): ...`. The orchestrator's constraints override
this: docs artefacts are not committed by the executor, and `.planning/` is gitignored in this
repo, so this SUMMARY is untracked by design. Only the two code commits exist.

---

## Scope closure — confirmed by reading, not assumed

- **Exactly two files changed** across `ae8e31a..3ecfecd`.
- **Both `agent_fail` lines keep `· 0 facts ·`** — `:2485` (`f"{str(_exc)[:160]} · 0 facts · {provider}"`)
  and `:2569` (`f"· 0 facts · {provider}"`). A failed angle really did establish zero.
- **The `meta` dict is byte-identical**: `angle`, `provider`, `cost`, `audit_id`. The operator
  asked about visible text, not recorded metadata, so `cost` still rides the row.
- **`build=lambda:` is still a thunk** at the call site (`:2157-2158`).
- **`own_researcher.py` untouched** — `git diff` across both commits for `own_researcher.py`
  and `test_own_researcher.py` is empty. Its separate line at `own_researcher.py:817` still
  reads `f"Own query done — {len(facts)} facts from "`, and its exact-text tests pass without
  edits.
- **Checkpoint-restore, not-researched and retry lines untouched.**
- **Cloudbuild unedited and unchanged.** `test_run_event_emit.py` is registered at
  `tribunal/cloudbuild.test-engine.yaml:514`; `EXPECTED_FILES=45` sits at `:535`. This change
  edits two existing files, adds none and renames none, so neither the file count nor the
  config moves. `git diff` for `tribunal/cloudbuild*.yaml` is empty.
- The orphaned stale tree at `.claude/worktrees/agent-af281d695d9b34c35/` was **not touched**;
  every grep was path-scoped under `tribunal/` with `-I --exclude-dir=__pycache__`.

---

## ⛔ NOT BUILT, NOT DEPLOYED, NOT RUN

This task ended at a commit. **No build, no `gcloud` command of any kind, no deploy, no
triggered run — zero spend.**

The change ships with the **next `tribunal-worker` / `tribunal-api` build**, alongside the
already-committed-but-unbuilt **`260831-jx2`** change. Neither is live.

## What is now UNOBSERVED

**Nobody has seen the shortened row in a live feed.** The contract is proven by 140 green
tests against a stubbed harness, and the D-06 guarantee is proven by a mutation that really
went red — but no operator has watched `Angle NN done · claude` appear on a real run's
progress feed. Until a build ships and a run executes, "the operator's row is fixed" is an
inference from tests, not an observation.

Also unobserved: the `own` stream's real fact count is genuinely gone from this line. The
operator accepted that trade knowingly, but the loss has not been seen in practice either.

## Threat Flags

None. The change **narrows** the surface: `_agent_done_text` reads only an `int` loop index
and an internal stream name from `_PROVIDER_RUNNERS`, so removing `_fact_count_label` removes
the last provider-controlled term from this row.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py` — FOUND, modified
- `tribunal/nestor_pulse_sdk/tests/test_run_event_emit.py` — FOUND, modified
- Commit `95f9d95` — FOUND
- Commit `3ecfecd` — FOUND
- Working tree clean (only untracked `.claude/`, pre-existing)
