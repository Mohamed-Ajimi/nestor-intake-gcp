---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 02
subsystem: tribunal-cost-truth
tags: [cost, audit, anthropic-cache, tool-fees, deep-research, decimal]
requires:
  - audit_log.cache_creation_tokens
  - run.cost_pending
provides:
  - compute-cache-create-pricing
  - compute-server-tool-fees
  - anthropic-cache-create-persisted
  - gemini-dr-usageMetadata-recorded
  - dr-grounding-fee-pending-fallback
affects:
  - Plan 15-05 (D15 feed reads per-call cost_usd; now includes cache-write + tool fees)
tech-stack:
  added: []
  patterns:
    - "compute() is the single cost authority: cache-create + server-tool fees added as optional params (default 0 -> backward compatible)"
    - "Server-tool flat fees read from _tool_fees object in cost_prices.json (published facts, never estimated)"
    - "DR grounding fee un-itemizable -> run.cost_pending via optional writer.mark_cost_pending; NULL number never written (C1 facts-only)"
    - "cache_creation_tokens persisted to non-hashed audit_log column; _payload_for_row untouched (T-15-04)"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/tests/test_cost_cache_write.py
  modified:
    - tribunal/nestor_pulse_sdk/audit/cost_table.py
    - tribunal/nestor_pulse_sdk/audit/cost_prices.json
    - tribunal/nestor_pulse_sdk/audit/audited_llm_client.py
    - tribunal/nestor_pulse_sdk/audit/writer.py
decisions:
  - "Server-tool fees priced via new compute() params (web_search_count/web_fetch_count) reading a _tool_fees table, keeping compute() the single cost authority rather than scattering fee math into the client"
  - "web_fetch flat fee = 0.0 (Anthropic bills web_fetch as input tokens only, already in prompt_tokens) — a documented fact, not an estimate"
  - "DR gemini thoughtsTokenCount folded into completion_tokens (thoughts bill at output rate) so compute() prices it with the existing formula"
  - "run.cost_pending set via an OPTIONAL, duck-typed writer.mark_cost_pending hook so the mandatory audit-writer protocol stays unchanged and the audit write never fails on a flag update"
metrics:
  duration: ~7m
  completed: 2026-07-24
---

# Phase 15 Plan 02: C1 Cost-Truth Fix Summary

Fixed the three C1 cost-truth defects in the tribunal audited client so displayed per-call cost is facts-only: Anthropic cache-CREATE tokens are now charged at the `cache_creation_5m` rate, `web_search`/`web_fetch` server-tool invocations are counted and priced at their published flat fee, and Gemini deep-research `usageMetadata` is recorded (priced when present, `run.cost_pending` when absent) — with unknown models still returning NULL and no number ever estimated. Because `run.cost_usd_total = SUM(audit_log.cost_usd)`, fixing per-call cost fixes the run total that previously showed ~€5 vs ~$43-45 real.

## What Was Built

**Task 1 — compute() cache-CREATE + tool fees** (`033e93b`): `compute()` gained three
optional keyword params — `cache_creation_tokens` (charged at `entry["cache_creation_5m"]/1e6`),
`web_search_count`, and `web_fetch_count` (flat per-call fees read from a new `_tool_fees`
object in `cost_prices.json`). All new terms use the existing `Decimal(str(...))` pattern (no
float). All default to 0 so every existing caller keeps identical results. The unknown-model
`return None` guard (Pitfall 5) is untouched. `cost_prices.json` gained `_tool_fees`
(`web_search`: $0.01/search = published $10/1000; `web_fetch`: $0.0 flat, billed as input
tokens), and the line-84 ESTIMATE comment is resolved: the DR per-token rates are the published
Gemini 2.5 Pro base rates (facts), and the un-itemizable grounding fee is marked pending rather
than estimated. Sonnet-4-6 already had a `cache_creation_5m` value (3.75), so no rate was invented.

**Task 2 — audited client threading** (`ac9948d`):
- Anthropic branch: `cache_creation_input_tokens` (previously extracted then dropped) is now
  passed into `compute(cache_creation_tokens=...)` AND persisted to the new
  `audit_log.cache_creation_tokens` column via `write_full_row`. Server-tool counts are read from
  `usage.server_tool_use.web_search_requests`/`web_fetch_requests` (new `_extract_anthropic_tool_counts`
  helper) and their fees enter the same call's `cost_usd`.
