---
phase: quick-260721-twy
plan: 01
subsystem: tribunal-intake
tags: [tribunal, intake, delegator, brief, audit, anthropic]
requires:
  - audited.anthropic_messages (existing egress, mirrored from skeptic.py)
  - research_division.divide / run_angles (verbatim research_prompt pass-through)
provides:
  - Delegator intake that always produces a research plan (no vague/clarification path)
  - Full context pack folded into the brief (no 4000-char truncation)
  - Multi-line fenced RESEARCH_PROMPT per focus area
affects:
  - Any run triggered from the intake backend (parked needs_input runs no longer expected from vague-gating)
tech-stack:
  added: []
  patterns:
    - audited.anthropic_messages (claude-sonnet-4-6) for the intake stage
    - RESEARCH_PROMPT_START / RESEARCH_PROMPT_END fenced multi-line blocks
key-files:
  created: []
  modified:
    - backend/app/research/brief.py
    - backend/tests/test_research_brief.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py
    - tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py
    - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
decisions:
  - Kept needs_clarification / clarifying_questions dict keys (always False/empty) for shape compat
  - Left _intake_detail() and vestigial needs_input/answer/worker-parking surface untouched
  - research_division.py needed NO change — divide()/run_angles() already pass multi-line prompts verbatim
metrics:
  duration: ~35 min
  completed: 2026-07-21
---

# Quick Task 260721-twy: Convert Tribunal Intake Gatekeeper into a Delegator — Summary

Converted the Tribunal intake stage from a gatekeeper (that could reject a brief as vague and ask clarifying questions) into a delegator that always produces a research plan, and deleted the force-proceed / clarification-cap rubberband machinery from both the backend brief composer and the tribunal pipeline. The intake stage now runs on `claude-sonnet-4-6` via the audited Anthropic path and emits full multi-line self-contained research prompts per focus area, with the full context pack carried verbatim in the brief.

## What Changed

### Task 1 — backend brief composer (`brief.py`)
- Deleted the `_CONTEXT_EXCERPT_CHARS = 4000` truncation constant; added `_CONTEXT_PACK_HEADER = "[CONTEXT PACK]"`.
- Replaced the two `[CLARIFICATION ANSWERS]` force-proceed sections with a single labeled `[CONTEXT PACK]` section carrying the **full** `context_pack_text` verbatim (untruncated). When no context pack is supplied, the entity-bits fallback (title / sector / goals) is emitted under the same header.
- The context section is no longer gated on `if ordered:` — it emits whenever context text or fallback bits exist (no reintroduced clarification semantics).
- Updated the docstring (removed the force-proceed / `_CLAR_CAP` paragraph; described the Context section).
- Tests: replaced `test_force_proceed_sections_present_with_questions` + `test_no_questions_yields_no_force_proceed_sections` with `test_full_context_pack_folded_untruncated` (>4000-char context with an end sentinel proving no truncation) and `test_no_clarification_marker_ever_present`. All other brief tests preserved.
- Commit: `ef6e941`

### Task 2 — tribunal intake delegator (`intake.py`)
- Model `gemini-2.5-flash` → `claude-sonnet-4-6`; `_intake_once()` now calls `audited.anthropic_messages(...)` (mirrors `skeptic.py`) with Anthropic text extraction (join `.text` of text-typed `resp.content` blocks).
- Deleted the vague path: `_FORCE_PROCEED_NOTE`, `_parse_vague_brief()`, the `allow_clarification` parameter, the `BRIEF_VAGUE` dispatch, `_make_thinking_config()`, `genai_types`, and the `google.genai` import.
- `adaptive_intake()` always returns `needs_clarification=False` / `clarifying_questions=[]` (keys kept for shape compat).
- Rewrote `_INTAKE_PROMPT_TEMPLATE` as a delegator prompt (removed the "ask clarifying questions" / "If the brief is VAGUE" framing; instructs the model the brief is operator-validated and it MUST produce a plan). Kept the `LANGUAGE` line, A-D taxonomy block, low/med/high stakes block, the `FOCUS_AREA: <label> | TAXONOMY: <A/B/C/D> | STAKES: <low/med/high>` line format, one-language-per-run rules, and one-focus-area-per-question rules.
- Changed `RESEARCH_PROMPT` from a one-line prefix to a fenced multi-line `RESEARCH_PROMPT_START` … `RESEARCH_PROMPT_END` block. Rewrote `_parse_clear_brief()` with a fenced-block accumulator that attaches the joined+stripped (newline-preserving) block to `focus_areas[-1]`; focus areas with no block keep `research_prompt == ""`. `DEEP_RESEARCH_PROMPT` stays one line. `_COVERAGE_RETRY_NOTE` + coverage retry preserved.
- Tests: `FakeAudited` / `FakeAuditedSequence` now expose `anthropic_messages` returning a fake Anthropic response (`.content` = list of text blocks); `test_audited_gemini_generate_called_once` → `test_audited_anthropic_messages_called_once` (asserts `claude-sonnet-4-6`); deleted `test_thinking_disabled_in_kwargs`, `TestVagueBrief`, `VAGUE_BRIEF_RESPONSE`, `test_vague_brief_skips_coverage_check`; canned responses use the fenced format; added `test_multi_line_research_prompt_preserves_newlines`.
- Commit: `f6e80ee`

