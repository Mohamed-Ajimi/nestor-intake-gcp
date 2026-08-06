---
phase: quick-260806-dn8
plan: 01
subsystem: tribunal-engine/report-synthesis
tags: [anthropic, opus-5, synthesis, cost-table, g-10, g-7]
requires:
  - anthropic==0.104.1 (already pinned, already on the critical path)
  - AuditedLLMClient.anthropic_messages (already used by ~113 skeptic calls)
provides:
  - report synthesis on claude-opus-5 with 20,000-token output caps
  - anthropic/claude-opus-5 price row (no NULL cost_usd on synthesis rows)
  - focus_area_questions / relabel_facets — the label -> full-question resolver
affects:
  - tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
  - tribunal/nestor_pulse_sdk/audit/cost_prices.json
  - tribunal/cloudbuild.test-engine.yaml
tech-stack:
  added: []
  patterns: [CR-08 prefix-match resolver, function-local import to keep the module import graph light]
key-files:
  created:
    - tribunal/nestor_pulse_sdk/tests/test_synthesis_opus5.py
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
    - tribunal/nestor_pulse_sdk/audit/cost_prices.json
    - tribunal/cloudbuild.test-engine.yaml
    - tribunal/nestor_pulse_sdk/tests/test_synthesize_report.py
    - tribunal/nestor_pulse_sdk/tests/test_citation_anchors.py
    - tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
    - tribunal/nestor_pulse_sdk/tests/test_report_sections.py
decisions:
  - The output cap ceiling is the anthropic SDK, not the model — 21,333, asserted as arithmetic
  - temperature/top_p/top_k dropped, not ported — HTTP 400 on Opus 5 with thinking on
  - A refusal discards partial content and takes the existing degraded path
  - Registered the new test file in cloudbuild.test-engine.yaml (43 -> 44), which the plan did not ask for
metrics:
  duration: ~75 min
  completed: 2026-08-06
  commits: 3
  tasks: 3 of 3
---

# Quick Task 260806-dn8: Synthesis on Opus 5, Uncapped, G-10 Closed — Summary

Tribunal report synthesis now runs on `claude-opus-5` via `audited.anthropic_messages`
with 20,000-token output caps, a real price row, and section headings that carry the
client's full question instead of the 120-character join key.

## ⛔ NOT DEPLOYED

Nothing was built, pushed or deployed. **No `gcloud` command ran at any point in this task.**
Three commits sit on `master` at `70f9f11`; the live Tribunal images are unchanged.

**What the operator must re-run before any measured run:**

1. `gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml` — the
   engine gate, now expecting **44 of 44** files (was 43). Read the build TEXT via
   `gcloud builds describe`; `builds submit | tail` returns the PIPE's status.
2. `gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml` — 13 files.
3. A **new Tribunal image build + deploy** of `tribunal-api` and `tribunal-worker`.
   This change is inert until then.
4. **All five 15.8 pre-flight gates (Q-PRE-0…Q-PRE-4) must be re-run.** The rebuild in
   step 3 invalidates the digest baseline verified 2026-08-06 and makes 15.8-14's deploy
   record stale. Q-PRE-4 (`roles/logging.logWriter` on `nestor-run@`) was still unpaid at
   the time of writing.
5. Assert `gcloud config get account` = `tools@dotto.be` and `project` =
   `project-cb01b861-cb4a-438d-b9a` immediately before **every** gcloud operation.

## What Was Built

### Task 1 — the three report-writing calls moved to Anthropic (`74cdf94`)

`final_synthesis_audited`, `_one_section` and the wrap call now reach
`audited.anthropic_messages` on `claude-opus-5`. The distiller, conflict detector and
scrubber are untouched — **4 `gemini_generate` call sites remain** (`_DISTILLER_MODEL` ×2,
`_CONFLICT_MODEL`, `_SCRUB_MODEL`), down from 7.

- `_make_synthesis_config` **replaced**, not adapted, by `_synthesis_kwargs(prompt,
  max_tokens)`. The old function returned a `google.genai` config *or `None`*, and both
  call sites turned `None` into "send no config at all". Anthropic requires `max_tokens`
  and `messages`, so the optional shape could not survive the port.
- `temperature=0.2` **dropped**. With thinking on by default, `temperature` / `top_p` /
  `top_k` are HTTP 400 on Opus 5. `thinking` and `budget_tokens` are deliberately not
  passed either. The docstring says so, so it is not "restored" later as a lost setting.
