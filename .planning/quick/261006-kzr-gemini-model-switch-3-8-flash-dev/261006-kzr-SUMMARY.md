---
phase: quick-261006-kzr
plan: 01
subsystem: tribunal engine (Gemini call sites)
tags: [gemini, model-switch, thinking_level, cost_prices, dev-only]
requires: []
provides:
  - pipeline/gemini_config.py (GEMINI_FLASH_DEFAULT, GEMINI_FLASH_LITE_DEFAULT, build_thinking_config, resolve_temperature, build_generate_config)
  - env-overridable model + thinking level for all 8 Gemini sites
  - price rows google/gemini-3.8-flash, google/gemini-3.5-flash-lite
  - scripts/gemini_model_smoke.py (live per-site config probe)
affects: [tribunal-worker, tribunal-api (on next dev deploy)]
tech-stack:
  added: []
  patterns: [one shared config helper per provider family; env read at call time for temperature]
key-files:
  created:
    - tribunal/nestor_pulse_sdk/pipeline/gemini_config.py
    - tribunal/nestor_pulse_sdk/tests/test_gemini_config.py
    - tribunal/nestor_pulse_sdk/tests/test_gemini_sites.py
    - tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py
  modified:
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/grouping.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/report_planner.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_evolve.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py
    - tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py
    - tribunal/nestor_pulse_sdk/audit/cost_prices.json
    - tribunal/nestor_pulse_sdk/tests/test_factlist_fallback.py
    - tribunal/nestor_pulse_sdk/tests/test_claim_distiller.py
decisions:
  - "D-261006-kzr: Gemini sites move to gemini-3.8-flash (gates, grouping, planner, workshop rank/meta/admission at low; conflict, scrub at high) and gemini-3.5-flash-lite (distiller at minimal), DEV only, every choice env-revertable"
  - "Gemini 3 gets thinking_level only, never with thinking_budget; no temperature sent to Gemini 3 unless NESTOR_GEMINI_TEMPERATURE is set"
  - "Workshop rank / evolve meta-review / admission classifier now get a config built for THEIR model (before, they got the gate model's config)"
  - "google-genai pin stays 1.75.0 — it already has ThinkingConfig.thinking_level + ThinkingLevel enum"
metrics:
  duration: ~45 min
  completed: 2026-10-06
  tasks: 3
  files: 14
---

# Quick 261006-kzr: Gemini model switch to 3.8-flash / 3.5-flash-lite (DEV) Summary

All eight tribunal Gemini sites now build their config through one helper (`pipeline/gemini_config.py`). The helper sends Gemini 3 `thinking_level` and never `thinking_budget` with it, and sends no temperature to Gemini 3. Defaults are gemini-3.8-flash (gates/grouping/planner/workshop at "low", conflict/scrub at "high") and gemini-3.5-flash-lite for the distiller (at "minimal"). Every site can be reverted with env vars and no rebuild. A live smoke on the DEV key passed 7/7 for about $0.006. Code only: no deploy, no push, prod untouched.

## Commits

| Task | Commit | Message |
|---|---|---|
| 1 | `1ec46a7` | feat(261006-kzr): shared gemini_config helper — thinking_level, temperature omit for Gemini 3, env-tunable |
| 2 | `b5cdf8a` | feat(261006-kzr): gemini sites → 3.8-flash / 3.5-flash-lite (dev), thinking_level via helper, env-overridable models, price rows |
| 3 | `efaca7f` | test(261006-kzr): live gemini model smoke script (dev key, no audit writes) |

No 4th commit: the distiller accepted "minimal" on the first call, so its default did not change.

## SDK pin finding (google-genai==1.75.0, the deployed pin)

