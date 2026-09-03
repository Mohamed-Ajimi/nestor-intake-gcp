# Quick task 260901-j6w — move the tribunal engine to claude-sonnet-5

**Date:** 2026-09-01
**Base:** `650310a` (asserted before any edit)
**Commit:** `df131ea` — ONE atomic commit, 9 files, 0 deletions
**Status:** ⛔ **NOT DEPLOYED. NOT OBSERVED.** Ends at a commit, as instructed. No build, no `gcloud`, no run, zero spend.

---

## What changed

### 1. The price row (added FIRST, committed WITH the swap)

`tribunal/nestor_pulse_sdk/audit/cost_prices.json` — added `anthropic/claude-sonnet-5`:

```json
"anthropic/claude-sonnet-5": {
  "prompt": 2.0, "completion": 10.0, "cache_read": 0.20, "cache_creation_5m": 2.50
}
```

Placed at the head of the `anthropic/claude-sonnet-*` family, with a `_claude_sonnet_5_source`
comment key in the file's existing house style (the `_claude_opus_5_source` precedent). The
comment records that the two cache figures are official published rates that *also* happen to
equal Anthropic's standard 0.1x / 1.25x multipliers on prompt — so nothing is passed off as an
independent reading that is not one.

**`anthropic/claude-sonnet-4-6` was NOT removed**, deliberately — historical runs, the untouched
`critique/` tooling and the legacy claude DR adapter all still resolve against it. Two ungated
tests (`test_audit_perf.py`, `test_cost_cache_write.py`) read its exact rates and still pass:
**10 passed** when run in isolation.

### 2. The six production model defaults → `claude-sonnet-5`

| # | File | Symbol | Mechanism |
|---|------|--------|-----------|
| 1 | `pipeline/tribunal/pipeline.py:255` | `_SKEPTIC_MODEL` | hardcoded — the cost driver |
| 2 | `pipeline/tribunal/intake.py:61` | `_INTAKE_MODEL` | hardcoded |
| 3 | `pipeline/tribunal/workshop.py:139` | `_WORKSHOP_MODEL` | `NESTOR_TRIBUNAL_WORKSHOP_MODEL` default |
| 4 | `pipeline/tribunal/workshop_rank.py:212` | `_EVOLVE_MODEL` | `..._EVOLVE_MODEL` default |
| 5 | `pipeline/tribunal/question_grouping.py:360` | `_GROUP_MODEL` | fallback default |
| 6 | `pipeline/tribunal/own_researcher.py:144` | `_MODEL` | `NESTOR_TRIBUNAL_OWN_MODEL` default |

**Every `os.environ.get(...)` override is byte-unchanged — only the default string moved.**
Verified in the diff: no env-var name, no `or` chain, no ordering touched.

`intake.py`'s module docstring (line 39) named the old version in its "DO NOT relax" invariant
block; it was updated, and now states explicitly that the intake/skeptic pair is kept equal and
that moving one means moving both.

### 3. A SEVENTH site — not on the task list, changed on purpose

`pipeline/tribunal/workshop_admission.py:592`. This is the `except` branch that fires when the
function-local `from ...workshop import _WORKSHOP_MODEL` fails; it exists **only to mirror
`_WORKSHOP_MODEL`**. Left on `claude-sonnet-4-6` it would have become a silent divergence — a
rarely-exercised path billing against a differently-priced model with nothing to surface it.
Changed, with a comment saying it must track `_WORKSHOP_MODEL`. (Deviation Rule 2.)

---

## Deliberately left on `claude-sonnet-4-6`

Everything on the task's do-not-change list, untouched and confirmed by grep:
`critique/judge.py:40`, `critique/content_compare.py:41`,
`pipeline/synthesis/outcomes_spike.py` (all refs), `quality_gate/llm_judge/rubric.py`,
`quality_gate/rubrics/default.yaml`, `nestor_pulse/tools/claude_deep_researcher.py`, and all of
`backend/`.

**Plus two findings the task did not anticipate — both reported rather than silently resolved:**

**(a) `nestor_pulse_sdk/tools/claude_adapter.py:20` — `MODEL = "claude-sonnet-4-6"`.**
This is in *neither* list. It is the audited wrapper around
`nestor_pulse/tools/claude_deep_researcher.py` — the legacy deep researcher the task explicitly
excludes as "a DIFFERENT stream" — so I left it, matching the exclusion's intent rather than its
literal file path. **It is nonetheless a LIVE production model constant on the research path:**
it is the `claude` deep-research stream in `research_division._STAKES_PROVIDER`
(`low` stakes → claude) and `_HIGH_REDUNDANCY_PROVIDER` (the second provider on doubled
high-stakes angles). **So the claude DR stream still runs on sonnet-4-6 and is not covered by
this task's saving.** If the operator intended that stream to move too, it is a one-line
follow-up — but it changes research *output*, not just cost, so I did not assume it.

