"""Tribunal tool definitions — Plan 01-14 Task 2.

Provides:
  - build_web_search(max_uses)        -> Anthropic server-side web_search_20250305 dict
  - build_web_fetch(max_uses, ...)    -> Anthropic server-side web_fetch_20250910 dict
  - EMIT_VERDICT_TOOL                 -> client-side tool schema (forced via tool_choice)
  - force_emit_verdict()              -> tool_choice dict that forces emit_verdict
  - EMIT_ORIENTATION_TOOL             -> client-side tool schema (question workshop, 15.2-10)
  - force_emit_orientation()          -> tool_choice dict that forces emit_orientation

CRITICAL INVARIANTS (ADR-006 §GOTCHA):
  - web_search and web_fetch are SERVER-SIDE tools: the API resolves them within the
    turn and returns *_tool_result blocks inline in resp.content. The client MUST NOT
    append a synthetic tool_result for server tools (HTTP 400 trap).
  - There are THREE client-side tools -- emit_verdict, emit_group_verdict and
    emit_orientation -- and each one is forced via tool_choice on its loop's FINAL
    turn so the loop always terminates with structured output rather than another
    search turn. Server tools still never receive a synthetic tool_result; that
    invariant is about the SERVER tools and is unaffected by how many client tools
    this module declares.
  - NEVER enable JSON structured-output mode (response format) on a citation-enabled
    call — citations + structured outputs = HTTP 400. emit_verdict via forced tool_choice
    is tool-use, NOT structured outputs — safe.
  - web_fetch_20250910 (NOT web_fetch_20260209 which requires code-execution tool).
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Server-side tool builders
# ---------------------------------------------------------------------------


def build_web_search(max_uses: int = 5) -> dict[str, Any]:
    """Return the Anthropic server-side web_search_20250305 tool dict.

    Shape mirrors nestor_pulse/tools/claude_deep_researcher.py:65 (read-only analog).

    Args:
        max_uses: Maximum number of web searches the model may perform in one turn.

    Returns:
        Tool dict to pass in messages.create(tools=[...]).
    """
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_uses,
    }


def build_web_fetch(
    max_uses: int = 3,
    allowed_domains: list[str] | None = None,
    max_content_tokens: int | None = 4000,
) -> dict[str, Any]:
    """Return the Anthropic server-side web_fetch_20250910 tool dict.

    SECURITY: web_fetch can only fetch URLs already present in context (from prior
    web_search / web_fetch results) — it cannot fetch model-self-generated URLs.
    allowed_domains + max_uses + max_content_tokens bound the exfiltration surface
    (T-14-01 mitigate disposition).

    citations.enabled is ALWAYS True so cite evidence traces back to fetched pages.
    Do NOT enable JSON response format here — citations + structured outputs = HTTP 400.

    Args:
        max_uses:           Maximum fetch calls per turn.
        allowed_domains:    Optional domain allowlist for exfiltration bounding.
        max_content_tokens: Cap on tokens returned per fetched page.

    Returns:
        Tool dict to pass in messages.create(tools=[...]).
    """
    tool: dict[str, Any] = {
        "type": "web_fetch_20250910",
        "name": "web_fetch",
        "max_uses": max_uses,
        "citations": {"enabled": True},
    }
    if allowed_domains is not None:
        tool["allowed_domains"] = allowed_domains
    if max_content_tokens is not None:
        tool["max_content_tokens"] = max_content_tokens
    return tool


# ---------------------------------------------------------------------------
# Client-side tool: emit_verdict
# ---------------------------------------------------------------------------

#: Client-side tool schema for the forced verdict emission.
#:
#: Forced via tool_choice on the final turn so the model MUST emit a structured
#: verdict rather than continuing to search. This is tool-use (NOT structured
#: outputs / JSON response format) — compatible with citations.
#:
#: Input fields:
#:   verdict      : "support" | "refute" | "insufficient"
#:   confidence   : 0.0–1.0 numeric score
#:   evidence_refs: list of cited evidence strings (short excerpts / URLs)
#
# DELIBERATE ASYMMETRY (plan 15.1-03 Task 1, G-06): this PER-CLAIM tool keeps its
# three-value verdict enum while EMIT_GROUP_VERDICT_TOOL below gains a fourth value.
# The only production callers of this tool are the NESTOR_TRIBUNAL_GROUP_VERIFY=false
# fallback branch and the coverage-gate re-entry, whose fate plan 15.1-07 owns. Do NOT
# "fix" the asymmetry by extending the enum below — it is intentional.
EMIT_VERDICT_TOOL: dict[str, Any] = {
    "name": "emit_verdict",
    "description": (
        "Emit a structured verdict on the claim after completing web research. "
        "Use 'support' if the claim is corroborated by independent web evidence. "
        "Use 'refute' if an independent source contradicts the claim (you MUST have "
        "web_fetch citation evidence to refute; do not refute based on absence alone). "
        "Use 'insufficient' if the evidence is ambiguous or insufficient to decide."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["support", "refute", "insufficient"],
                "description": "Verdict on the claim based on retrieved web evidence.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence score 0.0–1.0 for the verdict.",
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Short excerpts or URLs from web_fetch citations that support "
                    "the verdict. Empty list is acceptable for 'insufficient'."
                ),
            },
        },
        "required": ["verdict", "confidence", "evidence_refs"],
    },
}


def force_emit_verdict() -> dict[str, Any]:
    """Return a tool_choice dict that forces the model to emit the emit_verdict tool.

    Pass as tool_choice=force_emit_verdict() on the final allowed turn to guarantee
    the loop terminates with a structured verdict rather than another search turn.

    Returns:
        {"type": "tool", "name": "emit_verdict"}
    """
    return {"type": "tool", "name": "emit_verdict"}


# ---------------------------------------------------------------------------
# Client-side tool: emit_group_verdict (Tribunal quality plan, Phase 3)
# ---------------------------------------------------------------------------

#: Forced client tool for GROUP verification. One skeptic session looks at all the
#: claim variants about the same entity|attribute at once, then emits:
#:   - per-claim verdicts (so adjudication still works claim-by-claim), AND
#:   - a reconciliation across the variants — the thing per-claim verification
#:     structurally cannot produce (it never sees the other variants), which is
#:     why contradictions like the two TacticalPad prices both "passed" before.
EMIT_GROUP_VERDICT_TOOL: dict[str, Any] = {
    "name": "emit_group_verdict",
    "description": (
        "Emit verdicts for a GROUP of related claims (all about the same entity and "
        "attribute) after completing web research, PLUS a reconciliation across them. "
        "Give one verdict per claim by its index. In 'reconciliation', resolve how the "
        "variants relate: are they the same fact (agree), different scopes/tiers/dates "
        "(scoped — say which), or a genuine contradiction (disputed=true). Provide the "
        "best current canonical value when one exists. Only refute a claim with an "
        "independent web_fetch citation — never on absence of evidence. "
        "Use 'superseded' when the claim was TRUE when written but has since been "
        "overtaken by a later change — do NOT use 'refute' for an overtaken-but-once-true "
        "fact. A superseded verdict MUST carry 'superseded_note' stating what changed and "
        "from when, quoted from the fetched source and never phrased from memory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "description": "One entry per claim in the group, by claim_index.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_index": {"type": "integer", "description": "0-based index of the claim within the group."},
                        "verdict": {"type": "string", "enum": ["support", "refute", "insufficient", "superseded"]},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "superseded_note": {
                            "type": "string",
                            "description": (
                                "REQUIRED when verdict=superseded: what changed and from when "
                                "(e.g. 'applied until 1 April 2026'). Stated from the fetched "
                                "source, never from memory."
                            ),
                        },
                    },
                    # superseded_note is deliberately NOT in `required`: every non-superseded
                    # verdict would otherwise have to carry an empty string.
                    "required": ["claim_index", "verdict", "confidence"],
                },
            },
            "reconciliation": {
                "type": "object",
                "description": "How the variants relate to each other.",
                "properties": {
                    "disputed": {"type": "boolean", "description": "True if the variants genuinely contradict and cannot be reconciled by scope/date."},
                    "relation": {"type": "string", "enum": ["agree", "scoped", "disputed", "single"], "description": "agree=same fact; scoped=different tier/date/region; disputed=real contradiction; single=only one claim."},
                    "note": {"type": "string", "description": "One-sentence explanation of the relation (name the scope/date if scoped)."},
                    "canonical": {"type": "string", "description": "The best current canonical value/statement, if one can be determined; else empty."},
                },
                "required": ["disputed", "relation", "note"],
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short excerpts or URLs from web_fetch citations backing the verdicts.",
            },
        },
        "required": ["verdicts", "reconciliation"],
    },
}


def force_emit_group_verdict() -> dict[str, Any]:
    """tool_choice that forces emit_group_verdict on the final group-skeptic turn."""
    return {"type": "tool", "name": "emit_group_verdict"}


# ---------------------------------------------------------------------------
# Client-side tool: emit_orientation (Phase 15.2 plan 10 — the question workshop)
# ---------------------------------------------------------------------------

#: Forced client tool for the question workshop's ORIENTATION session (D2 step 1).
#: One session per client-validated question: a handful of searches, at most a
#: couple of fetches, then this tool. It emits two things and nothing else —
#: `findings` (what a researcher needs to know before writing sub-questions) and
#: `brief_conflicts` (D4's "the brief assumes X, the world says Y" flags, which
#: plan 15.2-06's "Disputed & changed" report section consumes as DATA).
#:
#: SCOPE (D4): the description tells the model in words that it may not propose
#: dropping, replacing, merging or reinterpreting the client's question. That is a
#: courtesy, not the control — the control is mechanical and lives in
#: `workshop.py` (PARENT is stamped in Python; a question with zero parsed
#: candidates gets its own text injected verbatim).
EMIT_ORIENTATION_TOOL: dict[str, Any] = {
    "name": "emit_orientation",
    "description": (
        "Emit the orientation result for ONE client-validated question after a small "
        "number of web searches and at most a couple of page fetches. "
        "'findings' are short, specific, factual notes that change HOW this question "
        "should be researched — who the real players are, what the current regime is, "
        "what changed recently. They are an orientation, not a research answer. "
        "'brief_conflicts' are places where the brief's stated assumption is "
        "contradicted by what you actually found: quote the fetched source, never "
        "phrase it from memory, and return an empty list rather than inventing a "
        "conflict. "
        "You may NOT propose dropping, replacing, merging or reinterpreting the "
        "client's question — the scope is fixed and already validated by the client; "
        "your job is to add depth, never to change what is being asked."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Short factual orientation notes about THIS question. Empty list "
                    "is acceptable when the searches found nothing that changes how "
                    "the question should be researched."
                ),
            },
            "brief_conflicts": {
                "type": "array",
                "description": (
                    "Places where the brief's stated assumption is contradicted by a "
                    "fetched source. Empty list when nothing conflicts."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "assumption": {
                            "type": "string",
                            "description": "What the brief assumes, in the brief's own terms.",
                        },
                        "world_says": {
                            "type": "string",
                            "description": (
                                "What the fetched source actually says, quoted from that "
                                "source and never phrased from memory."
                            ),
                        },
                        "source_url": {
                            "type": "string",
                            "description": (
                                "The http(s) URL of the fetched page the contradiction "
                                "came from, when you have one."
                            ),
                        },
                    },
                    # source_url is deliberately NOT in `required`, for exactly the
                    # reason superseded_note is not required in EMIT_GROUP_VERDICT_TOOL
                    # above: a conflict spotted in a search snippet with no fetched page
                    # would otherwise have to carry an empty string, and requiring the
                    # field would push the model to fabricate a plausible-looking URL.
                    "required": ["assumption", "world_says"],
                },
            },
        },
        "required": ["findings"],
    },
}


def force_emit_orientation() -> dict[str, Any]:
    """tool_choice that forces emit_orientation on the final orientation turn.

    Pass as tool_choice=force_emit_orientation() on the last allowed turn of the
    question workshop's orientation loop, so the session terminates with structured
    orientation data rather than another billed search turn.

    Returns:
        {"type": "tool", "name": "emit_orientation"}
    """
    return {"type": "tool", "name": "emit_orientation"}