I downloaded the 1.75.0 wheel (`pip download --no-deps`) and grepped `google/genai/types.py`:
- `class ThinkingLevel(_common.CaseInSensitiveEnum)` is present (line 316). Its values are **UPPERCASE**: `THINKING_LEVEL_UNSPECIFIED`, `MINIMAL`, `LOW`, `MEDIUM`, `HIGH`.
- `ThinkingConfig.thinking_level: Optional[ThinkingLevel]` is present (line 5345).
- **No SDK bump needed.** `tribunal/requirements.txt` is unchanged.
- `test_gemini_config.py` gave 67 passed under both google-genai 2.25.0 (global Python 3.12) and 1.75.0 (a scratch venv, `PYTHONPATH=tribunal`).

## Full tribunal suite: baseline vs after

| | passed | failed | errors | skipped | xfailed |
|---|---|---|---|---|---|
| Baseline (HEAD 727074d, before any change) | 2451 | 204 | 24 | 21 | 3 |
| After (b5cdf8a) | 2545 | 204 | 24 | 21 | 3 |

- +94 passed = 67 (`test_gemini_config.py`) + 27 (`test_gemini_sites.py`).
- The FAILED/ERROR node-id sets are **identical** (226 ids each, `comm` both ways empty). There are **zero new failures**. The 204/24 is the known local-env baseline.
- The first "after" run showed 3 NEW failures, all in my own caplog tests; see Deviation 1. They were fixed, and the rerun above is clean.

## Pinned tests changed, and why

- `test_factlist_fallback.py:1739`: `steps._DISTILLER_MODEL == "gemini-2.5-flash"` → `"gemini-3.5-flash-lite"`. Reason: operator ruling 261006-kzr. This is the pin that the steps.py "DO NOT FINISH THE JOB" comment names. I also updated the ~1284 docstring mention.
- `test_claim_distiller.py:252-253`: the literal is replaced by `steps._DISTILLER_MODEL`. Reason: a second literal would only duplicate the pin in test_factlist_fallback.
- `test_thinking_disabled_in_kwargs`: **unchanged**, and it still passes (it only asserts that a `config` kwarg is present).
- Untouched as instructed: the 2.5 literals that only stand for an arbitrary priced model (test_audit_perf, test_cost_cache_write, test_feed_enrichment) and the fixtures.
- Grep confirmed that no non-test `.py` under `pipeline/` has an `= "gemini-2.5…"` or `= "gemini-3.7…"` assignment left.

## Price rows (G-7 guard)

I read these from https://ai.google.dev/gemini-api/docs/pricing on 2026-10-06 (Standard paid tier, per 1M tokens). The page was fetched with `curl` because WebFetch is not in the executor's toolset. No number was derived.

| Row | prompt | completion | cache_read | cache_creation_5m | Notes |
|---|---|---|---|---|---|
| google/gemini-3.8-flash | 0.75 | 3.75 | 0.075 | 0 | Introductory through 2026-12-31. The page says 1.50 / 7.50 / 0.15 from 2027-01-01, and this is recorded in `_gemini_3_8_flash_source`. |
| google/gemini-3.5-flash-lite | 0.30 | 2.50 | 0.03 | 0 | The page gives no end date and no future rate. See `_gemini_3_5_flash_lite_source`. |

- `cache_creation_5m: 0` follows the existing 3.7 row's convention: Google bills cache storage per hour, not per write token.
- The page labels output prices "including thinking tokens".
- I appended a dated sentence to `_gemini_2_5_flash_correction`: the row stays for historical audit rows and for the env revert path.
- `test_gemini_sites.py` asserts that `compute()` is not None for every site default, and checks both rows against the published rates. No xfail was needed.

## Live smoke (DEV key `Nestor_Gemini`, project-cb01b861, read-only secret access)

