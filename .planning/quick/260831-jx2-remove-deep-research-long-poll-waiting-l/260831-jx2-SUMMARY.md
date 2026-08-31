---
quick_id: 260831-jx2
status: complete
base: 49f2eb5
head: df36c14
deployed: false
date: 2026-08-31
files_modified:
  - tribunal/nestor_pulse_sdk/audit/audited_llm_client.py
  - tribunal/nestor_pulse_sdk/tests/test_own_researcher.py
commits:
  - 44541be  test(260831-jx2)  invert the long-poll test to guard feed silence  [RED]
  - 972e21d  feat(260831-jx2)  remove the four waiting emissions + dead constant  [GREEN]
  - df36c14  docs(260831-jx2)  correct the test file's own stale coverage note  [deviation]
---

# Quick 260831-jx2 — remove the deep-research long-poll waiting lines

## What was asked

Operator request 2026-08-31, verbatim: **"remove these logs from deep research"**. The operator
watches the live run feed and judged the long-poll waiting lines noise, and accepts the consequence:
full feed silence for up to 35 minutes during a deep-research call.

## What changed

Four `kind="thinking"` emissions deleted from the two deep-research poll loops in
`audited_llm_client.py`:

| # | Provider | Emission | Was at |
|---|----------|----------|--------|
| 1 | Google | dispatch announcement (`Waiting on Google … normal shape of this call.`) | ~:1492-1512 |
| 2 | Google | strided heartbeat (`Still waiting on Google … THIS IS A WAIT, NOT A STALL.`) | ~:1584-1615 |
| 3 | OpenAI | dispatch announcement (`Waiting on OpenAI …`) | ~:1864-1883 |
| 4 | OpenAI | strided heartbeat (`Still waiting on OpenAI … NOT A STALL.`) | ~:1938-1962 |

Plus the now-dead `_POLL_EVENT_STRIDE` constant and its explanatory paragraph. After the four
deletions the scoped grep returned **zero surviving source references**, so it was removed outright
rather than kept. Its `NESTOR_RUN_EVENT_POLL_STRIDE` override is set by no deploy script in this repo,
so nothing is stranded.

Net: **25 insertions, 117 deletions** in the source file.

### Deliberately untouched

All five `agent_fail` emissions survive and were re-asserted present by gate: Google job-reported-fail,
Google gave-up, OpenAI failed/cancelled, OpenAI incomplete, OpenAI gave-up. Also untouched: the
rejoin/resume events, the `safe_job_id` guard blocks, `RESUME_REDISPATCH`, the `_CURRENT_RUN`
ContextVar, the `run_events` import, every `log.*` call, `import os` (still used at nine other sites),
and every cloudbuild YAML.

### Three stale narratives corrected

The plan flagged two; a third was found during execution (see Deviations).

1. **Module docstring** (`audited_llm_client.py:34`) claimed the loops narrate "dispatch, a strided
   progress line stating elapsed minutes and attempt number IN WORDS". Trimmed to what remains.
2. **Block comment** (`:96-112`) claimed "The events below are the fix". Replaced with the removal
   note. **The 2026-07-27 incident history was kept** — a run mid long-poll misread as a stall — and
   is now flagged as a risk the silence makes *easier*, not as a solved problem, with a note that
   restoring the heartbeat is a decision to re-open with the operator rather than a bug to fix.
3. **Test file module docstring** item 25 — see Deviations.

## The RED proof

The test was inverted and run against the **still-unedited** source at commit `44541be`. It failed,
and the failure output enumerated exactly the four lines being removed — one dispatch plus three
heartbeats at polls 10, 20 and 30:

```
nestor_pulse_sdk\tests\test_own_researcher.py:1327: in test_a_long_poll_emits_no_waiting_chatter
    assert not [text for text in thinking if text.startswith("Waiting on")], (
E   AssertionError: the dispatch announcement was removed on operator request 2026-08-31;
    the feed emitted it anyway: [
      'Waiting on Google deep-research-max-preview-04-2026 - background research dispatched,
       polling every 30s for up to 35 minutes. A long silence here is the normal shape of this call.',
      'Still waiting on Google ... 5 min elapsed, poll 10 of 70, ... THIS IS A WAIT, NOT A STALL.',
      'Still waiting on Google ... 10 min elapsed, poll 20 of 70, ... THIS IS A WAIT, NOT A STALL.',
      'Still waiting on Google ... 15 min elapsed, poll 30 of 70, ... THIS IS A WAIT, NOT A STALL.']
1 failed in 1.87s
```

The red was real and it was specific. The assertions were not vacuous.

## The GREEN result — real numbers

The suite **did** run locally. F1 was correct: `tribunal/pyproject.toml` requires `>=3.11` and the
gcloud bundled interpreter is **Python 3.11.9**. A scratchpad venv was built from it and dependencies
installed one at a time as each collection error named them: `pytest 9.1.1`, `pytest-asyncio 1.4.0`,
`httpx 0.28.1`, then `sqlalchemy`, `fastapi`, `pyyaml`, then `openai` and `alembic`.

| Stage | Result |
|-------|--------|
| Baseline before any edit (2 files) | **69 passed, 0 failed, 0 skipped** |
| New test vs. unedited source | **1 failed** (the RED above) |
| After the fix (2 files) | **69 passed, 0 failed, 0 skipped** |

Reconciliation: the total is **unchanged at 69** — one test renamed, none added, none removed. No
drift to explain.

`openai` was installed deliberately: the first baseline read `65 passed, 4 skipped`, and those 4 skips
were the OpenAI resume tests in `test_provider_resume.py`. Since this change edits OpenAI code, a skip
there would have been a hole. Installing `openai` converted all 4 to real passes. **There are zero
skips in the reported numbers.**

The three named tests, individually confirmed:

```
test_a_long_poll_emits_no_waiting_chatter                     PASSED   (was RED)
test_a_poll_with_no_run_context_emits_nothing                 PASSED   (untouched)
test_a_rejoined_job_says_so_and_a_refused_id_is_never_quoted  PASSED   (untouched)
```

### Blast radius, measured rather than assumed

The plan scoped testing to two files. I widened it: 22 test files reference `audited_llm_client` or
`run_events`. Running all 22 gave **10 failed, 747 passed, 3 skipped** — all 10 in
`test_outcomes_spike.py`, which I never touched, and which **passes in isolation** (order-dependent
pollution from an unraisable `LLMJudgeGate.grade` coroutine, `KeyError: '__import__'`).

Rather than assert those were pre-existing, I measured it. I temporarily reverted only my two files to
`49f2eb5` with a targeted `git checkout 49f2eb5 -- <two paths>` and re-ran the identical 22-file batch
in the identical environment:

| | failed | passed | skipped |
|---|---|---|---|
| At base `49f2eb5` | 10 | 747 | 3 |
| At HEAD (my change) | 10 | 747 | 3 |

**Byte-identical counts, and the same 10 test ids.** The failures are pre-existing and unrelated. The
two files were then restored with `git checkout HEAD -- <two paths>`; `git status --porcelain` on
`tribunal/` came back empty, confirming an exact restore. No `git stash`, no `git clean`, no blanket
reset was used at any point — my work was already committed at `972e21d` before the experiment.

(An earlier run showed 26 failures; 16 of those were `test_yield_schema.py` failing on a missing
`alembic`, which I then installed. That was my venv, not the repo.)

## Gates

Scoped to named paths per F2, because a repo-root recursive grep matches the stale
`.claude/worktrees/agent-af281d695d9b34c35/` copy and the `.pyc`, and would read red on correct code.
That orphaned tree was not edited or deleted.

```
ABSENCE+PRESENCE OK            # 0 hits for the 5 removed phrases; all 5 agent_fail sentinels present
SOURCE CLEAN + STRIDE FULLY REMOVED
py_compile OK                  # both files
```

