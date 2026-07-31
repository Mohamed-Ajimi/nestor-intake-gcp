"""Tribunal tool definitions — Plan 01-14 Task 2.

Provides:
  - build_web_search(max_uses)        -> Anthropic server-side web_search_20250305 dict
  - build_web_fetch(max_uses, ...)    -> Anthropic server-side web_fetch_20250910 dict
  - EMIT_VERDICT_TOOL                 -> client-side tool schema (forced via tool_choice)
  - force_emit_verdict()              -> tool_choice dict that forces emit_verdict
  - EMIT_ORIENTATION_TOOL             -> client-side tool schema (question workshop, 15.2-10)
  - force_emit_orientation()          -> tool_choice dict that forces emit_orientation
  - EMIT_QUESTION_GROUPS_TOOL         -> client-side tool schema (D-R4 grouping, 15.6-01)
  - force_emit_question_groups()      -> tool_choice dict that forces emit_question_groups
  - EMIT_ADMISSION_TOOL               -> client-side tool schema (D-R10 admission, 15.7-05)
  - force_emit_admission()            -> tool_choice dict that forces emit_admission

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


# ---------------------------------------------------------------------------
# Client-side tool: emit_question_groups (Phase 15.6 plan 01 — D-R4 grouping)
# ---------------------------------------------------------------------------

#: The cross-question sentence the grouping description carries, as the FIRST of
#: two engine-authored options. D-W3-5 makes THIS ONE the rule: a mandate group
#: holds members from exactly ONE client question.
GROUP_RULE_SINGLE_PARENT_ONLY = (
    "Every group must contain questions from ONE client question only -- the "
    "bracketed label at the start of each line. Never mix two labels in one group."
)

#: The SECOND option, which is spec § 4's original permissive wording. It is NOT
#: an alternative policy and NOT an operator knob. D-W3-5 overrode the sentence it
#: comes from, so it survives for exactly one situation: when single-parent
#: grouping is ARITHMETICALLY IMPOSSIBLE because there are more client questions
#: than groups available. Telling a model to do the impossible guarantees an
#: unusable answer, so in that case, and only that case, the permissive rule ships.
GROUP_RULE_CROSS_QUESTION_ALLOWED = (
    "A group MAY span two client questions -- the bracketed labels at the start of "
    "each line -- where those questions genuinely need the same research "
    "groundwork. Prefer a single label per group; mix only where the overlap is real."
)

#: WHICH RULE SHIPS IS DERIVED, NEVER PASSED. `question_grouping.group_winners`
#: computes it as:
#:
#:     GROUP_RULE_SINGLE_PARENT_ONLY
#:         if len(client_questions) <= max_groups
#:         else GROUP_RULE_CROSS_QUESTION_ALLOWED
#:
#: Deterministic, no flag, and no call-site decision — a caller cannot select the
#: permissive rule, it can only present arithmetic that forces it.

#: Forced client tool for the workshop's GROUPING turn (D-R4, phase 15.6 wave 3).
#: One call per run: the winners arrive as a NUMBERED LIST and the model returns
#: which numbers belong together, so shared research groundwork is searched once
#: per topic instead of once per sub-question.
#:
#: THE SCHEMA IS INDEX-ADDRESSED, AND THAT IS THE SECURITY CONTROL, NOT A
#: CONVENIENCE. Winner text reaches three third-party research providers VERBATIM,
#: so a schema with a text field would let the grouping model REWRITE a question on
#: its way into a paid provider prompt — a second model handed a channel into the
#: research query (T-15.2-60). There is therefore no text, question, label or title
#: property anywhere below: the model's entire question-identifying surface is
#: integers, and `question_grouping.build_groups` stamps every string a consumer
#: reads (`parent`, `parents`, `group_id`) in Python from the winners list.
#: `gates.py` addresses untrusted claims by INDEX for exactly this reason.
#:
#: The `description` is a FORMAT STRING with two slots the caller fills:
#:   {max_groups}          — the ceiling moves when the discovery bracket takes a slot
#:   {cross_question_rule} — GROUP_RULE_SINGLE_PARENT_ONLY or the permissive twin
EMIT_QUESTION_GROUPS_TOOL: dict[str, Any] = {
    "name": "emit_question_groups",
    "description": (
        "Group the numbered research questions above by the RESEARCH GROUNDWORK "
        "they share -- the same sources, the same market, the same regulatory "
        "regime, the same body of evidence a researcher would have to assemble "
        "before answering any of them. Do NOT group by surface wording: two "
        "questions that read alike but need different sources belong apart, and "
        "two worded differently that need the same sources belong together. "
        "{cross_question_rule} "
        "One client question MAY split across two groups when it is really two "
        "topics. "
        "Return AT MOST {max_groups} groups. Return FEWER when the material has "
        "fewer real topics -- fewer is a correct answer and never padded: do not "
        "invent or split groups to reach the maximum. "
        "Every number in the list must appear in exactly one group: use each "
        "number once, leave none out."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "description": (
                    "The groups you chose, best-supported first. At most the "
                    "maximum stated above, and fewer when the material warrants."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "member_numbers": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "The numbers of the questions that belong in this "
                                "group, taken from the numbered list above. Use "
                                "each number at most once, across all groups."
                            ),
                        },
                        "why_grouped": {
                            "type": "string",
                            "description": (
                                "One short sentence on the shared research "
                                "groundwork these questions need. Used for the run "
                                "log only."
                            ),
                        },
                    },
                    # why_grouped is deliberately NOT in `required`, for the reason
                    # this file states twice above (source_url on
                    # EMIT_ORIENTATION_TOOL, superseded_note on
                    # EMIT_GROUP_VERDICT_TOOL): requiring a field the model does not
                    # actually have produces a fabricated value. A group with no
                    # stated reason still dispatches correctly; a group with an
                    # invented reason pollutes the run log an operator reads.
                    "required": ["member_numbers"],
                },
            },
        },
        "required": ["groups"],
    },
}


def force_emit_question_groups() -> dict[str, Any]:
    """tool_choice that forces emit_question_groups on the final grouping turn.

    Pass as tool_choice=force_emit_question_groups() on the grouping call, so the
    turn terminates with a structured membership answer rather than prose this
    module would then have to parse out of model text.

    Returns:
        {"type": "tool", "name": "emit_question_groups"}
    """
    return {"type": "tool", "name": "emit_question_groups"}


# ---------------------------------------------------------------------------
# Client-side tools: serpapi_search + emit_fact_list
# (Phase 15.2 plan 12 — the D10 own-researcher, our fourth research stream)
#
# THE PROTOCOL SPLIT THAT GOVERNS THE OWN-RESEARCHER'S LOOP. Everything above
# this line is either a SERVER tool (web_search / web_fetch, resolved by the API
# inside the turn) or a TERMINAL client tool (emit_*, forced on the final turn
# and never answered). `serpapi_search` is neither: it is a client-side tool the
# model calls MID-LOOP and expects an ANSWER to. So the own-researcher's loop has
# to do BOTH things in the same turn and must never confuse them:
#
#   * a `serpapi_search` tool_use block MUST get a real `tool_result` block back,
#     with a matching `tool_use_id`, in a following user message — otherwise the
#     conversation is malformed and the model cannot continue;
#   * a `web_fetch` block MUST NOT get a synthetic `tool_result` — that is the
#     HTTP 400 trap stated at lines 11-14 of this module.
#
# A single turn can legitimately contain both kinds. When it does, the API returns
# stop_reason "tool_use" and defers the remaining server-tool work to the next
# request; `own_researcher.py` handles both branches explicitly, appending ONE
# assistant turn plus ONE user message carrying only the CLIENT tool results.
# ---------------------------------------------------------------------------

#: Client-side search tool backed by OUR SerpApi account (D10).
#:
#: Deliberately offered INSTEAD OF Anthropic's server-side web search, not
#: alongside it: the whole point of the D10 stream is that we control the search,
#: and offering both would double-pay for the same turn and blur which provider
#: the run's search spend belongs to.
SERPAPI_SEARCH_TOOL: dict[str, Any] = {
    "name": "serpapi_search",
    "description": (
        "Search Google through our own SerpApi account and get back the organic "
        "results (title, link, snippet) for one query. Use it to FIND sources; "
        "then use web_fetch to actually READ the promising ones before you assert "
        "anything — a snippet is a pointer, not evidence. "
        "Only 'q' is required. Every other field is optional and is clamped on our "
        "side, so a value outside its range is corrected rather than rejected: "
        "'num' is clamped to 1-10, and 'hl'/'gl' must be two-letter codes or they "
        "are dropped. Searching costs money, so make each query count: prefer a "
        "few precise, differently-angled queries over many near-identical ones."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "q": {
                "type": "string",
                "description": "The search query. One question or phrase, not a list.",
            },
            "hl": {
                "type": "string",
                "description": (
                    "UI language as a two-letter code (e.g. 'nl', 'fr'), taken from "
                    "the question's language tags. Omit if unsure."
                ),
            },
            "gl": {
                "type": "string",
                "description": (
                    "Two-letter country code to bias results (e.g. 'be', 'nl'). "
                    "Omit if unsure."
                ),
            },
            "num": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "How many organic results to return (1-10, default 10).",
            },
        },
        # Only `q` is required, for the same reason superseded_note and source_url
        # are optional above: forcing the model to emit a value it does not have
        # produces a fabricated one, and every optional field here has a safe
        # Python-side default.
        "required": ["q"],
    },
}


#: The forced client tool that ENDS an own-researcher session. Its output is the
#: same D8 fact-list shape the other three research streams produce, so the
#: downstream merge sees four identical streams rather than a special case.
EMIT_FACT_LIST_TOOL: dict[str, Any] = {
    "name": "emit_fact_list",
    "description": (
        "Emit everything you established in this research session, exactly once, "
        "as a structured fact list. Call this when you have read enough pages — "
        "and you will be required to call it on the final turn regardless. "
        "Each fact must be ONE self-contained assertion (no conjunctions joining "
        "two facts), stated with the statistics, named entities and dates you "
        "actually found. "
        "'source_url' MUST be a page you fetched IN THIS SESSION. Never invent a "
        "URL, never cite a page you only saw as a search snippet, and never cite "
        "from memory: a statement you cannot trace to a page you read in this "
        "session does not belong in this list at all. "
        "'quality' describes the SOURCE: official = government, regulator, "
        "standards body, official filing or academic; press = established press "
        "or a recognised data provider; other = anything else. "
        "'certainty' is 'certain' only when two or more INDEPENDENT sources "
        "corroborate the fact; otherwise 'single'. If in doubt, say 'single'. "
        "'evidence' is the shortest VERBATIM sentence copied EXACTLY, word for "
        "word, from the page you fetched — it is used to LOCATE and remove the "
        "passage if the fact is later discredited, so a paraphrase or a "
        "translation is useless. "
        "'not_found' is what you looked for and could NOT establish. Say it "
        "plainly rather than omitting it: a named gap is information, silence is "
        "not. Return an empty list only if there genuinely was nothing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "description": "One entry per fact you established in this session.",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {
                            "type": "string",
                            "description": "One self-contained factual assertion.",
                        },
                        "source_url": {
                            "type": "string",
                            "description": (
                                "The http(s) URL of the page you FETCHED that "
                                "supports this fact."
                            ),
                        },
                        "quality": {
                            "type": "string",
                            "enum": ["official", "press", "other"],
                            "description": "Your assessment of the source's standing.",
                        },
                        "certainty": {
                            "type": "string",
                            "enum": ["certain", "single"],
                            "description": (
                                "'certain' only with two or more independent "
                                "corroborating sources; else 'single'."
                            ),
                        },
                        "evidence": {
                            "type": "string",
                            "description": (
                                "The shortest VERBATIM sentence from the fetched "
                                "page stating this fact, copied word for word."
                            ),
                        },
                    },
                    # quality / certainty / evidence are deliberately NOT required.
                    # A missing value must CLAMP to the safe default ("other" /
                    # "single" — fail toward more checking, G-11) rather than force
                    # the model to emit an empty string or invent a grade it does
                    # not have. Same reasoning as superseded_note above.
                    "required": ["statement", "source_url"],
                },
            },
            "not_found": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Short plain-words lines: things you looked for and could not "
                    "establish. Empty list when nothing was missing."
                ),
            },
        },
        "required": ["facts"],
    },
}


def force_emit_fact_list() -> dict[str, Any]:
    """tool_choice that forces emit_fact_list on the final own-researcher turn."""
    return {"type": "tool", "name": "emit_fact_list"}


# ---------------------------------------------------------------------------
# Client-side tool: emit_admission (Phase 15.7 plan 05 — the D-R10 admission gate)
# ---------------------------------------------------------------------------

#: Forced client tool for the D-R10 ADMISSION session: the cheap grounded lookup
#: that decides whether an angle the loop INVENTED earns a research slot.
#:
#: THE TEST IS THE PREMISE, NOT THE ANSWER. The model is asked whether the
#: entities, markets, mechanisms and metrics the angle names actually EXIST and
#: whether desk research could plausibly settle the question — never whether
#: someone has already settled it. Read the other way round, the rule admits
#: already-documented angles (low research value) and rejects novel ones (high
#: research value): a novelty filter pointed backwards, which measured as all four
#: invented angles rejected and zero survivors.
#:
#: THERE IS DELIBERATELY NO URL FIELD ON THIS SCHEMA, AND THAT ABSENCE IS THE
#: CONTROL. A URL the model types is the model's own output line, not evidence:
#: offering the field at all is exactly how the measurement harness's bug got in,
#: where a looser guard admitted 2 of 3 angles whose only URL was a literal "-"
#: (which is truthy) because the model had "evidenced" its own angle by restating
#: that its own entities exist. The admitting URL is read ONLY from the server-tool
#: result blocks, by `workshop_admission.admission_evidence` via
#: `skeptic._collect_citation_urls`. The tool may return a QUOTE; it may never
#: return the source. Compare `EMIT_QUESTION_GROUPS_TOOL` above, whose entire
#: question-identifying surface is integers for the same reason.
#:
#: `quote` and `why` are deliberately NOT in `required`, for the same reason
#: `source_url` is not required on `EMIT_ORIENTATION_TOOL`: requiring a field the
#: model may not honestly have is how a model gets pushed into inventing a
#: plausible-looking value, and a rejected premise has nothing to quote. The
#: SCHEMA BLOCK ITSELF is kept free of the substring `url` on purpose, so the
#: absence of a source field is greppable rather than merely intended.
EMIT_ADMISSION_TOOL: dict[str, Any] = {
    "name": "emit_admission",
    "description": (
        "Emit the admission verdict for ONE invented research angle, after a small "
        "number of web searches. The test is whether the PREMISE IS REAL: do the "
        "entities, markets, mechanisms and metrics this angle names actually exist, "
        "and could desk research plausibly settle the question. "
        "Whether anyone has ALREADY ANSWERED the question is NOT the test and must "
        "never count against the angle -- a question nobody has published on is a "
        "better research question, not a worse one. "
        "Set premise_real to true only when the searches showed you that the named "
        "things exist. Quote the search result that showed you, verbatim, and never "
        "phrase it from memory. "
        "You do not supply a source address of any kind: the engine reads that from "
        "the search results themselves, so a quote written without searching admits "
        "nothing at all."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "premise_real": {
                "type": "boolean",
                "description": (
                    "True when the searches established that the entities, markets, "
                    "mechanisms and metrics the angle names exist, and that desk "
                    "research could plausibly settle it. False otherwise."
                ),
            },
            "quote": {
                "type": "string",
                "description": (
                    "A short verbatim quote from the search result that established "
                    "the premise. Empty when premise_real is false."
                ),
            },
            "why": {
                "type": "string",
                "description": (
                    "One clause naming which part of the premise the searches "
                    "established, or which part they failed to establish."
                ),
            },
        },
        # `quote` and `why` are deliberately NOT required -- see the note above.
        "required": ["premise_real"],
    },
}


def force_emit_admission() -> dict[str, Any]:
    """tool_choice that forces emit_admission on the final admission turn.

    Pass as tool_choice=force_emit_admission() on the last allowed turn of the
    D-R10 admission loop, so the session terminates with a structured verdict
    rather than another billed search turn.

    Returns:
        {"type": "tool", "name": "emit_admission"}
    """
    return {"type": "tool", "name": "emit_admission"}