```
site      | model                 | think   | temp    | max_out | finish | prompt | cand | thoughts | ms   | result
gates     | gemini-3.8-flash      | low     | omitted | 4096    | STOP   |     60 |    7 |      200 | 3172 | PASS
grouping  | gemini-3.8-flash      | low     | omitted | 4096    | STOP   |     69 |   24 |        0 | 1452 | PASS
planner   | gemini-3.8-flash      | low     | omitted | 4096    | STOP   |    443 |   90 |        0 | 2187 | PASS
rank      | gemini-3.8-flash      | low     | omitted | 4096    | STOP   |     65 |    1 |        0 | 1640 | PASS
conflict  | gemini-3.8-flash      | high    | omitted | None    | STOP   |    137 |  108 |      355 | 5656 | PASS
scrub     | gemini-3.8-flash      | high    | omitted | 32768   | STOP   |    117 |   31 |      501 | 7500 | PASS
distiller | gemini-3.5-flash-lite | minimal | omitted | 65535   | STOP   |     87 |   93 |        0 |  828 | PASS
TOTAL tokens: prompt=978 candidates=354 thoughts=1056
APPROX SPEND (thoughts billed as output): $0.005866
7/7 PASS
```

- No HTTP 400 at any site, and no MAX_TOKENS finish.
- Every site produced output in its contract shape: KEEP/DROP lines, `n | entity | attribute`, the real planner template's LENGTH/TABLES/FOCUS lines, the A/B letter, the conflict JSON array, the scrub verbatim-string array, and `FACET ||| CLAIM ||| EVIDENCE` lines through `_split_distiller_line`.
- The planner smoke used the real `report_planner._PROMPT_TEMPLATE`.
- **Accepted distiller thinking level: "minimal"** (no retry needed). It matches the steps.py default `_DISTILLER_THINKING = "minimal"`.
- **Spend: about $0.0059** (3.8-flash $0.00561 + 3.5-flash-lite $0.00026), with thoughts priced as output.
- The key never appeared in output, files or commits. The only gcloud verb used was `secrets versions access`.

## New env vars and revert recipe

| Site | Model env (default) | Thinking env (default) |
|---|---|---|
| claim gates | `NESTOR_TRIBUNAL_GATE_MODEL` (gemini-3.8-flash) | `NESTOR_TRIBUNAL_GATE_THINKING` (low) |
| grouping | `NESTOR_TRIBUNAL_GROUP_MODEL` (gemini-3.8-flash) | `NESTOR_TRIBUNAL_GROUP_THINKING` (low) |
| report planner | `NESTOR_TRIBUNAL_PLANNER_MODEL` (gemini-3.8-flash) | `NESTOR_TRIBUNAL_PLANNER_THINKING` (low) |
| workshop rank (critique + judge) | `NESTOR_TRIBUNAL_WORKSHOP_RANK_MODEL` (existing; now gemini-3.8-flash) | `NESTOR_TRIBUNAL_WORKSHOP_RANK_THINKING` (low) |
| evolve meta-review | `NESTOR_TRIBUNAL_WORKSHOP_META_MODEL` (existing; inherits rank) | uses rank's |
| admission classifier | resolved `model` / `_RANK_MODEL`; fallback `GEMINI_FLASH_DEFAULT` | uses rank's ("low" if that import fails) |
| conflict detector | `NESTOR_CONFLICT_MODEL` (gemini-3.8-flash) | `NESTOR_CONFLICT_THINKING` (high) |
| scrub | `NESTOR_SCRUB_MODEL` (gemini-3.8-flash) | `NESTOR_SCRUB_THINKING` (high) |
| claim distiller | `NESTOR_DISTILLER_MODEL` (gemini-3.5-flash-lite) | `NESTOR_DISTILLER_THINKING` (minimal) |
| all sites | — | `NESTOR_GEMINI_TEMPERATURE` (unset = omitted for Gemini 3; read at call time) |
| scrub ceiling | `NESTOR_SCRUB_MAX_TOKENS` (32768; was a hard 8192) | — |

**Revert to 3.7-era behaviour** (per site): set `<SITE>_MODEL=gemini-3.7-flash`, `<SITE>_THINKING=off` and `NESTOR_GEMINI_TEMPERATURE=0`. This gives `thinking_budget=0` with temperature 0.0, and `test_revert_gate_to_37_era_request` proves the dump. NESTOR_GEMINI_TEMPERATURE applies to every site at once.

