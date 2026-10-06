---
phase: quick-261006-kzr
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tribunal/nestor_pulse_sdk/pipeline/gemini_config.py
  - tribunal/nestor_pulse_sdk/tests/test_gemini_config.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/grouping.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/report_planner.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_evolve.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py
  - tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py
  - tribunal/nestor_pulse_sdk/audit/cost_prices.json
  - tribunal/nestor_pulse_sdk/tests/test_gemini_sites.py
  - tribunal/nestor_pulse_sdk/tests/test_factlist_fallback.py
  - tribunal/nestor_pulse_sdk/tests/test_claim_distiller.py
  - tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py
autonomous: true
requirements: [QUICK-261006-kzr]

must_haves:
  truths:
    - "Every switched Gemini site defaults to the operator-approved model: 3.8-flash for gates, grouping, planner, workshop rank (and through it evolve meta-review and the admission classifier), conflict and scrub; 3.5-flash-lite for the claim distiller"
    - "Each site's model can be set back by an env var with no rebuild, and the helper then sends the old config for that model family (thinking_budget=0 on 2.x Flash, no thinking config on 2.x Pro, temperature 0.0 where the site sent it before)"
    - "No config ever carries thinking_budget and thinking_level together, and a non-lite Gemini 3 model is never sent 'minimal'"
    - "By default no switched site sends temperature to a Gemini 3 model; setting NESTOR_GEMINI_TEMPERATURE sends that value"
    - "Every new default model has a price row in audit/cost_prices.json, so compute() does not write NULL cost_usd (the G-7 defect)"
    - "A live smoke against the DEV Gemini key ran each real site config once: no HTTP 400, non-empty text, finish_reason not MAX_TOKENS, parseable output, total spend of a few cents"
    - "The full tribunal pytest has no new failures compared with a baseline taken on HEAD before the change"
  artifacts:
    - path: "tribunal/nestor_pulse_sdk/pipeline/gemini_config.py"
      provides: "Shared Gemini generation-config helper: model defaults, thinking config per model family, temperature policy"
      exports: ["GEMINI_FLASH_DEFAULT", "GEMINI_FLASH_LITE_DEFAULT", "build_thinking_config", "resolve_temperature", "build_generate_config"]
    - path: "tribunal/nestor_pulse_sdk/tests/test_gemini_config.py"
      provides: "Unit tests for the helper"
    - path: "tribunal/nestor_pulse_sdk/tests/test_gemini_sites.py"
      provides: "Per-site default model, env override, config-shape and price-row guards"
    - path: "tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py"
      provides: "Live smoke of each site config against the real Gemini API"
    - path: "tribunal/nestor_pulse_sdk/audit/cost_prices.json"
      provides: "Price rows google/gemini-3.8-flash and google/gemini-3.5-flash-lite"
      contains: "google/gemini-3.8-flash"
  key_links:
    - from: "pipeline/tribunal/gates.py _make_config"
      to: "pipeline/gemini_config.build_generate_config"
      via: "direct call; workshop_rank, workshop_evolve and workshop_admission reach it through gates._make_config(model=..., level=...)"
      pattern: "build_generate_config\\("
    - from: "pipeline/synthesis/steps.py conflict_detector"
      to: "_make_conflict_config"
      via: "config kwarg passed to audited.gemini_generate (today it passes no config at all)"
      pattern: "_make_conflict_config\\("
    - from: "scripts/gemini_model_smoke.py"
      to: "the site config builders"
      via: "imports the real site modules and calls their builders, so the smoke sends exactly what production sends"
      pattern: "_make_distiller_config|_make_scrub_config|_make_conflict_config"
---

<objective>
Move the tribunal engine's Gemini call sites off gemini-2.5-flash, gemini-2.5-pro and gemini-3.7-flash, on DEV only (operator ruling 2026-10-06; Google retires 2.5 on 2026-10-20). This also changes how the sites ask for thinking (Gemini 3 `thinking_level` instead of the deprecated `thinking_budget`) and stops them sending temperature to Gemini 3, through one shared helper that reads env vars. Every model choice can be reverted with an env var and no rebuild. A live smoke against the dev key proves the new model ids and configs are accepted.

Purpose: the 2.5 models stop working on 2026-10-20. 3.8-flash costs the same as 3.7-flash. Gemini 3 rejects requests that send both thinking fields (HTTP 400), and Google warns that temperature below 1.0 can cause looping.
Output: helper module + tests, rewired sites, price rows, updated pins, live smoke script + its measured result. Code commits only — NO deploy, NO push, prod untouched.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@tribunal/requirements.txt

<operator_mapping>
Operator-approved, NOT negotiable (all paths under tribunal/nestor_pulse_sdk/):

