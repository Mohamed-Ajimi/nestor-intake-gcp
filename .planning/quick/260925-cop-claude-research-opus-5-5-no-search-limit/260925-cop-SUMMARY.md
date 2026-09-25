---
status: complete
quick_id: 260925-cop
date: 2026-09-25
---
# Quick 260925-cop — Claude research on claude-opus-5-5, no web-search cap

Operator ruling 2026-09-25. File: tribunal/nestor_pulse/tools/claude_deep_researcher.py.
- model claude-sonnet-4-6 -> claude-opus-5-5 (env NESTOR_CLAUDE_RESEARCH_MODEL)
- Opus 5.5 rejects thinking.type=enabled + budget_tokens (HTTP 400, measured) -> thinking.type=adaptive + output_config.effort (env NESTOR_CLAUDE_RESEARCH_EFFORT, default high; max also accepted)
- max_tokens 16000 -> 32000 (env NESTOR_CLAUDE_RESEARCH_MAX_TOKENS)
- web_search max_uses REMOVED (no cap)
- NEW pause_turn continuation: every content block kept; paused turn sent back; at most NESTOR_CLAUDE_RESEARCH_MAX_CONTINUATIONS=10. Before, a pause would have been taken as the final answer.
- claude_adapter.py audit label imports the real model; legacy_tools_snapshot.json regenerated per its update rule.

Tests: new test_claude_research_opus_nocap.py (6). Full tribunal suite locally: 204 failed / 24 errors IDENTICAL to an untouched baseline worktree, +6 passed, 0 new failures.

Known gap (pre-existing): the legacy researcher returns no usage, so Claude research cost is NOT in run totals; cost_prices.json has no opus-5-5 entry. Remaining brakes on an uncapped call: per-angle timeout NESTOR_DR_TIMEOUT_S (40 min) and the continuation bound. DEV ONLY.