**Revert to 2.5-era behaviour** (until 2026-10-20): set only the MODEL env, e.g. `NESTOR_DISTILLER_MODEL=gemini-2.5-flash` or `NESTOR_SCRUB_MODEL=gemini-2.5-pro`. The legacy branch then reproduces the old request automatically: Flash gets `thinking_budget=0` with temperature 0.0, and Pro gets no thinking config. The tests prove the dumps are byte-identical for the distiller (65535 / 0.0 / budget 0), for scrub (8192 / 0.0, with `NESTOR_SCRUB_MAX_TOKENS=8192`) and for conflict (empty config).

**Behaviour changes beyond the model id** (all deliberate, per plan):
- The planner's `_MAX_OUTPUT_TOKENS` went 1536 → 4096.
- The scrub ceiling went 8192 → 32768.
- The conflict detector now sends a config. Before, it sent none.
- workshop_rank / evolve meta / admission now get a config built for their own model, not the gate model's.

## Finding for the operator: thought tokens are billed but NOT costed (not fixed here)

`AuditedLLMClient.gemini_generate` (`audit/audited_llm_client.py:937`, and the same at `:1297`) books `completion_tokens = usage_metadata.candidates_token_count` only. No non-test code reads `thoughts_token_count`. Google bills thinking tokens as output (the pricing page says "Output price (including thinking tokens)"), so they never reach `cost_usd`.
- **Evidence from this smoke:** 1056 thought tokens against 354 candidate tokens. The engine would have booked about $0.0019 of the $0.0059 actually billed, under-costing the smoke by about 67%.
- Per site: gates 200 thoughts for 7 output tokens (at "low"), conflict 355 for 108 (at "high"), scrub 501 for 31 (at "high").
- The defect predates this change: 3.7 already thought at budget 0, per the 260901-lf2 notes. "high" on conflict/scrub makes it larger.
- It is left unfixed because it changes the 7-year audit path. This is threat T-kzr-04 (accepted).

## Deviations from Plan

1. **[Rule 1 - Bug] caplog tests failed only in a full-suite run.** Found in Task 2's full-suite diff. Three `test_gemini_config.py` warning tests passed alone but failed after the DB tests. Cause: `alembic/env.py` calls `logging.config.fileConfig`, whose default `disable_existing_loggers=True` disables the helper's logger. Fix: the autouse fixture now sets `gc.logger.disabled = False` through monkeypatch. I proved the fix by forcing the logger disabled and running the file (67 passed). The fix was committed with Task 2 (`b5cdf8a`).
2. **Pricing page fetched with curl, not WebFetch.** WebFetch is not available to this executor. It was a read-only GET of the same URL, and the numbers were transcribed verbatim (see the table).
3. **Smoke run before the Task 2 commit.** The working tree was identical to `b5cdf8a` at the time, and Task 3 was committed after.
4. **Distiller smoke prompt uses the real contract order** `FACET ||| CLAIM_TEXT ||| EVIDENCE`, from the steps.py prompt and test_claim_distiller. The plan's text said "claim ||| evidence ||| facet". The assertion is the same: 3 columns through `_split_distiller_line`.

## Known Stubs

None.

## Threat Flags

None. The smoke script adds no new network surface to the engine: it is an operator-run CLI that uses the existing dev key and does no DB/GCS writes.

## Self-Check: PASSED

- FOUND: tribunal/nestor_pulse_sdk/pipeline/gemini_config.py
- FOUND: tribunal/nestor_pulse_sdk/tests/test_gemini_config.py
- FOUND: tribunal/nestor_pulse_sdk/tests/test_gemini_sites.py
- FOUND: tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py
- FOUND commits: 1ec46a7, b5cdf8a, efaca7f
