---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 04
subsystem: engine-observability
tags: [density, feed, deep_research, audit, operator-ruling, no-op-by-ruling]
status: COMPLETE — 3/3 tasks, ruled option-c (no source change)
requires:
  - "tribunal/nestor_pulse_sdk/audit/audited_llm_client.py (read-only, the density target)"
  - "tribunal/nestor_pulse_sdk/tests/test_own_researcher.py (read-only, the CI pin inventory)"
provides:
  - ".planning/phases/21-.../21-DENSITY-AUDIT.md — the per-site keep/cut verdict, ruled 2026-08-10"
  - "An operator amendment to D-13: where money and guard-refusal collide, money is dominant (KEEP)"
affects: []
tech-stack:
  added: []
  patterns:
    - "diagnose-before-trim (D-12): the verdict is a reviewable artifact, not a commit message"
    - "a plan may close with a documented decision NOT to act"
key-files:
  created:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-DENSITY-AUDIT.md
  modified: []
decisions:
  - "option-c ruled 2026-08-10: no change to audited_llm_client.py; the audit IS the deliverable"
  - "D-13 AMENDED [OPERATOR]: where the money clause and the guard-refusal clause collide in one line, money is dominant and the line is KEPT — lines 1408 and 1710 are both KEEP"
  - "Re-read the feed after 21-01/03/05/06 land and one run executes; option-a and option-b stay costed and available"
metrics:
  tasks-completed: 3
  tasks-total: 3
  completed: 2026-08-10
---

# Phase 21 Plan 04: Density Pass Diagnosis Summary

The `deep_research` feed's own numbers, re-derived at source: 13 emit sites, 8 of 8 `thinking`
lines in D-13's KEEP classes, and a volume ceiling less than half what the plan assumed — so the
operator ruled **no line in this file is cut**, and the audit itself is the deliverable.

**Status: COMPLETE, 3/3 tasks. Nothing under `tribunal/` was modified — by ruling, not by
omission.** SC5 is satisfied by a diagnosis the operator ruled on, which is exactly what D-12
asked for.

## What was done

**Task 1 — the density audit** (commit `796d398`). Created `21-DENSITY-AUDIT.md`: five sections —
what was measured, the 13-row per-site table, the contradiction, the volume arithmetic, and four
costed options with a recommendation. Every number re-derived from the code, not copied from the
plan's table.

**Task 2 — the blocking ruling** (checkpoint, resolved 2026-08-10). The operator selected
**option-c** and amended D-13. Both recorded verbatim under `## Operator ruling`.

**Task 3 — apply the ruling.** Under option-c this is a **documented no-op**: no edit to
`audited_llm_client.py`, no edit to `test_own_researcher.py`, no file under `tribunal/` touched.
Closed out explicitly rather than silently skipped, and verified as an empty diff below.

## The operator's ruling, verbatim

**(1) Option `option-c` — no change to `audited_llm_client.py`:**

> The audit document IS the deliverable. The operator accepted your reasoning: the content is not
> noise by D-13's own rule, the real volume is roughly half what the plan assumed, and
> `deep_research` only read as overwhelming because it was the sole stage speaking while eight said
> nothing. Whether this file was ever the problem gets re-read after 21-01/21-03/21-05/21-06 land.

**(2) Lines 1408 and 1710 — both KEEP, money wins:**

> Where D-13's money clause and its guard-refusal-commentary clause collide, the money clause is
> dominant. This is an operator amendment to D-13 resolving the contradiction in favour of KEEP.

**This is a ruling, not an inference.** D-13 was `[ASSISTANT — CORRECTABLE]`; on this point it is
now `[OPERATOR]`. The amended rule reads, in effect: CUT guard-refusal commentary, parser-defect
explanations, and lines about the engine's own defensive machinery — **unless the same line also
states a cost, in which case it is KEPT.** It applies to both sites, both providers, and any future
line of the same shape.

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
| `build=lambda` / `emit_safe` parity | — | **13 / 13** | holds, unchanged |
| `EXPECTED_FILES` in `cloudbuild.test-engine.yaml` | 44 | **44** | match, unmoved |

### The three divergences, and why they matter

The operator directed that these corrections are part of the deliverable's value, so they are
recorded in the audit and repeated here.

1. **Four sites are CI-pinned, not five** — 1408, 1436, 1495, 1594, all on the **Google** path.
   `test_own_researcher.py` exercises `gemini_deep_research_raw` only; `test_provider_resume.py`
   does call `openai_deep_research_raw` (`:296-355`) but installs no recorder, so it asserts
   nothing about feed-row text. **Every OpenAI-side line is unpinned and freely rewritable at zero
   test cost** — which lowers Option A's price if it is ever revisited.

2. **The volume multiplier is 8 calls, not 19.** The dispatch report's own header reads
   "4 groups × 3 providers = 12 angles"; 19 is the *member* count (7+6+5+1) packed **into** those
   queries, not a per-call figure. Of the four peer streams (`degraded_parallel.py:101` — `gemini`,
   `claude`, `openai`, `own`) only gemini and openai route through this file. So 4 groups × 2
   deep-research providers = **8 calls**. At `max_attempts=70` / `poll_interval=30` /
   `_POLL_EVENT_STRIDE=10`, each call emits 1 waiting line + ≤7 heartbeats: a **64-row ceiling,
   ~40 typical — not "roughly a hundred"**. This materially weakened Option B, which buys back
   ~35 rows rather than ~90.

