# Quick Task 260901-lf2 — Switch the tribunal Flash stages to gemini-3.7-flash

**Date:** 2026-09-01
**Base commit:** `df131ea` (asserted before any edit)
**Commit:** `300be1a` — ONE atomic commit, 7 files, +91 / −9, zero deletions
**Status:** COMMITTED, **NOT BUILT, NOT DEPLOYED, NEVER RUN**

---

## 1. What changed

### Five model swaps, `gemini-2.5-flash` → `gemini-3.7-flash`

| # | File | Symbol | Line (post-edit) |
|---|------|--------|------------------|
| 1 | `tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py` | `_GATE_MODEL` | 87 |
| 2 | `tribunal/nestor_pulse_sdk/pipeline/tribunal/grouping.py` | `_GROUPER_MODEL` | 100 |
| 3 | `tribunal/nestor_pulse_sdk/pipeline/tribunal/report_planner.py` | `_PLANNER_MODEL` | 44 |
| 4 | `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py` | `_RANK_MODEL` — **env default only**, `os.environ.get` preserved | 225 |
| 5 | `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py` | fallback literal mirroring `_RANK_MODEL` | 925 |

### ⚠ A SIXTH CALL SITE MOVES THAT THE TASK DID NOT LIST

`workshop_evolve.py:219`:

```python
_META_MODEL = os.environ.get(
    "NESTOR_TRIBUNAL_WORKSHOP_META_MODEL", workshop_rank._RANK_MODEL
)
```

The evolve **meta-review** call takes its default *from* `_RANK_MODEL`, so it moved
to 3.7-flash **by inheritance**. This file was not edited and needed no edit — but
it means **six** effective call sites changed behaviour, not five. Recorded in a
warning comment at `_RANK_MODEL` so the coupling is visible from the site being
edited. No evidence was gathered specifically for the meta-review prompt.

### The distiller was deliberately left alone

`pipeline/synthesis/steps.py:1456` `_DISTILLER_MODEL` **stays on `gemini-2.5-flash`**.
A 25-line comment was added above it (the only change to that file — `+25 / −0`,
the assignment itself is untouched) recording both reasons:

1. **It was not exercised by the evidence.** The decision rests on replaying the 267
   real Flash prompts from run `fb9484dd`. This path is the D-14 fallback that only
   fires when a stream fails to return a fact list, and every stream complied in
   `fb9484dd` — so it contributed **zero** of those 267 prompts. There is no
   evidence at all for its behaviour under 3.7.
2. **Documented format fragility.** The V-01 defect: the distiller returned 278
   well-formed claims and the parser dropped every one because the model emitted the
   literal string `<TAB>` instead of a tab. A model swap on an unexercised,
   format-critical parser path is exactly the risk that produced that incident.

The comment also names `test_factlist_fallback.py`'s literal pin as the guard, so a
future editor finds the test and the reasoning together.

### Price table — one addition, two corrections

`tribunal/nestor_pulse_sdk/audit/cost_prices.json`

**ADDED** `google/gemini-3.7-flash`: `prompt 0.75`, `completion 3.75`,
`cache_read 0.075`, `cache_creation_5m 0`.
Comment `_gemini_3_7_flash_source` records that these are **introductory rates valid
through 2026-12-31, doubling to 1.50 / 7.50 / 0.15 on 2027-01-01**, with an explicit
instruction to change the numbers and the note together. (`_`-prefixed sibling keys
are the file's existing convention and are stripped by `_load_prices()` — verified in
`cost_table.py`, so the comment cannot be mistaken for a model row.)

**CORRECTED** (both rows previously **understated real spend**):

| Row | Field | Before | After |
|-----|-------|--------|-------|
| `google/gemini-2.5-flash` | prompt | 0.15 | **0.30** |
| `google/gemini-2.5-flash` | completion | 0.60 | **2.50** |
| `google/gemini-2.5-flash` | cache_read | 0.0375 | **0.03** |
| `google/gemini-2.5-pro` | cache_read | 0.3125 | **0.125** |

`gemini-2.5-pro` `prompt 1.25` / `completion 10.0` were left alone as instructed. Its
comment records the **tiered pricing** ($1.25/$10 at ≤200k prompt tokens, $2.50/$15
above) and that this table encodes only the lower tier — the same flat-rate
limitation already recorded for `gpt-5.6-sol`.