- `git diff --name-only 49f2eb5..HEAD` returns **exactly the two planned paths**.
- No YAML changed. `cloudbuild.test-engine.yaml` still reads `EXPECTED_FILES=45`, with both test files
  still listed at `:498` and `:502`. No file added or removed, so F6 holds untouched.
- The removed literals still appear in `test_own_researcher.py` — correct and required, since the new
  test asserts their absence and must name them. Repo-wide, that test file is now the **only** source
  file mentioning them (F5 confirmed independently).

## Deviations from plan

**1. [Rule 1 — stale narrative] A third false docstring, in the test file.**
- **Found during:** Task 3, reading the file after the rename.
- **Issue:** `test_own_researcher.py`'s module docstring, coverage item 25, still advertised *"a long
  provider poll narrates itself in words: elapsed minutes, attempt number, and the sentence that
  separates a wait from a stall"* — the precise behaviour just deleted, and the exact opposite of what
  test 25 now asserts. The plan's F3 caught this defect class at two sites in the source but did not
  check the test file.
- **Fix:** item 25 rewritten to describe the silence contract and cite the operator request.
- **Commit:** `df36c14`

**2. [Gate discipline] A gate went red on correct code; the prose was changed, not the gate.**
- **Found during:** Task 2, first run of the absence gate.
- **Issue:** My replacement comment quoted the removed strings verbatim to explain what had gone —
  so it tripped the `NOT A STALL` absence grep and the `_POLL_EVENT_STRIDE` zero-reference grep. Two
  hits, both in a comment, neither a live emission.
- **Resolution:** The gate was sound as the plan wrote it; my comment was the problem. I reworded the
  comment to describe the removal without reciting it, and left a note in the file explaining *why* the
  wording is not quoted there, so the next person does not re-introduce it. The gate was not weakened
  or rescoped and the fix was not undone.
- **Worth recording:** `NESTOR_RUN_EVENT_POLL_STRIDE` does **not** contain `_POLL_EVENT_STRIDE` as a
  substring (`_EVENT_POLL_STRIDE` vs `_POLL_EVENT_STRIDE` — same words, different order). The env var
  name is safe to mention in prose and was kept, since an operator may have it set somewhere outside
  this repo.

## Status: NOT DEPLOYED

- **No deploy was performed. No build, no `gcloud` command of any kind was run.** This task ended at a
  commit, as instructed.
- The change **ships with the next `tribunal-worker` / `tribunal-api` build**. Until that build and
  deploy happen, the live services still emit the waiting lines.
- **A research run that has already finished is unaffected.** These emissions only ever fired inside a
  live poll loop, and nothing rewrites a completed run's feed. Historical runs keep their existing
  lines.
- The audit row, its payload and its hash chain were never touched by these events and are not touched
  by their removal.

## What is now UNOBSERVED

Stated plainly, because the tests prove a contract and not a live outcome:

1. **Nobody has watched the live feed go quiet.** The silence is proven only by a fake-HTTP harness
   asserting three string shapes are absent. Only the **next real deep-research run**, watched by the
   operator on the live feed, demonstrates the operator-visible outcome they asked for.
2. **The OpenAI path has no direct silence test.** `test_a_long_poll_emits_no_waiting_chatter` drives
   the **Gemini** loop. Blocks 3 and 4 (OpenAI) are covered only by the static absence grep and by the
   15 `test_provider_resume.py` tests continuing to pass — not by a 31-poll OpenAI silence assertion.
3. **The 35-minute silence has not been experienced.** The harness monkeypatches `asyncio.sleep` to a
   no-op, so 31 polls complete in milliseconds. Nobody has sat through the real wait with no feed
   output, which is the thing the 2026-07-27 incident says is easy to misread.
4. **The deploy itself remains unexercised for this change.** Per standing project state, the deployed
   code path is separate from what is committed here.
</content>