**(b) `pipeline/tribunal/pipeline.py:4762` — `"claude": "Claude claude-sonnet-4-6 +web"`.**
A live (non-comment) string inside `_dr_model_display()`, the UI label for "which DR model was
called". **Left unchanged because it is TRUE:** it describes the adapter in (a), which still is
sonnet-4-6. Proven at runtime:

```
claude_adapter.MODEL       = claude-sonnet-4-6
_dr_model_display('claude') = 'Claude claude-sonnet-4-6 +web'   <- matches
```

Changing it to sonnet-5 would have made the UI assert a model the run never calls. I considered
deriving it from `claude_adapter.MODEL` (the idiom the gemini/openai entries already use) and
rejected it: `claude_adapter` imports the legacy `nestor_pulse` package at module level, so a
function-local import on the live feed path could raise where today it cannot.

**Consequence for verification criterion 3, stated honestly rather than dressed as green** —
see below.

---

## Verification

**1. The price row resolves — the most important check.** Exercised through the real
`cost_table.compute()`, not just a JSON read:

```
compute('anthropic','claude-sonnet-5',   1M in, 1M out) = Decimal('12.0000000')   <- NOT None
compute('anthropic','claude-sonnet-4-6', 1M in, 1M out) = Decimal('18.00000000')
compute('anthropic','claude-sonnet-5', all-cached in, 1M cache-write) = Decimal('2.7000000')
```

`12 = 2 + 10` and `2.7 = 0.20 + 2.50` confirm all four fields are reachable, cache rates included.
**Negative control** (proves the lookup actually bites, rather than returning a number for
anything): `compute('anthropic','claude-sonnet-6-does-not-exist')` → `None`, with the
`Unknown LLM model cost ... writing NULL cost_usd (Pitfall 5)` warning. That is the G-7 shape,
and it is what the new row averts.

**All six resolved defaults priced, each asserted `is not None`:**

```
_SKEPTIC_MODEL   = claude-sonnet-5 -> 0.0070000
_INTAKE_MODEL    = claude-sonnet-5 -> 0.0070000
_WORKSHOP_MODEL  = claude-sonnet-5 -> 0.0070000
_EVOLVE_MODEL    = claude-sonnet-5 -> 0.0070000
_GROUP_MODEL     = claude-sonnet-5 -> 0.0070000
own _MODEL       = claude-sonnet-5 -> 0.0070000
```

**2. JSON validity:** `json.loads()` succeeds, 36 top-level keys.

**3. Scoped grep** (`-I --exclude-dir=__pycache__`, explicit path — a repo-root grep is unsound
here because `.claude/worktrees/agent-af281d695d9b34c35/` is an orphaned stale copy; it was not
touched). `grep -rn "claude-sonnet-4-6" tribunal/nestor_pulse_sdk/pipeline/tribunal/` returns
**6 hits: 5 comments/docstrings + 1 live string.** No live *default* remains — the one live
string is the `_dr_model_display` label in (b) above, which is correct as written.
**I am not calling this criterion fully green:** it is green on its intent (no live default), with
one explained, verified-true exception.

**4. Test suite — the explicit 45-file list from `cloudbuild.test-engine.yaml`.** Run with the
provided venv (Python 3.11.9, `openai` present). I did *not* run the tests directory as a
directory; the gate script asserts `collecting: 45 of 45` first, mirroring the config's own
`EXPECTED_FILES` guard.

| | passed | failed | skipped | errors |
|---|---|---|---|---|
| **Baseline** (at `650310a`, before any edit) | **1943** | 3 | 13 | 6 |
| **After the change** | **1943** | 3 | 13 | 6 |

**Byte-identical, and the same failure/error names both times** — so this is a genuine regression
pass, not a coincidence of totals:

- `test_checkpoint_resume.py::test_worker_park_branch_keeps_the_cancel_guard`
- `test_status_gates.py::test_recovered_retries_and_cost_pending_never_degrade`
- `test_status_gates.py::test_worker_writes_the_status_terminal_state_computed`
- 6 errors: `test_dispatch_pii.py::test_never_raises` (2), `test_fact_list_parser.py::test_parser_never_raises` (4)

These are **pre-existing and proven so by measurement** — the baseline run above was taken before
a single file was edited.

**⚠ The 45-file gate does not pin the tribunal model identity anywhere.** It proves no regression;
it proves *nothing about the swap itself*. The only test that pinned the literal is **ungated**
(below). That gap is why I added arms rather than only editing one.

---

## Tests modified — every one, with reasoning

Only `tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py`. **It is in NEITHER cloudbuild
config**, so nothing in CI runs it; I ran it directly.