- `_synthesis_text(response) -> (text, refused)` reads `stop_reason` **first**, then joins
  **every** `type == "text"` block in order — never `content[0]`, because thinking blocks
  precede text blocks. Blocks are read through the existing
  `pipeline.tribunal.skeptic._block_get`, imported function-locally to keep this module's
  import graph light. It never raises.
- A refusal **discards any partial content** and takes the same degraded path as an empty
  response, with its own log line. `stop_reason == "max_tokens"` logs a WARNING naming the
  section and the cap.
- Every user-visible degraded string is byte-identical: `*(Section generation failed:
  {exc})*`, `*(Section generation returned no content.)*`, and `final_synthesis_audited`
  returning `""`. `_SYNTHESIS_SYSTEM` is byte-identical to the base commit (verified by
  `diff`).

### Task 2 — caps raised, price row added (`74cdf94` + `5e6425c`)

- `_ANTHROPIC_NONSTREAMING_MAX_TOKENS = 21_333`, with the derivation in a comment. Both
  `_SECTION_MAX_TOKENS` and `_WRAP_MAX_TOKENS` moved 8192 → **20,000**. The test spells
  the arithmetic (`int(600 * 128_000 / 3600)`) rather than copying the literal, and asserts
  the bound bites exactly where the SDK's guard does (21,333 passes, 21,334 does not).
- `anthropic/claude-opus-5` added to `cost_prices.json` with all four rate fields and a
  `_claude_opus_5_source` comment recording that `cache_read`/`cache_creation_5m` are
  **derived** (0.1× / 1.25× of `prompt`, the same derivation every other `anthropic/*` row
  uses) and **inert today** — nothing on the synthesis path sends `cache_control`.
- `final_synthesis_audited`'s `max_tokens: int = 16384` default left alone; a test asserts
  it is inside the bound.

### Task 3 — G-10 closed (`70f9f11`)

One resolver, spelled once:

- `focus_area_questions(mission_brief) -> {label: full_question}`. The full text was
  **already in the brief** — `_compose_parent_assignment` joins the two halves with exactly
  one blank line after collapsing whitespace *inside each half*, so the first paragraph of
  `research_prompt` is the client's untruncated question. No new kwarg, no new plumbing.
- `relabel_facets(counts, brief)` — the thin display wrapper `pipeline.py` calls, so
  `pipeline.py` carries no logic of its own.

The match is CR-08's **prefix test** (`pipeline.py:1928`, "a label is a PREFIX of its text
by construction"). **No new hardcoded 120** — `grep -n "120" steps.py` returns only two
docstring-prose lines. The label's whitespace is collapsed before comparison, because
comparing a raw label against collapsed text is the CR-01 defect exactly.

All four degenerate briefs fall back to the label, each with its own assertion: no
`research_prompt`; the `intake.py` assignment shape; a question-less brief whose first
paragraph is the BRIEF (F6); and no `focus_areas` at all. Two more were added: a
`research_prompt` equal to the label, and a label carrying an interior newline.

`fa` stays the key everywhere it is a key — `render_fact_ledger(facet=fa)`, the
`included_focus_areas` filter, the `focus_areas` list. `extract_focus_areas` is asserted to
still return the **labels**.

## The G-10 RED Proof — verbatim, against pristine HEAD (`7ad3fc8`)

Run with a **gemini-shaped** fake, because at HEAD `synthesize_report` still called
`audited.gemini_generate`. Command:

```
cd tribunal && <venv>/python.exe -m pytest <scratchpad>/test_g10_red_prechange.py -q -p no:cacheprovider --no-header
```