The `google/gemini-2.5-flash` row is **retained**: the distiller still calls it and
historical runs reference the key.

> **Consequence worth stating plainly:** `cost_usd` is computed and stored per row at
> write time. Correcting the table does **not** retroactively repair historical audit
> rows — every past run total computed from the old Flash row still understates its
> Flash cost. Recorded in the row comment.

---

## 2. Verification — real numbers

### 2.1 `compute()` proof through the real cost table

Run against `nestor_pulse_sdk.audit.cost_table.compute()` (not a JSON read):

```
ADDED ROW  google/gemini-3.7-flash
  compute("google","gemini-3.7-flash",1M,1M,0)  = 4.500000000   expect 4.50   OK
    prompt only     (1M,0,0)                    = 0.750000000   expect 0.75   OK
    completion only (0,1M,0)                    = 3.750000000   expect 3.75   OK
    cache_read only (1M,0,1M)                   = 0.075000000   expect 0.075  OK

CORRECTED ROW  google/gemini-2.5-flash
  compute("google","gemini-2.5-flash",1M,1M,0)  = 2.80000000    expect 2.80   OK
    prompt only     (1M,0,0)                    = 0.30000000    expect 0.30   OK
    completion only (0,1M,0)                    = 2.50000000    expect 2.50   OK
    cache_read only (1M,0,1M)                   = 0.03000000    expect 0.03   OK

CORRECTED ROW  google/gemini-2.5-pro
    cache_read only (1M,0,1M)                   = 0.125000000   expect 0.125  OK
    prompt only     (unchanged)                 = 1.250000000   expect 1.25   OK
    completion only (unchanged)                 = 10.000000000  expect 10.0   OK
```

Both headline figures landed exactly as the task predicted: **4.50** (0.75+3.75) and
**2.80** (0.30+2.50). Each rate was also exercised **in isolation** (1M tokens in
exactly one bucket) so a transposed pair cannot hide inside a summed total.

**NEGATIVE CONTROL — the lookup bites:**

```
compute('google','gemini-4.9-flash-does-not-exist',1M,1M,0) = None            OK
  ...and the loader logged the real Pitfall-5 warning:
  "Unknown LLM model cost: provider='google' model='gemini-4.9-flash-does-not-exist'
   -- writing NULL cost_usd (Pitfall 5)"
positive control: real row is not None and not 0 -> Decimal('4.500000000')     OK
```

The negative control is what makes the twelve OKs above mean something: an invented
name returns `None` (the honest unknown branch), not a confident `Decimal("0")`.

### 2.2 JSON validity

`json.loads` succeeded. 40 top-level keys = 14 `_`-comment keys (stripped by
`_load_prices`) + **26 model rows**.

### 2.3 The `gemini-2.5-flash` grep — and why the raw grep is misleading

The task's exact grep returns **2** matches, not 1:

```
$ grep -rn -I '"gemini-2.5-flash"' tribunal/nestor_pulse_sdk/ --exclude-dir=tests --exclude-dir=__pycache__
steps.py:1454:#: "gemini-2.5-flash"`), so changing it here turns that test RED. ...
steps.py:1456:_DISTILLER_MODEL = "gemini-2.5-flash"
```

**Line 1454 is prose inside a comment I wrote myself** — it quotes the test assertion
so the guard is findable. That is the documented "grep matches prose *about* the
thing" trap, and I introduced it. Reporting the raw count as "1" would have been
wrong; reporting it as "2 live sites" would also have been wrong.

So the count was settled by **AST**, parsing real `ast.Constant` string values and
excluding comments and docstrings:

```
LIVE string literal "gemini-2.5-flash": 1 site(s)
    steps.py:1456   ->  _DISTILLER_MODEL

LIVE string literal "gemini-3.7-flash": 5 site(s)
    gates.py:87              ->  _GATE_MODEL
    grouping.py:100          ->  _GROUPER_MODEL
    report_planner.py:44     ->  _PLANNER_MODEL
    workshop_admission.py:925->  model
    workshop_rank.py:225     ->  _RANK_MODEL