| Site | Constant | Old | New default | Thinking default | New model env var | New thinking env var |
|---|---|---|---|---|---|---|
| claim gates | pipeline/tribunal/gates.py `_GATE_MODEL` (line 87) | gemini-3.7-flash | gemini-3.8-flash | low | NESTOR_TRIBUNAL_GATE_MODEL | NESTOR_TRIBUNAL_GATE_THINKING |
| grouping | pipeline/tribunal/grouping.py `_GROUPER_MODEL` (line 100) | gemini-3.7-flash | gemini-3.8-flash | low | NESTOR_TRIBUNAL_GROUP_MODEL | NESTOR_TRIBUNAL_GROUP_THINKING |
| report planner | pipeline/tribunal/report_planner.py `_PLANNER_MODEL` (line 44) | gemini-3.7-flash | gemini-3.8-flash | low | NESTOR_TRIBUNAL_PLANNER_MODEL | NESTOR_TRIBUNAL_PLANNER_THINKING |
| workshop rank (critique + tournament judge) | pipeline/tribunal/workshop_rank.py `_RANK_MODEL` (line 224, already env NESTOR_TRIBUNAL_WORKSHOP_RANK_MODEL) | gemini-3.7-flash | gemini-3.8-flash | low | (existing) | NESTOR_TRIBUNAL_WORKSHOP_RANK_THINKING |
| evolve meta-review | pipeline/tribunal/workshop_evolve.py `_META_MODEL` (line 218, env NESTOR_TRIBUNAL_WORKSHOP_META_MODEL, default = workshop_rank._RANK_MODEL) | inherits | inherits | rank's | (existing) | uses rank's |
| admission classifier fallback literal | pipeline/tribunal/workshop_admission.py line 925 | "gemini-3.7-flash" | derive from helper GEMINI_FLASH_DEFAULT | rank's | — | uses rank's |
| conflict resolver | pipeline/synthesis/steps.py `_CONFLICT_MODEL` (line 3538) | gemini-2.5-pro | gemini-3.8-flash | high | NESTOR_CONFLICT_MODEL | NESTOR_CONFLICT_THINKING |
| scrub (span proposal) | pipeline/synthesis/steps.py `_SCRUB_MODEL` (line 3649) | gemini-2.5-pro | gemini-3.8-flash | high | NESTOR_SCRUB_MODEL | NESTOR_SCRUB_THINKING |
| claim distiller (D-14 fact-list fallback + safety-net/full extraction) | pipeline/synthesis/steps.py `_DISTILLER_MODEL` (line 1670) | gemini-2.5-flash | gemini-3.5-flash-lite | minimal (fall back to low if the live smoke shows 400) | NESTOR_DISTILLER_MODEL | NESTOR_DISTILLER_THINKING |

UNCHANGED: Deep Research agent (`NESTOR_GEMINI_DR_AGENT`, deep-research-max-preview-04-2026), the read-only ADK arm (tribunal/nestor_pulse/, deep-research-pro-preview-12-2025), every OpenAI and Claude model.
Doc facts given by the orchestrator (do NOT re-research): Gemini 3 uses `thinking_level` in {"minimal","low","medium","high"}; `thinking_budget` is deprecated and sending BOTH is HTTP 400; gemini-3.8-flash does NOT accept "minimal"; Google says to keep temperature at its default 1.0 for Gemini 3, because values below 1.0 "may lead to unexpected behavior, such as looping or degraded performance"; 3.8-flash is priced $0.75 input / $3.75 output per 1M tokens through 2026-12-31.
</operator_mapping>