```
FF                                                                       [100%]
================================== FAILURES ===================================
___ test_g10_the_heading_carries_the_full_client_question_not_the_join_key ____

    def test_g10_the_heading_carries_the_full_client_question_not_the_join_key():
        audited = CapturingAudited()
        report = _run(
            synthesize_report(
                mission_brief=BRIEF,
                provider_reports=PROVIDER_REPORTS,
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        heads = [ln for ln in report.splitlines() if ln.startswith("## ")]
>       assert f"## {FULL_QUESTION}" in heads, (
            "G-10: the section heading must render the client's FULL question.\n"
            f"  rendered headings: {heads!r}"
        )
E       AssertionError: G-10: the section heading must render the client's FULL question.
E           rendered headings: ['## Executive Summary', '## Welke fuel retailers in Europa passen vandaag dynamic pricing toe op brandstof en/of shopproducten, hoe wordt dit operat', '## Cross-cutting Synthesis', '## Sources']
E       assert '## Welke fuel retailers in Europa passen vandaag dynamic pricing toe op brandstof en/of shopproducten, hoe wordt dit operationeel ingericht en wat levert het op?' in ['## Executive Summary', '## Welke fuel retailers in Europa passen vandaag dynamic pricing toe op brandstof en/of shopproducten, hoe wordt dit operat', '## Cross-cutting Synthesis', '## Sources']

..\..\..\..\scratchpad\test_g10_red_prechange.py:75: AssertionError
____________ test_g10_the_section_prompt_quotes_the_full_question _____________

    def test_g10_the_section_prompt_quotes_the_full_question():
        ...
>       assert FULL_QUESTION in section_prompt, (
            "G-10: the section assignment must quote the full question, not the label."
        )
E       AssertionError: G-10: the section assignment must quote the full question, not the label.
E       assert 'Welke fuel retailers in Europa passen vandaag dynamic pricing toe op brandstof en/of shopproducten, hoe wordt dit operationeel ingericht en wat levert het op?' in 'CLIENT BRIEF / RESEARCH REQUEST:\nResearch fuel retail pricing.\n\nYOUR ASSIGNMENT: write ONE markdown section of the...Fact-checked research ---\n\n### Provider: gemini\n\nResearch prose.\n\n--- End research ---\n\nWrite the section now.'

..\..\..\..\scratchpad\test_g10_red_prechange.py:96: AssertionError
=========================== short test summary info ===========================
FAILED ...::test_g10_the_heading_carries_the_full_client_question_not_the_join_key
FAILED ...::test_g10_the_section_prompt_quotes_the_full_question
2 failed in 4.80s
```

**The failure output reproduces the shipped symptom exactly**: the heading ends
`...hoe wordt dit operat`, which is the string the operator read in run `368ff3a0`'s
delivered report.

## The G-7 RED Proof — verbatim, before the price row was added

```
$ python -c "from nestor_pulse_sdk.audit import cost_table; print(repr(cost_table.compute(
    provider='anthropic', model='claude-opus-5', prompt_tokens=1_000_000,
    completion_tokens=1_000_000, cached_tokens=0)))"
Unknown LLM model cost: provider='anthropic' model='claude-opus-5' -- writing NULL cost_usd (Pitfall 5)
PRE-CHANGE compute(anthropic/claude-opus-5) = None
```

After: `Decimal('30.00000000')` ($5 in + $25 out). Had the port shipped without this row,
the three most expensive calls of every run would have written NULL `cost_usd` and
`SUM(cost_usd)` would have silently skipped them.

A third RED was captured for Task 3's shipped test module: `tests/test_synthesis_opus5.py`
failed collection with
`ImportError: cannot import name 'focus_area_questions' from '...synthesis.steps'`.

## Test Results — as measured

**Runner:** `C:\Users\ajimimo\Desktop\MOELD\Nestor\.venv\Scripts\python.exe`, **Python
3.11.9**. Its package set matches `tribunal/requirements.txt` exactly on every relevant
pin: `pytest==8.4.2`, `pytest-asyncio==0.26.0`, `anthropic==0.104.1`,
`google-genai==1.75.0`, `openai==2.38.0`. This is a better runner than a scratchpad venv
built from gcloud's bundled Python 3.14 — Python 3.11 does not have the
`inspect.getsource`/`__doc__` dedent trap, and `openai` is present, so neither of those
known local-failure classes fires here at all.

### The engine gate — the exact file list from `cloudbuild.test-engine.yaml`

```
cd tribunal && <venv>/python.exe -m pytest <the N paths named in the yaml> -m "not live" -q -p no:cacheprovider --no-header
```

| Tree | Files | passed | failed | skipped | errors |
|------|-------|--------|--------|---------|--------|
| Base `7ad3fc8` (pristine) | 43 | **1809** | 0 | 13 | 6 |
| After all 3 tasks | 44 | **1850** | 0 | 13 | 6 |

**Delta = +41, which is exactly the 41 tests in the new `test_synthesis_opus5.py`.**
Nothing else moved.

### The gates config

```
cd tribunal && <venv>/python.exe -m pytest <the 13 paths in cloudbuild.test-gates.yaml> -m "not live" -q
```

**187 passed, 2 deselected** — flat, and byte-identical to Cloud Build's last recorded
`68699517`. A flat 187 is the correct result here.

### Reconciliation against the known local-failure arithmetic