1. **`test_audited_anthropic_messages_called_once` (line 186)** — updated the literal
   `"claude-sonnet-4-6"` → `"claude-sonnet-5"`. Read first: this is a **literal pin, not a
   relationship test**, so updating the literal is correct. I deliberately did **not** rewrite it
   as `== _INTAKE_MODEL`, which would compare the constant to itself and pass for *any* value —
   a vacuous gate. The failure message now says so, so nobody "simplifies" it later.
2. **Docstrings** at file level (line 13) and on that test (line 182) — updated; they named the
   old version.
3. **ADDED `test_intake_model_equals_skeptic_model`** — pins `_INTAKE_MODEL == _SKEPTIC_MODEL` as
   a **relationship**. `intake.py` has documented this equality as a DO-NOT-RELAX invariant since
   260721-twy, but the two constants live in different modules and **nothing tested it** — they
   could have drifted silently. Version-agnostic by construction, so it survives the next move.
4. **ADDED `test_intake_model_has_a_price_row`** — a G-7 `is not None` guard through the real
   `compute()`, mirroring the arm `test_synthesis_opus5.py` carries for claude-opus-5. This is the
   durable form of "verify the row resolves": the defect cannot silently recur for this stage.

`test_tribunal_intake.py`: **30 passed, 1 failed** (was 28 passed, 1 failed — 29 → 31 tests).

**The 1 failure is pre-existing and PROVEN, not asserted.** `test_divide_falls_back_to_label_plus_
base_when_no_research_prompt` (line 443) is a whitespace/newline expectation
(`"Competitor strategy: base context"` vs a newline-joined form) with no relation to any model
literal. I proved it by reverting `intake.py` alone to its pristine state via
`git checkout -- <that one file>` and re-running: **1 failed, 28 passed** — it fails identically
with the model untouched, while the model assertion passed. I then re-applied both edits and
re-verified.

**No other test needed changing.** `test_cost_serpapi.py`, `test_hash_chain_replay.py` and
`test_coverage_reentry.py` reference `claude-sonnet-4-6` for cost lookups and fixtures and still
pass because that price row was retained; `test_outcomes_spike.py` pins the rubric judge model,
which is on the do-not-change list.

**One measurement trap worth recording:** running `test_outcomes_spike.py` alongside other files
produced **10 spurious failures**; run alone it is **32 passed**. Same cross-file-pollution
mechanism the task warns about for the tests *directory*, at smaller scale. Do not read a
multi-file ad-hoc pytest invocation here as a result — use the explicit gate list.

---

## Deploy status and the honest cost claim

⛔ **NOT DEPLOYED.** This ends at commit `df131ea`. Shipping it requires a
**`tribunal-api` + `tribunal-worker`** build and deploy — both images carry the
`pipeline/tribunal/` modules changed here. Nothing about this change is live, and no run has
exercised sonnet-5.

⚠ **The ~13% saving is ARITHMETIC ON MEASURED TOKENS, not an observed result.** The inputs are
real (79% of run `fb9484dd`'s cost was the skeptic stage, $19.68 of $24.78 priced; $2/$10 vs
$3/$15 published) but the projection assumes **the new model consumes comparable token volumes
and the same number of tool-use turns**. It may not: a different model can take more or fewer
web_search/web_fetch turns per skeptic session, and the ~30% tokenizer inflation applied here is
itself an adjustment factor, not a measurement of this model. Per-token the swap is 33% cheaper;
after the tokenizer adjustment ~13%; **the real figure is unknown until a run executes.** Do not
report ~$2.62/run as achieved.

Also unmeasured: **output quality**. Six stages that shape research questions, grouping and
verification now run on a different model. Nothing here tests that, and the engine gate cannot —
its LLM egress is entirely hand-written fakes.

---

## Follow-ups (recorded, not done)

1. **Deploy** `tribunal-api` + `tribunal-worker`; prove digests.
2. **Decide on `tools/claude_adapter.py`** — the claude DR stream is still sonnet-4-6. If it moves,
   `_dr_model_display`'s label must move in the same commit or the UI starts lying.
3. **The engine gate pins no model identity.** `test_tribunal_intake.py` is registered in neither
   cloudbuild config, so the two new arms (including the G-7 guard) do not run in CI. Registering
   it means adding the path **and** bumping `EXPECTED_FILES` 45 → 46 in one edit, per that
   config's own rule.
4. The 3 pre-existing failures and 6 errors remain open and were out of scope.

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/audit/cost_prices.json` — FOUND, valid JSON, row resolves via `compute()`
- All 6 model-default files — FOUND, all resolve to `claude-sonnet-5` and price non-`None`
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py` — FOUND, fallback mirrored
- `tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py` — FOUND, 30 passed / 1 pre-existing fail
- Commit `df131ea` — FOUND in `git log`, 9 files, 0 deletions, working tree clean