### Task 3 — tribunal pipeline (`pipeline.py`)
- Deleted `_CLAR_CAP`, `clar_rounds`, `force_proceed`, and the `allow_clarification` kwarg on the `adaptive_intake()` call (reduced to `brief`/`audited`/`run_id`/`tenant_id`).
- Deleted the force-proceed synthetic-mission block and the `needs_clarification` early-return branch — the run always proceeds to research division.
- Kept `_intake_detail()` result-surfacing + `raise_if_cancelled` untouched.
- **Verified read-only** (no transform added): `research_division.divide()` assigns `query = fa["research_prompt"]` verbatim (only `.strip()`; no `.splitlines()[0]`, no `.split("\n")`, no truncation), and `run_angles()` forwards `angle.get("query", "")` unmodified to the provider runner — multi-line research prompts pass through whole. `research_division.py` needed no change.
- Updated the module docstring (removed the "Vague-brief early return" shape block; described the delegator + vestigial keys).
- Commit: `4355bc2`

## Verification (structural — dev box has no Python/Docker)

All whole-change greps pass:
- `brief.py`: `CLARIFICATION ANSWERS` = 0, `_CONTEXT_EXCERPT_CHARS` = 0, `[CONTEXT PACK]` present.
- `intake.py`: zero for `BRIEF_VAGUE`, `_FORCE_PROCEED_NOTE`, `gemini_generate`, `genai_types`, `allow_clarification`; present: `anthropic_messages`, `claude-sonnet-4-6`, `RESEARCH_PROMPT_START`, `RESEARCH_PROMPT_END`, `_COVERAGE_RETRY_NOTE`.
- `pipeline.py`: zero for `_CLAR_CAP`, `force_proceed`, `clar_rounds`, `allow_clarification`.
- `research_division.py`: zero `splitlines()[0]` / `split("\n")` on the query path (multi-line pass-through confirmed).
- FOCUS_AREA line-format contract preserved in `intake.py`.

Tests authored by construction; the full tribunal + backend suites run later in Cloud Build (per constraint — no local pytest/py_compile).

## Deviations from Plan

None — plan executed exactly as written. `research_division.py` was inspected as Task 3 step 5 required and confirmed correct, so it was not modified (the plan explicitly said "otherwise change nothing").

## Vestigial Surface Kept (intentional, per plan)

- `needs_clarification` / `clarifying_questions` dict keys (always False / empty).
- `_intake_detail()` in `pipeline.py` (its now-unreachable `needs_clarification` branch is harmless).
- The `needs_input` run status, the `/answer` endpoint, and worker parking logic — untouched (API routes / worker code out of scope).

## Notes for Deploy (out of scope here)

The intake stage now calls Anthropic (`claude-sonnet-4-6`) instead of Gemini — the tribunal service must have the Anthropic key wired (per MEMORY: `Nestor_Claude2`) and Anthropic credits topped up before live runs.

## Self-Check: PASSED

All 5 modified files present on disk; all 3 task commits (`ef6e941`, `f6e80ee`, `4355bc2`) found in git log.