- **The 6 errors are the Windows `PYTEST_CURRENT_TEST` 32767-char limit**, verbatim
  `ValueError: the environment variable is longer than 32767 characters`, all at *setup*
  of hostile-input parametrised tests: 4 in `test_dispatch_pii.py::test_never_raises` and
  2 in `test_fact_list_parser.py::test_parser_never_raises`. **They are present
  identically at the base commit**, so they are not this change. The brief estimated ~3;
  the measured number is 6.
- **The Python 3.14 `test_run_events_api.py` class did not fire** — this runner is 3.11.
- **The "`openai` absent" class did not fire** — `openai==2.38.0` is installed. Skipped
  count is 13 locally, which matches Cloud Build's 13 rather than the 17 the brief
  predicted for an `openai`-less environment. That is the same reason.
- **Cloud Build `3a7a580a` recorded 1812 passed at 43 files; this runner records 1809 +
  6 errored = 1815 collected-and-would-have-passed at the same 43 files.** A 3-item
  difference in the opposite direction to the errors, i.e. this machine collects 3 more
  items than Cloud Build did. I did **not** chase it: `git log 8dc2fa3..HEAD -- tribunal/`
  returns **0 commits**, so the tree is byte-identical to what Cloud Build ran, and the
  residual is environmental parametrisation. **It is stated rather than resolved, and it
  is the one number in this SUMMARY that is not fully accounted for.**

### Files that could NOT be collected locally — none

Both `test_engine_e2e_stubbed.py` and `test_tribunal_pipeline.py` imported and ran here
(`httpx` and `sqlalchemy` are both installed in this venv), contrary to the brief's
expectation. `test_tribunal_pipeline.py` + `test_factlist_fallback.py` = **100 passed**.
The `ast`-lift harness was not used anywhere.

### Verification of the untouched caps

```
git diff 7ad3fc8 -- .../workshop.py .../brief_input.py   ->  0 lines (EMPTY)
git diff 7ad3fc8 -- .../pipeline.py | grep -c GATE_DECISION_CONTEXT  ->  0
```

`_LABEL_MAX_CHARS` (120), `_GATE_DECISION_CONTEXT_CHARS`, `_QUESTION_MAX_CHARS` (400 /
600) and `_DECISION_MAX_CHARS` (400 / 4000) are byte-identical to the base commit;
`_GATE_DECISION_CONTEXT_CHARS`' block was `diff`'d line-for-line and is IDENTICAL (only
its line number moved, by the 3 lines of the new import).

The whole `pipeline.py` diff is **two hunks**: the `relabel_facets` import and the
`claims_per_facet=` line.

## Deviations from Plan

### 1. [Rule 1 — plan fact wrong] F8 named THREE fakes; there are FOUR

- **Found during:** Task 1, at the engine-gate run.
- **Issue:** `tests/test_report_sections.py` carries its own `RecordingAudited` +
  `_FakeResponse` that also drives `synthesize_report` through the real pipeline. F8's
  cross-reference (`grep -l gemini_generate` × `grep -l 'synthesize_report|
  final_synthesis_audited'`) missed it. That file **is** in the engine gate.
- **How it surfaced, and this is the good news:** the test's own guard bit —
  `AssertionError: the fake recorded nothing — the test proves nothing`, with the log
  line `'RecordingAudited' object has no attribute 'anthropic_messages'`. A tolerant
  assertion would have gone green on a fake that recorded zero prompts.
- **Fix:** same swap as the other three.
- **Commit:** `74cdf94`.

The same cross-reference also surfaces `test_factlist_fallback.py` and
`test_tribunal_pipeline.py`. Both were checked and **neither needed a change**: the first
mentions `synthesize_report` only in docstrings and its Gemini fake drives the distiller;
the second **monkeypatches `synthesize_report` wholesale**, so it never reaches a provider
surface. Both green.

### 2. [Rule 1 — pre-existing bug] `test_synthesize_report.py::_run` used `asyncio.get_event_loop()`

- **Found during:** Task 1.
- **Issue:** `RuntimeError: There is no current event loop in thread 'MainThread'` on
  Python ≥ 3.10 once any earlier test in the session has closed the loop. **5 of the
  file's 7 tests fail in a combined run and all 7 pass in isolation.**
- **Proved pre-existing:** stashed my changes, re-ran the 43-file gate + that file on
  pristine `7ad3fc8` → the same 5 failures.
- **Why it survived:** the file is registered in **neither** cloudbuild config, so CI has
  never executed it.
- **Fix applied** (it owns its own loop now) rather than deferred, because the file is
  named in this plan's own `files_modified` and leaving a known-red file there would have
  made every subsequent verification run ambiguous. Commit `74cdf94`.