```

**Exactly one** live 2.5-flash site (the distiller) and **exactly five** live 3.7-flash
sites at the intended symbols. Re-run against the committed tree — same result.

### 2.4 Engine gate — baseline taken at `df131ea` BEFORE editing

File list extracted **programmatically** from `cloudbuild.test-engine.yaml` (not
transcribed): 45 paths, `EXPECTED_FILES=45`, all 45 present on disk.

| Run | Result |
|-----|--------|
| **Baseline @ `df131ea`** (first attempt) | 3 failed, 1943 passed, 13 skipped, 6 errors |
| **Baseline @ `df131ea`** (after installing `structlog`) | **0 failed, 1946 passed, 13 skipped, 6 errors** |
| **After the change** | **0 failed, 1946 passed, 13 skipped, 6 errors** |

**Identical.** Zero regressions.

Two environment facts, both proven rather than asserted:
- The initial 3 failures were `ModuleNotFoundError: No module named 'structlog'` — a
  gap in the scratchpad venv, not a code defect. Installing `structlog 26.1.0` cleared
  all three and the *baseline was re-taken before any edit*.
- The **6 errors are pre-existing and Windows-only**:
  `ValueError: the environment variable is longer than 32767 characters`, raised at
  *setup* of a parametrized test whose id is a multi-thousand-character string. Present
  at `df131ea` before any edit, identical count after (6 → 6). They would not occur on
  the Linux Cloud Build runner.

### 2.5 Second gate — `cloudbuild.test-gates.yaml` (13 files)

Not requested, but run because this change edits `gates.py` and `steps.py`, which that
config owns. Compared **pristine `df131ea`** (extracted via `git archive`, working tree
untouched — no stash, no worktree) against the changed tree:

| Tree | Result |
|------|--------|
| Pristine `df131ea` | 1 failed, 189 passed, 2 deselected |
| Changed | 1 failed, 189 passed, 2 deselected |

Identical. The single failure,
`test_claim_distiller.py::TestClaimDistillerNormalPath::test_thinking_disabled_in_kwargs`,
is **pre-existing at `df131ea`** and is on the distiller path this task did not change.

---

## 3. Tests touched: **NONE** — and why that is the right outcome

**No test file was edited.** I read every candidate before concluding that. The reason
no edit was needed is that the tests touching the changed symbols reference them
**symbolically**, so they follow the constants automatically:

| Test | Reference | Disposition |
|------|-----------|-------------|
| `test_gate_replay.py:864` | `set(audited.models) == {gates._GATE_MODEL}` | **Relationship** — preserved, follows the swap |
| `test_workshop_critique.py:699` | `... == grouping._GROUPER_MODEL` | **Relationship** — preserved, follows the swap |
| `test_factlist_fallback.py:1382` | `== [steps._DISTILLER_MODEL]` | **Relationship** — preserved |
| `test_factlist_fallback.py:1739` | `steps._DISTILLER_MODEL == "gemini-2.5-flash"` | **Literal pin, left RED-if-changed on purpose.** This is the guard enforcing "do not finish the job" on the distiller. Still green because the distiller did not move. |
| `test_audit_perf.py:216` | `("google","gemini-2.5-flash")` in a fake aggregation row | Arbitrary label; the 2.5-flash row is retained. Unaffected. |
| `test_feed_enrichment.py:673/681/711` | `model="gemini-2.5-flash"` in / out | **Pass-through identity test** with a stubbed cost (`"0.0123"`). A relationship test — preserved, not "updated". |
| `test_claim_distiller.py:252` | asserts distiller model | Distiller unchanged. Unaffected. |
| `test_cost_cache_write.py:226-231` | `gemini-2.5-pro` prompt 1.25 / completion 10.0 | Exercises **only** prompt+completion, which I did not change. `cache_read` is untouched by this test. Unaffected. |
| `test_cost_serpapi.py:454+` | `gpt-5.6-sol` rates | Unrelated model. Unaffected. |
| `test_gate_calibration.py:45,54` | docstring prose only | `@live`-marked, deselected. No assertion. |

The recorded call fixtures under `tests/fixtures/run_4cbb5311/recorded/` (38 files +
`index.json` + `REPORT.md`) name `gemini-2.5-flash` **hundreds of times**. These are
**historical records of a real past run** and were deliberately **not** touched —
rewriting them would falsify the audit fixture.

**Verified explicitly** that the two symbolic assertions actually execute rather than
passing vacuously: `test_gate_replay.py` runs **11 passed** on both trees, with
`_GATE_MODEL` now resolving to `gemini-3.7-flash`.

> **Honest caveat on that file:** `test_gate_replay.py` is in
> `cloudbuild.test-gates.yaml`, **not** in the engine gate — so the `_GATE_MODEL`
> assertion does **not** run in the 45-file engine gate at all. It was run separately
> here.
>
> One misleading intermediate result, recorded because it nearly became a false
> finding: running that test in a 3-test batch produced
> `RuntimeError: There is no current event loop in thread 'MainThread'`. Running the
> **same trio in the same order against pristine `df131ea`** reproduced the identical
> failure — it is a pre-existing test-ordering artifact of `asyncio.get_event_loop()`
> on Python 3.11, not a consequence of this change.

---

## 4. What is NOT proven

- **No run has executed on `gemini-3.7-flash`.** Not one. Every behavioural claim
  below comes from the replay, not from the pipeline.
- **The position-bias improvement was measured on TRUNCATED prompts.** The audit blobs
  cap request bodies at **2000 characters**, so the replay fed both models the same
  truncated text. That makes it a **fair A/B** — both sides saw identical input — but
  it is **not identical to the live call**, which sends the full prompt. The 69.9% vs
  58.4% figure is real and comparable; it is not a measurement of production behaviour.
- **The +$1.50/run projection is arithmetic over replayed token counts**, not an
  observed run total. Real cost depends on live token volumes.
- **`report_planner.py` is the site most exposed to truncation** and is unproven: it
  has the tightest output ceiling of the five (`_MAX_OUTPUT_TOKENS = 1536`) and 3.7
  spends output tokens on reasoning. Which of the 267 replayed prompts were planner
  prompts was not broken out, so only the aggregate zero-error result covers it.
- **`workshop_evolve._META_MODEL`** moved by inheritance with no evidence of its own.
- **3.7 thinks despite `thinkingConfig.thinkingBudget=0`.** The "thinking disabled"
  design constraint stated in the `gates.py`, `grouping.py` and `report_planner.py`
  module docstrings is now **an intent we request and do not get**. Annotated at each
  site rather than deleted, since the docstrings still correctly describe the intent.
- The 6 engine-gate errors and 1 gates-gate failure are pre-existing and were **not**
  fixed (out of scope).

---

## 5. Deploy requirement

**NOT DEPLOYED. NOT BUILT.** No `gcloud`, no build, no deploy was run — the task ended
at a commit, as instructed.

This change needs a **`tribunal-api` + `tribunal-worker`** build, because the edited
modules (`pipeline/tribunal/*`, `pipeline/synthesis/steps.py`, `audit/cost_prices.json`)
are imported by both service entrypoints.

⚠ **It must be built alongside the still-unbuilt `260901-j6w` Sonnet 5 change**, which
moved the six production tribunal defaults to `claude-sonnet-5` and is also sitting in
git undeployed. Two undeployed model changes now stack on the same services; deploying
one without the other ships a half-configured engine.

Per the recorded deploy rules: derive the surface **by import**, never by substring;
pin `--account tools@dotto.be` on every `gcloud` command (the config drifts
mid-session); and prove the revision by `status.imageDigest`, never by the mutable tag.

---

## Self-Check: PASSED

- `tribunal/nestor_pulse_sdk/audit/cost_prices.json` — FOUND, valid JSON, 26 model rows
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py` — FOUND, `_GATE_MODEL` = 3.7
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/grouping.py` — FOUND, `_GROUPER_MODEL` = 3.7
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/report_planner.py` — FOUND, `_PLANNER_MODEL` = 3.7
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py` — FOUND, `_RANK_MODEL` = 3.7, `os.environ.get` intact
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py` — FOUND, fallback = 3.7
- `tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py` — FOUND, `_DISTILLER_MODEL` still 2.5-flash
- Commit `300be1a` — FOUND in `git log`, 7 files, zero deletions
- Working tree clean apart from untracked `.claude/` (pre-existing, not mine)
