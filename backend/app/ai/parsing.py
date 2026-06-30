"""JSON-extraction + cost-estimate ports of the legacy edge-function helpers.

Parity reference (carry the legacy behaviour exactly):
- ``extract_json``       — docs/supabase-functions/apply-intake-skill.ts:141-153
                           (strip ```json / ``` fences, slice first ``{`` .. last
                           ``}``, json.loads; raise on a missing object). Used by
                           the apply-intake-skill + context-pack object outputs.
- ``extract_json_array`` — docs/supabase-functions/structure-answers.ts:55 and
                           extract-insights.ts:114 both do
                           ``text.match(/```json\\s*([\\s\\S]*?)\\s*```/) ?? text.match(/(\\[[\\s\\S]*\\])/)``
                           i.e. prefer a ```json fenced block, else the first
                           ``[`` .. last ``]``. Those two skills return JSON ARRAYS.
- ``estimate_cost_usd``  — apply-intake-skill.ts:135-139 / generate-context-pack.ts:148-152
                           (in_tok/1e6*3 + out_tok/1e6*15, rounded to 4 decimals;
                           Claude Sonnet $3/MTok in, $15/MTok out).

Grep-guard: this module constructs NO database engines or sessions — pure
string/JSON/number work only.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Legacy Claude Sonnet pricing (USD per 1M tokens), apply-intake-skill.ts:135-139.
_INPUT_USD_PER_MTOK = 3
_OUTPUT_USD_PER_MTOK = 15

# Fence strippers for the JSON-OBJECT path (apply-intake-skill.ts:144). The legacy
# did three sequential replaces on the trimmed string: leading ```json (case-
# insensitive), then a leading bare ```, then a trailing ```.
_RE_LEADING_JSON_FENCE = re.compile(r"^```json\s*", re.IGNORECASE)
_RE_LEADING_FENCE = re.compile(r"^```\s*")
_RE_TRAILING_FENCE = re.compile(r"```\s*$")

# Fenced + bare patterns for the JSON-ARRAY path (structure-answers.ts:55).
# Non-greedy capture inside a ```json ... ``` block, falling back to the first
# ``[`` through the last ``]`` (greedy) when no fence is present.
_RE_FENCED_JSON = re.compile(r"```json\s*([\s\S]*?)\s*```")
_RE_BARE_ARRAY = re.compile(r"(\[[\s\S]*\])")


def extract_json(text: str) -> Any:
    """Parse a single JSON OBJECT out of a Claude response (verbatim legacy port).

    Strips a leading ```json or ``` fence and a trailing ``` fence, then slices
    from the first ``{`` to the last ``}`` and ``json.loads`` it. Raises
    ``ValueError("No JSON object found in Claude output")`` when no braces are
    present — the caller marks the skill_run ``failed`` on this (D-09).

    Source: docs/supabase-functions/apply-intake-skill.ts:141-153.
    """
    cleaned = text.strip()
    cleaned = _RE_LEADING_JSON_FENCE.sub("", cleaned)
    cleaned = _RE_LEADING_FENCE.sub("", cleaned)
    cleaned = _RE_TRAILING_FENCE.sub("", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in Claude output")
    return json.loads(cleaned[start : end + 1])


def extract_json_array(text: str) -> Any:
    """Parse a JSON ARRAY out of a Claude response (verbatim legacy port).

    Prefers the contents of a ```json ... ``` fenced block; if there is no fence,
    falls back to the first ``[`` through the last ``]``. Raises
    ``ValueError`` when neither is present.

    Source: docs/supabase-functions/structure-answers.ts:55,
            docs/supabase-functions/extract-insights.ts:114.
    """
    match = _RE_FENCED_JSON.search(text)
    if match is not None:
        return json.loads(match.group(1))
    match = _RE_BARE_ARRAY.search(text)
    if match is None:
        raise ValueError("No JSON array found in Claude output")
    return json.loads(match.group(1))


def estimate_cost_usd(in_tok: int, out_tok: int) -> float:
    """Estimate the USD cost of a Claude call from token usage (verbatim legacy port).

    ``round(in_tok / 1_000_000 * 3 + out_tok / 1_000_000 * 15, 4)`` — the legacy
    $3/MTok input + $15/MTok output Sonnet rates, persisted on
    ``skill_runs.cost_estimate_usd``.

    Source: docs/supabase-functions/apply-intake-skill.ts:135-139.
    """
    return round(
        in_tok / 1_000_000 * _INPUT_USD_PER_MTOK
        + out_tok / 1_000_000 * _OUTPUT_USD_PER_MTOK,
        4,
    )