### 3. [Rule 2 — missing critical] Registered `test_synthesis_opus5.py` in the engine gate

- **Issue:** the plan created a new test file but did not register it. An unregistered
  test file is never executed in CI — the exact silent-skip class that
  `cloudbuild.test-engine.yaml`'s own 100-line preamble exists to prevent, and that this
  repository has booked repeatedly.
- **Fix:** path + `EXPECTED_FILES` 43 → 44 in ONE edit and ONE commit, per that config's
  stated rule, with a commentary block naming the owner and the reason. Verified: the
  yaml parses, 44 unique paths are named, all 44 exist on disk, and the build-step arg is
  **5,282 characters** — well under the 10,000-char Cloud Build limit that once broke this
  file.
- **Commit:** `70f9f11`.

### 4. [Plan gate defect] Task 1's third `<automated>` check expects the wrong number

- The plan asserts `grep -n "gemini_generate" steps.py | grep -v '^ *[0-9]*: *#' | wc -l`
  should be **3**. Two things are wrong with it:
  1. The `grep -v` filter is a no-op — `grep -n` output is `1854:            response =
     ...`, which never matches `^ *[0-9]*: *#`. Docstring lines are therefore counted.
  2. **3 is a count of MODELS, not call sites.** `_DISTILLER_MODEL` has **two** call sites
     (`_distill_unit` and `_retry_fact_list`), so the correct call-site count is **4**.
- **Measured:** pristine HEAD had 7 `await audited.gemini_generate(` call sites; the tree
  now has 4, at `_DISTILLER_MODEL` ×2, `_CONFLICT_MODEL` and `_SCRUB_MODEL`. Exactly the
  3 report-writer sites were removed, which is what the gate meant to check. **The
  invariant holds; the number in the plan does not.** Nothing was changed to satisfy it.

### 5. [Judgment call, flagged as the plan asked] The third prompt site

Task 3a's flagged third display site — the section prompt's assignment quote at
`steps.py:1024` — **was included**, as the plan recommended. It is one line
(`f"  \"{title}\"\n"`) and is trivially revertible if the operator disagrees. The
reasoning is in the code comment.

## Threat Flags

None. No new network endpoint, auth path, file-access pattern or schema change. The one
new trust-boundary crossing — client-authored question text reaching a rendered `##`
heading — is `T-dn8-01` in the plan's own register and is mitigated as specified: the text
is whitespace-collapsed upstream by `_compose_parent_assignment`, so it cannot forge block
structure or a second heading, and the prefix test means a value that is not the label's
own expansion is never used.

## Known Stubs

None. No hardcoded empty value, placeholder string or unwired component was introduced.

## Operator Notes Carried Forward

1. **Synthesis cost rises roughly 4–7×**, from ~$1.04 to ~$4–7 per run. Opus 5's thinking
   tokens bill as OUTPUT, so the 20,000 cap is a cost lever as well as a quality one.
2. **Prompt caching is the obvious next lever and is NOT implemented.** Every section call
   repeats the identical `reports_concatenated` block. The price row's `cache_read` /
   `cache_creation_5m` fields are already correct for when it lands. It needs a
   cache-breakpoint design plus a check that the parallel `asyncio.gather` does not race
   the cache write.
3. **The 600 s per-call timeout is now a live failure mode.** The SDK sets it. A section
   that times out surfaces as `*(Section generation failed: ...)*` in the delivered report
   — visible, not silent, which is intended.
4. **Two pre-existing gate gaps, neither fixed here** (both already booked in STATE.md):
   `test_tribunal_pipeline.py` and `test_synthesize_report.py` are in **neither**
   cloudbuild config. The second is what let deviation #2 live.

## Self-Check: PASSED

Created files exist:
- `FOUND: tribunal/nestor_pulse_sdk/tests/test_synthesis_opus5.py`
- `FOUND: .planning/quick/260806-dn8-synthesis-opus5-uncap-g10/260806-dn8-SUMMARY.md`

Commits exist on `master`:
- `FOUND: 74cdf94` — feat(dn8-01): move Tribunal report synthesis to claude-opus-5
- `FOUND: 5e6425c` — feat(dn8-02): add the anthropic/claude-opus-5 price row
- `FOUND: 70f9f11` — feat(dn8-03): G-10 — render the full client question, not the join key

`git diff --diff-filter=D --name-only 7ad3fc8 HEAD` is **empty** — no file was deleted.
Working tree clean apart from this SUMMARY.
