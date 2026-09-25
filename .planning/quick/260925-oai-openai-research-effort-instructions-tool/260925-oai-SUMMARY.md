---
status: complete
quick_id: 260925-oai
date: 2026-09-25
---
# Quick 260925-oai — OpenAI research: high effort, shared instructions, current search tool

Operator ruling 2026-09-25. File: tribunal/nestor_pulse_sdk/audit/audited_llm_client.py (openai_deep_research_raw, the responses.create call).
- reasoning effort: provider default -> {"effort": "high"} (env NESTOR_OPENAI_DR_EFFORT)
- instructions: none -> the SAME RESEARCH_SYSTEM_PROMPT the Claude stream sends (lazy import from nestor_pulse.tools.claude_deep_researcher; one text, no copy)
- tool: web_search_preview -> web_search. Still no search cap (no max_tool_calls).
- Model unchanged: gpt-5.6-sol (env NESTOR_OPENAI_DR_MODEL).

Probe on this account before the change: background create -> completed, reasoning.effort echoed "high", tools ["web_search"].
Tests: new test in test_deep_research_adapters.py pins the four request kwargs. Related suites 145 passed; full tribunal suite 0 new failures vs baseline. DEV ONLY.