<current_config_sites>
Extracted from HEAD — the executor does not need to explore for these:
- gates.py `_make_config()` (~line 149): GenerateContentConfig(max_output_tokens=4096, temperature=0.0, thinking_config=ThinkingConfig(thinking_budget=0)); bare `except Exception: return None`. It is reused by workshop_rank.py lines 609 and 1665 (critique, tournament), workshop_evolve.py line 1243 (meta-review) and workshop_admission.py line 937 (classifier). Those callers send `_RANK_MODEL` / `_META_MODEL` / the admission `model`, but they get the GATE config.
- grouping.py `_make_config()` (~line 127): the same shape as gates (4096 / 0.0 / budget 0).
- report_planner.py `_make_config()` (~line 87): genai_types is imported at module top; ThinkingConfig(thinking_budget=0) in try/except; kwargs max_output_tokens=_MAX_OUTPUT_TOKENS (1536), temperature 0.0.
- steps.py `_make_distiller_config()` (~line 1738): max_output_tokens=_DISTILLER_MAX_TOKENS (65535), temperature=0.0, ThinkingConfig(thinking_budget=0). Its except-branch rebuilds WITHOUT thinking (keep that shape). Used at line 2217 (via kwargs) and in `_retry_fact_list` (~line 2930).
- steps.py `conflict_detector` (~line 3598): calls audited.gemini_generate(model=_CONFLICT_MODEL, contents=prompt) with NO config at all. Today that means: model default output limit, model default temperature, model default thinking.
- steps.py scrub (~line 3776): config = GenerateContentConfig(max_output_tokens=_SCRUB_MAX_TOKENS (8192), temperature=0.0), with no thinking config (2.5-pro rejects budget 0).
- AuditedLLMClient.gemini_generate (audit/audited_llm_client.py line 899) passes **kwargs through to `models.generate_content`. It computes completion_tokens from `usage_metadata.candidates_token_count` ONLY. It never reads `thoughts_token_count` (grep returns 0 hits in non-test code).
- audit/cost_prices.json has rows for google/gemini-2.5-pro, google/gemini-2.5-flash and google/gemini-3.7-flash (0.75 / 3.75 / cache_read 0.075 / cache_creation_5m 0, with a long `_gemini_3_7_flash_source` note). It has NO row for gemini-3.8-flash or gemini-3.5-flash-lite. compute() on an unknown model returns None → NULL cost_usd → SUM skips it (the G-7 defect). See the guard pattern in tests/test_tribunal_intake.py `test_intake_model_has_a_price_row` (~line 217).
- Tests that pin old literals: tests/test_factlist_fallback.py:1739 (`steps._DISTILLER_MODEL == "gemini-2.5-flash"`, the guard named in the steps.py "DO NOT FINISH THE JOB" comment) and tests/test_claim_distiller.py:252-253 (`call["model"] == "gemini-2.5-flash"`). These use 2.5 literals only as arbitrary priced models and do NOT change: test_audit_perf.py:216, test_cost_cache_write.py:206/243, test_feed_enrichment.py:673/711, and the fixtures under tests/fixtures/run_4cbb5311/ (historical recordings — never edit).
- SDK: tribunal/requirements.txt pins google-genai==1.75.0, which is what the Cloud Run image gets. The local global Python 3.12 (`~/AppData/Local/Programs/Python/Python312/python.exe`) has google-genai 2.25.0 installed. There, `ThinkingConfig` has fields include_thoughts / thinking_budget / thinking_level, and `types.ThinkingLevel` is an enum with MINIMAL / LOW / MEDIUM / HIGH (values are UPPERCASE strings).
- Tribunal tests: `cd tribunal && <py312> -m pytest -q -p no:cacheprovider`. DB tests use testcontainers, which pick a random host port, so the native postgres.exe holding 5432 does not matter. Docker Desktop must be running. On this machine, the full suite has a KNOWN local-env baseline of about 204 failed / 24 errors (quick tasks 260925-cop and 260929-mt8). Only NEW failures count.
- Dev Gemini secret: Secret Manager id `Nestor_Gemini` (infra/variables.tf `tribunal_gemini_secret_id`) in project `project-cb01b861-cb4a-438d-b9a` (DEV), account `tools@dotto.be`.
</current_config_sites>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Shared Gemini config helper (thinking_level, temperature policy, env-tunable) + unit tests + SDK-pin check</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/gemini_config.py, tribunal/nestor_pulse_sdk/tests/test_gemini_config.py</files>
  <behavior>
    - build_thinking_config("gemini-3.8-flash", "low") → a ThinkingConfig whose model_dump(exclude_none=True) has thinking_level LOW and NO thinking_budget key
    - build_thinking_config("gemini-3.8-flash", "minimal") → clamped to LOW, and a warning is logged (3.8-flash does not accept minimal; the same clamp applies to every Gemini 3 model id that does not contain "flash-lite")
    - build_thinking_config("gemini-3.5-flash-lite", "minimal") → MINIMAL (not clamped)
    - build_thinking_config("gemini-3.8-flash", "high") → HIGH
    - build_thinking_config(<any gemini-3 id>, "off") → ThinkingConfig(thinking_budget=0) with NO thinking_level (the 3.7-era revert path)
    - build_thinking_config("gemini-2.5-flash", <any level>) → thinking_budget=0 only; build_thinking_config("gemini-2.5-pro", <any level>) → None (2.x Pro rejects budget 0) — this is the legacy-family branch
    - unknown level string (e.g. "banana") → warning + treated as "low"; level matching is case-insensitive
    - PROPERTY: for every model in {3.8-flash, 3.5-flash-lite, 3.7-flash, 2.5-flash, 2.5-pro} × every level in {minimal, low, medium, high, off, garbage}, the dumped config never has both thinking_budget and thinking_level set
    - resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) with NESTOR_GEMINI_TEMPERATURE unset → None (omitted); with "" → None; with "0.3" → 0.3; resolve_temperature("gemini-2.5-flash", legacy_temperature=0.0) unset → 0.0; resolve_temperature("gemini-2.5-pro", legacy_temperature=None) → None
    - build_generate_config("gemini-3.8-flash", level="low", max_output_tokens=4096, legacy_temperature=0.0) → dumped config has max_output_tokens 4096, thinking_config.thinking_level LOW, and NO temperature key
    - build_generate_config(..., max_output_tokens=None) → no max_output_tokens key (the model default — used by the conflict site)
    - graceful degrade: monkeypatch the helper's ThinkingConfig construction to raise → build_generate_config still returns a config, with NO thinking_config at all (it must never fall back to thinking_budget). If google.genai cannot be imported → returns None.
  </behavior>
  <action>