- `gemini_deep_research_raw`: now surfaces `usageMetadata` (new `_extract_gemini_dr_usage` helper)
  in the returned envelope instead of discarding it. Absent for the recorded run-4cbb5311 (confirmed
  by RESEARCH Q3), so the envelope omits it and the pending fallback fires.
- `end_call` google branch: prices DR calls from camelCase `usageMetadata`
  (`promptTokenCount`/`candidatesTokenCount`/`thoughtsTokenCount`, thoughts folded into
  completion at the output rate); when absent for a successful DR call it sets `dr_cost_pending`
  and calls the optional `writer.mark_cost_pending` — never writing a placeholder number.
- `_payload_for_row` / `_build_payload_dict` untouched → hash chain unaffected (T-15-04).

**Task 3 — test_cost_cache_write.py** (`5c8c810`): four tests with exact Decimals from
`cost_prices.json` (no approximations): `test_cache_write_charged` (delta == cache-create term
exactly; default==explicit-0), `test_web_search_fee_added` (delta == N×$0.01; web_fetch adds 0),
`test_dr_usage_recorded` (usageMetadata present → priced with thoughts at output rate; absent →
`run` in `pending_runs`, zero fabricated tokens), `test_unknown_model_null` (returns None even
with cache/tool args). A self-contained `_FakeWriter` (accepts `cache_creation_tokens`, exposes
`mark_cost_pending`) + `_make_client` build the client with no DB/GCS.

## Verification Strategy (author-by-construction — no local Python)

The dev box has no Python/Docker (project memory), so the PRIMARY pytest gate
`pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` **must run in Cloud Build / the
migrate-job at deploy** — it could not run locally. This is the documented per-task gate for
Tasks 1/2/3. The chain-unaffected proof `pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x`
is also deferred to Cloud Build.

Static + data validation performed locally instead:
- JSON validity confirmed via node (`cost_prices.json` parses).
- All acceptance greps pass: `cache_creation_tokens` count ≥ 2 in cost_table.py (6); unknown-model
  `return None` + Pitfall-5 warning present; `cache_creation_tokens=cache_creation_input_tokens`
  threaded into compute (2); `usageMetadata` used in client (10); `web_search` fee entry in JSON;
  four named tests present; `is None` asserted; no `~` approximations in the test.
- `git diff` confirms `_payload_for_row`/`_build_payload_dict` were NOT touched (chain frozen).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extended `writer.write_full_row` with `cache_creation_tokens`**
- **Found during:** Task 2
- **Issue:** The plan's `key_link` and acceptance criterion require `audited_llm_client` to
  persist `cache_creation` to the audit row via the writer call, but `write_full_row` had no such
  param and `writer.py` was NOT in the plan's `files_modified` list — the required persistence
  could not be satisfied through the existing interface.
- **Fix:** Added an optional `cache_creation_tokens: Optional[int] = None` kwarg to
  `write_full_row` and the matching non-hashed column to its INSERT. Additive and
  backward-compatible (non-anthropic callers persist NULL). Verified `15-03-PLAN.md` does NOT
  touch `writer.py`, so there is no parallel-executor conflict.
- **Files modified:** tribunal/nestor_pulse_sdk/audit/writer.py
- **Commit:** ac9948d

## Known Stubs

None. `run.cost_pending` is set from real runtime facts (absent DR usageMetadata); the exact
grounding amount is backfilled from GCP billing by design (C1). No UI-facing empty stubs.

## Threat Flags

None. All new surface is covered by the plan's threat register: T-15-04 (cache_creation_tokens
persisted as a non-hashed column; `_payload_for_row` untouched — asserted by the existing
`test_chain_green_after_cost_migration` plus a `git diff` check here), T-15-05 (facts-only:
unknown → NULL via `test_unknown_model_null`, un-itemizable DR grounding → `cost_pending`, never a
placeholder), T-15-SC (no new packages).

## Self-Check: PASSED

- Files: cost_table.py, cost_prices.json, audited_llm_client.py, writer.py,
  test_cost_cache_write.py — all FOUND.
- Commits 033e93b, ac9948d, 5c8c810 — all present in `git log`.
