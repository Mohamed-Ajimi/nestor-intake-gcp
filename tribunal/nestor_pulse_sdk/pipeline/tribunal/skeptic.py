"""Tribunal skeptic tool-use loop — Plan 01-14 Task 3.

Implements `run_skeptic()`: a hand-written async tool-use loop over
`audited.anthropic_messages` that actively commissions web evidence
via Anthropic's server-side web_search + web_fetch (citations on),
then forces a client-side `emit_verdict` tool call to terminate.

ADR-006 central technical constraint:
  The loop is hand-written async Python — NOT the Anthropic agent SDK's query entry
  point, which owns its own LLM egress and would bypass the audit hash chain
  (D-07 invariant). Every call goes through `audited.anthropic_messages`, keeping
  the full audit trail intact.

SERVER vs CLIENT tool dispatch protocol (CRITICAL — HTTP-400-trap):
  web_search_20250305 and web_fetch_20250910 are SERVER-SIDE tools.
  The API resolves them WITHIN the turn; their *_tool_result blocks
  appear INLINE in resp.content automatically.

  THE CLIENT MUST NOT append a synthetic tool_result for a server tool.
  Doing so → HTTP 400 from the Anthropic API.

  Loop invariant for server tools:
    1. Receive resp with server-tool results already inline in resp.content.
    2. Append the assistant turn {"role":"assistant","content":resp.content}
       to extend context — this is the ONLY message appended.
    3. Re-call without any tool_result.

  Loop termination:
    When the model emits the CLIENT tool `emit_verdict`, parse its input
    and return the verdict dict immediately.

Prompt caching:
  The shared claim+sources content block is sent with
  cache_control={"type":"ephemeral"} so the 2nd/3rd skeptic on the same
  claim reads the prefix at 0.1× cost. This is the primary cost lever
  (with stakes triage) bounding the multi-agent verification tax.

Task-1 confirmed defaults (overridable via env — see budget.py):
  survival rule  : majority-independent (majority + independent-source-required-to-refute)
  max_budget_usd : 5.00
  governor       : flag-budget-capped
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from nestor_pulse_sdk.pipeline.tribunal.tools import (
    EMIT_VERDICT_TOOL,
    build_web_fetch,
    build_web_search,
    force_emit_verdict,
)

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop cap constant — max_turns = 4 (plan spec: default <= 4)
# ---------------------------------------------------------------------------

_MAX_TURNS_DEFAULT = 4  # max_turns = 4 (grep target for test_max_turns_default_at_most_four)

# ---------------------------------------------------------------------------
# Max output tokens for skeptic calls.
# The Anthropic Messages API requires max_tokens; 8192 gives ample room for
# tool use turns plus the emit_verdict response.
# ---------------------------------------------------------------------------

_SKEPTIC_MAX_TOKENS = 8192

# ---------------------------------------------------------------------------
# Server-side tool name sentinels (for protocol dispatch)
# ---------------------------------------------------------------------------
_SERVER_TOOL_TYPES = frozenset({
    "web_search_tool_result",
    "web_fetch_tool_result",
})

# Do NOT add the client tool "emit_verdict" here — it triggers loop exit.

# ---------------------------------------------------------------------------
# Skeptic system prompt
# ---------------------------------------------------------------------------

_SKEPTIC_SYSTEM = """\
You are a rigorous fact-checking skeptic. Your job is to evaluate a specific claim
from a research report by searching for and fetching independent web sources.

Protocol:
1. Use web_search to find relevant independent sources (NOT the original source of the claim).
2. Use web_fetch to retrieve and read the actual source pages returned by web_search.
3. Evaluate whether the fetched sources corroborate, contradict, or are insufficient to judge the claim.
4. Call emit_verdict with your final verdict:
   - "support": independent evidence corroborates the claim.
   - "refute": independent evidence contradicts the claim (MUST have a web_fetch citation).
     Do NOT refute based on absence of evidence alone.
   - "insufficient": evidence is ambiguous or insufficient to decide.