3. **The D-14 demotion is pre-paid at four sites, not two.** The OpenAI path mirrors Gemini's:
   `:1704-1708` sits beside site 1710 and `:1817-1822` beside site 1824. No new log call would be
   needed at any of the four money sites (nor at `agent_fail` sites 1569, 1622, 1969).

### A fourth correction — Option D as the plan worded it was wrong

The plan describes 1408 and 1710 as "the two **unpinned** guard-refusal lines". **1408 IS pinned** —
`"refused"` and `"paid for again"` are both asserted at `test_own_researcher.py:1392-1396`. Only
1710 is unpinned. Option D was therefore never the free one-line edit it read as. Moot under
option-c, but recorded so it is not re-proposed on a false premise.

## The contradiction recorded for the next reader

21-CONTEXT.md's premise for this file — *"most of its lines are exception-path commentary addressed
to an engineer"* — is contradicted by the measurement. Eight of eight `thinking` lines are money or
long-silence, D-13's two KEEP classes. The verbatim line 21-CONTEXT.md quotes as its own evidence
of noise ends "so it is paid for again" — a money warning D-13 says to KEEP. **Under D-13, the
correct content trim of this file is zero cuts**, and the ruling adopted exactly that.

Four of those lines are additionally pinned by a registered CI test whose own comment reads *"the
wording is the deliverable — this run was misread as a stall once"* (`test_own_researcher.py:1321`),
referring to the 2026-07-27 incident in which a 25-minute long poll was read as a hang and a paid
run was nearly re-executed from the start.

## The diff

**Empty under `tribunal/`, by ruling.** `git diff --name-only tribunal/` returns nothing.
The only files this plan created or changed are the two `.planning/` documents:

- `21-DENSITY-AUDIT.md` (created, then amended with the ruling)
- `21-04-SUMMARY.md` (this file)

## Deviations from Plan

None. The plan instructed that a re-derived count differing from the planner's table wins and is
recorded as such; the divergences above are that instruction operating, not deviations from it.
Task 3 performing no edit is the ruled outcome, which the plan explicitly anticipated: *"a plan
that closes with a documented decision not to act is a completed plan."*

## Verification

| criterion | result |
|---|---|
| `21-DENSITY-AUDIT.md` exists, non-empty | 260 lines |
| per-site table names ≥13 sites (`grep -c "^| 1"`) | **13** |
| `grep -c "test_own_researcher"` ≥ 1 | 7 |
| `grep -c "NOT A STALL"` ≥ 1 | 1 |
| `grep -ci "contradict"` ≥ 1 | 2 |
| `grep -c "Option A\|Option B\|Option C"` ≥ 3 | 5 |
| `## Operator ruling` carries the dated, verbatim selection | line 221; option + D-13 amendment both recorded |
| lines 1408 / 1710 classified explicitly, not inferred | both KEEP in the table, attributed to the operator |
| pytest: `test_own_researcher` + `test_provider_resume` + `test_deep_research_adapters` | **77 passed in 16.52s** |
| `git diff --name-only tribunal/` (option-c requires empty) | **empty** |
| thunk discipline: `emit_safe` count == `build=lambda` count | **13 == 13** |
| every `kind=` literal ∈ `RUN_EVENT_KINDS` (import-and-assert, not a grep) | **PASS** — 13 literals (`thinking`, `agent_fail`), 12 declared kinds, zero outside |
| `EXPECTED_FILES=44` in `cloudbuild.test-engine.yaml` | **44**, unmoved — no test file added |
| no pinned assertion loosened, no feed line deleted | vacuous under option-c — nothing was edited |
| STATE.md / ROADMAP.md untouched | confirmed |

## For the next reader — do not re-open this as an oversight

`audited_llm_client.py` was deliberately left alone. That was a ruling made with the per-site
table, the CI pin inventory and the volume arithmetic all in view.

The question is **sequenced, not closed**. After 21-01 (the collapse toggle actually collapses),
21-03, 21-05 and 21-06 (the eight silent stages get bodies) land and one run executes, re-read the
feed. If `deep_research` still reads as too verbose, option-a and option-b remain fully costed in
`21-DENSITY-AUDIT.md` § 5, with their test impact already measured.

Anyone who does take up that later edit is bound by: D-14 (demote to `log.warning`, never delete —
pre-paid at 1408, 1436, 1710, 1824); the thunk rule (a shorter string is still built inside
`build=lambda:`, never hoisted above `emit_safe`); the pin rule (source and test edits in ONE
commit, assertions re-derived and never loosened, the cardinality bound `2 <= len(thinking) <= 8`
kept as a bound); no new event kind or meta key (D-03); and no `stage` value change.

## Self-Check: PASSED

- `21-DENSITY-AUDIT.md` — FOUND on disk, 260 lines, committed
- `21-04-SUMMARY.md` — FOUND on disk, committed
- commit `796d398` (audit) — FOUND
- commit `4cb156f` (interim summary at checkpoint) — FOUND
- no modification to `STATE.md` or `ROADMAP.md` — confirmed
- no modification under `tribunal/` — confirmed by empty `git diff --name-only tribunal/`
