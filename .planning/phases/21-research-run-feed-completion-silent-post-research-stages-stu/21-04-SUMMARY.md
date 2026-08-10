---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 04
subsystem: engine-observability
tags: [density, feed, deep_research, audit, blocked-on-operator]
status: PAUSED AT CHECKPOINT — Task 2 of 3
requires:
  - "tribunal/nestor_pulse_sdk/audit/audited_llm_client.py (read-only, the density target)"
  - "tribunal/nestor_pulse_sdk/tests/test_own_researcher.py (read-only, the CI pin inventory)"
provides:
  - ".planning/phases/21-.../21-DENSITY-AUDIT.md — the per-site keep/cut verdict, awaiting ruling"
affects: []
tech-stack:
  added: []
  patterns: ["diagnose-before-trim (D-12): the verdict is a reviewable artifact, not a commit message"]
key-files:
  created:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-DENSITY-AUDIT.md
  modified: []
decisions:
  - "Recommended option-c (no change to audited_llm_client.py) — the operator has NOT yet ruled"
metrics:
  tasks-completed: 1
  tasks-total: 3
  completed: 2026-08-10
---

# Phase 21 Plan 04: Density Pass Diagnosis Summary

The `deep_research` feed's own numbers, re-derived at source: 13 emit sites, 8 of 8 `thinking`
lines in D-13's KEEP classes, and a volume ceiling less than half what the plan assumed —
so the recommended verdict is that no line in this file needs cutting.

**Status: PAUSED at Task 2, a blocking `checkpoint:decision`. Task 3 has not started and MUST
NOT start until the operator rules.** No source file has been modified.

## What was done

**Task 1 — the density audit** (commit `796d398`). Created `21-DENSITY-AUDIT.md`, 219 lines,
five sections: what was measured, the 13-row per-site table, the contradiction, the volume
arithmetic, and four costed options with a recommendation. Every number was re-derived from the
code rather than copied from the plan's table.

## The re-derived counts, and whether they matched

| measurement | plan's table | measured | verdict |
|---|---|---|---|
| `emit_safe` sites in `audited_llm_client.py` | 13 | **13** | match |
| all on `stage="deep_research"` | yes | **yes** | match |
| `kind="thinking"` sites | 8 (1408, 1436, 1495, 1594, 1710, 1824, 1866, 1942) | **8, same lines** | match |
| `kind="agent_fail"` sites | 5 (1569, 1622, 1911, 1925, 1969) | **5, same lines** | match |
| thinking lines in D-13 KEEP classes | 8 of 8 | **8 of 8** | match |
| CI-pinned thinking sites | 5 | **4** | ⚠ **diverges** |
| volume multiplier from run `368ff3a0` | 19 sub-questions | **8 deep-research calls** | ⚠ **diverges** |
| sites with a pre-paid `log.warning` demotion | 2 | **4** | ⚠ **diverges** |
| `build=lambda` / `emit_safe` parity | — | **13 / 13** | baseline holds |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | 44 | **44** | match, unmoved |

### The three divergences, and why they matter

1. **Four sites are CI-pinned, not five** — 1408, 1436, 1495, 1594, all on the **Google** path.
   `test_own_researcher.py` exercises `gemini_deep_research_raw` only; `test_provider_resume.py`
   does call `openai_deep_research_raw` but installs no recorder, so it asserts nothing about feed
   text. **Every OpenAI-side line is unpinned and freely rewritable at zero test cost**, which
   lowers Option A's price.

2. **The volume multiplier is 8 calls, not 19.** The dispatch report's own header reads
   "4 groups × 3 providers = 12 angles"; the 19 is the *member* count packed into those queries,
   not a per-call figure. Only `gemini` and `openai` of the four peer streams route through this
   file. So: 4 groups × 2 deep-research providers = 8 calls × ≤8 rows = **a 64-row ceiling,
   ~40 typical — not "roughly a hundred"**. This weakens Option B's case: it buys back ~35 rows,
   not ~90.

3. **The D-14 demotion is pre-paid at four sites, not two.** The OpenAI path mirrors Gemini's:
   `:1704-1708` sits beside site 1710 and `:1817-1822` beside site 1824. No new log call is needed
   at any of the four money sites.

**A fourth correction, to Option D's premise as written in the plan:** it describes 1408 and 1710
as "the two unpinned guard-refusal lines". **1408 IS pinned** (`"refused"` and `"paid for again"`,
`test_own_researcher.py:1392-1396`). Only 1710 is unpinned. Option D is therefore not the free
one-line edit it reads as.

## The contradiction recorded for the operator

21-CONTEXT.md's premise for this file — *"most of its lines are exception-path commentary
addressed to an engineer"* — is contradicted by the measurement. Eight of eight `thinking` lines
are money or long-silence, D-13's two KEEP classes. The verbatim line 21-CONTEXT.md quotes as its
evidence of noise ends "so it is paid for again" — a money warning D-13 says to KEEP.
**Under D-13 as written, the correct content trim of this file is zero cuts.**

## Deviations from Plan

None. The plan explicitly instructed that a re-derived count differing from the planner's table
wins and is recorded as such; the three divergences above are that instruction operating, not
deviations from it.

## Verification

| criterion | result |
|---|---|
| `21-DENSITY-AUDIT.md` exists, non-empty | 219 lines |
| per-site table names ≥13 sites (`grep -c "^| 1"`) | **13** |
| `grep -c "test_own_researcher"` ≥ 1 | **7** |
| `grep -c "NOT A STALL"` ≥ 1 | **1** |
| `grep -ci "contradict"` ≥ 1 | **2** |
| `grep -c "Option A\|Option B\|Option C"` ≥ 3 | **5** |
| `## Operator ruling` exists and is empty | heading at line 218, file ends at 219 (blank) |
| no file under `tribunal/` modified | `git diff --name-only tribunal/` empty |

The Task 3 pytest gate (`test_own_researcher.py`, `test_provider_resume.py`,
`test_deep_research_adapters.py`) was **not run**: no source file changed, so it would only
re-measure an empty diff. It is Task 3's gate and must be run by whoever resumes **if and only if
the ruling authorises a source edit**.

## Deferred / blocked

**Task 3 is blocked on the Task 2 ruling and its scope is defined entirely by it.** If the ruling
is option-c, Task 3 makes NO source edit and this plan closes with the audit as its deliverable —
that is a completed plan, not an abandoned one, and it should not be re-opened later as an
oversight.

Binding rules for whoever executes Task 3:
- **D-14**: a line leaving the feed is demoted to `log.warning`, never deleted. Pre-paid at
  sites 1408, 1436, 1710, 1824 — do not add a duplicate log call there.
- **The thunk rule**: a shorter string is still built inside `build=lambda:`. Never hoist it above
  the `emit_safe` call while tidying. Baseline parity is 13 / 13.
- **The pin rule**: source edit and test edit land in ONE commit. Never loosen an assertion to make
  a rewrite pass; re-derive it, and keep the cardinality bound `2 <= len(thinking) <= 8` as a bound.
- No new event kind, no new meta key, no `stage` value change (D-03).
- Do not touch the five `agent_fail` sites unless the ruling names them.

## Self-Check: PASSED

- `21-DENSITY-AUDIT.md` — FOUND, committed in `796d398` (`git show --stat` lists it)
- commit `796d398` — FOUND
- no modification to `STATE.md` or `ROADMAP.md` — confirmed