Be rigorous. A claim should only be refuted if you have found independent, cited evidence
that directly contradicts it. Absence of corroboration alone warrants "insufficient", not "refute".
"""


# ---------------------------------------------------------------------------
# Core skeptic loop
# ---------------------------------------------------------------------------


def _extract_emit_verdict_block(content: list[Any]) -> Any | None:
    """Return the emit_verdict client tool_use block, or None if not present."""
    for block in content:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        block_name = getattr(block, "name", None) or (
            block.get("name") if isinstance(block, dict) else None
        )
        if block_type == "tool_use" and block_name == "emit_verdict":
            return block
    return None


def _is_server_tool_content(content: list[Any]) -> bool:
    """Return True if resp.content contains only server-tool-result blocks (no client tool_use)."""
    has_server = False
    for block in content:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type in _SERVER_TOOL_TYPES:
            has_server = True
        elif block_type == "tool_use":
            # Client tool — not server-only content
            return False
    return has_server


def _block_get(obj: Any, key: str) -> Any:
    """Read a field from a content block that may be an object or a dict."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_json(value: Any, expect: type) -> Any:
    """Coerce a tool-input field the model returned as a JSON-encoded STRING.

    F-01 (live run 4cbb5311, 2026-07-22): the model sometimes emits object/array
    tool-input fields (e.g. reconciliation, verdicts) as JSON strings, which
    crashed the verdict parsers with `'str' object has no attribute 'get'`.
    If `value` is a str, attempt json.loads; return the (decoded) value only if
    it is an instance of `expect`, else None so callers fall back to their
    existing defaults.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, expect) else None


def _collect_citation_urls(content: list[Any]) -> list[str]:
    """Pull source URLs surfaced by the server tools this turn.

    web_search_tool_result -> .content is a list of web_search_result {url,...}
    web_fetch_tool_result  -> .content is a web_fetch_result carrying a url
    text blocks            -> may carry .citations [{url,...}]
    Handles both object and dict block shapes. Order-preserving.
    """
    urls: list[str] = []
    for block in content:
        btype = _block_get(block, "type")
        if btype == "web_search_tool_result":
            inner = _block_get(block, "content") or []
            if isinstance(inner, list):
                for item in inner:
                    u = _block_get(item, "url")
                    if u:
                        urls.append(u)
        elif btype == "web_fetch_tool_result":
            inner = _block_get(block, "content")
            u = _block_get(inner, "url") if inner is not None else None
            if u:
                urls.append(u)
        elif btype == "text":
            cits = _block_get(block, "citations") or []
            if isinstance(cits, list):
                for c in cits:
                    u = _block_get(c, "url")
                    if u:
                        urls.append(u)
    return urls


def _parse_verdict(block: Any, citations: list[str] | None = None) -> dict[str, Any]:
    """Extract the verdict dict from an emit_verdict tool_use block.

    `citations` are the web_search/web_fetch source URLs accumulated across the
    loop (Plan 01-15 follow-through; previously hardcoded []). These feed
    persist_tribunal_claims -> claim_source rows, so citation recall reflects the
    evidence the skeptic actually fetched.
    """
    if isinstance(block, dict):
        inp = block.get("input") or {}
    else:
        inp = getattr(block, "input", {}) or {}
    # F-01 hardening: the model may return `input` itself (or evidence_refs)
    # as a JSON-encoded string — coerce before any .get access.
    inp = _coerce_json(inp, dict) or {}

    return {
        "verdict": inp.get("verdict", "insufficient"),
        "confidence": float(inp.get("confidence", 0.0)),
        "evidence_refs": list(_coerce_json(inp.get("evidence_refs"), list) or []),
        "citations": list(citations or []),
    }


def _content_to_serialisable(content: list[Any]) -> list[Any]:
    """Convert response content blocks to serialisable dicts for messages list."""
    result = []
    for block in content:
        if isinstance(block, dict):
            result.append(block)
        elif hasattr(block, "__dict__"):
            result.append({
                k: v for k, v in block.__dict__.items() if not k.startswith("_")
            })
        else:
            result.append({"type": str(getattr(block, "type", "unknown"))})
    return result


async def run_skeptic(
    *,
    claim: dict[str, Any],
    sources: list[dict[str, Any]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    model: str,
    max_turns: int = _MAX_TURNS_DEFAULT,
) -> dict[str, Any]:
    """Drive a hand-written skeptic tool-use loop over audited.anthropic_messages.

    Sends the claim + its source context (prompt-cached) to Claude with
    web_search + web_fetch + emit_verdict tools available.

    SERVER tools (web_search/web_fetch): the API resolves these within the turn;
    their results appear INLINE in resp.content. The client MUST NOT append a
    synthetic tool_result — only append the assistant turn to extend context.

    CLIENT tool (emit_verdict): terminates the loop; parsed into a verdict dict.

    Args:
        claim:      Claim dict with 'text', 'stakes', 'facet' keys.
        sources:    List of source dicts from prior research (URL + snippet).
        audited:    AuditedLLMClient — the ONLY LLM egress (never direct provider).
        run_id:     UUID of the current run (audit chain).
        tenant_id:  UUID of the current tenant (audit chain).
        model:      Anthropic model string (e.g. "claude-opus-4-8").
        max_turns:  Maximum loop iterations before forcing emit_verdict (default 4).

    Returns:
        Verdict dict: {verdict, confidence, evidence_refs, citations}
    """
    # -----------------------------------------------------------------------
    # Build the initial messages list
    # -----------------------------------------------------------------------
    claim_text = claim.get("text", "")
    sources_text = "\n".join(
        f"- {s.get('url', 'unknown')} — {s.get('snippet', '')}"
        for s in sources
    ) or "(no prior sources)"

    # Shared claim+sources document block — cache_control ephemeral so the
    # 2nd/3rd skeptic on the same claim reads this prefix at 0.1× cost.
    shared_block = {
        "type": "text",
        "text": (
            f"CLAIM TO EVALUATE:\n{claim_text}\n\n"
            f"PRIOR SOURCES (for context):\n{sources_text}"
        ),
        "cache_control": {"type": "ephemeral"},
    }

    msgs: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [shared_block],
        }
    ]

    # Tools: server-side search+fetch, client-side emit_verdict
    tools = [
        build_web_search(max_uses=5),
        build_web_fetch(max_uses=3, max_content_tokens=4000),
        EMIT_VERDICT_TOOL,
    ]

    # Source URLs the skeptic fetched, accumulated across turns (web_search/web_fetch
    # happen on early turns; emit_verdict fires later — so we collect as we go).
    collected_urls: list[str] = []

    # -----------------------------------------------------------------------
    # Tool-use loop (bounded by max_turns)
    # -----------------------------------------------------------------------
    for turn in range(1, max_turns + 1):
        is_final_turn = (turn == max_turns)

        # On the final turn, force the model to emit emit_verdict
        call_kwargs: dict[str, Any] = {}
        if is_final_turn:
            call_kwargs["tool_choice"] = force_emit_verdict()
            log.debug("skeptic: final turn %d — forcing emit_verdict", turn)

        resp = await audited.anthropic_messages(
            run_id=run_id,
            tenant_id=tenant_id,
            model=model,
            messages=msgs,
            tools=tools,
            max_tokens=_SKEPTIC_MAX_TOKENS,
            **call_kwargs,
        )

        content = resp.content if isinstance(resp.content, list) else []
        # Accumulate any web_search/web_fetch source URLs surfaced this turn.
        for u in _collect_citation_urls(content):
            if u not in collected_urls:
                collected_urls.append(u)

        # -----------------------------------------------------------------------
        # Inspect the response
        # -----------------------------------------------------------------------
        if resp.stop_reason == "tool_use":
            # Check for client-side emit_verdict first
            verdict_block = _extract_emit_verdict_block(content)
            if verdict_block is not None:
                log.debug("skeptic: emit_verdict fired on turn %d — terminating", turn)
                return _parse_verdict(verdict_block, collected_urls)

            # No emit_verdict — model used server tools (web_search/web_fetch).
            # SERVER-tool protocol: their results are ALREADY inline in resp.content.
            # DO NOT construct a tool_result. Only append the assistant turn.
            log.debug(
                "skeptic: server tool(s) used on turn %d — appending assistant turn", turn
            )
            assistant_turn = {
                "role": "assistant",
                "content": _content_to_serialisable(content),
            }
            msgs.append(assistant_turn)
            # Continue loop — no synthetic tool_result appended

        else:
            # stop_reason is "end_turn" or something unexpected
            log.warning(
                "skeptic: unexpected stop_reason %r on turn %d — returning insufficient",
                resp.stop_reason,
                turn,
            )
            return {
                "verdict": "insufficient",
                "confidence": 0.0,
                "evidence_refs": [],
                "citations": list(collected_urls),
            }

    # Should not be reached (final turn forces emit_verdict), but defensive fallback
    log.error("skeptic: loop exhausted without emit_verdict — returning insufficient")
    return {
        "verdict": "insufficient",
        "confidence": 0.0,
        "evidence_refs": [],
        "citations": list(collected_urls),
    }