BEFORE any code: take the regression baseline. With Docker Desktop up, run the full tribunal suite on untouched HEAD with `-rfE` and save the output to the scratchpad as baseline.txt. Record the passed/failed/errors counts. Use run_in_background with a generous timeout if it is slow. Task 2 diffs against this file.

SDK-pin check (requirement 2): do not trust the local 2.25.0. Run `pip download google-genai==1.75.0 --no-deps -d <scratchpad>/genai175`, then unzip the wheel and grep google/genai/types.py for `thinking_level` and `class ThinkingLevel`. Record in the SUMMARY whether 1.75.0 has the field and the enum, and whether the enum values are uppercase. If 1.75.0 LACKS thinking_level, STOP and report — do not bump the SDK silently. The operator said only bump it if strictly required, and then pin it exactly.

Create pipeline/gemini_config.py. It is a small, light module: imports only os, logging and, lazily, google.genai.types. The package __init__ files are empty, so it imports cheaply and the smoke script can import it. Contents:
(a) GEMINI_FLASH_DEFAULT = "gemini-3.8-flash" and GEMINI_FLASH_LITE_DEFAULT = "gemini-3.5-flash-lite". Add a comment block dated 261006-kzr that records the operator ruling, the 2026-10-20 retirement of 2.5 on Google Cloud, and the 3.8-flash introductory pricing.
(b) A private family test: model ids starting "gemini-1." or "gemini-2." are LEGACY; everything else is treated as Gemini 3+.
(c) build_thinking_config(model, level, genai_types=None). It returns a ThinkingConfig built with EXACTLY ONE kwarg, or None, per the behavior list. LEGACY family ignores the level: Flash gets thinking_budget=0 and Pro (id contains "-pro") gets None. This keeps an env revert to 2.5 byte-faithful to today's request. "off" on Gemini 3+ gives thinking_budget=0. Otherwise thinking_level is set via `genai_types.ThinkingLevel[LEVEL.upper()]` when the enum exists, else the uppercase string. Log each clamp/unknown-level warning once per (model, level) pair, not per call.
(d) resolve_temperature(model, legacy_temperature). If NESTOR_GEMINI_TEMPERATURE is set and non-empty, return float of it. Otherwise LEGACY family returns legacy_temperature (the site's historical value) and Gemini 3+ returns None. Read the env at CALL time, not import time, so one env flip moves every site.
(e) build_generate_config(model, *, level, max_output_tokens=None, legacy_temperature=None). It builds a GenerateContentConfig from only the non-None fields. If constructing the ThinkingConfig raises, log at debug and build WITHOUT thinking_config (requirement 4 — never resend thinking_budget as a substitute). If google.genai is unimportable, return None.
Write a module docstring that explains the revert recipe. To return a site to 3.7-era behaviour: set its MODEL env to gemini-3.7-flash, its THINKING env to off, and NESTOR_GEMINI_TEMPERATURE=0. To return to 2.5: set the MODEL env only.

Write tests/test_gemini_config.py first (RED), then implement (GREEN). Tests use model_dump(exclude_none=True) on the returned objects and monkeypatch for env. Then run the new test file a second time under google-genai 1.75.0, to prove the deployed pin builds identical configs. Create a throwaway venv in the scratchpad, `pip install google-genai==1.75.0 pytest pytest-asyncio`, and run pytest on just that file with PYTHONPATH=tribunal and `-p no:cacheprovider`. Record the result. The package is the already-pinned production dependency, so this is not a new package. The venv lives in the scratchpad only, so nothing in the repo changes.

Commit (code only, `git add` the two files explicitly): `feat(261006-kzr): shared gemini_config helper — thinking_level, temperature omit for Gemini 3, env-tunable`.
  </action>
  <verify>
    <automated>cd tribunal && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest nestor_pulse_sdk/tests/test_gemini_config.py -q -p no:cacheprovider</automated>
  </verify>
  <done>Helper exists with the five exports. test_gemini_config.py passes under BOTH google-genai 2.25.0 (global) and 1.75.0 (scratch venv). The baseline full-suite counts are saved in the scratchpad. The SDK-pin finding is recorded for the SUMMARY. One atomic commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Rewire all eight sites to the helper with env-overridable models, add price rows, update pinned tests, add site guards, full-suite diff</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/tribunal/gates.py, tribunal/nestor_pulse_sdk/pipeline/tribunal/grouping.py, tribunal/nestor_pulse_sdk/pipeline/tribunal/report_planner.py, tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py, tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_evolve.py, tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_admission.py, tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py, tribunal/nestor_pulse_sdk/audit/cost_prices.json, tribunal/nestor_pulse_sdk/tests/test_gemini_sites.py, tribunal/nestor_pulse_sdk/tests/test_factlist_fallback.py, tribunal/nestor_pulse_sdk/tests/test_claim_distiller.py</files>
  <behavior>
    - Default model per site equals the operator_mapping table (gates/grouping/planner/rank/evolve-meta/conflict/scrub = gemini-3.8-flash; distiller = gemini-3.5-flash-lite); admission's import-failure fallback equals gemini_config.GEMINI_FLASH_DEFAULT
    - Env override: with NESTOR_TRIBUNAL_GATE_MODEL=gemini-2.5-flash (and each other site's MODEL env), a fresh interpreter sees the overridden constant. Use a subprocess `python -c` with the env set, NOT importlib.reload, because reloading steps.py has module-level side effects.
    - Each site builder's dumped config: thinking_level per the mapping, no thinking_budget, no temperature (with NESTOR_GEMINI_TEMPERATURE unset), and max_output_tokens as below
    - The workshop path: gates._make_config(model=_RANK_MODEL, level=_RANK_THINKING) is what rank/evolve/admission send, and the meta-review config is built for _META_MODEL rather than _GATE_MODEL
    - Revert faithfulness: with the distiller MODEL env set to gemini-2.5-flash in a subprocess, _make_distiller_config() dumps to thinking_budget 0 + temperature 0.0 + max 65535 — today's exact request
    - G-7 guard: compute(provider="google", model=<each site default>, …) is not None, i.e. cost_prices.json has a row for every default
  </behavior>
  <action>
Wire every site to pipeline/gemini_config.py per the operator_mapping table (decisions D-261006-kzr mapping, requirements 1–5).

gates.py: `_GATE_MODEL = os.environ.get("NESTOR_TRIBUNAL_GATE_MODEL", GEMINI_FLASH_DEFAULT)` and `_GATE_THINKING = os.environ.get("NESTOR_TRIBUNAL_GATE_THINKING", "low")`. `_make_config(model=None, level=None)` returns build_generate_config(model or _GATE_MODEL, level=level or _GATE_THINKING, max_output_tokens=4096, legacy_temperature=0.0). Keep the "return None on failure" contract that callers rely on.

grouping.py: same pattern with NESTOR_TRIBUNAL_GROUP_MODEL / NESTOR_TRIBUNAL_GROUP_THINKING, max 4096, legacy_temperature 0.0.

report_planner.py: NESTOR_TRIBUNAL_PLANNER_MODEL / NESTOR_TRIBUNAL_PLANNER_THINKING. Raise `_MAX_OUTPUT_TOKENS` 1536 → 4096. Add a dated note: the 3.7 comment already flagged this as the Flash site most exposed to truncation; raising the ceiling only caps and changes no output shape; requirement 5 says budgets must be ≥ current. legacy_temperature 0.0.

workshop_rank.py: `_RANK_MODEL` default becomes GEMINI_FLASH_DEFAULT (env name unchanged). Add `_RANK_THINKING = os.environ.get("NESTOR_TRIBUNAL_WORKSHOP_RANK_THINKING", "low")`. Both gates._make_config() calls (lines ~609, ~1665) become gates._make_config(model=_RANK_MODEL, level=_RANK_THINKING).

workshop_evolve.py: the meta-review call (~1243) becomes gates._make_config(model=_META_MODEL, level=workshop_rank._RANK_THINKING).

workshop_admission.py: the config call (~937) passes the resolved classifier `model` and workshop_rank._RANK_THINKING; if that import also fails, use "low". The fallback literal (~925) becomes GEMINI_FLASH_DEFAULT imported from gemini_config. Keep the "MIRRORS workshop_rank._RANK_MODEL" comment and append that it is now derived, not copied (261006-kzr).

steps.py:
- `_DISTILLER_MODEL = os.environ.get("NESTOR_DISTILLER_MODEL", GEMINI_FLASH_LITE_DEFAULT)` and `_DISTILLER_THINKING = os.environ.get("NESTOR_DISTILLER_THINKING", "minimal")`.
- `_make_distiller_config()` delegates to the helper (max 65535 kept, legacy_temperature 0.0). The helper owns the graceful-degrade path now, so the old nested except-branch goes. Update the docstring: it no longer "disables thinking"; it requests the lowest level the model accepts.
- `_CONFLICT_MODEL` = env NESTOR_CONFLICT_MODEL, default GEMINI_FLASH_DEFAULT, with `_CONFLICT_THINKING` env default "high".
- Add a `_make_conflict_config()` builder (max_output_tokens=None = the model default, i.e. the same output limit as today; legacy_temperature=None, because today this site sends no temperature). Make conflict_detector pass it as `config` when it is not None.
- `_SCRUB_MODEL` = env NESTOR_SCRUB_MODEL, default GEMINI_FLASH_DEFAULT, with `_SCRUB_THINKING` default "high".
- `_SCRUB_MAX_TOKENS` = int(env NESTOR_SCRUB_MAX_TOKENS, default 32768). 8192 was sized for a 2.5-pro that thinks anyway; "high" thinking on 3.8-flash must not truncate a JSON list (requirement 5: ≥ current).
- Add a `_make_scrub_config()` builder (legacy_temperature 0.0) and use it in place of the inline config.

COMMENT HISTORY (requirement 3): delete NO existing evidence comment. Add a dated `261006-kzr (2026-10-06)` note at each of these: gates `_GATE_MODEL` block; grouping `_GROUPER_MODEL`; planner `_PLANNER_MODEL`; workshop_rank `_RANK_MODEL` block and the `_CRITIQUE_*` thinking warning (~line 190 — say that thinking is now requested at "low" on 3.8-flash per operator ruling, that the 2.5-era 17–18 KEEP warning and the 3.7 counter-evidence both stand, and that no 3.8 measurement exists yet); the "⛔ DELIBERATELY STILL gemini-2.5-flash" distiller block (record that the operator overrode it because 2.5 retires 2026-10-20; that reason 1, no evidence on this path, STILL HOLDS for 3.5-flash-lite; that `_split_distiller_line` is the separator guard for reason 2; and that test_factlist_fallback.py now pins the new literal); the steps.py module docstring's "gemini-2.5-pro does NOT support thinking_budget=0" anti-pattern paragraph; and the docstrings at gates.py ~31, grouping.py ~14 and report_planner.py ~15 that say "gemini-2.5-flash, thinking disabled". Each note says what changed (model, thinking_level instead of thinking_budget, temperature no longer sent to Gemini 3) and why (Google's retirement date, the deprecation, the HTTP 400 when both fields are sent, Google's "<1.0 may loop" guidance).

PRICE ROWS (requirement 8 — these are the G-7 guard): add `google/gemini-3.8-flash` with prompt 0.75 and completion 3.75 (given), plus a `_gemini_3_8_flash_source` note in the same style as the 3.7 note: dated 261006-kzr, introductory through 2026-12-31, and "no run has executed on 3.8 yet". Read cache_read, and any post-2026-12-31 rate, from Google's published Gemini API pricing page (WebFetch https://ai.google.dev/gemini-api/docs/pricing).
Add `google/gemini-3.5-flash-lite` the same way, with prices read from that page and the source + date recorded in a `_gemini_3_5_flash_lite_source` note.
NEVER invent or derive a number. If the page does not give a 3.5-flash-lite price, leave that row out, mark its G-7 guard `xfail(strict=True, reason=...)` and flag it in the SUMMARY as owed.
Append a dated sentence to `_gemini_2_5_flash_correction`: the distiller no longer calls 2.5-flash by default, and the row stays for historical audit rows and the env revert path. The 2.5-pro and 3.7 rows stay unchanged.

TESTS:
- test_factlist_fallback.py:1739 → assert `"gemini-3.5-flash-lite"`, and update the ~1284 docstring mention. Reason: operator ruling 261006-kzr; this test is the pin the steps.py comment names.
- test_claim_distiller.py:252-253 → compare against `steps._DISTILLER_MODEL` (reason: a literal there duplicates the pin in test_factlist_fallback). Leave test_thinking_disabled_in_kwargs unchanged if it still passes; if it needs changing, change it and say why.
- New tests/test_gemini_sites.py covers every bullet in behavior. The workshop_rank/evolve/admission imports may need the same importorskip pattern other tests use.
- Grep tests for any other assertion that breaks, and fix each one with a stated reason. Do NOT touch the 2.5 literals that only stand for an arbitrary priced model, and do NOT touch fixtures.

Then run the full tribunal suite with `-rfE`, save it as after.txt in the scratchpad, and diff the failing/erroring node ids against baseline.txt. The bar is zero NEW failures; any new one is fixed, not explained away. Also confirm with a grep that no non-test .py under tribunal/nestor_pulse_sdk/pipeline still contains a "gemini-2.5" or "gemini-3.7" assignment. Filter comment lines and use the assignment pattern: `grep -rnE '^[^#]*= *"gemini-(2\.5|3\.7)' ... | grep -v '/tests/'` must print nothing.

Commit (code only, explicit paths): `feat(261006-kzr): gemini sites → 3.8-flash / 3.5-flash-lite (dev), thinking_level via helper, env-overridable models, price rows`.
  </action>
  <verify>
    <automated>cd tribunal && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest nestor_pulse_sdk/tests/test_gemini_config.py nestor_pulse_sdk/tests/test_gemini_sites.py nestor_pulse_sdk/tests/test_factlist_fallback.py nestor_pulse_sdk/tests/test_claim_distiller.py nestor_pulse_sdk/tests/test_distiller_separators.py nestor_pulse_sdk/tests/test_gate_replay.py nestor_pulse_sdk/tests/test_workshop_critique.py -q -p no:cacheprovider -m "not live"</automated>
  </verify>
  <done>All eight sites resolve their model from an env var whose default matches the mapping. Every site builds its config through the helper. The conflict site now sends a config. No "gemini-2.5"/"gemini-3.7" assignment is left in pipeline code. Both price rows exist (or the 3.5-flash-lite gap is xfail-flagged with the reason). The full-suite diff against baseline shows zero new failures, with counts recorded. One atomic commit.</done>
</task>

<task type="auto">
  <name>Task 3: Live smoke of every real site config against the DEV Gemini key (cents)</name>
  <files>tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py</files>
  <action>
Create scripts/gemini_model_smoke.py (requirement 7).

It builds its client as genai.Client(api_key=os.environ["GOOGLE_API_KEY"], vertexai=False). It exits with code 2 and a clear message if the variable is missing. It never prints, logs or writes the key, and puts nothing from it in exception text: catch API errors and print only status code + message. It deliberately does NOT use AuditedLLMClient, so there are no DB writes, no audit rows and no GCS. Say so in the docstring.

It imports the REAL site modules and calls their REAL builders, so the request equals production. It makes exactly one call per site, with a tiny prompt shaped like that site's output contract. Assertion per site:
(1) gates — gates._make_config() with gates._GATE_MODEL. Two short claims; ask for exactly one line per claim, "<n>: KEEP" or "<n>: DROP". Assert 2 parseable lines.
(2) grouping — grouping._make_config() with _GROUPER_MODEL. Two claims; ask for "<n> | <entity> | <attribute>" lines. Assert 2 lines with 3 fields.
(3) report planner — report_planner._make_config() with _PLANNER_MODEL. Two focus labels plus three lines of fake research; use the real output contract (LENGTH_RECOMMENDED / TABLES_RECOMMENDED / FOCUS lines). Assert each regex matches.
(4) workshop rank judge — gates._make_config(model=workshop_rank._RANK_MODEL, level=workshop_rank._RANK_THINKING). An A-vs-B pairwise question; ask for a single letter. Assert the reply is A or B. This config is also what evolve meta-review and the admission classifier send.
(5) conflict — steps._make_conflict_config() with _CONFLICT_MODEL. Three numbered claims, two of which contradict; ask for ONLY a JSON array in the site's schema. Assert steps._extract_json_array returns a list.
(6) scrub — steps._make_scrub_config() with _SCRUB_MODEL. One discredited claim plus a 3-sentence report; ask for a JSON array of verbatim strings. Assert it parses as a list of str.
(7) distiller — steps._make_distiller_config() with _DISTILLER_MODEL. A 3-sentence report; ask for "claim ||| evidence ||| facet" lines. Assert that steps._split_distiller_line parses at least one line into 3 columns.
For (7), if the call fails with HTTP 400 and the message concerns thinking level, retry ONCE with the config rebuilt at level "low" and report which level the model accepted. The executor then sets the steps.py `_DISTILLER_THINKING` default to the accepted level ("lowest the model accepts", per the operator). If it changed, rerun test_gemini_sites.py and commit that fix separately.

Every site must have: no exception, non-empty response.text, finish_reason not MAX_TOKENS, and its shape assertion passing. Print one line per site: site, model, thinking level actually sent (read back from the config), temperature sent ("omitted" expected), max_output_tokens, finish_reason, prompt/candidates/thoughts token counts from usage_metadata, latency ms, PASS/FAIL. Exit non-zero if any site fails.

Run it with the key held only in the process env, in one Bash command:
`GOOGLE_API_KEY="$(gcloud secrets versions access latest --secret=Nestor_Gemini --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a)" ~/AppData/Local/Programs/Python/Python312/python.exe tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py`
That is a READ-only secret access on DEV. Do NOT echo the variable or redirect it to a file, and use no other gcloud verb. If the permission system blocks the secret read, do not look for a workaround. Stop and return a checkpoint that gives the operator that exact command to run with the `!` prefix, then continue once they paste the output.

From the printed token counts, compute the smoke's spend using the new price rows (thoughts are billed as output) and put it in the SUMMARY. Expect a few cents at most.

Also record this measured finding for the operator, and DO NOT fix it in this task (it changes the 7-year audit path and was not asked for): AuditedLLMClient.gemini_generate books completion_tokens = candidates_token_count only, so any thoughts_token_count printed above is billed by Google but NOT costed by the engine. The defect predates this change (3.7 already thought at budget 0). "high" on conflict/scrub makes it larger. Quote the smoke's thoughts numbers as the evidence.

Commit (code only): `test(261006-kzr): live gemini model smoke script (dev key, no audit writes)`.
  </action>
  <verify>
    <automated>GOOGLE_API_KEY="$(gcloud secrets versions access latest --secret=Nestor_Gemini --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a)" ~/AppData/Local/Programs/Python/Python312/python.exe tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py</automated>
  </verify>
  <done>The smoke exits 0 with 7/7 PASS lines, each showing the new model id, the expected thinking level and temperature "omitted". The accepted distiller level is known and matches the steps.py default. Spend and thoughts-token counts are in the SUMMARY, plus the uncosted-thought-tokens finding. The key never appeared in output, files or commits. One atomic commit (plus at most one follow-up commit if the distiller level default changed).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Secret Manager → local process | The dev Gemini API key enters an operator workstation process env for the smoke only |
| engine → Gemini API | Model id + generation config cross here; a rejected config would fail every run's gate/grouping/synthesis calls |
| engine → audit cost table | Model id must resolve to a price row or cost_usd is NULL |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-kzr-01 | Information disclosure | scripts/gemini_model_smoke.py + the Task 3 run command | mitigate | The key exists only in a single command's env via `$(gcloud secrets versions access ...)`. The script never prints, logs or writes it, and its error handler prints only status + message. No file in the repo or scratchpad holds it. |
| T-kzr-02 | Denial of service | all eight Gemini sites | mitigate | The helper can never send thinking_budget together with thinking_level (unit-test property over every model × level), and clamps "minimal" for non-lite 3.x. The live smoke proves every real site config is accepted before the orchestrator deploys. A per-site env revert is available with no rebuild. |
| T-kzr-03 | Repudiation / audit integrity | audit/cost_prices.json | mitigate | Price rows for both new defaults, with a G-7 test guard per site default. Numbers come only from Google's published page, never derived. |
| T-kzr-04 | Repudiation / audit integrity | AuditedLLMClient thought tokens | accept | Pre-existing under-costing of thoughts_token_count. Measured by the smoke and reported to the operator, NOT fixed here (7-year audit path, not in scope). |
| T-kzr-05 | Tampering (output quality) | workshop critic / distiller parser under a new model | accept | No 3.8 / 3.5-lite measurement exists. DEV-only rollout per operator ruling; existing comments that hold the 2.5/3.7 evidence are preserved with dated notes; the separator-tolerant parser guards the distiller. |
| T-kzr-SC | Tampering | pip install google-genai==1.75.0 into a scratch venv | accept | Already the pinned production dependency (tribunal/requirements.txt). The venv lives in the scratchpad only; no new package enters the repo. |
</threat_model>

<verification>
- test_gemini_config.py green under google-genai 2.25.0 and 1.75.0.
- test_gemini_sites.py + the updated pins green.
- Full tribunal suite: zero new failures vs the HEAD baseline, with both count lines recorded.
- No `= "gemini-2.5…"` / `= "gemini-3.7…"` assignment left in non-test pipeline code.
- Live smoke 7/7 PASS on the DEV key, spend in cents.
- `git log` shows 3 (or 4) code commits. No push, no deploy, no gcloud verb other than `secrets versions access`, and no file outside tribunal/ changed.
</verification>

<success_criteria>
Every row of the operator mapping is implemented, env-overridable, and sends Gemini-3-valid thinking with no temperature by default. The revert path reproduces today's request for 2.5 models from env alone. Price rows exist. Tests prove the invariants, and a cheap live call proves Google accepts each real site config. Prod and the deploy are untouched; the orchestrator owns the dev deploy.
</success_criteria>

<output>
Create `.planning/quick/261006-kzr-gemini-model-switch-3-8-flash-dev/261006-kzr-SUMMARY.md` (force-add; .planning/ is gitignored) containing:
- the SDK 1.75.0 finding;
- baseline vs after suite counts;
- which pinned tests changed and why;
- the price-row sources;
- the smoke table and spend;
- the accepted distiller thinking level;
- the full list of new env vars, with the revert recipe for both 3.7-era and 2.5-era behaviour;
- the uncosted thought-tokens finding.
</output>
