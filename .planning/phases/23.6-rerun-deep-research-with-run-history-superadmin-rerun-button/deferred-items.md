# Phase 23.6 — deferred / open items (2026-09-25)

## DEF-23.6-01 — Finish the dev walkthrough
Choose an older run + reload; fr/en copy; rerun on a DELIVERED intake stays delivered; client report link unchanged.

## DEF-23.6-02 — Claude research cost is not counted
`tribunal/nestor_pulse/tools/claude_deep_researcher.py` returns only {status, report} — no usage — so the Claude
stream's cost is absent from run totals (was already true on Sonnet 4.6). `cost_prices.json` has no
`anthropic/claude-opus-5-5` entry. Opus 5.5 with no search cap is the most expensive setup so far; the Anthropic
console is the only view of it. Fix: return usage + server_tool_use counts and add the opus-5-5 price row.

## DEF-23.6-03 — First observation of Opus 5.5 research owed
Next dev run: worker log `Claude deep research complete: model=claude-opus-5-5 … N web searches, M request(s),
stop_reason=…`; per-angle duration from tribunal.run_event; report length vs the Sonnet 4.6 baseline (20–29k chars).
Watch for pause_turn continuations and the 40-min per-angle timeout.

## DEF-23.6-04 — Speed: remaining levers
Question workshop ~17 min (sequential rounds — code change); verification concurrency
`NESTOR_TRIBUNAL_SKEPTIC_CONCURRENCY` 8 → 16 not applied (env only). Research calls are now bounded by the slowest
Gemini call.

## DEF-23.6-05 — Gemini at 15 concurrent shares the prod key
No 429 seen on the first rerun. Dev load draws on the shared Gemini quota and monthly spend cap.

## DEF-23.6-06 — Prod promotion not done
Prod still: research concurrency 4, Claude research Sonnet 4.6 capped at 10 searches, no rerun/history UI,
migration 0018 not applied. Promotion = release-client.sh + a new env var on the prod worker (TF var needed).

## Carried from 23.5 / earlier
Sources stale-title fix (12 of 14 bad labels on dev run 4e91bb85) not built; skill-runs list never shows
error_message; rotate the dev Anthropic key pasted in chat (Nestor_Claude_Temp v2) and the older chat-exposed keys.
